"""Real urllib/HTTPConnection chains; only DNS, sockets and TLS are synthetic."""
import http.client as http_client
import io
import ipaddress
import os
import socket
import ssl
import time
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack, contextmanager
from unittest import mock

from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.support import http, url_security
from multi_search_mcp.src.support.url_security import UrlSecurityError

PUBLIC_IP = "93.184.216.34"
FAKE_IP = "198.18.0.93"
OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
CONNECT_OK = b"HTTP/1.1 200 Connection established\r\n\r\n"

def addresses(address, port):
    """A real getaddrinfo-shaped answer, with the requested port preserved."""
    v6 = ":" in address
    return [(socket.AF_INET6 if v6 else socket.AF_INET, socket.SOCK_STREAM, 6,
             "", (address, port, 0, 0) if v6 else (address, port))]

class WireSocket:
    def __init__(self, responses, connect_error=None, read_error=None):
        self.responses = list(responses)
        self.events = []
        self.sent = []
        self.closed = False
        self.connect_error, self.read_error = connect_error, read_error
        self.timeout = "not set"

    def settimeout(self, timeout):
        self.timeout = timeout
        self.events.append(("timeout", timeout))

    def connect(self, address):
        self.events.append(("connect", address))
        if self.connect_error:
            raise self.connect_error

    def bind(self, address):
        self.events.append(("bind", address))

    def setsockopt(self, *args):
        pass

    def sendall(self, data):
        self.sent.append(bytes(data))

    def makefile(self, mode):
        if self.read_error:
            failure = self.read_error
            class FailingStream(io.BytesIO):
                def read(self, *args):
                    raise failure
                def read1(self, *args):
                    raise failure
                def readline(self, *args):
                    raise failure
            return FailingStream()
        return io.BytesIO(self.responses.pop(0))

    def close(self):
        self.closed = True

class HttpConnectBoundaryTests(unittest.TestCase):
    @contextmanager
    def wire(self, dns=None, *, responses=None, opt_in=False,
             connect_error=None, read_error=None):
        sockets = []
        answers = responses if responses is not None else [OK]

        def factory(*_args, **_kwargs):
            sock = WireSocket(answers, connect_error, read_error)
            sockets.append(sock)
            return sock

        def default_dns(host, port, *args, **kwargs):
            # Even literal-IP paths through socket.create_connection hit this
            # stub; nothing in these tests ever reaches the OS resolver.
            if host in {"localhost", "proxy.example"}:
                return addresses("127.0.0.1", port)
            try:
                ipaddress.ip_address(host)
            except ValueError:
                return addresses(PUBLIC_IP, port)
            return addresses(host, port)

        def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kwargs):
            # Explicitly replace this entry too so the suite isolation guard
            # knows the transport is synthetic. Still exercise bottom-level
            # getaddrinfo/socket.socket, not a ready-made connection response.
            if timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
                timeout = socket.getdefaulttimeout()
            family, socktype, proto, _, sockaddr = socket.getaddrinfo(
                *address, type=socket.SOCK_STREAM,
            )[0]
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(socket, "create_connection", side_effect=create_connection))
            stack.enter_context(mock.patch.dict(os.environ, {"MULTI_SEARCH_ALLOW_FAKE_IP": "1" if opt_in else ""}))
            stack.enter_context(mock.patch.object(urllib.request, "getproxies", return_value={}))
            # A missed mock is a hard error rather than an external connection.
            stack.enter_context(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("real socket forbidden")))
            lookup = stack.enter_context(mock.patch.object(socket, "getaddrinfo", side_effect=dns or default_dns))
            make_socket = stack.enter_context(mock.patch.object(socket, "socket", side_effect=factory))
            tls = stack.enter_context(mock.patch.object(http._ssl_ctx, "wrap_socket", side_effect=lambda sock, **kwargs: sock))
            yield sockets, lookup, make_socket, tls

    def request(self, url, *, proxy=None, deadline=True, timeout=0.25, request=None):
        req = request or urllib.request.Request(url)
        req.timeout = timeout
        if proxy is not None:
            req.set_proxy(proxy, "http")
        if deadline is True:
            req._multi_search_deadline = time.monotonic() + 3
        elif deadline is not False:
            req._multi_search_deadline = deadline
        handler = http._DeadlineHTTPSHandler(context=http._ssl_ctx) if req.type == "https" else http._DeadlineHTTPHandler()
        # Real urllib.do_open -> real HTTP(S)Connection.request/connect/getresponse.
        response = handler.https_open(req) if req.type == "https" else handler.http_open(req)
        with response:
            return response.read()

    def redirect(self, target, *, deadline):
        req = urllib.request.Request("http://origin.example/start")
        req.timeout = 0.25
        if deadline:
            req._multi_search_deadline = time.monotonic() + 3
        return http._SafeHTTPRedirectHandler().redirect_request(
            req, io.BytesIO(), 302, "Found", {}, target,
        )

    def assert_no_wire(self, sockets, make_socket):
        self.assertEqual([packet for sock in sockets for packet in sock.sent], [])
        make_socket.assert_not_called()

    def test_direct_literal_and_private_dns_never_create_socket(self):
        for deadline in (False, True):
            for scheme in ("http", "https"):
                for host in ("127.0.0.1", "10.0.0.8", "[::1]", "private.example"):
                    with self.subTest(deadline=deadline, scheme=scheme, host=host), self.wire(
                        lambda host, port, *a, **k: addresses("10.0.0.8", port),
                    ) as (sockets, dns, factory, _):
                        with self.assertRaises(UrlSecurityError):
                            self.request(f"{scheme}://{host}/", deadline=deadline)
                        self.assert_no_wire(sockets, factory)
                        self.assertEqual(dns.call_count, int(host == "private.example"))

    def test_mixed_dns_answers_rejected_before_any_public_address_is_dialed(self):
        for deadline in (False, True):
            with self.subTest(deadline=deadline), self.wire(
                lambda host, port, *a, **k: addresses(PUBLIC_IP, port) + addresses("127.0.0.1", port),
            ) as (sockets, dns, factory, _):
                with self.assertRaises(UrlSecurityError):
                    self.request("http://mixed.example/", deadline=deadline)
                dns.assert_called_once()
                self.assert_no_wire(sockets, factory)

    def test_initial_public_dns_is_used_once_with_no_rebinding_lookup(self):
        for deadline in (False, True):
            for scheme in ("http", "https"):
                calls = []

                def rebind(host, port, *args, **kwargs):
                    calls.append(host)
                    return addresses(PUBLIC_IP if len(calls) == 1 else "127.0.0.1", port)

                with self.subTest(deadline=deadline, scheme=scheme), self.wire(rebind) as (sockets, dns, _, tls):
                    self.assertEqual(self.request(f"{scheme}://rebind.example/page", deadline=deadline), b"ok")
                    dns.assert_called_once()
                    self.assertEqual(calls, ["rebind.example"])
                    self.assertEqual([event for event in sockets[0].events if event[0] == "connect"],
                                     [("connect", (PUBLIC_IP, 443 if scheme == "https" else 80))])
                    if scheme == "https":
                        self.assertEqual(tls.call_args.kwargs["server_hostname"], "rebind.example")

    def test_proxy_http_and_https_reject_private_targets_before_get_or_connect(self):
        targets = ("127.0.0.1", "169.254.169.254", "2130706433", "0x7f000001",
                   "127.1", "010.0.0.05", "[64:ff9b::a00:1]", "[::ffff:10.0.0.1]",
                   "[2002:0a00:0001::]", "private.example", "user:secret@public.example")
        for deadline in (False, True):
            for scheme in ("http", "https"):
                for host in targets:
                    with self.subTest(deadline=deadline, scheme=scheme, host=host), self.wire(
                        lambda host, port, *a, **k: addresses("10.0.0.5", port),
                        responses=[CONNECT_OK, OK] if scheme == "https" else [OK],
                    ) as (sockets, dns, factory, _):
                        with self.assertRaises(UrlSecurityError) as error:
                            self.request(f"{scheme}://{host}/admin", proxy="localhost:7890", deadline=deadline)
                        self.assertNotIn("secret", str(error.exception))
                        self.assert_no_wire(sockets, factory)
                        self.assertEqual(dns.call_count, int(host == "private.example"))

    def test_public_target_uses_local_proxy_but_target_is_pinned_on_wire(self):
        for deadline in (False, True):
            for scheme in ("http", "https"):
                target_queries = []

                def rebind(host, port, *args, **kwargs):
                    if host == "localhost":
                        return addresses("127.0.0.1", port)
                    target_queries.append(host)
                    return addresses(PUBLIC_IP if len(target_queries) == 1 else "127.0.0.1", port)

                with self.subTest(deadline=deadline, scheme=scheme), self.wire(
                    rebind, responses=[CONNECT_OK, OK] if scheme == "https" else [OK],
                ) as (sockets, dns, _, tls):
                    self.assertEqual(self.request(f"{scheme}://public.example/page?q=1", proxy="localhost:7890", deadline=deadline), b"ok")
                    self.assertEqual(target_queries, ["public.example"])
                    self.assertEqual(dns.call_count, 2)  # target + proxy hop, once each
                    sock = sockets[0]
                    self.assertIn(("connect", ("127.0.0.1", 7890)), sock.events)
                    wire = b"".join(sock.sent)
                    if scheme == "http":
                        self.assertIn(f"GET http://{PUBLIC_IP}:80/page?q=1 ".encode(), wire)
                    else:
                        self.assertIn(f"CONNECT {PUBLIC_IP}:443 ".encode(), wire)
                        self.assertIn(b"GET /page?q=1 ", wire)
                        self.assertEqual(tls.call_args.kwargs["server_hostname"], "public.example")
                    self.assertIn(b"Host: public.example", wire)

    def test_proxy_pins_ipv6_route_but_preserves_sni_and_credentials_boundary(self):
        ip = "2606:4700::1111"
        for scheme in ("http", "https"):
            def lookup(host, port, *args, **kwargs):
                return addresses("127.0.0.1" if host == "localhost" else ip, port)
            with self.subTest(scheme=scheme), self.wire(
                lookup, responses=[CONNECT_OK, OK] if scheme == "https" else [OK],
            ) as (sockets, dns, _, tls):
                req = urllib.request.Request(f"{scheme}://public.example/", headers={
                    "Proxy-Authorization": "Basic synthetic", "Authorization": "Bearer fixture",
                })
                self.assertEqual(self.request(req.full_url, request=req, proxy="localhost:7890"), b"ok")
                packets = sockets[0].sent
                if scheme == "https":
                    self.assertIn(f"CONNECT [{ip}]:443 ".encode(), packets[0])
                    self.assertIn(b"Proxy-Authorization: Basic synthetic", packets[0])
                    self.assertNotIn(b"Authorization: Bearer", packets[0])
                    self.assertNotIn(b"Proxy-Authorization", b"".join(packets[1:]))
                    self.assertIn(b"Authorization: Bearer fixture", b"".join(packets[1:]))
                    self.assertEqual(tls.call_args.kwargs["server_hostname"], "public.example")
                else:
                    self.assertIn(f"GET http://[{ip}]:80/ ".encode(), packets[0])
                dns.assert_has_calls([
                    mock.call("public.example", 443 if scheme == "https" else 80, type=socket.SOCK_STREAM),
                    mock.call("localhost", 7890, type=socket.SOCK_STREAM),
                ])

    def test_proxy_retry_restores_routing_state_and_reuses_target_pin(self):
        with self.wire() as (sockets, dns, _, _):
            req = urllib.request.Request("http://public.example/retry")
            req.set_proxy("localhost:7890", "http")
            for _ in range(2):
                self.assertEqual(self.request(req.full_url, request=req), b"ok")
                self.assertTrue(req.has_proxy())
            self.assertEqual([call.args[0] for call in dns.call_args_list],
                             ["public.example", "localhost", "localhost"])
            for sock in sockets:
                self.assertIn(f"GET http://{PUBLIC_IP}:80/retry ".encode(), b"".join(sock.sent))

    def test_explicit_proxy_handler_without_environment_works(self):
        for scheme in ("http", "https"):
            with self.subTest(scheme=scheme), self.wire(
                responses=[CONNECT_OK, OK] if scheme == "https" else [OK],
            ) as (sockets, _, _, tls), mock.patch.object(urllib.request, "proxy_bypass", return_value=False):
                with http.urlopen_retry(f"{scheme}://public.example/", timeout=1,
                    extra_handlers=(urllib.request.ProxyHandler({scheme: "http://localhost:7890"}),),
                ) as response:
                    self.assertEqual(response.read(), b"ok")
                self.assertIn(("connect", ("127.0.0.1", 7890)), sockets[0].events)

    def test_direct_url_cannot_inherit_proxy_exception_or_wrong_port(self):
        direct = urllib.request.Request("http://localhost:7890/")
        proxied = urllib.request.Request("http://public.example/")
        proxied.set_proxy("localhost:7890", "http")
        with mock.patch.object(http, "_configured_proxy_addresses", return_value={("localhost", 7890)}):
            self.assertFalse(http._is_trusted_proxy_hop(direct, "localhost", 7890))
            self.assertTrue(http._is_trusted_proxy_hop(proxied, "LOCALHOST", 7890))
            self.assertFalse(http._is_trusted_proxy_hop(proxied, "localhost", 7891))
        with self.wire() as (sockets, _, factory, _):
            with self.assertRaises(UrlSecurityError):
                self.request(direct.full_url, request=direct)
            self.assert_no_wire(sockets, factory)

    def test_socket_timeout_applied_before_connect_with_and_without_deadline(self):
        for deadline in (False, True):
            for timeout, default, expected in ((0.25, None, 0.25), (None, 0.75, None),
                                               (socket._GLOBAL_DEFAULT_TIMEOUT, 0.75, 0.75)):
                with self.subTest(deadline=deadline, timeout=timeout), self.wire() as (sockets, _, _, _), \
                     mock.patch.object(socket, "getdefaulttimeout", return_value=default):
                    self.request("http://public.example/", timeout=timeout, deadline=deadline)
                    event, actual = sockets[0].events[0]
                    self.assertEqual(event, "timeout")
                    if expected is None and deadline:
                        self.assertGreater(actual, 0)
                        self.assertLessEqual(actual, 3)
                    else:
                        self.assertEqual(actual, expected)
                    self.assertEqual(sockets[0].events[1], ("connect", (PUBLIC_IP, 80)))

    def test_deadline_shorter_than_explicit_timeout_wins_at_connect_and_read(self):
        with self.wire() as (sockets, _, _, _), mock.patch.object(http.time, "monotonic", return_value=10.0):
            self.request("http://public.example/", timeout=0.25, deadline=10.1)
            for kind, value in sockets[0].events:
                if kind == "timeout":
                    self.assertAlmostEqual(value, 0.1)

    def test_explicit_short_timeout_is_not_expanded_during_reads(self):
        with self.wire() as (sockets, _, _, _):
            self.request("http://public.example/", timeout=0.25)
            for kind, value in sockets[0].events:
                if kind == "timeout":
                    self.assertLessEqual(value, 0.25)
        for failure in ("connect_error", "read_error"):
            with self.subTest(failure=failure), self.wire(**{failure: TimeoutError("synthetic timeout")}) as (sockets, _, _, _):
                with self.assertRaises((TimeoutError, urllib.error.URLError)):
                    self.request("http://public.example/", timeout=0.25, deadline=False)
                self.assertEqual(sockets[0].events[0], ("timeout", 0.25))
                self.assertTrue(sockets[0].closed)

    def test_numeric_hosts_never_acquire_fake_ip_dns_exception(self):
        hosts = (FAKE_IP, str(int(ipaddress.ip_address(FAKE_IP))), "0xc612005d", "198.18.93", "0306.022.0.0135",
                 "2130706433", "0x7f000001", "127.1", "010.0.0.05", "%33%33%32%33%30%36%38%35%30%39",
                 "３３２３０６８５０９", "198。18。0。93")
        for host in hosts:
            for deadline in (False, True):
                with self.subTest(host=host, deadline=deadline), self.wire(
                    lambda host, port, *a, **k: addresses(FAKE_IP, port), opt_in=True,
                ) as (sockets, dns, factory, _):
                    with self.assertRaises(UrlSecurityError):
                        url_security.validate_public_http_url(f"http://{host}/")
                    with self.assertRaises(UrlSecurityError):
                        url_security.resolve_validated_addresses(host, 80)
                    with self.assertRaises(UrlSecurityError):
                        self.request(f"http://{host}/", deadline=deadline)
                    self.assert_no_wire(sockets, factory)
                    dns.assert_not_called()

    def test_domain_fake_ip_opt_in_and_public_numeric_positive(self):
        for opt_in in (False, True):
            with self.subTest(opt_in=opt_in), self.wire(
                lambda host, port, *a, **k: addresses(FAKE_IP, port), opt_in=opt_in,
            ) as (sockets, dns, factory, _):
                if opt_in:
                    self.assertEqual(self.request("http://tun.example/"), b"ok")
                    self.assertIn(("connect", (FAKE_IP, 80)), sockets[0].events)
                else:
                    with self.assertRaises(UrlSecurityError):
                        self.request("http://tun.example/")
                    self.assert_no_wire(sockets, factory)
                dns.assert_called_once()
        for host in (PUBLIC_IP, "134744072", "0x08080808", "8.8"):
            with self.subTest(host=host), self.wire() as (sockets, _, _, _):
                self.assertEqual(self.request(f"http://{host}/"), b"ok")
                self.assertTrue(any(kind == "connect" for kind, _ in sockets[0].events))

    def test_redirect_pin_survives_without_deadline_and_never_resolves_twice(self):
        for deadline in (False, True):
            count = []

            def rebind(host, port, *args, **kwargs):
                count.append(host)
                return addresses(PUBLIC_IP if len(count) == 1 else "127.0.0.1", port)

            with self.subTest(deadline=deadline), self.wire(rebind) as (sockets, dns, _, _):
                redirected = self.redirect("http://redirect.example/next", deadline=deadline)
                self.assertEqual(redirected._multi_search_pinned_addresses[("redirect.example", 80)][0][4][0], PUBLIC_IP)
                self.assertEqual(self.request(redirected.full_url, request=redirected, deadline=deadline), b"ok")
                dns.assert_called_once()
                self.assertIn(("connect", (PUBLIC_IP, 80)), sockets[0].events)

    def test_redirect_to_proxy_keeps_the_original_checked_destination(self):
        for deadline in (False, True):
            seen = []
            def rebind(host, port, *args, **kwargs):
                if host == "localhost":
                    return addresses("127.0.0.1", port)
                seen.append(host)
                return addresses(PUBLIC_IP if len(seen) == 1 else "10.0.0.5", port)
            with self.subTest(deadline=deadline), self.wire(rebind) as (sockets, dns, _, _):
                redirected = self.redirect("http://redirect.example/next", deadline=deadline)
                self.assertEqual(self.request(redirected.full_url, request=redirected,
                    deadline=deadline, proxy="localhost:7890"), b"ok")
                self.assertEqual(seen, ["redirect.example"])
                self.assertEqual(dns.call_count, 2)  # redirect target + proxy hop
                self.assertIn(f"GET http://{PUBLIC_IP}:80/next ".encode(), b"".join(sockets[0].sent))

    def test_redirect_fake_ip_policy_matches_validation_and_dial(self):
        for deadline in (False, True):
            for opt_in in (False, True):
                with self.subTest(deadline=deadline, opt_in=opt_in), self.wire(
                    lambda host, port, *a, **k: addresses(FAKE_IP, port), opt_in=opt_in,
                ) as (sockets, dns, factory, _):
                    if opt_in:
                        redirected = self.redirect("http://tun.example/next", deadline=deadline)
                        self.assertEqual(self.request(redirected.full_url, request=redirected, deadline=deadline), b"ok")
                        self.assertIn(("connect", (FAKE_IP, 80)), sockets[0].events)
                    else:
                        with self.assertRaises(UrlSecurityError):
                            self.redirect("http://tun.example/next", deadline=deadline)
                        self.assert_no_wire(sockets, factory)
                    dns.assert_called_once()
            for host in (FAKE_IP, "3323068509", "0xc612005d", "198.18.93", "10.0.0.5", "private.example"):
                with self.subTest(host=host, deadline=deadline), self.wire(
                    lambda host, port, *a, **k: addresses("10.0.0.5", port), opt_in=True,
                ) as (sockets, dns, factory, _):
                    with self.assertRaises(UrlSecurityError):
                        self.redirect(f"http://{host}/next", deadline=deadline)
                    self.assert_no_wire(sockets, factory)
                    self.assertEqual(dns.call_count, int(host == "private.example"))

    def test_embedded_ipv4_policy_is_explicit(self):
        for address in ("64:ff9b::a00:1", "2002:0a00:0001::", "2002:c0a8:0101::", "::ffff:10.0.0.1"):
            with self.subTest(address=address), self.wire() as (sockets, _, factory, _):
                with self.assertRaises(UrlSecurityError):
                    self.request(f"http://[{address}]/")
                self.assert_no_wire(sockets, factory)
        self.assertEqual(url_security.validate_public_http_url("https://[64:ff9b::5db8:d822]/"),
                         "https://[64:ff9b::5db8:d822]/")

    def test_dns_result_timeout_is_recomputed_after_admission(self):
        future, pool, clock = mock.Mock(), mock.Mock(), [10.0]
        def submit(*_args):
            clock[0] = 10.8
            return future
        pool.submit_nowait.side_effect = submit
        with mock.patch.object(url_security, "_DNS_POOL", pool), mock.patch.object(
            url_security.time, "monotonic", side_effect=lambda: clock[0],
        ):
            url_security._run_bounded_dns(lambda: [], deadline=11.0)
        self.assertAlmostEqual(future.result.call_args.kwargs["timeout"], 0.2)

    def test_exa_and_firecrawl_deadline_branches(self):
        from multi_search_mcp.src.scrape.scrapers import exa, firecrawl
        for module, function in ((exa, exa.scrape_url_exa), (firecrawl, firecrawl.scrape_url_firecrawl)):
            with self.subTest(backend=module.__name__):
                response = io.BytesIO(b'{"results":[{"text":"body"}],"success":true,"data":{"markdown":"body"}}')
                with mock.patch.object(module, "urlopen_retry", return_value=response) as opened:
                    self.assertNotIn("error", function("https://example.com", "synthetic", timeout=30, deadline=time.monotonic()+1))
                self.assertGreater(opened.call_args.kwargs["timeout"], 0)
                self.assertLessEqual(opened.call_args.kwargs["timeout"], 1)

    def test_bounded_reads_strict_tls_and_delegated_rebuild_remain(self):
        with self.wire(responses=[b"HTTP/1.1 200 OK\r\nContent-Length: 99\r\n\r\n"]), \
             mock.patch.object(http, "MAX_RESPONSE_BYTES", 8):
            with self.assertRaises(http.ResponseTooLargeError):
                self.request("http://public.example/")
        self.assertEqual(http._ssl_ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(http._ssl_ctx.check_hostname)
        if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
            self.assertFalse(http._ssl_ctx.options & ssl.OP_IGNORE_UNEXPECTED_EOF)
        with mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl", return_value={"markdown": "body"}) as backend:
            result = scrape_url_smart("HTTPS://Example.COM:8443/a\\b c", backends=("firecrawl",))
        self.assertEqual(result["via"], "firecrawl")
        self.assertEqual(backend.call_args.args[0], "https://example.com:8443/a%5Cb%20c")

if __name__ == "__main__":
    unittest.main()

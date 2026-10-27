"""Real urllib/HTTPConnection chains; only DNS, sockets and TLS are synthetic.

The outbound targets are fixed provider hostnames, so the HTTP layer never
resolves a name itself: the standard library socket connect does, exactly like
a browser or curl. These tests exercise that boundary directly.
"""
import io
import ipaddress
import os
import socket
import ssl
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack, contextmanager
from unittest import mock

import multi_search_mcp.src.search.search_runner as search_runner_module
from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.search.search_runner import ProviderSpec, SearchRunner, SearchRunnerConfig
from multi_search_mcp.src.support import http, url_security
from multi_search_mcp.src.support.concurrency import BoundedDaemonExecutor
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
        self.responses = responses
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
    def wire(self, dns=None, *, responses=None,
             connect_error=None, read_error=None):
        sockets = []
        # One shared response queue: redirects, retries and proxy tunnels open
        # new sockets but consume responses in wire order.
        answers = list(responses) if responses is not None else [OK]

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
            # Prove no opt-in switch is required: fake-IP answers must just work.
            stack.enter_context(mock.patch.dict(os.environ, {}, clear=False))
            os.environ.pop("MULTI_SEARCH_ALLOW_FAKE_IP", None)
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

    def redirect(self, target, *, deadline=True, url="http://origin.example/start"):
        req = urllib.request.Request(url)
        req.timeout = 0.25
        if deadline is True:
            req._multi_search_deadline = time.monotonic() + 3
        elif deadline is not False:
            req._multi_search_deadline = deadline
        return http._SafeHTTPRedirectHandler().redirect_request(
            req, io.BytesIO(), 302, "Found", {}, target,
        )

    def assert_no_wire(self, sockets, make_socket):
        self.assertEqual([packet for sock in sockets for packet in sock.sent], [])
        make_socket.assert_not_called()

    def test_fixed_provider_domain_with_fake_or_private_dns_answer_connects(self):
        for answer in ("198.18.1.241", "28.1.2.3", "10.0.0.5"):
            for scheme in ("http", "https"):
                with self.subTest(answer=answer, scheme=scheme), self.wire(
                    lambda host, port, *a, **k: addresses(answer, port),
                ) as (sockets, dns, _, tls):
                    self.assertEqual(
                        self.request(f"{scheme}://api.search.brave.com/page?q=1"),
                        b"ok",
                    )
                    dns.assert_called_once()
                    self.assertEqual(dns.call_args.args[:2], ("api.search.brave.com", 443 if scheme == "https" else 80))
                    self.assertIn(("connect", (answer, 443 if scheme == "https" else 80)), sockets[0].events)
                    if scheme == "https":
                        self.assertEqual(tls.call_args.kwargs["server_hostname"], "api.search.brave.com")

    def test_socket_connect_is_the_only_dns_caller_for_a_request(self):
        for scheme in ("http", "https"):
            with self.subTest(scheme=scheme), self.wire() as (sockets, dns, _, _):
                self.assertEqual(self.request(f"{scheme}://provider.example/page"), b"ok")
                dns.assert_called_once_with("provider.example", 443 if scheme == "https" else 80, type=socket.SOCK_STREAM)
                self.assertEqual(len(sockets), 1)

    def test_ip_literal_targets_rejected_before_any_socket(self):
        hosts = (
            "127.0.0.1", "10.0.0.8", "169.254.169.254", "2130706433",
            "0x7f000001", "127.1", "010.0.0.05", "[::1]",
            "[64:ff9b::a00:1]", "[2002:0a00:0001::]", "[::ffff:10.0.0.1]",
            FAKE_IP, str(int(ipaddress.ip_address(FAKE_IP))), "0xc612005d", "198.18.93",
        )
        for deadline in (False, True):
            for scheme in ("http", "https"):
                for host in hosts:
                    with self.subTest(deadline=deadline, scheme=scheme, host=host), self.wire(
                        lambda host, port, *a, **k: addresses(PUBLIC_IP, port),
                    ) as (sockets, dns, factory, _):
                        with self.assertRaises(UrlSecurityError):
                            self.request(f"{scheme}://{host}/admin", deadline=deadline)
                        self.assert_no_wire(sockets, factory)
                        dns.assert_not_called()

    def test_public_numeric_literal_forms_still_connect(self):
        for host in (PUBLIC_IP, "134744072", "0x08080808", "8.8"):
            with self.subTest(host=host), self.wire() as (sockets, _, _, _):
                self.assertEqual(self.request(f"http://{host}/"), b"ok")
                self.assertTrue(any(kind == "connect" for kind, _ in sockets[0].events))

    def test_direct_localhost_is_rejected_before_any_socket(self):
        for url in ("http://localhost/admin", "http://api.localhost/admin", "http://%6cocalhost/admin"):
            with self.subTest(url=url), self.wire() as (sockets, dns, factory, _):
                with self.assertRaises(UrlSecurityError):
                    self.request(url)
                self.assert_no_wire(sockets, factory)
                dns.assert_not_called()

    def test_explicit_proxy_hands_hostname_to_proxy_without_local_target_lookup(self):
        for scheme in ("http", "https"):
            with self.subTest(scheme=scheme), self.wire(
                responses=[CONNECT_OK, OK] if scheme == "https" else [OK],
            ) as (sockets, dns, _, tls):
                self.assertEqual(
                    self.request(f"{scheme}://api.example.com/page?q=1", proxy="localhost:7890"),
                    b"ok",
                )
                # Only the proxy hop is resolved here; the provider hostname is
                # forwarded and the proxy resolves it.
                dns.assert_called_once_with("localhost", 7890, type=socket.SOCK_STREAM)
                sock = sockets[0]
                self.assertIn(("connect", ("127.0.0.1", 7890)), sock.events)
                wire = b"".join(sock.sent)
                if scheme == "http":
                    self.assertIn(b"GET http://api.example.com/page?q=1 ", wire)
                else:
                    self.assertIn(b"CONNECT api.example.com:443 ", wire)
                    self.assertIn(b"GET /page?q=1 ", wire)
                    self.assertEqual(tls.call_args.kwargs["server_hostname"], "api.example.com")
                self.assertIn(b"Host: api.example.com", wire)

    def test_explicit_proxy_may_be_a_loopback_literal(self):
        for scheme in ("http", "https"):
            with self.subTest(scheme=scheme), self.wire(
                responses=[CONNECT_OK, OK] if scheme == "https" else [OK],
            ) as (sockets, dns, _, _):
                self.assertEqual(
                    self.request(f"{scheme}://api.example.com/", proxy="127.0.0.1:7890"),
                    b"ok",
                )
                dns.assert_called_once_with("127.0.0.1", 7890, type=socket.SOCK_STREAM)
                self.assertIn(("connect", ("127.0.0.1", 7890)), sockets[0].events)

    def test_private_literal_target_is_rejected_even_through_a_proxy(self):
        for scheme in ("http", "https"):
            with self.subTest(scheme=scheme), self.wire(
                responses=[CONNECT_OK, OK] if scheme == "https" else [OK],
            ) as (sockets, dns, factory, _):
                with self.assertRaises(UrlSecurityError):
                    self.request(f"{scheme}://169.254.169.254/admin", proxy="localhost:7890")
                self.assert_no_wire(sockets, factory)
                dns.assert_not_called()

    def test_redirect_allows_same_origin_and_http_to_https_upgrade(self):
        same_host = self.redirect("http://origin.example/next")
        self.assertEqual(same_host.full_url, "http://origin.example/next")
        self.assertFalse(hasattr(same_host, "_multi_search_pinned_addresses"))
        upgraded = self.redirect("https://origin.example/next")
        self.assertEqual(upgraded.full_url, "https://origin.example/next")
        self.assertFalse(hasattr(upgraded, "_multi_search_pinned_addresses"))

    def test_redirect_rejects_cross_host_downgrade_port_change_and_private_literal(self):
        with self.assertRaises(UrlSecurityError) as cross:
            self.redirect("http://other.example/next")
        self.assertIn("cross-host", str(cross.exception))
        self.assertNotIn("other.example", str(cross.exception))
        with self.assertRaises(UrlSecurityError) as downgrade:
            self.redirect("http://origin.example/next", url="https://origin.example/start")
        self.assertIn("downgrade", str(downgrade.exception).lower())
        with self.assertRaises(UrlSecurityError) as port:
            self.redirect("http://origin.example:444/next")
        self.assertIn("scheme and port", str(port.exception))
        for target, reason in (
            ("http://127.0.0.1/admin?token=secret", "loopback"),
            ("http://10.0.0.5/admin", "private"),
            ("http://169.254.169.254/latest/meta-data", "link-local"),
            ("http://[64:ff9b::a00:1]/admin", "private"),
            ("http://localhost/admin", "localhost"),
        ):
            with self.subTest(target=target), self.assertRaises(UrlSecurityError) as unsafe:
                self.redirect(target)
            self.assertIn("unsafe redirect target", str(unsafe.exception))
            self.assertIn(reason, str(unsafe.exception))
            self.assertNotIn("token=secret", str(unsafe.exception))

    def test_same_host_redirect_is_followed_and_unsafe_target_is_not_connected(self):
        redirect = (
            b"HTTP/1.1 302 Found\r\nLocation: http://origin.example/next\r\n"
            b"Content-Length: 0\r\n\r\n"
        )
        with self.wire(responses=[redirect, OK]) as (sockets, dns, _, _):
            with http.urlopen_retry(
                "http://origin.example/start", timeout=2,
                extra_handlers=(urllib.request.ProxyHandler({}),),
            ) as response:
                self.assertEqual(response.read(), b"ok")
        self.assertEqual(len(sockets), 2)
        for sock in sockets:
            self.assertIn(("connect", (PUBLIC_IP, 80)), sock.events)

        evil = (
            b"HTTP/1.1 302 Found\r\nLocation: http://evil.example/collect?token=secret\r\n"
            b"Content-Length: 0\r\n\r\n"
        )
        with self.wire(responses=[evil]) as (sockets, dns, factory, _):
            with self.assertRaises(UrlSecurityError) as error:
                http.urlopen_retry(
                    "http://origin.example/start", timeout=2,
                    extra_handlers=(urllib.request.ProxyHandler({}),),
                )
        self.assertIn("cross-host", str(error.exception))
        self.assertNotIn("evil.example", str(error.exception))
        self.assertNotIn("token=secret", str(error.exception))
        # Only the checked origin was dialed; the rejected target never was.
        self.assertEqual(len(sockets), 1)
        self.assertIn(("connect", (PUBLIC_IP, 80)), sockets[0].events)
        dns.assert_called_once_with("origin.example", 80, type=socket.SOCK_STREAM)

    def test_redirect_keeps_the_original_deadline(self):
        deadline = time.monotonic() + 3
        redirected = self.redirect("http://origin.example/next", deadline=deadline)
        self.assertEqual(redirected._multi_search_deadline, deadline)
        self.assertLessEqual(redirected.timeout, 3)

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
                if failure == "read_error":
                    self.assertTrue(sockets[0].closed)

    def test_embedded_ipv4_literal_policy_is_explicit(self):
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

class SearchRouteFakeIpTests(unittest.TestCase):
    """The `all` route fans out past the old 8-slot DNS pool boundary."""

    def test_all_route_sources_have_no_local_dns_capacity_errors(self):
        names = list(search_runner_module.ROUTE_SOURCE_ORDER["all"])
        # Every source must reach the resolver at the same time. A barrier
        # proves the fan-out really is concurrent, without a sleep: the old
        # 8-slot DNS pool could not admit more than 8 of these 12 lookups.
        barrier = threading.Barrier(len(names))

        def slow_dns(host, port, *args, **kwargs):
            barrier.wait(timeout=2)
            return addresses(PUBLIC_IP, port)

        def factory(*_args, **_kwargs):
            return WireSocket([OK])

        def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kwargs):
            if timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
                timeout = socket.getdefaulttimeout()
            family, socktype, proto, _, sockaddr = socket.getaddrinfo(*address, type=socket.SOCK_STREAM)[0]
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock

        providers = {}
        lookups = []

        def provider_for(name):
            def call(query, config, ctx, api_key):
                with http.urlopen_retry(
                    f"http://search.{name}.example/query", timeout=5,
                    extra_handlers=(urllib.request.ProxyHandler({}),),
                ) as response:
                    response.read()
                return [{"source": name, "title": "hit", "url": f"https://result.{name}.example/"}]
            return call

        for name in names:
            providers[name] = ProviderSpec(name, name, provider_for(name), key_required=False)
        pool = BoundedDaemonExecutor(max_workers=len(names), thread_name_prefix="test-all-route")
        runner = SearchRunner(
            SearchRunnerConfig("all", {}, 5, "google", {}),
            providers,
            route_resolver=lambda _route: list(names),
            executor=pool,
        )
        try:
            with mock.patch.object(socket, "create_connection", side_effect=create_connection), \
                    mock.patch.dict(os.environ, {}, clear=False), \
                    mock.patch.object(urllib.request, "getproxies", return_value={}), \
                    mock.patch.object(socket, "getaddrinfo", side_effect=slow_dns) as dns, \
                    mock.patch.object(socket, "socket", side_effect=lambda *a: factory()):
                os.environ.pop("MULTI_SEARCH_ALLOW_FAKE_IP", None)
                rows = runner.run("query")
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(len(rows), len(names))
        self.assertEqual(dns.call_count, len(names))
        for row in rows:
            self.assertNotIn("error", row, row)
            self.assertEqual(row["source"], row["source"])
            self.assertNotIn("DNS", str(row))
            self.assertNotIn("capacity", str(row))

if __name__ == "__main__":
    unittest.main()

"""Offline regressions for the local HTTP connect and proxy trust boundary."""
import email.message
import io
import os
import socket
import time
import unittest
import urllib.request
import urllib.response
from types import SimpleNamespace
from unittest import mock

import http.client as http_client

from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.support import http, url_security
from multi_search_mcp.src.support.url_security import UrlSecurityError


PUBLIC_IP = "93.184.216.34"
FAKE_IP = "198.18.0.93"


def _answers(host, port, address):
    del host, port
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
    return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]


class _RecordingConnection:
    def __init__(self, host, **options):
        del options
        self.host = host
        self.calls = []
        self._tunnel = lambda: None

    def _create_connection(self, address, timeout=None, source_address=None, **socket_options):
        del timeout, source_address, socket_options
        self.calls.append(address)
        sock = mock.Mock(name="socket")
        sock.makefile.return_value = io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        return sock


class _RecordingHandler(urllib.request.HTTPHandler):
    def do_open(self, factory, request, **options):
        self.connection = factory(request.host, **options)
        self.connection._create_connection((request.host.split(":", 1)[0], request.port or 80), timeout=1)
        return self.connection


class HttpConnectBoundaryTests(unittest.TestCase):
    def test_first_literal_private_connection_is_rejected_before_socket_stub(self):
        handler = _RecordingHandler()
        request = SimpleNamespace(
            host="127.0.0.1:80", port=80,
            _multi_search_deadline=time.monotonic() + 3,
        )
        with self.assertRaises(UrlSecurityError) as error:
            http._open_with_deadline(handler, _RecordingConnection, request)
        self.assertIn("loopback", str(error.exception))
        self.assertEqual(handler.connection.calls, [])

    def test_rebinding_between_preflight_and_connect_cannot_dial_private(self):
        answers = iter([[PUBLIC_IP], ["127.0.0.1"]])

        class RebindHandler(urllib.request.HTTPHandler):
            def do_open(self, factory, request, **options):
                connection = factory(request.host, **options)
                connection._create_connection(("127.0.0.1", 80), timeout=1)
                return connection

        with mock.patch.object(
            url_security, "resolve_host_addresses",
            side_effect=lambda host, port, **kwargs: _answers(host, port, next(answers)),
        ), mock.patch.object(http.socket, "socket") as factory:
            with self.assertRaises(UrlSecurityError):
                http._open_with_deadline(
                    RebindHandler(), http_client.HTTPConnection,
                    SimpleNamespace(
                        host="rebind.example:80", port=80,
                        _multi_search_deadline=time.monotonic() + 2,
                    ),
                )
        factory.assert_not_called()

    def test_no_deadline_still_rejects_literal_private_and_rebinding(self):
        request = SimpleNamespace(host="10.0.0.8:80", port=80)
        with self.assertRaises(UrlSecurityError):
            http._open_with_deadline(_RecordingHandler(), _RecordingConnection, request)

    def test_explicit_localhost_proxy_is_trusted_but_private_target_is_not(self):
        request = urllib.request.Request("http://10.0.0.8/admin")
        request.set_proxy("localhost:7890", "http")
        self.assertTrue(http._is_trusted_proxy_hop(request, "localhost", 7890))
        self.assertFalse(http._is_trusted_proxy_hop(request, "localhost", 7891))
        self.assertFalse(http._is_trusted_proxy_hop(request, "10.0.0.8", 80))
        direct = urllib.request.Request("http://localhost:7890/")
        self.assertFalse(http._is_trusted_proxy_hop(direct, "localhost", 7890))

    def test_fake_ip_opt_in_is_resolved_only_and_never_global(self):
        resolver = lambda _host: [FAKE_IP]
        with mock.patch.dict(os.environ, {url_security.FAKE_IP_ENV: ""}):
            with self.assertRaises(UrlSecurityError):
                url_security.validate_public_http_url("https://tun.example/", resolver=resolver)
        with mock.patch.dict(os.environ, {url_security.FAKE_IP_ENV: "1"}):
            self.assertEqual(
                url_security.validate_public_http_url("https://tun.example/", resolver=resolver),
                "https://tun.example/",
            )
            with self.assertRaises(UrlSecurityError):
                url_security.validate_public_http_url(f"https://{FAKE_IP}/")
            with self.assertRaises(UrlSecurityError):
                url_security.validate_public_http_url(
                    "https://private.example/", resolver=lambda _host: ["10.0.0.5"],
                )

    def test_embedded_private_ipv4_is_rejected_without_python_version_luck(self):
        for address in (
            "64:ff9b::a00:1", "2002:0a00:0001::", "2002:c0a8:0101::", "::ffff:10.0.0.1",
        ):
            with self.subTest(address=address):
                with self.assertRaises(UrlSecurityError):
                    url_security.validate_public_http_url(f"https://[{address}]/")
        with mock.patch.object(url_security.ipaddress.IPv6Address, "is_reserved", False):
            self.assertEqual(
                url_security.validate_public_http_url("https://[64:ff9b::5db8:d822]/"),
                "https://[64:ff9b::5db8:d822]/",
            )

    def test_dns_result_timeout_is_recomputed_after_admission(self):
        future = mock.Mock()
        pool = mock.Mock()
        clock = [10.0]

        def submit(*_args):
            clock[0] = 10.8
            return future

        pool.submit_nowait.side_effect = submit
        with mock.patch.object(url_security, "_DNS_POOL", pool), mock.patch.object(
            url_security.time, "monotonic", side_effect=lambda: clock[0],
        ):
            url_security._run_bounded_dns(lambda: [], deadline=11.0)
        self.assertAlmostEqual(future.result.call_args.kwargs["timeout"], 0.2)

    def test_exa_and_firecrawl_deadlines_reduce_timeout_without_network(self):
        from multi_search_mcp.src.scrape.scrapers import exa, firecrawl

        for module in (exa, firecrawl):
            with self.subTest(backend=module.__name__):
                response = mock.MagicMock()
                response.headers.get.return_value = None
                response.read.return_value = b'{"results":[{"title":"T","text":"body"}],"statuses":[{"status":"success"}],"success":true,"data":{"markdown":"body"}}'
                response.__enter__.return_value = response
                response.__exit__.return_value = False
                with mock.patch.object(module, "urlopen_retry", return_value=response) as opened:
                    result = module.scrape_url_exa(
                        "https://example.com", "synthetic", timeout=30, deadline=time.monotonic() + 1,
                    ) if module is exa else module.scrape_url_firecrawl(
                        "https://example.com", "synthetic", timeout=30, deadline=time.monotonic() + 1,
                    )
                self.assertNotIn("error", result)
                self.assertGreater(opened.call_args.kwargs["timeout"], 0)
                self.assertLessEqual(opened.call_args.kwargs["timeout"], 1)

    def test_safe_deadline_request_stays_bounded_and_delegated_rebuild_remains(self):
        response = mock.MagicMock()
        response.headers.get.return_value = None
        response.read.side_effect = lambda size=-1: b"x" * size
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with mock.patch.object(http._shared_opener, "open", return_value=response) as opened:
            with http.urlopen_retry("https://93.184.216.34/", timeout=2) as result:
                with self.assertRaises(http.ResponseTooLargeError):
                    http.read_limited(result)
        opened.assert_called_once()
        with mock.patch(
            "multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl",
            return_value={"markdown": "body"},
        ) as backend:
            result = scrape_url_smart(
                "HTTPS://Example.COM:8443/a\\b c", backends=("firecrawl",),
                url_resolver=mock.Mock(side_effect=AssertionError("delegated DNS")),
            )
        self.assertEqual(result["via"], "firecrawl")
        self.assertEqual(backend.call_args.args[0], "https://example.com:8443/a%5Cb%20c")


class _RedirectHandler(urllib.request.BaseHandler):
    def default_open(self, request):
        headers = email.message.Message()
        headers["Location"] = "https://redirect.example/next"
        response = urllib.response.addinfourl(io.BytesIO(b""), headers, request.full_url, 302)
        response.msg = "Found"
        return response


if __name__ == "__main__":
    unittest.main()

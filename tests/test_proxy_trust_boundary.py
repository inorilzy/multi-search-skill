"""F-01: exact configured proxy hops may resolve to loopback; targets may not."""
import email.message
import io
import socket
import unittest
import urllib.error
import urllib.request
import urllib.response
from unittest import mock

from multi_search_mcp.src.support import http, url_security
from multi_search_mcp.src.support.url_security import UrlSecurityError


class ProxyServer(io.BufferedIOBase):
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read1(self, size):
        if not self.chunks:
            return b""
        data = self.chunks.pop(0)
        return data[:size]

    def readable(self):
        return True


class FakeProxySocket:
    instances = []

    def __init__(self):
        self.connected = []
        self.timeout = None
        self.closed = False
        self.sent = b""
        self.__class__.instances.append(self)

    def settimeout(self, value):
        self.timeout = value

    def setsockopt(self, *args):
        pass

    def bind(self, address):
        pass

    def connect(self, address):
        self.connected.append(address)

    def sendall(self, data):
        self.sent += data

    def makefile(self, mode):
        return ProxyServer([b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"])

    def close(self):
        self.closed = True


class ProxyTrustTests(unittest.TestCase):
    def setUp(self):
        FakeProxySocket.instances = []

    @staticmethod
    def _proxy_request(url="http://example.com/page"):
        request = urllib.request.Request(url)
        request.set_proxy("localhost:7890", "http")
        return request

    def test_localhost_proxy_is_a_trusted_exact_hop(self):
        with mock.patch.object(http, "_configured_proxy_addresses", return_value={("localhost", 7890)}):
            request = self._proxy_request()
            self.assertTrue(http._is_trusted_proxy_hop(request, "localhost", 7890))
            self.assertTrue(http._is_trusted_proxy_hop(request, "LOCALHOST", 7890))
            self.assertFalse(http._is_trusted_proxy_hop(request, "localhost", 7891))

    def test_ipv4_and_ipv6_local_proxies_are_trusted(self):
        for proxy, host in (("127.0.0.1:7890", "127.0.0.1"), ("[::1]:7890", "::1")):
            with self.subTest(proxy=proxy):
                request = urllib.request.Request("http://example.com/page")
                request.set_proxy(proxy, "http")
                self.assertTrue(http._is_trusted_proxy_hop(request, host, 7890))
                self.assertFalse(http._is_trusted_proxy_hop(request, host, 7890 + 1))

    def test_direct_loopback_is_not_a_proxy_hop(self):
        request = urllib.request.Request("http://127.0.0.1:7890/")
        self.assertFalse(http._is_trusted_proxy_hop(request, "127.0.0.1", 7890))
        request = urllib.request.Request("http://localhost:7890/")
        self.assertFalse(http._is_trusted_proxy_hop(request, "localhost", 7890))

    def test_hostname_proxy_connect_succeeds_through_loopback(self):
        # Two different DNS boundaries are exercised here: the logical target is
        # resolved and validated for its public address, the configured proxy hop
        # is resolved separately and may be loopback. Only the proxy is dialled.
        target_ip = "93.184.216.34"
        calls = []

        def dns(host, port, *args, **kwargs):
            calls.append((host, int(port)))
            if (host, int(port)) == ("example.com", 80):
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (target_ip, 80))]
            if (host, int(port)) == ("localhost", 7890):
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 7890))]
            raise AssertionError(f"unexpected DNS lookup {(host, port)}")

        request = urllib.request.Request("http://example.com/page")
        with mock.patch.object(urllib.request, "getproxies", return_value={"http": "http://localhost:7890"}), \
                mock.patch.object(urllib.request, "proxy_bypass", return_value=False), \
                mock.patch.object(url_security.socket, "getaddrinfo", side_effect=dns), \
                mock.patch.object(socket, "create_connection", side_effect=lambda *a, **k: FakeProxySocket()), \
                mock.patch.object(http.socket, "socket", side_effect=lambda *a: FakeProxySocket()):
            with http.urlopen_retry(
                request, timeout=2, extra_handlers=(urllib.request.ProxyHandler({"http": "http://localhost:7890"}),),
            ) as response:
                self.assertEqual(response.read(), b"ok")
        # Both boundaries were really consulted: the target through validation and
        # the proxy hop through plain resolution. Zero DNS calls cannot pass.
        self.assertIn(("example.com", 80), calls)
        self.assertIn(("localhost", 7890), calls)
        self.assertEqual(sorted(set(calls)), [("example.com", 80), ("localhost", 7890)])
        self.assertEqual(len(FakeProxySocket.instances), 1)
        self.assertEqual(FakeProxySocket.instances[0].connected, [("127.0.0.1", 7890)])
        sent = FakeProxySocket.instances[0].sent
        self.assertIn(b"Host: example.com", sent)
        # The proxy is asked to reach the validated address, never the raw name.
        self.assertIn(f"http://{target_ip}:80/page".encode(), sent)
        self.assertNotIn(b"http://example.com", sent)

    def test_direct_loopback_target_still_rejected(self):
        def dns(_host, _port, *args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

        with mock.patch.object(url_security.socket, "getaddrinfo", side_effect=dns), \
                mock.patch.object(http.socket, "socket") as factory:
            with self.assertRaises(UrlSecurityError):
                http.urlopen_retry(
                    "http://localhost/", timeout=2,
                    extra_handlers=(urllib.request.ProxyHandler({}),),
                )
        factory.assert_not_called()

    def test_direct_private_target_still_rejected(self):
        with mock.patch.object(http.socket, "socket") as factory, \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("unsafe target reached transport")):
            with self.assertRaises(UrlSecurityError):
                http.urlopen_retry(
                    "http://10.0.0.8/", timeout=2,
                    extra_handlers=(urllib.request.ProxyHandler({}),),
                )
        factory.assert_not_called()

    def test_redirect_to_loopback_is_rejected_even_with_trusted_proxy(self):
        class Redirecting(urllib.request.BaseHandler):
            def default_open(self, req):
                headers = email.message.Message()
                headers["Location"] = "http://localhost/admin?token=secret"
                response = urllib.response.addinfourl(io.BytesIO(b""), headers, req.full_url, 302)
                response.msg = "Found"
                return response

        request = urllib.request.Request("http://example.com/start")
        with mock.patch.object(urllib.request, "getproxies", return_value={"http": "http://localhost:7890"}), \
                mock.patch("multi_search_mcp.src.support.http._validate_redirect_target", wraps=url_security._validate_redirect_target), \
                mock.patch.object(http.socket, "socket", side_effect=lambda *a: FakeProxySocket()):
            with self.assertRaises(UrlSecurityError) as caught:
                http.urlopen_retry(
                    request, timeout=2, redirect_resolver=lambda _host: ["127.0.0.1"],
                    extra_handlers=(Redirecting(),),
                )
        self.assertIn("loopback", str(caught.exception))
        self.assertNotIn("token=secret", str(caught.exception))

    def test_explicit_proxy_handler_without_env_is_trusted(self):
        request = urllib.request.Request("http://example.com/page")
        request.set_proxy("localhost:7890", "http")
        self.assertTrue(http._is_trusted_proxy_hop(request, "localhost", 7890))
        self.assertFalse(http._is_trusted_proxy_hop(request, "localhost", 7891))


if __name__ == "__main__":
    unittest.main()

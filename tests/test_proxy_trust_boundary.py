"""Outbound proxy boundary: the proxy hop is standard-library behaviour.

Outbound destinations are fixed provider hostnames. With an explicit proxy the
hostname is handed to the proxy (which resolves it); without one the standard
library socket connect resolves it. Neither path lets a non-public IP literal
become the destination.
"""
import email.message
import io
import socket
import unittest
import urllib.request
import urllib.response
from unittest import mock

from multi_search_mcp.src.support import http
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


class ProxyBoundaryTests(unittest.TestCase):
    def setUp(self):
        FakeProxySocket.instances = []

    def _proxy_request(self, url="http://example.com/page"):
        request = urllib.request.Request(url)
        request.set_proxy("localhost:7890", "http")
        return request

    def test_explicit_proxy_forwards_the_hostname_and_resolves_only_the_proxy(self):
        lookups = []

        def dns(host, port, *args, **kwargs):
            lookups.append((host, int(port)))
            if (host, int(port)) == ("localhost", 7890):
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 7890))]
            raise AssertionError(f"target must not be resolved locally: {(host, port)}")

        def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kwargs):
            family, socktype, proto, _, sockaddr = socket.getaddrinfo(*address, type=socket.SOCK_STREAM)[0]
            sock = FakeProxySocket()
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock

        request = self._proxy_request()
        with mock.patch.object(urllib.request, "getproxies", return_value={"http": "http://localhost:7890"}), \
                mock.patch.object(urllib.request, "proxy_bypass", return_value=False), \
                mock.patch.object(socket, "getaddrinfo", side_effect=dns), \
                mock.patch.object(socket, "create_connection", side_effect=create_connection), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("real socket forbidden")):
            with http.urlopen_retry(
                request, timeout=2, extra_handlers=(urllib.request.ProxyHandler({"http": "http://localhost:7890"}),),
            ) as response:
                self.assertEqual(response.read(), b"ok")

        # Only the configured proxy hop was resolved; the target name went to it.
        self.assertEqual(lookups, [("localhost", 7890)])
        self.assertEqual(len(FakeProxySocket.instances), 1)
        self.assertEqual(FakeProxySocket.instances[0].connected, [("127.0.0.1", 7890)])
        sent = FakeProxySocket.instances[0].sent
        self.assertIn(b"Host: example.com", sent)
        self.assertIn(b"GET http://example.com/page", sent)

    def test_proxy_may_be_a_loopback_literal(self):
        def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kwargs):
            sock = FakeProxySocket()
            sock.settimeout(timeout)
            sock.connect(address)
            return sock

        request = self._proxy_request()
        with mock.patch.object(urllib.request, "getproxies", return_value={"http": "http://127.0.0.1:7890"}), \
                mock.patch.object(urllib.request, "proxy_bypass", return_value=False), \
                mock.patch.object(socket, "create_connection", side_effect=create_connection), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("real socket forbidden")):
            with http.urlopen_retry(
                request, timeout=2, extra_handlers=(urllib.request.ProxyHandler({"http": "http://127.0.0.1:7890"}),),
            ) as response:
                self.assertEqual(response.read(), b"ok")
        self.assertEqual(FakeProxySocket.instances[0].connected, [("127.0.0.1", 7890)])

    def test_direct_loopback_target_still_rejected(self):
        with mock.patch.object(http.socket, "socket") as factory:
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
                mock.patch.object(http.socket, "socket", side_effect=lambda *a: FakeProxySocket()):
            with self.assertRaises(UrlSecurityError) as caught:
                http.urlopen_retry(
                    request, timeout=2,
                    extra_handlers=(Redirecting(),),
                )
        self.assertIn("localhost", str(caught.exception))
        self.assertNotIn("token=secret", str(caught.exception))

    def test_explicit_proxy_handler_without_env_is_used(self):
        def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kwargs):
            sock = FakeProxySocket()
            sock.settimeout(timeout)
            sock.connect(address)
            return sock

        with mock.patch.object(urllib.request, "getproxies", return_value={}), \
                mock.patch.object(urllib.request, "proxy_bypass", return_value=False), \
                mock.patch.object(socket, "create_connection", side_effect=create_connection), \
                mock.patch.object(http.socket, "socket", side_effect=AssertionError("real socket forbidden")):
            with http.urlopen_retry(
                "http://example.com/page", timeout=2,
                extra_handlers=(urllib.request.ProxyHandler({"http": "http://127.0.0.1:7890"}),),
            ) as response:
                self.assertEqual(response.read(), b"ok")
        self.assertEqual(FakeProxySocket.instances[0].connected, [("127.0.0.1", 7890)])


if __name__ == "__main__":
    unittest.main()

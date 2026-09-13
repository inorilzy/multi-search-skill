import email.message
import io
import ssl
import unittest
import urllib.error
import urllib.request
import urllib.response
from unittest import mock

from multi_search_mcp.src.support import http
from multi_search_mcp.src.support.url_security import UrlSecurityError


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


class SlowSocket:
    """Synthetic socket whose reads obey the currently configured timeout."""

    def __init__(self, clock, chunks, timeout):
        self.clock, self.chunks, self.timeout = clock, list(chunks), timeout
        self.read_timeouts = []
        self.stream_closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def setsockopt(self, *args):
        pass

    def sendall(self, data):
        pass

    def close(self):
        pass

    def makefile(self, mode):
        sock = self

        class Raw(io.RawIOBase):
            def readable(self):
                return True

            def readinto(self, target):
                if not sock.chunks:
                    return 0
                delay, data = sock.chunks.pop(0)
                sock.read_timeouts.append(sock.timeout)
                if delay > sock.timeout:
                    sock.clock.now += sock.timeout
                    raise TimeoutError("synthetic socket timed out")
                sock.clock.now += delay
                target[:len(data)] = data
                return len(data)

            def close(self):
                sock.stream_closed = True
                super().close()

        return io.BufferedReader(Raw())


class HttpDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        patcher = mock.patch("time.monotonic", side_effect=self.clock.monotonic)
        patcher.start()
        self.addCleanup(patcher.stop)
        network = mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected network"))
        network.start()
        self.addCleanup(network.stop)

    def test_ssl_retries_receive_only_the_remaining_budget(self):
        timeouts = []
        expected = object()

        def open_response(request, timeout):
            timeouts.append(timeout)
            if len(timeouts) < 3:
                self.clock.now += 0.4
                raise ssl.SSLEOFError("synthetic SSL EOF")
            return expected

        with mock.patch.object(http._shared_opener, "open", side_effect=open_response):
            self.assertIs(http.urlopen_retry("https://93.184.216.34/", timeout=1), expected)
        self.assertEqual(len(timeouts), 3)
        for actual, expected_timeout in zip(timeouts, (1, 0.6, 0.2)):
            self.assertAlmostEqual(actual, expected_timeout)

    def test_expired_ssl_attempt_does_not_start_another_request(self):
        def open_response(request, timeout):
            self.clock.now += timeout
            raise ssl.SSLEOFError("synthetic SSL EOF")

        with mock.patch.object(http._shared_opener, "open", side_effect=open_response) as opened:
            with self.assertRaises(TimeoutError):
                http.urlopen_retry("https://93.184.216.34/", timeout=1)
        self.assertEqual(opened.call_count, 1)
        self.assertAlmostEqual(self.clock.now, 1)

    def _socket(self, *, status="200 OK", chunked=False, slow=True):
        framing = "Transfer-Encoding: chunked" if chunked else "Content-Length: 6"
        chunks = [(0.1, f"HTTP/1.1 {status}\r\n{framing}\r\n\r\n".encode())]
        delay = 0.4 if slow else 0.1
        chunks.extend((delay, body) for body in (
            (b"2\r\nab\r\n", b"2\r\ncd\r\n", b"2\r\nef\r\n0\r\n\r\n")
            if chunked else (b"ab", b"cd", b"ef")
        ))
        return SlowSocket(self.clock, chunks, 1)

    def _open(self, *, scheme="http"):
        return http.urlopen_retry(
            f"{scheme}://93.184.216.34/page", timeout=1,
            extra_handlers=(urllib.request.ProxyHandler({}),),
        )

    def test_slow_body_uses_header_and_body_total_budget(self):
        for chunked in (False, True):
            with self.subTest(chunked=chunked):
                self.clock.now = 0
                sock = self._socket(chunked=chunked)
                with mock.patch("socket.create_connection", return_value=sock):
                    with self._open() as response:
                        with self.assertRaises(TimeoutError):
                            response.read()
                self.assertAlmostEqual(self.clock.now, 1)
                self.assertTrue(sock.stream_closed)

    def test_http_error_body_uses_the_same_deadline(self):
        sock = self._socket(status="429 Too Many Requests")
        with mock.patch("socket.create_connection", return_value=sock):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self._open()
            with error.exception as response:
                with self.assertRaises(TimeoutError):
                    response.read()
        self.assertAlmostEqual(self.clock.now, 1)
        self.assertTrue(sock.stream_closed)

    def test_https_response_body_has_the_same_budget(self):
        sock = self._socket()
        with mock.patch("socket.create_connection", return_value=sock), mock.patch.object(
            http._ssl_ctx, "wrap_socket", side_effect=lambda connected, **kwargs: connected,
        ):
            with self._open(scheme="https") as response:
                with self.assertRaises(TimeoutError):
                    response.read()
        self.assertAlmostEqual(self.clock.now, 1)
        self.assertTrue(sock.stream_closed)

    def test_tcp_connect_time_is_deducted_before_tls_handshake(self):
        sock = self._socket(slow=False)
        handshake_timeouts = []

        def connect(_address, timeout, source_address=None):
            sock.timeout = timeout
            self.clock.now += 0.6
            return sock

        def handshake(connected, **kwargs):
            handshake_timeouts.append(connected.timeout)
            self.clock.now += min(0.6, connected.timeout)
            if connected.timeout < 0.6:
                raise TimeoutError("synthetic TLS handshake timed out")
            return connected

        with mock.patch("socket.create_connection", side_effect=connect), mock.patch.object(
            http._ssl_ctx, "wrap_socket", side_effect=handshake,
        ), mock.patch.object(sock, "close", wraps=sock.close) as closed:
            with self.assertRaises((TimeoutError, urllib.error.URLError)):
                self._open(scheme="https")
        self.assertEqual(len(handshake_timeouts), 1)
        self.assertAlmostEqual(handshake_timeouts[0], 0.4)
        self.assertAlmostEqual(self.clock.now, 1)
        self.assertTrue(closed.called)

    def test_proxy_connect_time_is_deducted_before_tls_with_sni_preserved(self):
        sock = SlowSocket(self.clock, [
            (0.3, b"HTTP/1.1 200 Connection established\r\n\r\n"),
            (0.1, b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"),
        ], 1)
        handshake_timeouts, hostnames, sent = [], [], []

        def connect(_address, timeout, source_address=None):
            sock.timeout = timeout
            self.clock.now += 0.2
            return sock

        def handshake(connected, **kwargs):
            handshake_timeouts.append(connected.timeout)
            hostnames.append(kwargs["server_hostname"])
            self.clock.now += min(0.6, connected.timeout)
            if connected.timeout < 0.6:
                raise TimeoutError("synthetic TLS handshake timed out")
            return connected

        request = urllib.request.Request("https://origin.example.test/page", headers={
            "Proxy-Authorization": "Basic SYNTHETIC",
        })
        with mock.patch("socket.create_connection", side_effect=connect), mock.patch.object(
            http._ssl_ctx, "wrap_socket", side_effect=handshake,
        ), mock.patch.object(sock, "sendall", side_effect=sent.append), mock.patch.object(
            sock, "close", wraps=sock.close,
        ) as closed:
            with self.assertRaises((TimeoutError, urllib.error.URLError)):
                http.urlopen_retry(request, timeout=1, extra_handlers=(
                    urllib.request.ProxyHandler({"https": "http://93.184.216.34:3128"}),
                ))
        self.assertEqual(hostnames, ["origin.example.test"])
        self.assertIn(b"CONNECT origin.example.test:443", b"".join(sent))
        self.assertIn(b"Proxy-Authorization: Basic SYNTHETIC", b"".join(sent))
        self.assertAlmostEqual(handshake_timeouts[0], 0.5)
        self.assertAlmostEqual(self.clock.now, 1)
        self.assertTrue(closed.called)

    def test_connection_returning_after_deadline_closes_before_tls(self):
        sock = self._socket(slow=False)

        def connect(_address, timeout, source_address=None):
            self.clock.now += timeout
            return sock

        with mock.patch("socket.create_connection", side_effect=connect), mock.patch.object(
            http._ssl_ctx, "wrap_socket", side_effect=lambda connected, **kwargs: connected,
        ) as handshake, mock.patch.object(sock, "close", wraps=sock.close) as closed:
            with self.assertRaises((TimeoutError, urllib.error.URLError)):
                self._open(scheme="https")
        self.assertFalse(handshake.called)
        self.assertTrue(closed.called)

    def test_redirect_body_timeout_closes_stream_without_waiting_for_exception_gc(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                self.clock.now = 0
                sock = SlowSocket(self.clock, [
                    (0.1, f"HTTP/1.1 {status} Redirect\r\nLocation: http://93.184.216.34/next\r\nContent-Length: 4\r\n\r\n".encode()),
                    (0.6, b"ab"), (0.6, b"cd"),
                ], 1)
                caught = []
                with mock.patch("socket.create_connection", return_value=sock):
                    try:
                        if hasattr(urllib.request.HTTPRedirectHandler, f"http_error_{status}"):
                            self._open()
                        else:
                            # Python 3.10 returns 308 as HTTPError instead of
                            # draining it automatically; its body has the same budget.
                            with self.assertRaises(urllib.error.HTTPError) as redirect:
                                self._open()
                            self.assertEqual(redirect.exception.code, status)
                            with redirect.exception as response:
                                response.read()
                    except TimeoutError as error:
                        caught.append(error)
                    self.assertEqual(len(caught), 1)
                    self.assertAlmostEqual(self.clock.now, 1)
                    self.assertTrue(sock.stream_closed)

    def test_https_proxy_success_preserves_tunnel_sni_and_origin_headers(self):
        sock = SlowSocket(self.clock, [
            (0.2, b"HTTP/1.1 200 Connection established\r\n\r\n"),
            (0.1, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n"),
            (0.1, b"ok"),
        ], 1)
        sent, hostnames = [], []

        def handshake(connected, **kwargs):
            hostnames.append(kwargs["server_hostname"])
            return connected

        request = urllib.request.Request("https://origin.example.test/page", headers={
            "Proxy-Authorization": "Basic SYNTHETIC",
        })
        with mock.patch("socket.create_connection", return_value=sock), mock.patch.object(
            http._ssl_ctx, "wrap_socket", side_effect=handshake,
        ), mock.patch.object(sock, "sendall", side_effect=sent.append):
            with http.urlopen_retry(request, timeout=1, extra_handlers=(
                urllib.request.ProxyHandler({"https": "http://93.184.216.34:3128"}),
            )) as response:
                self.assertEqual(response.read(), b"ok")
        self.assertEqual(hostnames, ["origin.example.test"])
        self.assertIn(b"CONNECT origin.example.test:443", sent[0])
        self.assertIn(b"Proxy-Authorization: Basic SYNTHETIC", sent[0])
        origin_request = b"".join(sent[1:])
        self.assertIn(b"GET /page HTTP/1.1", origin_request)
        self.assertIn(b"Host: origin.example.test", origin_request)
        self.assertNotIn(b"Proxy-Authorization", origin_request)
        self.assertTrue(sock.stream_closed)

    def test_redirect_connections_share_the_original_budget(self):
        socks = [SlowSocket(self.clock, [(0.4, (
            b"HTTP/1.1 302 Found\r\nLocation: http://93.184.216.34/next\r\n"
            b"Content-Length: 0\r\n\r\n"
        ))], 1) for _ in range(3)]
        with mock.patch("socket.create_connection", side_effect=socks) as connected:
            with self.assertRaises(TimeoutError):
                self._open()
        self.assertEqual(connected.call_count, 3)
        self.assertAlmostEqual(self.clock.now, 1)

    def test_complete_response_keeps_context_read_and_metadata_protocol(self):
        sock = self._socket(slow=False)
        with mock.patch("socket.create_connection", return_value=sock):
            with self._open() as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.geturl(), "http://93.184.216.34/page")
                self.assertEqual(response.headers["Content-Length"], "6")
                self.assertEqual(response.read(2), b"ab")
                self.assertEqual(response.read(), b"cdef")
        self.assertTrue(sock.stream_closed)

    def test_read_variants_preserve_bytes_and_enforce_the_same_budget(self):
        def readinto_all(response):
            chunks, buffer = [], bytearray(2)
            while size := response.readinto(buffer):
                chunks.append(bytes(buffer[:size]))
            return b"".join(chunks)

        readers = {
            "read(1)": lambda response: b"".join(iter(lambda: response.read(1), b"")),
            "read1(2)": lambda response: b"".join(iter(lambda: response.read1(2), b"")),
            "readline": lambda response: b"".join(iter(response.readline, b"")),
            "iteration": lambda response: b"".join(response),
            "readinto": readinto_all,
        }
        for name, read in readers.items():
            for slow in (False, True):
                with self.subTest(reader=name, slow=slow):
                    self.clock.now = 0
                    delay = 0.4 if slow else 0.1
                    sock = SlowSocket(self.clock, [
                        (0.1, b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\n"),
                        (delay, b"a\n"), (delay, b"b\n"), (delay, b"c\n"),
                    ], 1)
                    with mock.patch("socket.create_connection", return_value=sock):
                        with self._open() as response:
                            if slow:
                                with self.assertRaises(TimeoutError):
                                    read(response)
                            else:
                                self.assertEqual(read(response), b"a\nb\nc\n")
                    self.assertAlmostEqual(self.clock.now, 1 if slow else 0.4)
                    self.assertTrue(sock.stream_closed)


class HttpCredentialRedirectTests(unittest.TestCase):
    def _redirect(self, target, headers, *, unredirected=False):
        seen = []

        class Handler(urllib.request.BaseHandler):
            def default_open(self, request):
                seen.append(request)
                response_headers = email.message.Message()
                response_headers["Location"] = target
                response = urllib.response.addinfourl(
                    io.BytesIO(b"safe"), response_headers, request.full_url,
                    302 if len(seen) == 1 else 200,
                )
                response.msg = "Found" if len(seen) == 1 else "OK"
                return response

        request = urllib.request.Request("https://93.184.216.34/start")
        for name, value in headers.items():
            add = request.add_unredirected_header if unredirected else request.add_header
            add(name, value)
        return request, Handler(), seen

    def test_cross_origin_credentials_are_rejected_before_following(self):
        for name in (
            "Authorization", "Cookie", "Proxy-Authorization", "X-API-Key",
            "X-Subscription-Token", "X-Appbuilder-Authorization",
        ):
            for unredirected in (False, True):
                with self.subTest(header=name, unredirected=unredirected):
                    request, handler, seen = self._redirect(
                        "https://151.101.1.69/collect", {name: "SYNTHETIC-CREDENTIAL"},
                        unredirected=unredirected,
                    )
                    with self.assertRaises(UrlSecurityError) as error:
                        http.urlopen_retry(request, timeout=1, extra_handlers=(handler,))
                    self.assertEqual(len(seen), 1)
                    self.assertNotIn("SYNTHETIC-CREDENTIAL", str(error.exception))

    def test_https_downgrade_is_rejected_without_credentials_too(self):
        request, handler, seen = self._redirect("http://151.101.1.69/collect", {})
        with self.assertRaises(UrlSecurityError):
            http.urlopen_retry(request, timeout=1, extra_handlers=(handler,))
        self.assertEqual(len(seen), 1)

    def test_port_change_is_cross_origin(self):
        request, handler, seen = self._redirect(
            "https://93.184.216.34:444/collect", {"Authorization": "SYNTHETIC-CREDENTIAL"},
        )
        with self.assertRaises(UrlSecurityError):
            http.urlopen_retry(request, timeout=1, extra_handlers=(handler,))
        self.assertEqual(len(seen), 1)

    def test_same_origin_redirect_keeps_credentials(self):
        request, handler, seen = self._redirect(
            "https://93.184.216.34:443/next", {"Authorization": "SYNTHETIC-CREDENTIAL"},
        )
        with http.urlopen_retry(request, timeout=1, extra_handlers=(handler,)) as response:
            self.assertEqual(response.read(), b"safe")
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[1].get_header("Authorization"), "SYNTHETIC-CREDENTIAL")


if __name__ == "__main__":
    unittest.main()

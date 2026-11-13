"""Existing-session CDP coverage uses only disposable IPv4 loopback servers."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import socket
import threading
import time
import unittest
from unittest import mock

from multi_search_mcp.src.plugins import chrome_session as chrome


_BRAVE_HOME = "https://api-dashboard.search.brave.com/app/dashboard"
_BRAVE_DATA = "https://api-dashboard.search.brave.com/app/dashboard/__data.json"
_EXA_HOME = "https://dashboard.exa.ai/home"
_EXA_APIS = ["https://dashboard.exa.ai/api/get-credits", "https://dashboard.exa.ai/api/orb/get-orb-plan"]
_SECRET = "synthetic-private-session"


def _cookie(name="search_api_users_auth", value=_SECRET, **overrides):
    result = {"name": name, "value": value, "domain": "api-dashboard.search.brave.com", "path": "/",
              "secure": True, "expires": -1, "session": True}
    result.update(overrides)
    return result


def _server_frame(payload: bytes, opcode=1, final=True) -> bytes:
    length = len(payload)
    encoded_length = (bytes([length]) if length < 126 else b"\x7e" + length.to_bytes(2, "big")
                      if length <= 65535 else b"\x7f" + length.to_bytes(8, "big"))
    return bytes([(0x80 if final else 0) | opcode]) + encoded_length + payload


def _read_exact(conn, count):
    data = bytearray()
    while len(data) < count:
        part = conn.recv(count - len(data))
        if not part:
            raise EOFError()
        data.extend(part)
    return bytes(data)


def _read_client_frame(conn):
    first, second = _read_exact(conn, 2)
    if not first & 0x80 or first & 0x70 or not second & 0x80:
        raise AssertionError("every client frame must be final, unextended and masked")
    length = second & 0x7f
    if length == 126:
        length = int.from_bytes(_read_exact(conn, 2), "big")
    elif length == 127:
        length = int.from_bytes(_read_exact(conn, 8), "big")
    if length > 2 * 1024 * 1024:
        raise AssertionError("unbounded client frame")
    mask = _read_exact(conn, 4)
    data = _read_exact(conn, length)
    return first & 0x0f, bytes(value ^ mask[index % 4] for index, value in enumerate(data))


def _upgrade_response(request: bytes, *, status="101 Switching Protocols", accept=None,
                      upgrade="websocket", connection="keep-alive, Upgrade", extra=""):
    headers = dict(line.split(b":", 1) for line in request.split(b"\r\n")[1:] if b":" in line)
    key = headers[b"Sec-WebSocket-Key"].strip()
    expected = base64.b64encode(hashlib.sha1(key + chrome._WS_GUID.encode("ascii")).digest()).decode("ascii")
    return (f"HTTP/1.1 {status}\r\nUpgrade: {upgrade}\r\nConnection: {connection}\r\n"
            f"Sec-WebSocket-Accept: {expected if accept is None else accept}\r\n{extra}\r\n").encode("ascii")


class _FakeChrome:
    def __init__(self, handler, response=None):
        self.handler = handler
        self.response = response or _upgrade_response
        self.request = b""
        self.requests = []
        self.frames = []
        self.errors = []
        self.conn = None
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen(1)
        self.listener.settimeout(2)

    def __enter__(self):
        def run():
            try:
                self.conn, address = self.listener.accept()
                if address[0] != "127.0.0.1":
                    raise AssertionError("test connection left loopback")
                with self.conn as conn:
                    conn.settimeout(2)
                    while not self.request.endswith(b"\r\n\r\n"):
                        self.request += _read_exact(conn, 1)
                        if len(self.request) > 16384:
                            raise AssertionError("oversized client upgrade")
                    response = self.response(self.request)
                    if response:
                        conn.sendall(response)
                    self.handler(conn, self)
            except (EOFError, ConnectionError):
                pass
            except Exception as exc:
                self.errors.append(exc)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.conn is not None:
            try:
                self.conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.listener.close()
        self.thread.join(2)
        if self.thread.is_alive():
            raise AssertionError("fake Chrome thread did not terminate")
        if self.errors and exc_type is None:
            raise self.errors[0]


def _drain(conn, server):
    while True:
        opcode, payload = _read_client_frame(conn)
        server.frames.append((opcode, payload))
        if opcode == 8:
            return


def _cdp_handler(*, urls=None, cookies=None, noise=False, fragmented=False, error=None):
    urls = list(urls or [_BRAVE_HOME])
    cookie_batches = list(cookies if cookies is not None else [[_cookie()]])
    page_checks = 0
    cookie_checks = 0

    def handle(conn, server):
        nonlocal page_checks, cookie_checks
        while True:
            opcode, payload = _read_client_frame(conn)
            server.frames.append((opcode, payload))
            if opcode == 8:
                return
            if opcode == 10:
                continue
            if opcode != 1:
                raise AssertionError("unexpected client opcode")
            message = json.loads(payload)
            server.requests.append(message)
            method = message["method"]
            if method == "Target.createTarget":
                result = {"targetId": "created-page"}
            elif method == "Target.attachToTarget":
                if message["params"] != {"targetId": "created-page", "flatten": True}:
                    raise AssertionError("attachment must be flattened and confined to the created page")
                result = {"sessionId": "attached-session"}
            elif method == "Target.getTargetInfo":
                if message["params"] != {"targetId": "created-page"}:
                    raise AssertionError("target polling escaped created page")
                url = urls[min(page_checks, len(urls) - 1)]
                page_checks += 1
                result = {"targetInfo": {"targetId": "created-page", "type": "page", "url": url}}
            elif method == "Network.getCookies":
                if message.get("sessionId") != "attached-session":
                    raise AssertionError("cookies must be read through the page's flattened session")
                result = {"cookies": cookie_batches[min(cookie_checks, len(cookie_batches) - 1)]}
                cookie_checks += 1
            elif method == "Target.detachFromTarget":
                if message["params"] != {"sessionId": "attached-session"}:
                    raise AssertionError("cleanup detached an unrelated session")
                continue
            else:
                raise AssertionError("unexpected CDP operation")
            reply = {"id": message["id"], "result": result}
            if "sessionId" in message:
                reply["sessionId"] = message["sessionId"]
            if error is not None:
                reply = {"id": message["id"], "error": {"message": error}}
            if noise:
                for unrelated in ({"method": "Network.event", "params": {"token": _SECRET}},
                                  {"id": message["id"] + 100, "result": {"token": _SECRET}},
                                  {"id": message["id"], "sessionId": "unrelated-session", "result": {}},
                                  {"id": True, "result": {"token": _SECRET}}):
                    conn.sendall(_server_frame(json.dumps(unrelated).encode()))
            data = json.dumps(reply).encode()
            if fragmented:
                middle = len(data) // 2
                conn.sendall(_server_frame(data[:middle], final=False) + _server_frame(b"heartbeat", opcode=9)
                             + _server_frame(data[middle:], opcode=0))
            else:
                conn.sendall(_server_frame(data))
    return handle


class ChromeSessionTests(unittest.TestCase):
    def test_capture_scopes_requests_masks_frames_and_keeps_chrome_and_page(self):
        statuses = []
        output = io.StringIO()
        with _FakeChrome(_cdp_handler(noise=True, fragmented=True)) as server:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output), mock.patch.object(
                socket, "getaddrinfo", side_effect=AssertionError("DNS is forbidden"),
            ):
                record = chrome.capture_session("brave", port=server.port, timeout=2, on_wait=statuses.append)
            self.assertEqual(record, {"cookie_header": f"search_api_users_auth={_SECRET}",
                                      "login_id": hashlib.sha256(_SECRET.encode()).hexdigest()})
            # Let the fake server consume the already-sent cleanup frames.
            server.thread.join(1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(server.request.split(b"\r\n")[0], b"GET /devtools/browser HTTP/1.1")
        self.assertEqual(server.requests[0]["params"], {"url": _BRAVE_HOME})
        cookie_requests = [row for row in server.requests if row["method"] == "Network.getCookies"]
        self.assertEqual([row["params"] for row in cookie_requests], [{"urls": [_BRAVE_DATA]}])
        self.assertEqual(server.requests[-1]["method"], "Target.detachFromTarget")
        self.assertEqual([payload for opcode, payload in server.frames if opcode == 10], [b"heartbeat"] * 4)
        self.assertEqual(server.frames[-1], (8, (1000).to_bytes(2, "big")))
        self.assertEqual(len(statuses), 2)
        self.assertTrue(all(_SECRET not in text and "ws:" not in text for text in statuses))

    def test_exa_uses_only_its_two_apis_and_prefers_exact_secure_token(self):
        cookies = [_cookie("next-auth.session-token", "ordinary", domain="dashboard.exa.ai"),
                   _cookie("__Secure-next-auth.session-token", "preferred", domain=".exa.ai"),
                   _cookie("other", "foreign", domain="example.com"),
                   _cookie("narrow", "credits-only", domain="dashboard.exa.ai", path="/api/get-credits")]
        with _FakeChrome(_cdp_handler(urls=[_EXA_HOME], cookies=[cookies])) as server:
            record = chrome.capture_session("exa", port=server.port, timeout=2)
        self.assertEqual(record["cookie_header"], "__Secure-next-auth.session-token=preferred; next-auth.session-token=ordinary")
        self.assertEqual(record["login_id"], hashlib.sha256(b"preferred").hexdigest())
        self.assertEqual(server.requests[0]["params"], {"url": _EXA_HOME})
        self.assertEqual(next(row["params"] for row in server.requests if row["method"] == "Network.getCookies"),
                         {"urls": _EXA_APIS})

    def test_polls_after_login_and_missing_cookie_without_accepting_suffixes(self):
        invalid_cookie = _cookie("arbitrary.next-auth.session-token", domain="dashboard.exa.ai")
        valid_cookie = _cookie("next-auth.session-token", domain="dashboard.exa.ai")
        with _FakeChrome(_cdp_handler(urls=["https://accounts.example.test/login?token=private", _EXA_HOME],
                                     cookies=[[invalid_cookie], [valid_cookie]])) as server:
            start = time.monotonic()
            record = chrome.capture_session("exa", port=server.port, timeout=3)
            elapsed = time.monotonic() - start
        self.assertEqual(record["cookie_header"], f"next-auth.session-token={_SECRET}")
        self.assertGreaterEqual(elapsed, 0.7)
        self.assertEqual(sum(row["method"] == "Network.getCookies" for row in server.requests), 2)
        self.assertEqual(sum(row["method"] == "Target.getTargetInfo" for row in server.requests), 3)

    def test_parameters_fail_before_any_socket(self):
        cases = [("other", {}, "provider"), ("BRAVE", {}, "provider"),
                 ("brave", {"port": 1023}, "port"), ("brave", {"port": 65536}, "port"),
                 ("brave", {"port": True}, "port"), ("brave", {"port": "9222"}, "port"),
                 ("brave", {"timeout": 0}, "timeout_value"), ("brave", {"timeout": float("inf")}, "timeout_value"),
                 ("brave", {"timeout": float("nan")}, "timeout_value"), ("brave", {"timeout": True}, "timeout_value"),
                 ("brave", {"timeout": 10 ** 1000}, "timeout_value")]
        with mock.patch.object(socket, "socket", side_effect=AssertionError("invalid input dialed a socket")):
            for provider, kwargs, kind in cases:
                with self.subTest(provider=provider, kwargs=kwargs), self.assertRaises(chrome.ChromeSessionError) as caught:
                    chrome.capture_session(provider, **kwargs)
                self.assertEqual(caught.exception.kind, kind)

    def test_cancel_before_connect(self):
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(socket, "socket") as dialed, self.assertRaises(chrome.ChromeSessionCancelled):
            chrome.capture_session("brave", cancel_event=cancel)
        dialed.assert_not_called()

    def test_connection_refused_has_fixed_sharing_guidance(self):
        sock = mock.Mock()
        sock.connect.side_effect = ConnectionRefusedError("private websocket address?token=" + _SECRET)
        with mock.patch.object(socket, "socket", return_value=sock), self.assertRaises(chrome.ChromeSessionError) as caught:
            chrome.capture_session("brave", port=9222)
        self.assertEqual(caught.exception.kind, "unavailable")
        self.assertIn("远程调试共享", str(caught.exception))
        self.assertNotIn(_SECRET, str(caught.exception))
        sock.connect.assert_called_once_with(("127.0.0.1", 9222))
        sock.close.assert_called_once()

    def test_upgrade_validates_status_accept_tokens_and_header_limit(self):
        cases = [({"status": "403 Forbidden"}, "denied"), ({"status": "404 Not Found"}, "unavailable"),
                 ({"accept": _SECRET}, "protocol"), ({"upgrade": "other"}, "protocol"),
                 ({"connection": "keep-alive"}, "protocol"),
                 ({"extra": "Sec-WebSocket-Extensions: permessage-deflate\r\n"}, "protocol"),
                 ({"extra": "X-Padding: " + "x" * 16384 + "\r\n"}, "protocol"),
                 ({"extra": " fold: invalid\r\n"}, "protocol"),
                 ({"status": "101 invalid\x00reason"}, "protocol"),
                 ({"extra": "Sec-WebSocket-Accept: duplicate\r\n"}, "protocol")]
        for options, kind in cases:
            with self.subTest(options=list(options)), _FakeChrome(
                _drain, response=lambda request: _upgrade_response(request, **options),
            ) as server:
                with self.assertRaises(chrome.ChromeSessionError) as caught:
                    chrome.capture_session("brave", port=server.port, timeout=1)
                self.assertEqual(caught.exception.kind, kind)
                self.assertNotIn(_SECRET, str(caught.exception))

    def test_split_upgrade_preserves_frame_bytes_following_headers(self):
        # A response frame may share a TCP packet with the HTTP upgrade.
        response = lambda request: _upgrade_response(request) + _server_frame("你好".encode())
        with _FakeChrome(_drain, response=response) as server:
            ws = chrome._WebSocket(server.port, chrome._Budget(1, None))
            try:
                self.assertEqual(ws.receive_text(), "你好")
            finally:
                ws.close()

    def test_header_can_span_multiple_tcp_reads(self):
        consumed = [threading.Event() for _ in range(3)]
        boundaries = []
        received = 0
        read_count = 0
        original_recv = chrome._WebSocket._recv

        def receive(ws, count):
            nonlocal received, read_count
            data = original_recv(ws, count)
            received += len(data)
            read_count += 1
            for index, boundary in enumerate(boundaries):
                if received >= boundary:
                    consumed[index].set()
            return data

        def send(conn, server):
            response = _upgrade_response(server.request)
            chunks = (response[:5], response[5:-3], response[-3:])
            boundaries.extend((5, len(response) - 3, len(response)))
            for index, chunk in enumerate(chunks):
                conn.sendall(chunk)
                if not consumed[index].wait(1):
                    raise AssertionError("client did not consume the preceding header chunk")
            conn.sendall(_server_frame(b"ready"))
            _drain(conn, server)
        with _FakeChrome(send, response=lambda request: b"") as server, mock.patch.object(
            chrome._WebSocket, "_recv", receive,
        ):
            ws = chrome._WebSocket(server.port, chrome._Budget(1, None))
            try:
                self.assertGreaterEqual(read_count, 3)
                self.assertEqual(ws.receive_text(), "ready")
            finally:
                ws.close()

    def test_extended_length_frames_round_trip_masked(self):
        with _FakeChrome(_drain) as server:
            ws = chrome._WebSocket(server.port, chrome._Budget(2, None))
            try:
                for length in (125, 126, 65535, 65536):
                    ws.send_frame(1, b"x" * length)
            finally:
                ws.close()
            server.thread.join(1)
        self.assertEqual([len(data) for opcode, data in server.frames if opcode == 1], [125, 126, 65535, 65536])
        data = b"x" * 65536
        def send(conn, server):
            conn.sendall(_server_frame(data))
            _drain(conn, server)
        with _FakeChrome(send) as server:
            ws = chrome._WebSocket(server.port, chrome._Budget(1, None))
            try:
                self.assertEqual(ws.receive_text(), data.decode())
            finally:
                ws.close()

    def test_frames_reject_rsv_binary_mask_malformed_and_huge_lengths(self):
        cases = [b"\xc1\x00", _server_frame(b"secret", opcode=2), b"\x81\x80",
                 _server_frame(b"", opcode=0), _server_frame(b"a", opcode=9, final=False),
                 b"\x89\x7e", b"\x81\x7e\x00\x01", b"\x81\x7f" + (42).to_bytes(8, "big"),
                 b"\x81\x7f" + (1 << 63).to_bytes(8, "big"),
                 b"\x81\x7f" + (chrome._MESSAGE_LIMIT + 1).to_bytes(8, "big"),
                 _server_frame(b"\xff"), _server_frame(b"x", opcode=8),
                 _server_frame((1005).to_bytes(2, "big"), opcode=8),
                 _server_frame((1000).to_bytes(2, "big") + b"\xff", opcode=8),
                 _server_frame(b"a", final=False) + _server_frame(b"b", opcode=1),
                 _server_frame(b"a" * chrome._MESSAGE_LIMIT, final=False) + _server_frame(b"b", opcode=0)]
        for data in cases:
            def send_bad(conn, server):
                conn.sendall(data)
                _drain(conn, server)
            with self.subTest(prefix=data[:10]), _FakeChrome(send_bad) as server:
                ws = chrome._WebSocket(server.port, chrome._Budget(1, None))
                try:
                    with self.assertRaises(chrome.ChromeSessionError) as caught:
                        ws.receive_text()
                    self.assertEqual(caught.exception.kind, "protocol")
                finally:
                    ws.close()

    def test_fragmented_utf8_with_ping_and_pong(self):
        data = "你好".encode()
        def send(conn, server):
            conn.sendall(_server_frame(data[:2], final=False) + _server_frame(b"ping", opcode=9)
                         + _server_frame(b"ignored", opcode=10) + _server_frame(data[2:], opcode=0))
            _drain(conn, server)
        with _FakeChrome(send) as server:
            ws = chrome._WebSocket(server.port, chrome._Budget(1, None))
            try:
                self.assertEqual(ws.receive_text(), "你好")
            finally:
                ws.close()
            server.thread.join(1)
        self.assertIn((10, b"ping"), server.frames)

    def test_server_close_is_masked_and_never_echoes_reason_in_diagnostics(self):
        def send(conn, server):
            conn.sendall(_server_frame((1008).to_bytes(2, "big") + _SECRET.encode(), opcode=8))
            _drain(conn, server)
        with _FakeChrome(send) as server:
            with self.assertRaises(chrome.ChromeSessionError) as caught:
                chrome.capture_session("brave", port=server.port, timeout=1)
            server.thread.join(1)
        self.assertEqual(caught.exception.kind, "denied")
        self.assertNotIn(_SECRET, str(caught.exception))
        self.assertEqual(server.frames[-1], (8, (1008).to_bytes(2, "big") + _SECRET.encode()))

    def test_timeout_and_cancel_during_approval_upgrade(self):
        for cancelled in (False, True):
            cancel = threading.Event()
            def stall(conn, server):
                if cancelled:
                    cancel.set()
                _read_exact(conn, 1)
            with self.subTest(cancelled=cancelled), _FakeChrome(stall, response=lambda request: b"") as server:
                start = time.monotonic()
                with self.assertRaises(chrome.ChromeSessionError) as caught:
                    chrome.capture_session("brave", port=server.port, timeout=0.25, cancel_event=cancel)
                self.assertEqual(caught.exception.kind, "cancelled" if cancelled else "timeout")
                self.assertLess(time.monotonic() - start, 0.7)
                if cancelled:
                    self.assertIsInstance(caught.exception, chrome.ChromeSessionCancelled)

    def test_continuous_events_and_slow_payload_cannot_extend_deadline(self):
        original_recv = chrome._WebSocket._recv
        real_monotonic = time.monotonic
        for slow_payload in (False, True):
            clock = [100.0]
            response_started = threading.Event()
            consumed = threading.Event()
            stopped = threading.Event()

            def receive(ws, count):
                data = original_recv(ws, count)
                if response_started.is_set():
                    # Each received piece consumes budget even though the
                    # producer keeps making progress without an idle timeout.
                    clock[0] += 0.04
                    consumed.set()
                return data

            def stream(conn, server):
                _read_client_frame(conn)
                response_started.set()
                if slow_payload:
                    conn.sendall(b"\x81\x7e" + (1000).to_bytes(2, "big"))
                    data = b"x"
                else:
                    data = _server_frame(json.dumps({"method": "private-event", "params": {"token": _SECRET}}).encode())
                while not stopped.is_set():
                    conn.sendall(data)
                    if not consumed.wait(1):
                        raise AssertionError("client stopped consuming the ongoing response")
                    consumed.clear()

            with self.subTest(slow_payload=slow_payload), _FakeChrome(stream) as server, mock.patch.object(
                chrome._WebSocket, "_recv", receive,
            ), mock.patch.object(chrome.time, "monotonic", side_effect=lambda: clock[0]):
                start = real_monotonic()
                try:
                    with self.assertRaises(chrome.ChromeSessionError) as caught:
                        chrome.capture_session("brave", port=server.port, timeout=0.15)
                    self.assertEqual(caught.exception.kind, "timeout")
                    self.assertGreaterEqual(clock[0], 100.15)
                    self.assertLess(real_monotonic() - start, 0.7)
                finally:
                    stopped.set()
                    consumed.set()

    def test_cancel_during_partial_cdp_response(self):
        cancel = threading.Event()
        reading_remainder = threading.Event()
        original_recv = chrome._WebSocket._recv

        def receive(ws, count):
            if count == 999:
                reading_remainder.set()
            return original_recv(ws, count)

        def partial_response(conn, server):
            _read_client_frame(conn)
            conn.sendall(b"\x81\x7e" + (1000).to_bytes(2, "big") + b"x")
            if not reading_remainder.wait(1):
                raise AssertionError("client did not begin reading the incomplete response")
            cancel.set()
            _read_exact(conn, 1)
        with _FakeChrome(partial_response) as server, mock.patch.object(chrome._WebSocket, "_recv", receive):
            start = time.monotonic()
            with self.assertRaises(chrome.ChromeSessionCancelled):
                chrome.capture_session("brave", port=server.port, timeout=2, cancel_event=cancel)
            self.assertTrue(reading_remainder.is_set())
            self.assertLess(time.monotonic() - start, 0.7)

    def test_denial_can_close_before_sending_upgrade_headers(self):
        with _FakeChrome(lambda conn, server: None, response=lambda request: b"") as server:
            with self.assertRaises(chrome.ChromeSessionError) as caught:
                chrome.capture_session("brave", port=server.port, timeout=1)
        self.assertEqual(caught.exception.kind, "denied")

    def test_missing_cookie_times_out_with_cancellable_polling(self):
        with _FakeChrome(_cdp_handler(cookies=[[]])) as server:
            with self.assertRaises(chrome.ChromeSessionError) as caught:
                chrome.capture_session("brave", port=server.port, timeout=0.15)
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertEqual(sum(row["method"] == "Network.getCookies" for row in server.requests), 1)
        cancel = threading.Event()
        def cancelled_cookies(conn, server):
            # Cancel exactly when the target is waiting for login cookies.
            _cdp_handler(cookies=[[]])(conn, server)
        with _FakeChrome(cancelled_cookies) as server:
            def cancel_on_login(status):
                if "标签页" in status:
                    cancel.set()
            with self.assertRaises(chrome.ChromeSessionCancelled):
                chrome.capture_session("brave", port=server.port, timeout=2, cancel_event=cancel, on_wait=cancel_on_login)

    def test_cdp_and_json_errors_are_fixed_and_never_log_secrets(self):
        def bad_json(conn, server):
            _read_client_frame(conn)
            conn.sendall(_server_frame(("invalid-json?token=" + _SECRET).encode()))
            _drain(conn, server)
        for handler in (_cdp_handler(error="failed?token=" + _SECRET), bad_json):
            output = io.StringIO()
            with _FakeChrome(handler) as server, contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                with self.assertRaises(chrome.ChromeSessionError) as caught:
                    chrome.capture_session("brave", port=server.port, timeout=1)
            self.assertNotIn(_SECRET, str(caught.exception))
            self.assertNotIn("?token", str(caught.exception))
            self.assertEqual(output.getvalue(), "")


class CookieBoundaryTests(unittest.TestCase):
    def capture(self, cookies, provider="brave"):
        urls = (_BRAVE_DATA,) if provider == "brave" else tuple(_EXA_APIS)
        return chrome._capture_cookies(cookies, provider, urls)

    def test_only_target_domain_path_and_live_cookies_are_returned(self):
        cookies = [_cookie(), _cookie("ancestor", "valid", domain=".search.brave.com", path="/app"),
                   _cookie("foreign", domain="elsewhere.test"), _cookie("parent-host-only", domain="brave.com"),
                   _cookie("public-suffix", domain=".com"), _cookie("suffix-confusion", domain="evilbrave.com"),
                   _cookie("wrong-path", path="/app/dashboard-other"), _cookie("unrelated-path", path="/admin"),
                   _cookie("expired", expires=time.time() - 2, session=False),
                   _cookie("nonfinite", expires=float("inf")), _cookie("negative", expires=-2)]
        record = self.capture(cookies)
        self.assertEqual(record["cookie_header"], f"ancestor=valid; search_api_users_auth={_SECRET}")

    def test_cookie_injection_and_ambiguous_duplicates_fail_without_raw_values(self):
        bad = [_cookie(name="unsafe\r\nHeader"), _cookie(value=_SECRET + "\r\nHeader: injected"),
               _cookie(value="two; next=bad"), _cookie(value="a,b"), _cookie(value="a\\b"),
               _cookie(value="a\x00b"), _cookie(value="a b"), _cookie(value="非英文"),
               _cookie(secure="yes"), _cookie(expires=True), _cookie(session=False),
               _cookie("__Secure-other", secure=False), _cookie("__Host-other", domain=".search.brave.com")]
        for cookie in bad:
            with self.subTest(fields=[key for key in cookie if cookie[key] != _cookie().get(key)]):
                with self.assertRaises(chrome.ChromeSessionError) as caught:
                    self.capture([_cookie(), cookie])
                self.assertNotIn(_SECRET, str(caught.exception))
        with self.assertRaises(chrome.ChromeSessionError):
            self.capture([_cookie(), _cookie(value="different")])

    def test_exact_required_names_and_secure_prefix_invariants(self):
        self.assertIsNone(self.capture([_cookie("xsearch_api_users_auth")]))
        self.assertIsNone(self.capture([_cookie(value="")]))
        for name in ("other.next-auth.session-token", "next-auth.session-token.0", "__Secure-next-auth.session-token.1"):
            self.assertIsNone(self.capture([_cookie(name, domain="dashboard.exa.ai")], "exa"))
        with self.assertRaises(chrome.ChromeSessionError):
            self.capture([_cookie("__Secure-next-auth.session-token", domain="dashboard.exa.ai", secure=False)], "exa")

    def test_header_size_is_bounded_and_login_id_tracks_required_session_only(self):
        first = self.capture([_cookie(), _cookie("noise", "first")])
        same = self.capture([_cookie(), _cookie("noise", "second")])
        new = self.capture([_cookie(value="new-session")])
        self.assertEqual(first["login_id"], same["login_id"])
        self.assertNotEqual(first["login_id"], new["login_id"])
        with self.assertRaises(chrome.ChromeSessionError):
            self.capture([_cookie(value="a" * chrome._COOKIE_LIMIT)])

    def test_dashboard_url_gate_rejects_origin_path_and_parser_confusion(self):
        for url in ("https://api-dashboard.search.brave.com.evil/app/dashboard",
                    "https://evil@api-dashboard.search.brave.com/app/dashboard",
                    "http://api-dashboard.search.brave.com/app/dashboard",
                    "https://api-dashboard.search.brave.com:444/app/dashboard",
                    "https://api-dashboard.search.brave.com/app/dashboard-evil",
                    "https://api-dashboard.search.brave.com/login?next=/app/dashboard",
                    "https://api-dashboard.search.brave.com/app/%64ashboard",
                    "\n" + _BRAVE_HOME, _BRAVE_HOME + "\r\n", "not a url"):
            with self.subTest(url=url):
                self.assertFalse(chrome._dashboard_ready(url, _BRAVE_HOME))
        self.assertTrue(chrome._dashboard_ready(_BRAVE_HOME + "/?safe=query#fragment", _BRAVE_HOME))


if __name__ == "__main__":
    unittest.main()

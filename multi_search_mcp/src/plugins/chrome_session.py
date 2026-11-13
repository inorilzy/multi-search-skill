"""Capture one dashboard login from Chrome's explicitly shared existing session.

The only connection is an IPv4 loopback WebSocket. Credentials stay in memory;
callers own persistence and must never include the returned header in diagnostics.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import secrets
import socket
import time
import urllib.parse
from collections.abc import Callable

from .builtin.brave_dashboard import DASHBOARD_URL as _BRAVE_DASHBOARD, DATA_URL as _BRAVE_DATA
from .builtin.exa_dashboard import CREDITS_URL as _EXA_CREDITS, PLAN_URL as _EXA_PLAN

__all__ = ["capture_session", "ChromeSessionError", "ChromeSessionCancelled"]

_HEADER_LIMIT = 16 * 1024
_MESSAGE_LIMIT = 1024 * 1024
_COOKIE_LIMIT = 64 * 1024
_POLL_INTERVAL = 0.4
_IO_INTERVAL = 0.1
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_TOKEN_CHARS = frozenset("!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_ERRORS = {
    "provider": "仅支持 Brave 和 Exa 的 Chrome 登录。",
    "port": "Chrome 连接端口必须是 1024 至 65535 的整数。",
    "timeout_value": "Chrome 登录等待时间必须是有限的正数。",
    "unavailable": "无法连接 Chrome。请在 chrome://inspect/#remote-debugging 启用远程调试共享，并确认连接端口。",
    "denied": "Chrome 未允许本次连接或已断开。请在 Chrome 中允许连接后重试。",
    "timeout": "等待 Chrome 授权或登录超时，请确认已允许连接并完成登录后重试。",
    "cancelled": "已取消 Chrome 登录。",
    "protocol": "Chrome 连接响应无效或超过安全限制，请重试。",
    "cdp": "Chrome 无法读取本次登录，请确认已允许连接后重试。",
    "cookies": "Chrome 登录凭据格式或作用域不安全，请重新登录后重试。",
}


class ChromeSessionError(ValueError):
    """A fixed public diagnostic that never embeds browser or transport data."""

    def __init__(self, kind: str = "protocol"):
        self.kind = kind if kind in _ERRORS else "protocol"
        super().__init__(_ERRORS[self.kind])


class ChromeSessionCancelled(ChromeSessionError):
    def __init__(self):
        super().__init__("cancelled")


class _Budget:
    def __init__(self, timeout: float, cancel_event):
        self.deadline = time.monotonic() + timeout
        self.cancel_event = cancel_event

    def remaining(self) -> float:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise ChromeSessionCancelled()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ChromeSessionError("timeout")
        return remaining

    def socket_timeout(self, sock) -> None:
        sock.settimeout(min(_IO_INTERVAL, self.remaining()))

    def pause(self) -> None:
        end = time.monotonic() + min(_POLL_INTERVAL, self.remaining())
        while True:
            remaining = min(end - time.monotonic(), self.remaining())
            if remaining <= 0:
                return
            time.sleep(min(_IO_INTERVAL, remaining))


class _WebSocket:
    def __init__(self, port: int, budget: _Budget):
        self.budget = budget
        self.sock = None
        self.buffer = bytearray()
        self.upgraded = False
        self.closed = False
        try:
            # A literal AF_INET address bypasses DNS, proxies and discovery files.
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            budget.socket_timeout(self.sock)
            self.sock.connect(("127.0.0.1", port))
            self._upgrade(port)
        except BaseException:
            self.close()
            raise

    def _send(self, data: bytes) -> None:
        sent = 0
        while sent < len(data):
            self.budget.socket_timeout(self.sock)
            try:
                count = self.sock.send(data[sent:])
            except socket.timeout:
                continue
            if not count:
                raise ChromeSessionError("denied")
            sent += count
        self.budget.remaining()

    def _recv(self, count: int) -> bytes:
        while True:
            self.budget.socket_timeout(self.sock)
            try:
                data = self.sock.recv(count)
            except socket.timeout:
                continue
            self.budget.remaining()
            if not data:
                raise ChromeSessionError("denied")
            return data

    def _read(self, count: int) -> bytes:
        self.budget.remaining()
        while len(self.buffer) < count:
            self.buffer.extend(self._recv(count - len(self.buffer)))
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result

    def _upgrade(self, port: int) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        self._send((
            "GET /devtools/browser HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii"))
        while b"\r\n\r\n" not in self.buffer:
            if len(self.buffer) >= _HEADER_LIMIT:
                raise ChromeSessionError()
            self.buffer.extend(self._recv(min(4096, _HEADER_LIMIT + 1 - len(self.buffer))))
        boundary = self.buffer.index(b"\r\n\r\n") + 4
        if boundary > _HEADER_LIMIT:
            raise ChromeSessionError()
        header = bytes(self.buffer[:boundary - 4])
        del self.buffer[:boundary]
        try:
            lines = header.decode("ascii").split("\r\n")
            status = lines[0].split(" ", 2)
            if any(not 32 <= ord(ch) <= 126 for ch in lines[0]):
                raise ChromeSessionError()
            if len(status) < 2 or status[0] != "HTTP/1.1" or status[1] != "101":
                kind = "denied" if len(status) >= 2 and status[1] in {"401", "403"} else "unavailable"
                raise ChromeSessionError(kind)
            headers: dict[str, list[str]] = {}
            for line in lines[1:]:
                name, separator, value = line.partition(":")
                if not separator or not name or any(ch not in _TOKEN_CHARS for ch in name):
                    raise ChromeSessionError()
                if any(ord(ch) < 32 and ch != "\t" or ord(ch) == 127 for ch in value):
                    raise ChromeSessionError()
                headers.setdefault(name.lower(), []).append(value.strip(" \t"))
            upgrade = ",".join(headers.get("upgrade", [])).lower()
            connection = {part.strip().lower() for part in ",".join(headers.get("connection", [])).split(",")}
            expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
            if (upgrade != "websocket" or "upgrade" not in connection
                    or headers.get("sec-websocket-accept") != [expected]
                    or "sec-websocket-extensions" in headers or "sec-websocket-protocol" in headers):
                raise ChromeSessionError()
        except UnicodeError:
            raise ChromeSessionError() from None
        self.upgraded = True

    def send_frame(self, opcode: int, payload: bytes) -> None:
        if len(payload) > _MESSAGE_LIMIT:
            raise ChromeSessionError()
        length = len(payload)
        size = (bytes([length | 0x80]) if length < 126 else
                b"\xfe" + length.to_bytes(2, "big") if length <= 65535 else
                b"\xff" + length.to_bytes(8, "big"))
        mask = secrets.token_bytes(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self._send(bytes([0x80 | opcode]) + size + mask + masked)

    def receive_text(self) -> str:
        parts = bytearray()
        fragmented = False
        while True:
            first, second = self._read(2)
            final, opcode = bool(first & 0x80), first & 0x0f
            if first & 0x70 or second & 0x80 or opcode not in {0, 1, 8, 9, 10}:
                raise ChromeSessionError()
            length = second & 0x7f
            if opcode >= 8 and (not final or length > 125):
                raise ChromeSessionError()
            if length == 126:
                length = int.from_bytes(self._read(2), "big")
                if length < 126:
                    raise ChromeSessionError()
            elif length == 127:
                length = int.from_bytes(self._read(8), "big")
                if length < 65536 or length >= 1 << 63:
                    raise ChromeSessionError()
            if length > _MESSAGE_LIMIT or opcode < 8 and len(parts) + length > _MESSAGE_LIMIT:
                raise ChromeSessionError()
            payload = self._read(length)
            if opcode == 8:
                if len(payload) == 1:
                    raise ChromeSessionError()
                if payload:
                    code = int.from_bytes(payload[:2], "big")
                    if not (code in {1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014}
                            or 3000 <= code <= 4999):
                        raise ChromeSessionError()
                    try:
                        payload[2:].decode("utf-8")
                    except UnicodeError:
                        raise ChromeSessionError() from None
                self.closed = True
                self.send_frame(8, payload)
                raise ChromeSessionError("denied")
            if opcode == 9:
                self.send_frame(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode == 1:
                if fragmented:
                    raise ChromeSessionError()
                fragmented = True
            elif not fragmented:
                raise ChromeSessionError()
            parts.extend(payload)
            if final:
                try:
                    return parts.decode("utf-8")
                except UnicodeError:
                    raise ChromeSessionError() from None

    def close(self) -> None:
        if self.sock is not None:
            try:
                if self.upgraded and not self.closed:
                    self.send_frame(8, (1000).to_bytes(2, "big"))
            except Exception:
                pass
            finally:
                try:
                    self.sock.close()
                except OSError:
                    pass
                self.sock = None


class _CDP:
    def __init__(self, websocket: _WebSocket):
        self.websocket = websocket
        self.next_id = 0

    def send(self, method: str, params: dict, session_id: str | None = None) -> int:
        self.next_id += 1
        message = {"id": self.next_id, "method": method, "params": params}
        if session_id is not None:
            message["sessionId"] = session_id
        self.websocket.send_frame(1, json.dumps(message, separators=(",", ":")).encode("utf-8"))
        return self.next_id

    def request(self, method: str, params: dict, session_id: str | None = None) -> dict:
        request_id = self.send(method, params, session_id)
        while True:
            text = self.websocket.receive_text()
            try:
                response = json.loads(text)
            except (ValueError, RecursionError):
                raise ChromeSessionError() from None
            if not isinstance(response, dict):
                raise ChromeSessionError()
            # Events, foreign request IDs and other flattened sessions carry no
            # authority for this request, and never reach public callbacks.
            if (type(response.get("id")) is not int or response["id"] != request_id
                    or response.get("sessionId") != session_id):
                continue
            if "error" in response:
                raise ChromeSessionError("cdp")
            result = response.get("result")
            if not isinstance(result, dict):
                raise ChromeSessionError()
            return result


def _identifier(value) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or any(not 33 <= ord(ch) <= 126 for ch in value):
        raise ChromeSessionError()
    return value


def _dashboard_ready(url, dashboard: str) -> bool:
    if not isinstance(url, str) or len(url) > _HEADER_LIMIT or any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
        return False
    try:
        actual, expected = urllib.parse.urlsplit(url), urllib.parse.urlsplit(dashboard)
        return (actual.scheme == "https" and actual.hostname == expected.hostname
                and actual.port in {None, 443} and actual.username is None and actual.password is None
                and actual.path in {expected.path, expected.path + "/"})
    except ValueError:
        return False


def _path_matches(path: str, target: str) -> bool:
    return target == path or target.startswith(path) and (path.endswith("/") or target[len(path):].startswith("/"))


def _capture_cookies(cookies, provider: str, urls: tuple[str, ...]) -> dict[str, str] | None:
    if not isinstance(cookies, list):
        raise ChromeSessionError()
    targets = [urllib.parse.urlsplit(url) for url in urls]
    host = targets[0].hostname
    domains = ({host, "search.brave.com", "brave.com"} if provider == "brave" else {host, "exa.ai"})
    accepted: dict[str, str] = {}
    now = time.time()
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise ChromeSessionError()
        domain, path = cookie.get("domain"), cookie.get("path")
        if (not isinstance(domain, str) or domain.lstrip(".") not in domains
                or domain.startswith("..") or not domain.startswith(".") and domain != host):
            continue
        if (not isinstance(path, str) or not path.startswith("/") or len(path) > _HEADER_LIMIT
                or any(ord(ch) < 32 or ord(ch) > 126 for ch in path)
                or not all(_path_matches(path, target.path) for target in targets)):
            continue
        secure, expires = cookie.get("secure"), cookie.get("expires")
        if type(secure) is not bool or type(expires) not in {int, float}:
            raise ChromeSessionError("cookies")
        try:
            finite = math.isfinite(expires)
        except OverflowError:
            finite = False
        if not finite or expires != -1 and expires <= now:
            continue
        session = cookie.get("session", expires == -1)
        if type(session) is not bool or session != (expires == -1):
            raise ChromeSessionError("cookies")
        name, value = cookie.get("name"), cookie.get("value")
        if (not isinstance(name, str) or not name or any(ch not in _TOKEN_CHARS for ch in name)
                or not isinstance(value, str)
                or any(not (ord(ch) == 33 or 35 <= ord(ch) <= 43 or 45 <= ord(ch) <= 58
                            or 60 <= ord(ch) <= 91 or 93 <= ord(ch) <= 126) for ch in value)):
            raise ChromeSessionError("cookies")
        if (name.startswith("__Secure-") and not secure
                or name.startswith("__Host-") and (not secure or domain != host or path != "/")):
            raise ChromeSessionError("cookies")
        if name in accepted and accepted[name] != value:
            raise ChromeSessionError("cookies")
        accepted[name] = value
    required = (("search_api_users_auth",) if provider == "brave" else
                ("__Secure-next-auth.session-token", "next-auth.session-token"))
    session_value = next((accepted[name] for name in required if accepted.get(name)), None)
    if session_value is None:
        return None
    header = "; ".join(f"{name}={value}" for name, value in sorted(accepted.items()))
    if len(header) > _COOKIE_LIMIT:
        raise ChromeSessionError("cookies")
    return {"cookie_header": header, "login_id": hashlib.sha256(session_value.encode("ascii")).hexdigest()}


def capture_session(
    provider: str, *, port: int = 9222, timeout: float = 120,
    cancel_event=None, on_wait: Callable[[str], None] | None = None,
) -> dict:
    """Open one fixed dashboard tab and return its private cookie header and ID.

    Chrome must already share remote debugging. Its user approval prompt and the
    new dashboard tab remain under user control. Cancellation accepts an object
    with ``is_set()`` (for example ``threading.Event``). This function closes only
    its own CDP connection, never the tab, browser, profile or stored credentials.
    """
    websocket = None
    cdp = None
    session_id = None
    try:
        if not isinstance(provider, str) or provider not in {"brave", "exa"}:
            raise ChromeSessionError("provider")
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ChromeSessionError("port")
        try:
            valid_timeout = type(timeout) in {int, float} and math.isfinite(timeout) and timeout > 0
        except OverflowError:
            valid_timeout = False
        if not valid_timeout:
            raise ChromeSessionError("timeout_value")
        budget = _Budget(timeout, cancel_event)
        budget.remaining()
        if on_wait is not None:
            on_wait("请在 Chrome 中允许本次连接。")
        try:
            websocket = _WebSocket(port, budget)
        except ChromeSessionError:
            raise
        except OSError:
            budget.remaining()
            raise ChromeSessionError("unavailable") from None
        cdp = _CDP(websocket)
        dashboard = _BRAVE_DASHBOARD if provider == "brave" else "https://dashboard.exa.ai/home"
        urls = (_BRAVE_DATA,) if provider == "brave" else (_EXA_CREDITS, _EXA_PLAN)
        target_id = _identifier(cdp.request("Target.createTarget", {"url": dashboard}).get("targetId"))
        session_id = _identifier(cdp.request("Target.attachToTarget", {"targetId": target_id, "flatten": True}).get("sessionId"))
        if on_wait is not None:
            on_wait("请在新打开的 Chrome 标签页中完成登录。")
        while True:
            info = cdp.request("Target.getTargetInfo", {"targetId": target_id}).get("targetInfo")
            if not isinstance(info, dict) or info.get("targetId") != target_id or info.get("type") != "page":
                raise ChromeSessionError()
            if _dashboard_ready(info.get("url"), dashboard):
                cookies = cdp.request("Network.getCookies", {"urls": list(urls)}, session_id).get("cookies")
                record = _capture_cookies(cookies, provider, urls)
                if record is not None:
                    budget.remaining()
                    return record
            budget.pause()
    except ChromeSessionError:
        raise
    except Exception:
        # Neither Python transport errors nor CDP/JSON/callback failures are a
        # public channel for browser response bodies, URLs or credential values.
        raise ChromeSessionError() from None
    finally:
        if websocket is not None:
            try:
                if cdp is not None and session_id is not None:
                    cdp.send("Target.detachFromTarget", {"sessionId": session_id})
            except Exception:
                pass
            finally:
                websocket.close()

"""OAuth login flows for Firecrawl and Parallel.

Firecrawl hands the user to a PKCE browser page and returns a REST API key.
Parallel uses RFC 8628 device code and stores Account API tokens in
``~/.multi-search/oauth.json``. Every HTTP request, sleep, clock and browser
action is injectable so tests run without external network or real waiting.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import secrets
import select
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TextIO

from ..support import http as support_http
from ..support.http import read_limited
from ..support.http_errors import read_json_error
from ..support.secrets import scrub_secrets
from . import oauth_store
from .builtin.firecrawl import (
    FIRECRAWL_CLI_AUTH_URL,
    FIRECRAWL_CLI_POLL_SECONDS,
    FIRECRAWL_CLI_STATUS_URL,
)

PARALLEL_REGISTER_URL = "https://platform.parallel.ai/getServiceKeys/register"
PARALLEL_DEVICE_CODE_URL = "https://platform.parallel.ai/getServiceKeys/device/code"
PARALLEL_TOKEN_URL = "https://platform.parallel.ai/getServiceKeys/token"
PARALLEL_REVOKE_URL = "https://platform.parallel.ai/getServiceKeys/token/revoke"
PARALLEL_SCOPE = "balance:read"
PARALLEL_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
PARALLEL_DEFAULT_INTERVAL_SECONDS = 5.0
PARALLEL_DEFAULT_EXPIRES_SECONDS = 600.0
PARALLEL_ACCOUNT_ENTRY = oauth_store.PARALLEL_ACCOUNT_ENTRY
PARALLEL_CLIENT_ENTRY = oauth_store.PARALLEL_CLIENT_ENTRY
REQUEST_TIMEOUT_SECONDS = 10.0

Emit = Callable[[dict[str, Any]], None]
Sleep = Callable[[float], None]
Clock = Callable[[], float]


class OAuthFlowError(RuntimeError):
    """One failed login step with a public error kind for the jsonl event."""

    def __init__(self, message: str, *, kind: str = "error", provider_error: str = ""):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.provider_error = provider_error


class OAuthCancelled(OAuthFlowError):
    def __init__(self) -> None:
        super().__init__("登录已取消。", kind="cancelled")


def _now() -> float:
    """Monotonic clock; module-level so tests can advance it in fake time."""
    return time.monotonic()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def code_challenge_s256(verifier: str) -> str:
    """RFC 7636 S256 challenge: unpadded base64url(SHA256(verifier))."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _emit(emit: Emit | None, event: dict[str, Any]) -> None:
    if emit is not None:
        emit(event)


def _stdin_closed(stream: TextIO | None) -> bool:
    """True when the controlling stdin was closed by the desktop or a pipe EOF.

    ``select`` is only used for real file descriptors; StringIO and other test
    doubles simply report ``closed``. One byte is consumed on an ordinary
    readable event, which is harmless because the OAuth flow never reads stdin.
    """
    if stream is None:
        return False
    try:
        if stream.closed:
            return True
    except Exception:  # noqa: BLE001 - a broken stream is a cancellation
        return True
    if os.name == "nt":
        return False
    try:
        descriptor = stream.fileno()
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        return False
    try:
        readable, _, _ = select.select([descriptor], [], [], 0)
    except (OSError, ValueError):
        return False
    if not readable:
        return False
    try:
        return os.read(descriptor, 1) == b""
    except OSError:
        return True


def _check_cancelled(stdin: TextIO | None, cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise OAuthCancelled()
    if _stdin_closed(stdin):
        raise OAuthCancelled()


def _http_kind(status: int) -> str:
    if status in (401, 403):
        return "invalid"
    if status == 429:
        return "rate_limit"
    if 400 <= status < 500:
        return "provider"
    return "error"


def _http_flow_error(
    exc: urllib.error.HTTPError,
    *,
    prefix: str,
    secrets: list[str],
) -> OAuthFlowError:
    status = int(getattr(exc, "code", 0) or 0)
    data, raw = read_json_error(exc)
    detail = ""
    provider_error = ""
    if isinstance(data, dict):
        provider_error = str(data.get("error") or "")
        for key in ("error_description", "message", "detail", "error"):
            value = data.get(key)
            if isinstance(value, str) and value and key != "error":
                detail = value
                break
    if not detail:
        detail = raw or str(getattr(exc, "reason", "") or "")
    message = f"{prefix}HTTP {status}: {detail}".strip()
    return OAuthFlowError(
        scrub_secrets(message, secrets),
        kind=_http_kind(status),
        provider_error=provider_error,
    )


def _open(http: Callable[..., Any] | None, request: urllib.request.Request, deadline: float | None):
    """Open one request with a per-call cap that also respects the flow deadline.

    ``deadline`` is a monotonic value from the same clock as :func:`_now`; the
    HTTP layer runs without its own deadline so a patched test clock stays
    consistent while production still gets one bounded request.
    """
    timeout = REQUEST_TIMEOUT_SECONDS
    if deadline is not None:
        timeout = max(0.001, min(float(timeout), deadline - _now()))
    opener = http if http is not None else support_http.urlopen_retry
    return opener(request, timeout=timeout, retries=0, deadline=None)


def _read_payload(
    response: Any,
    *,
    prefix: str,
    secrets: list[str],
    expect_json: bool,
) -> dict[str, Any]:
    try:
        raw = read_limited(response)
    except Exception as exc:  # noqa: BLE001 - provider text is untrusted
        raise OAuthFlowError(
            scrub_secrets(f"{prefix}读取响应失败：{exc}", secrets),
            kind="network",
        ) from None
    if not expect_json:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        raise OAuthFlowError(f"{prefix}响应不是有效 JSON。", kind="provider") from None
    if not isinstance(payload, dict):
        raise OAuthFlowError(f"{prefix}响应格式未知。", kind="provider")
    return payload


def _request(
    http: Callable[..., Any] | None,
    request: urllib.request.Request,
    *,
    deadline: float | None,
    prefix: str,
    secrets: list[str],
    expect_json: bool = True,
) -> dict[str, Any]:
    try:
        with _open(http, request, deadline) as response:
            return _read_payload(
                response, prefix=prefix, secrets=secrets, expect_json=expect_json,
            )
    except urllib.error.HTTPError as exc:
        raise _http_flow_error(exc, prefix=prefix, secrets=secrets) from None
    except OAuthFlowError:
        raise
    except TimeoutError:
        raise OAuthFlowError(f"{prefix}请求超时。", kind="timeout") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise OAuthFlowError(
            scrub_secrets(f"{prefix}网络错误：{exc}", secrets), kind="network",
        ) from None


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    http: Callable[..., Any] | None,
    deadline: float | None,
    prefix: str,
    secrets: list[str],
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    return _request(http, request, deadline=deadline, prefix=prefix, secrets=secrets)


def _post_form(
    url: str,
    fields: dict[str, Any],
    *,
    http: Callable[..., Any] | None,
    deadline: float | None,
    prefix: str,
    secrets: list[str],
    expect_json: bool = True,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    return _request(
        http, request, deadline=deadline, prefix=prefix, secrets=secrets,
        expect_json=expect_json,
    )


def _expires_at(seconds: Any) -> str:
    try:
        lifetime = float(seconds)
    except (TypeError, ValueError):
        lifetime = PARALLEL_DEFAULT_EXPIRES_SECONDS
    return (_utcnow() + timedelta(seconds=lifetime)).isoformat()


def _parse_expires_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def credential_expired(record: dict[str, Any], *, now: datetime | None = None) -> bool:
    """True only for a parseable expiry in the past; unknown expiry stays usable."""
    moment = _parse_expires_at(record.get("expires_at"))
    if moment is None:
        return False
    return (now or _utcnow()) >= moment


def firecrawl_login(
    *,
    credential: str,
    emit: Emit | None = None,
    save_credential: Callable[[str], Any],
    no_browser: bool = False,
    timeout: float = 300.0,
    stdin: TextIO | None = None,
    cancel_event: Any = None,
    http: Callable[..., Any] | None = None,
    sleep: Sleep | None = None,
    clock: Clock | None = None,
    open_browser: Callable[[str], Any] | None = None,
) -> str:
    """Run the Firecrawl PKCE hand-off and return the minted API key.

    ``save_credential`` runs before the ``complete`` event so a completed event
    always means the key is already in keys.json.
    """
    sleep = _sleep if sleep is None else sleep
    clock = _now if clock is None else clock
    opener = webbrowser.open if open_browser is None else open_browser
    session_id = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = code_challenge_s256(verifier)
    query = urllib.parse.urlencode({"code_challenge": challenge, "source": "coding-agent"})
    url = f"{FIRECRAWL_CLI_AUTH_URL}?{query}#session_id={session_id}"

    _emit(emit, {"event": "open_url", "url": url})
    if not no_browser:
        opener(url)
    _emit(emit, {"event": "waiting"})

    deadline = clock() + float(timeout)
    secrets_guard = [verifier]
    while True:
        _check_cancelled(stdin, cancel_event)
        remaining = deadline - clock()
        if remaining <= 0:
            raise OAuthFlowError("Firecrawl 授权超时，请重新登录。", kind="timeout")
        sleep(min(FIRECRAWL_CLI_POLL_SECONDS, remaining))
        _check_cancelled(stdin, cancel_event)

        payload = _post_json(
            FIRECRAWL_CLI_STATUS_URL,
            {"session_id": session_id, "code_verifier": verifier},
            http=http,
            deadline=deadline,
            prefix="Firecrawl: ",
            secrets=secrets_guard,
        )
        status = payload.get("status")
        if status == "complete":
            api_key = payload.get("apiKey") or payload.get("api_key")
            if not isinstance(api_key, str) or not api_key:
                raise OAuthFlowError("Firecrawl 授权完成但未返回 API key。", kind="provider")
            secrets_guard.append(api_key)
            save_credential(api_key)
            _emit(emit, {"event": "complete", "credential": credential})
            return api_key
        if status in {"pending", "waiting", "processing"} or status is None:
            continue
        if status == "expired":
            raise OAuthFlowError("Firecrawl 授权会话已过期，请重新登录。", kind="provider")
        detail = payload.get("error") or payload.get("message") or status
        if isinstance(detail, dict):
            detail = json.dumps(detail, ensure_ascii=False)
        raise OAuthFlowError(
            scrub_secrets(f"Firecrawl 授权失败：{detail}", secrets_guard), kind="provider",
        )


def _client_id_from(payload: dict[str, Any]) -> str:
    """Find ``client_id`` in the registration response, including nested data."""
    for key in ("client_id", "clientId"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    for value in payload.values():
        if isinstance(value, dict):
            nested = _client_id_from(value)
            if nested:
                return nested
    return ""


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parallel_login(
    *,
    credential: str = PARALLEL_ACCOUNT_ENTRY,
    emit: Emit | None = None,
    no_browser: bool = False,
    timeout: float = 300.0,
    stdin: TextIO | None = None,
    cancel_event: Any = None,
    http: Callable[..., Any] | None = None,
    sleep: Sleep | None = None,
    clock: Clock | None = None,
    open_browser: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Run the Parallel device-code flow and persist the account tokens."""
    sleep = _sleep if sleep is None else sleep
    clock = _now if clock is None else clock
    opener = webbrowser.open if open_browser is None else open_browser

    client_id = oauth_store.get_client_id(PARALLEL_CLIENT_ENTRY)
    if not client_id:
        registered = _post_json(
            PARALLEL_REGISTER_URL,
            {},
            http=http,
            deadline=None,
            prefix="Parallel: ",
            secrets=[],
        )
        client_id = _client_id_from(registered)
        if not client_id:
            raise OAuthFlowError("Parallel 注册失败：响应中没有 client_id。", kind="provider")
        oauth_store.set_client_id(PARALLEL_CLIENT_ENTRY, client_id)

    device = _post_form(
        PARALLEL_DEVICE_CODE_URL,
        {"client_id": client_id, "scope": PARALLEL_SCOPE},
        http=http,
        deadline=None,
        prefix="Parallel: ",
        secrets=[client_id],
    )
    device_code = device.get("device_code")
    user_code = device.get("user_code")
    if not isinstance(device_code, str) or not device_code:
        raise OAuthFlowError("Parallel 设备码响应缺少 device_code。", kind="provider")
    if not isinstance(user_code, str):
        user_code = ""
    verification_uri = device.get("verification_uri") or device.get("verification_url")
    verification_complete = device.get("verification_uri_complete")
    url = verification_complete or verification_uri
    if not isinstance(url, str) or not url:
        raise OAuthFlowError("Parallel 设备码响应缺少验证地址。", kind="provider")

    _emit(emit, {"event": "open_url", "url": url, "user_code": user_code})
    if not no_browser:
        opener(url)
    _emit(emit, {"event": "waiting"})

    interval = max(0.0, _number(device.get("interval"), PARALLEL_DEFAULT_INTERVAL_SECONDS))
    expires_in = _number(device.get("expires_in"), PARALLEL_DEFAULT_EXPIRES_SECONDS)
    deadline = min(clock() + float(timeout), clock() + expires_in)
    secrets_guard = [device_code, client_id]

    while True:
        _check_cancelled(stdin, cancel_event)
        remaining = deadline - clock()
        if remaining <= 0:
            raise OAuthFlowError("Parallel 设备码登录超时，请重新登录。", kind="timeout")
        sleep(min(interval, remaining))
        _check_cancelled(stdin, cancel_event)

        try:
            token = _post_form(
                PARALLEL_TOKEN_URL,
                {
                    "grant_type": PARALLEL_DEVICE_GRANT,
                    "device_code": device_code,
                    "client_id": client_id,
                },
                http=http,
                deadline=deadline,
                prefix="Parallel: ",
                secrets=secrets_guard,
            )
        except OAuthFlowError as exc:
            error = exc.provider_error
            if error == "authorization_pending":
                pass
            elif error == "slow_down":
                interval += 5.0
            elif error == "expired_token":
                raise OAuthFlowError(
                    "Parallel 设备码已过期，请重新运行登录。", kind="provider",
                ) from None
            elif error == "access_denied":
                raise OAuthFlowError("Parallel 授权被拒绝。", kind="provider") from None
            else:
                raise
        else:
            access_token = token.get("access_token")
            refresh_token = token.get("refresh_token")
            if not isinstance(access_token, str) or not access_token:
                raise OAuthFlowError("Parallel 令牌响应缺少 access_token。", kind="provider")
            if not isinstance(refresh_token, str):
                refresh_token = ""
            record = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": _expires_at(token.get("expires_in")),
                "token_type": token.get("token_type") or "Bearer",
                "scope": token.get("scope") or PARALLEL_SCOPE,
            }
            oauth_store.set_entry(credential, record)
            _emit(emit, {"event": "complete", "credential": credential})
            return record


def parallel_access_token(
    record: dict[str, Any],
    *,
    http: Callable[..., Any] | None = None,
    deadline: float | None = None,
) -> str:
    """Return a live access token, refreshing and persisting a rotated pair."""
    token = record.get("access_token")
    if isinstance(token, str) and token and not credential_expired(record):
        return token
    refresh_token = record.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise OAuthFlowError(
            "Parallel 登录已过期，请重新运行 login parallel --method oauth。", kind="invalid",
        )
    client_id = oauth_store.get_client_id(PARALLEL_CLIENT_ENTRY)
    fields: dict[str, Any] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if client_id:
        fields["client_id"] = client_id
    try:
        token_payload = _post_form(
            PARALLEL_TOKEN_URL,
            fields,
            http=http,
            deadline=deadline,
            prefix="Parallel: ",
            secrets=[refresh_token, token if isinstance(token, str) else ""],
        )
    except OAuthFlowError:
        raise OAuthFlowError(
            "Parallel 登录已过期，请重新运行 login parallel --method oauth。", kind="invalid",
        ) from None
    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthFlowError(
            "Parallel 登录已过期，请重新运行 login parallel --method oauth。", kind="invalid",
        )
    rotated = token_payload.get("refresh_token")
    updated = dict(record)
    updated["access_token"] = access_token
    updated["refresh_token"] = rotated if isinstance(rotated, str) and rotated else refresh_token
    updated["expires_at"] = _expires_at(token_payload.get("expires_in"))
    if token_payload.get("token_type"):
        updated["token_type"] = token_payload["token_type"]
    oauth_store.set_entry(PARALLEL_ACCOUNT_ENTRY, updated)
    return access_token


def parallel_logout(
    entry: str = PARALLEL_ACCOUNT_ENTRY,
    *,
    http: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Revoke the stored grant when possible, then always delete the entry."""
    record = oauth_store.get_entry(entry)
    if record is None:
        return {"removed": False, "message": "未找到该凭据条目。"}
    token = record.get("refresh_token") or record.get("access_token") or ""
    message = ""
    if isinstance(token, str) and token:
        client_id = oauth_store.get_client_id(PARALLEL_CLIENT_ENTRY)
        fields: dict[str, Any] = {"token": token}
        if client_id:
            fields["client_id"] = client_id
        try:
            _post_form(
                PARALLEL_REVOKE_URL,
                fields,
                http=http,
                deadline=None,
                prefix="Parallel: ",
                secrets=[token, record.get("access_token") if isinstance(record.get("access_token"), str) else ""],
                expect_json=False,
            )
        except OAuthFlowError as exc:
            message = f"已退出登录，但撤销令牌失败：{exc.message}"
    oauth_store.delete_entry(entry)
    payload: dict[str, Any] = {"removed": True}
    if message:
        payload["message"] = message
    return payload

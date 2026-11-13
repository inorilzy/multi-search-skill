"""Complete Chrome session login without exposing browser credentials to the UI."""
from __future__ import annotations

import os
import time
from typing import TextIO

from . import oauth, oauth_store
from .base import BalanceContext


def _port() -> int:
    try:
        value = int(os.environ.get("MULTI_SEARCH_CHROME_DEBUG_PORT", "9222"))
        if not 1024 <= value <= 65535:
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise oauth.OAuthFlowError("Chrome 会话共享端口无效，须为 1024–65535。", kind="invalid") from None


def _verify(provider: str, cookie: str, deadline: float) -> dict:
    context = BalanceContext(timeout=10, deadline=deadline)
    if provider == "brave":
        from .builtin.brave_dashboard import fetch_dashboard
    else:
        from .builtin.exa_dashboard import fetch_dashboard
    return fetch_dashboard(cookie, context)


class _Cancellation:
    def __init__(self, stdin: TextIO | None):
        self.stdin = oauth._watched_stdin(stdin)

    def is_set(self) -> bool:
        return oauth._stdin_closed(self.stdin)


def login(provider: str, entry: str, *, timeout: float = 300, stdin: TextIO | None = None, emit=None) -> dict:
    from .chrome_session import ChromeSessionCancelled, ChromeSessionError, capture_session

    emit = emit or (lambda event: None)
    cancellation = _Cancellation(stdin)
    deadline = time.monotonic() + timeout
    previous = ""

    def waiting(message: str) -> None:
        nonlocal previous
        if message != previous:
            emit({"event": "waiting", "message": message})
            previous = message

    try:
        waiting("请在 Chrome 允许连接；随后会在现有 Chrome 中打开服务商页面，复用已有登录。")
        record = capture_session(provider, port=_port(), timeout=timeout,
                                 cancel_event=cancellation, on_wait=waiting)
        if cancellation.is_set():
            raise ChromeSessionCancelled()
        waiting("已取得此服务商的登录会话，正在验证额度查询。")
        from .builtin.exa_dashboard import DashboardUnavailable as ExaDashboardUnavailable
        limited = False
        data = None
        try:
            data = _verify(provider, record["cookie_header"], deadline)
        except ExaDashboardUnavailable as exc:
            if exc.kind != "rate_limit":
                raise
            # A quota cooldown does not invalidate the session captured from the logged-in page.
            limited = True
        if cancellation.is_set():
            raise ChromeSessionCancelled()

        previous_record = oauth_store.read_oauth_file().get(entry, {})
        if not isinstance(previous_record, dict):
            raise oauth_store.OAuthStoreError("后台登录记录格式无效，未覆盖。")
        saved_record = {**previous_record, **record}
        profile = None
        if provider == "brave":
            from .builtin import brave_dashboard
            # Only the login owns this captured session; quota refreshes never rewrite it.
            saved_record.pop("profile", None)
            if isinstance(data, dict):
                profile = brave_dashboard._profile(data.get("profile"), brave_dashboard._cookie_secrets(record["cookie_header"]))
            if profile:
                saved_record["profile"] = profile
        oauth_store.set_entry(entry, saved_record)
        if provider == "brave" and profile:
            try:
                brave_dashboard.sync_account(profile, oauth_store.balance_credential_ref(entry, saved_record))
            except (ValueError, OSError):
                raise oauth.OAuthFlowError("Chrome 会话已保存，但账号资料保存失败；请检查本地凭据存储后重试。", kind="storage") from None
        message = ("已从 Chrome 保存登录会话；额度接口暂时限流，请稍后刷新。" if limited
                   else "已从 Chrome 保存此服务商的登录会话，额度查询已验证。")
        emit({"event": "complete", "provider": provider, "credential": entry, "message": message})
        return {"ok": True, "exit_code": 0, "provider": provider, "credential": entry}
    except (ChromeSessionCancelled, oauth.OAuthCancelled, KeyboardInterrupt):
        emit({"event": "error", "error_kind": "cancelled", "message": "登录已取消。"})
    except ChromeSessionError as exc:
        emit({"event": "error", "error_kind": "browser", "message": str(exc)})
    except oauth.OAuthFlowError as exc:
        emit({"event": "error", "error_kind": exc.kind, "message": exc.message})
    except oauth_store.OAuthStoreError:
        emit({"event": "error", "error_kind": "storage", "message": "无法保存登录会话，原有凭据未覆盖。"})
    except Exception:  # Provider and browser bodies may contain secrets; never echo an arbitrary exception.
        emit({"event": "error", "error_kind": "verification",
              "message": "Chrome 会话暂时无法通过额度查询验证；请确认控制台已登录后重试。"})
    return {"ok": False, "exit_code": 1}

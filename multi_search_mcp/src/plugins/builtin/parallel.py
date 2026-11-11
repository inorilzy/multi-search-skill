"""Parallel provider declaration and Account API balance adapter."""
import json
import urllib.error
import urllib.request

from ...state.key_state import key_fingerprint
from ...support.http import read_limited
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets
from .. import oauth, oauth_store
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin

PARALLEL_BALANCE_URL = "https://api.parallel.ai/account/service/v1/balance"
_BALANCE_HTTP_ERROR_KINDS = {
    401: "invalid",
    403: "invalid",
    429: "rate_limit",
}


def _error_report(credential: str, message: str, kind: str = "error") -> BalanceReport:
    return BalanceReport(
        provider="parallel",
        status="error",
        error_kind=kind,
        message=scrub_secrets(message, credential),
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def balance_parallel(credential: str, ctx: BalanceContext) -> BalanceReport:
    """Query the Account API balance, refreshing the device-code token if needed."""
    try:
        record = oauth_store.get_entry(oauth_store.PARALLEL_ACCOUNT_ENTRY)
    except oauth_store.OAuthStoreError as exc:
        return BalanceReport(
            provider="parallel",
            status="error",
            error_kind="internal",
            message=scrub_secrets(str(exc)),
        )
    if record is None:
        return BalanceReport(
            provider="parallel",
            status="needs_credential",
            message="未登录 Parallel Account API，请运行 login parallel --method oauth。",
        )
    try:
        token = oauth.parallel_access_token(record, http=ctx.http, deadline=ctx.deadline)
    except oauth.OAuthFlowError as exc:
        return BalanceReport(
            provider="parallel",
            status="needs_credential",
            message=scrub_secrets(exc.message, credential),
        )

    request = urllib.request.Request(
        PARALLEL_BALANCE_URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with ctx.open(request) as response:
            data = json.loads(read_limited(response))
    except urllib.error.HTTPError as exc:
        row = http_error_row(
            "parallel", exc, secret=token, kinds=_BALANCE_HTTP_ERROR_KINDS, prefix="Parallel: ",
        )
        return _error_report(token, row["error"], row["kind"])
    except (ValueError, TypeError):
        return _error_report(token, "Parallel: 余额响应不是有效 JSON。")

    if not isinstance(data, dict):
        return _error_report(token, "Parallel: 余额响应格式未知。")
    cents = data.get("credit_balance_cents")
    remaining = (
        cents / 100
        if isinstance(cents, (int, float)) and not isinstance(cents, bool)
        else None
    )
    message = (
        "后付费账户（will_invoice=true），余额字段为 0。"
        if data.get("will_invoice") is True
        else ""
    )
    return BalanceReport(
        provider="parallel",
        status="ok",
        scope="account",
        unit="usd",
        remaining=remaining,
        message=message,
        key_fingerprint=key_fingerprint(token) if token else None,
    )


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "parallel",
            missing_message="missing PARALLEL_API_KEY",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_parallel, q, key, cfg.counts["parallel"], timeout=ctx.timeout, deadline=ctx.deadline,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='parallel',
    label='Parallel',
    key_provider='parallel',
    search_sources=('parallel',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "parallel"),
        AuthMethod("oauth", "浏览器登录（查余额用）", "parallel_account", "balance_only"),
    ),
    balance=balance_parallel,
    balance_credential="parallel_account",
    balance_note='先运行 login parallel --method oauth 完成设备码登录，再查询 Account API 余额。',
)

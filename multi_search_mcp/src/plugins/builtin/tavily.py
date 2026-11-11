"""Tavily provider declaration."""
import json
import urllib.error
import urllib.request

from ...state.key_state import key_fingerprint
from ...support.http import read_limited
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin, ScrapeBackendSpec


TAVILY_BALANCE_URL = "https://api.tavily.com/usage"
# The usage endpoint is limited to 10 calls per 10 minutes; cache for the
# whole window so a few CLI calls cannot exhaust it.
TAVILY_BALANCE_TTL_SECONDS = 600
_BALANCE_HTTP_ERROR_KINDS = {
    401: "invalid",
    403: "invalid",
    402: "quota_exhausted",
    429: "rate_limit",
}


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _error_report(credential: str, message: str, kind: str = "error") -> BalanceReport:
    return BalanceReport(
        provider="tavily",
        status="error",
        error_kind=kind,
        message=scrub_secrets(message, credential),
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def balance_tavily(credential: str, ctx: BalanceContext) -> list[BalanceReport]:
    """Return the key-level and account-level Tavily credit usage."""
    request = urllib.request.Request(
        TAVILY_BALANCE_URL,
        headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"},
    )
    try:
        with ctx.open(request) as response:
            data = json.loads(read_limited(response))
    except urllib.error.HTTPError as exc:
        row = http_error_row(
            "tavily", exc, secret=credential, kinds=_BALANCE_HTTP_ERROR_KINDS, prefix="Tavily: ",
        )
        return [_error_report(credential, row["error"], row["kind"])]
    except (ValueError, TypeError):
        return [_error_report(credential, "Tavily: 余额响应不是有效 JSON。")]

    if not isinstance(data, dict):
        return [_error_report(credential, "Tavily: 余额响应格式未知。")]

    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    usage = _number(key.get("usage"))
    limit = _number(key.get("limit"))
    key_report = BalanceReport(
        provider="tavily",
        status="ok",
        scope="key",
        unit="credits",
        remaining=None if limit is None or usage is None else limit - usage,
        limit=limit,
        used=usage,
        period="month",
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )

    account = data.get("account") if isinstance(data.get("account"), dict) else {}
    plan_usage = _number(account.get("plan_usage"))
    plan_limit = _number(account.get("plan_limit"))
    paygo_usage = _number(account.get("paygo_usage"))
    paygo_limit = _number(account.get("paygo_limit"))
    details = []
    if account.get("current_plan"):
        details.append(f"套餐 {account['current_plan']}")
    if plan_usage is not None or plan_limit is not None:
        details.append(f"plan {plan_usage}/{plan_limit} credits")
    if paygo_usage is not None or paygo_limit is not None:
        details.append(f"paygo {paygo_usage}/{paygo_limit} credits")
    # Aggregate only the numbers the response actually provides; a missing
    # paygo block must not silently become zero.
    account_limit = plan_limit
    if paygo_limit is not None:
        account_limit = paygo_limit if account_limit is None else account_limit + paygo_limit
    account_used = plan_usage
    if paygo_usage is not None:
        account_used = paygo_usage if account_used is None else account_used + paygo_usage
    account_report = BalanceReport(
        provider="tavily",
        status="ok",
        scope="account",
        unit="credits",
        remaining=None if account_limit is None or account_used is None else account_limit - account_used,
        limit=account_limit,
        used=account_used,
        period="month",
        key_fingerprint=key_fingerprint(credential) if credential else None,
        message="；".join(details),
    )
    return [key_report, account_report]


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "tavily",
            missing_message="missing TAVILY_API_KEY",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_tavily, q, key, cfg.counts["tavily"], timeout=ctx.timeout, deadline=ctx.deadline,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='tavily',
    label='Tavily',
    key_provider='tavily',
    search_sources=('tavily',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "tavily"),
    ),
    balance=balance_tavily,
    balance_ttl_seconds=TAVILY_BALANCE_TTL_SECONDS,
    scrape_backends=(
        ScrapeBackendSpec("tavily", "tavily", True, dispatch="_scrape_tavily", order=3),
    ),
)

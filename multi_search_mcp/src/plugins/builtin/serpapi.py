"""SerpAPI provider declaration."""
import json
import urllib.error
import urllib.parse
import urllib.request

from ...state.key_state import key_fingerprint
from ...support.http import read_limited
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin


SERPAPI_BALANCE_URL = "https://serpapi.com/account.json"
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
        provider="serpapi",
        status="error",
        error_kind=kind,
        message=scrub_secrets(message, credential),
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def balance_serpapi(credential: str, ctx: BalanceContext) -> BalanceReport:
    """Return the monthly search quota; the account API is free of charge."""
    url = f"{SERPAPI_BALANCE_URL}?{urllib.parse.urlencode({'api_key': credential})}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with ctx.open(request) as response:
            data = json.loads(read_limited(response))
    except urllib.error.HTTPError as exc:
        row = http_error_row(
            "serpapi", exc, secret=credential, kinds=_BALANCE_HTTP_ERROR_KINDS, prefix="SerpAPI: ",
        )
        return _error_report(credential, row["error"], row["kind"])
    except (ValueError, TypeError):
        return _error_report(credential, "SerpAPI: 余额响应不是有效 JSON。")

    if not isinstance(data, dict):
        return _error_report(credential, "SerpAPI: 余额响应格式未知。")
    remaining = _number(data.get("total_searches_left"))
    limit = _number(data.get("searches_per_month"))
    resets_at = data.get("plan_renewal_date")
    if not isinstance(resets_at, str):
        resets_at = None
    # Never forward the account payload: it echoes api_key and account_email.
    return BalanceReport(
        provider="serpapi",
        status="ok",
        scope="key",
        unit="searches",
        remaining=remaining,
        limit=limit,
        used=_number(data.get("this_month_usage")),
        resets_at=resets_at,
        period="month",
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "serpapi",
            missing_message="missing SERPAPI_API_KEY / SERPAPI_KEY",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_serpapi, q, key, cfg.counts["serpapi"], cfg.serpapi_engine,
                timeout=ctx.timeout,
                deadline=ctx.deadline, publish_partial=ctx.publish_partial,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='serpapi',
    label='SerpAPI',
    key_provider='serpapi',
    search_sources=('serpapi',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "serpapi"),
    ),
    balance=balance_serpapi,
)

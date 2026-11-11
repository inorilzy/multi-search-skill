"""Firecrawl provider declaration."""
import json
import urllib.error
import urllib.request

from ...state.key_state import key_fingerprint
from ...support.http import read_limited
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin, ScrapeBackendSpec


FIRECRAWL_BALANCE_URL = "https://api.firecrawl.dev/v2/team/credit-usage"
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
        provider="firecrawl",
        status="error",
        error_kind=kind,
        message=scrub_secrets(message, credential),
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def balance_firecrawl(credential: str, ctx: BalanceContext) -> BalanceReport:
    """Return the team credit balance; every key of one team shares it."""
    request = urllib.request.Request(
        FIRECRAWL_BALANCE_URL,
        headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"},
    )
    try:
        with ctx.open(request) as response:
            data = json.loads(read_limited(response))
    except urllib.error.HTTPError as exc:
        row = http_error_row(
            "firecrawl", exc, secret=credential, kinds=_BALANCE_HTTP_ERROR_KINDS, prefix="Firecrawl: ",
        )
        return _error_report(credential, row["error"], row["kind"])
    except (ValueError, TypeError):
        return _error_report(credential, "Firecrawl: 余额响应不是有效 JSON。")

    if not isinstance(data, dict):
        return _error_report(credential, "Firecrawl: 余额响应格式未知。")
    if data.get("success") is False:
        error = data.get("error") or data.get("message") or "request failed"
        if isinstance(error, dict):
            error = json.dumps(error, ensure_ascii=False)
        return _error_report(credential, f"Firecrawl: {error}")

    usage = data.get("data") if isinstance(data.get("data"), dict) else {}
    remaining = _number(usage.get("remainingCredits"))
    limit = _number(usage.get("planCredits"))
    resets_at = usage.get("billingPeriodEnd")
    if not isinstance(resets_at, str):
        resets_at = None
    return BalanceReport(
        provider="firecrawl",
        status="ok",
        scope="team",
        unit="credits",
        remaining=remaining,
        limit=limit,
        # remainingCredits can include coupons/PAYG that planCredits excludes,
        # so there is no reliable used number to derive here.
        used=None,
        resets_at=resets_at,
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "firecrawl",
            missing_message="missing FIRECRAWL_API_KEY",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_firecrawl, q, key, cfg.counts["firecrawl"], timeout=ctx.timeout, deadline=ctx.deadline,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='firecrawl',
    label='Firecrawl',
    key_provider='firecrawl',
    search_sources=('firecrawl',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "firecrawl"),
        AuthMethod("oauth", "浏览器登录", "firecrawl"),
    ),
    balance=balance_firecrawl,
    scrape_backends=(
        ScrapeBackendSpec("firecrawl_key", "firecrawl", True,
                          dispatch="_scrape_firecrawl_key", order=4),
        ScrapeBackendSpec("firecrawl_anon", "firecrawl", False, supports_anonymous=True,
                          dispatch="_scrape_firecrawl_anon", order=5),
        ScrapeBackendSpec("firecrawl", "firecrawl", False, dispatch="_scrape_firecrawl", order=1,
                          legacy_channels=("firecrawl_key", "firecrawl_anon")),
    ),
)

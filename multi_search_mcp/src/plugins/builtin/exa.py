"""Exa provider declaration."""
import json
import urllib.error
import urllib.request

from ...state.key_state import key_fingerprint
from ...support.http import read_limited
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin, ScrapeBackendSpec


EXA_BALANCE_URL = "https://admin-api.exa.ai/team-management/credits"
_BALANCE_HTTP_ERROR_KINDS = {
    401: "invalid",
    403: "invalid",
    402: "quota_exhausted",
    429: "rate_limit",
}
EXA_BALANCE_NOTE = "需要联系 Exa 开通 Team Management API 后创建 service key（EXA_SERVICE_KEY）。"


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _error_report(credential: str, message: str, kind: str = "error") -> BalanceReport:
    return BalanceReport(
        provider="exa",
        status="error",
        error_kind=kind,
        message=scrub_secrets(message, credential),
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def balance_exa(credential: str, ctx: BalanceContext) -> BalanceReport:
    """Return the team USD credit balance from the Team Management API."""
    request = urllib.request.Request(
        EXA_BALANCE_URL,
        headers={"x-api-key": credential, "Accept": "application/json"},
    )
    try:
        with ctx.open(request) as response:
            data = json.loads(read_limited(response))
    except urllib.error.HTTPError as exc:
        row = http_error_row(
            "exa", exc, secret=credential, kinds=_BALANCE_HTTP_ERROR_KINDS, prefix="Exa: ",
        )
        return _error_report(credential, row["error"], row["kind"])
    except (ValueError, TypeError):
        return _error_report(credential, "Exa: 余额响应不是有效 JSON。")

    if not isinstance(data, dict):
        return _error_report(credential, "Exa: 余额响应格式未知。")
    return BalanceReport(
        provider="exa",
        status="ok",
        scope="team",
        unit="usd",
        remaining=_number(data.get("credits_usd")),
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "exa",
            missing_message="missing EXA_API_KEY",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_exa, q, key, cfg.counts["exa"], timeout=ctx.timeout, deadline=ctx.deadline,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='exa',
    label='Exa',
    key_provider='exa',
    search_sources=('exa',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "exa"),
        AuthMethod("api", "管理 Key（查余额用）", "exa_admin", "balance_only"),
    ),
    balance=balance_exa,
    balance_credential="exa_admin",
    balance_note=EXA_BALANCE_NOTE,
    scrape_backends=(
        ScrapeBackendSpec("exa", "exa", True, dispatch="_scrape_exa", order=2),
    ),
)

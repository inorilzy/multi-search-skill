"""Jina AI provider declaration."""
import json
import urllib.error
import urllib.parse
import urllib.request

from ...state.key_state import key_fingerprint
from ...support.http import read_limited
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin, ScrapeBackendSpec


JINA_BALANCE_URL = "https://dash.jina.ai/api/v1/api_key/fe_user"
_BALANCE_HTTP_ERROR_KINDS = {
    401: "invalid",
    403: "invalid",
    402: "quota_exhausted",
    429: "rate_limit",
}
JINA_BALANCE_NOTE = "非公开接口：余额来自 Jina dashboard 的内部 API，可能随时变化。"


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _error_report(credential: str, message: str, kind: str = "error") -> BalanceReport:
    return BalanceReport(
        provider="jina",
        status="error",
        error_kind=kind,
        message=scrub_secrets(message, credential),
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def balance_jina(credential: str, ctx: BalanceContext) -> BalanceReport:
    """Return the token balance from Jina's unofficial dashboard endpoint."""
    url = f"{JINA_BALANCE_URL}?{urllib.parse.urlencode({'api_key': credential})}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with ctx.open(request) as response:
            data = json.loads(read_limited(response))
    except urllib.error.HTTPError as exc:
        row = http_error_row(
            "jina", exc, secret=credential, kinds=_BALANCE_HTTP_ERROR_KINDS, prefix="Jina: ",
        )
        return _error_report(credential, row["error"], row["kind"])
    except (ValueError, TypeError):
        return _error_report(credential, "Jina: 余额响应不是有效 JSON。")

    if not isinstance(data, dict):
        return _error_report(credential, "Jina: 余额响应格式未知。")
    wallet = data.get("wallet") if isinstance(data.get("wallet"), dict) else {}
    return BalanceReport(
        provider="jina",
        status="ok",
        scope="key",
        unit="tokens",
        remaining=_number(wallet.get("total_balance")),
        limit=None,
        used=None,
        key_fingerprint=key_fingerprint(credential) if credential else None,
        message=JINA_BALANCE_NOTE,
    )


PLUGIN = ProviderPlugin(
    id='jina',
    label='Jina AI',
    key_provider='jina',
    auth_methods=(
        AuthMethod("api", "API Key", "jina"),
    ),
    balance=balance_jina,
    scrape_backends=(
        ScrapeBackendSpec("jina_key", "jina", True, dispatch="_scrape_jina_key", order=0),
        ScrapeBackendSpec("jina_anon", "jina", False, supports_anonymous=True,
                          dispatch="_scrape_jina_anon", order=1),
        ScrapeBackendSpec("jina", "jina", False, supports_anonymous=True,
                          dispatch="_scrape_jina", order=0,
                          legacy_channels=("jina_anon", "jina_key")),
    ),
)

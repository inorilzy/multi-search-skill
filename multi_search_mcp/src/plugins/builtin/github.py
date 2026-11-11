"""GitHub provider declaration."""
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ...state.key_state import key_fingerprint
from ...support.http import read_limited
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin


GITHUB_BALANCE_URL = "https://api.github.com/rate_limit"
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
        provider="github",
        status="error",
        error_kind=kind,
        message=scrub_secrets(message, credential),
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def _reset_time(resource: dict) -> str | None:
    reset = _number(resource.get("reset"))
    if reset is None:
        return None
    try:
        return datetime.fromtimestamp(reset, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def balance_github(credential: str, ctx: BalanceContext) -> list[BalanceReport]:
    """Return search and code-search quota; anonymous queries are supported."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if credential:
        headers["Authorization"] = f"Bearer {credential}"
    request = urllib.request.Request(GITHUB_BALANCE_URL, headers=headers)
    try:
        with ctx.open(request) as response:
            data = json.loads(read_limited(response))
    except urllib.error.HTTPError as exc:
        row = http_error_row(
            "github", exc, secret=credential, kinds=_BALANCE_HTTP_ERROR_KINDS, prefix="GitHub: ",
        )
        return [_error_report(credential, row["error"], row["kind"])]
    except (ValueError, TypeError):
        return [_error_report(credential, "GitHub: 余额响应不是有效 JSON。")]

    if not isinstance(data, dict):
        return [_error_report(credential, "GitHub: 余额响应格式未知。")]
    resources = data.get("resources") if isinstance(data.get("resources"), dict) else {}
    reports = []
    for name in ("search", "code_search"):
        resource = resources.get(name) if isinstance(resources.get(name), dict) else {}
        remaining = _number(resource.get("remaining"))
        limit = _number(resource.get("limit"))
        reports.append(BalanceReport(
            provider="github",
            status="ok",
            scope="key",
            unit="requests",
            remaining=remaining,
            limit=limit,
            used=_number(resource.get("used")),
            resets_at=_reset_time(resource),
            period="hour",
            key_fingerprint=key_fingerprint(credential) if credential else None,
            message=f"{name}: {remaining}/{limit} requests",
        ))
    return reports


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "github_repos",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_github_repos, q, cfg.counts["github"], key or "", timeout=ctx.timeout,
                deadline=ctx.deadline,
            ),
        ),
        registry._provider_spec(
            "github_code",
            missing_message="missing GITHUB_TOKEN / GH_TOKEN (GitHub code search requires a token)",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_github_code, q, cfg.counts["github_code"], key or "", timeout=ctx.timeout,
                deadline=ctx.deadline,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='github',
    label='GitHub',
    key_provider='github',
    search_sources=('github_repos', 'github_code'),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "github"),
    ),
    # An empty balance credential means "optional": use the GitHub search token
    # when configured, otherwise query the unauthenticated rate limit.
    balance_credential='',
    balance=balance_github,
)

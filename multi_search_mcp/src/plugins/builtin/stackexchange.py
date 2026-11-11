"""Stack Exchange provider declaration."""
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin
from ..quota_record import quota_report


def balance_stackexchange(credential: str, ctx: BalanceContext) -> BalanceReport:
    """Read the daily quota recorded by the last successful search."""
    return quota_report("stackexchange", credential, unit="requests", period="day")


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "stackoverflow",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_stackoverflow, q, cfg.counts["stackoverflow"], timeout=ctx.timeout,
                deadline=ctx.deadline, api_key=key or "",
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='stackexchange',
    label='Stack Exchange',
    key_provider='stackexchange',
    search_sources=('stackoverflow',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "stackexchange"),
    ),
    # An empty balance credential means optional: use the configured search key
    # when present, otherwise read the anonymous search record.
    balance_credential='',
    balance=balance_stackexchange,
    balance_note='搜索一次后显示每日配额。',
)

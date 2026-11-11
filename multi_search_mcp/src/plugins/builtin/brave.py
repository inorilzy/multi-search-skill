"""Brave Search provider declaration."""
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin
from ..quota_record import quota_report


def balance_brave(credential: str, ctx: BalanceContext) -> BalanceReport:
    """Read the monthly quota recorded by the last successful search."""
    return quota_report("brave", credential, unit="requests", period="month")


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "brave",
            missing_message="missing BRAVE_SEARCH_API_KEY / BRAVE_API_KEY",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_brave, q, key, cfg.counts["brave"], timeout=ctx.timeout, deadline=ctx.deadline,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='brave',
    label='Brave Search',
    key_provider='brave',
    search_sources=('brave',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "brave"),
    ),
    balance=balance_brave,
    balance_note='搜索一次后显示本月配额。',
)

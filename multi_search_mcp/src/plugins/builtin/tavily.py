"""Tavily provider declaration."""
from ..base import AuthMethod, ProviderPlugin, ScrapeBackendSpec


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
    balance_note='Key 与账户用量查询待实现。',
    scrape_backends=(
        ScrapeBackendSpec("tavily", "tavily", True, dispatch="_scrape_tavily", order=3),
    ),
)

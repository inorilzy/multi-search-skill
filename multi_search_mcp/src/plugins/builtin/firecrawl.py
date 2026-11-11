"""Firecrawl provider declaration."""
from ..base import AuthMethod, ProviderPlugin, ScrapeBackendSpec


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
    balance_note='团队 credits 余额查询待实现。',
    scrape_backends=(
        ScrapeBackendSpec("firecrawl_key", "firecrawl", True,
                          dispatch="_scrape_firecrawl_key", order=4),
        ScrapeBackendSpec("firecrawl_anon", "firecrawl", False, supports_anonymous=True,
                          dispatch="_scrape_firecrawl_anon", order=5),
        ScrapeBackendSpec("firecrawl", "firecrawl", False, dispatch="_scrape_firecrawl", order=1,
                          legacy_channels=("firecrawl_key", "firecrawl_anon")),
    ),
)

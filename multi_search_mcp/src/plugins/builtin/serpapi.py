"""SerpAPI provider declaration."""
from ..base import AuthMethod, ProviderPlugin


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
    balance_note='免费账户余额查询待实现。',
)

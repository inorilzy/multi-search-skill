"""Hacker News provider declaration."""
from ..base import ProviderPlugin


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "hackernews",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(registry.search_hackernews, q, cfg.counts["hackernews"], timeout=ctx.timeout, deadline=ctx.deadline),
        ),
    )


PLUGIN = ProviderPlugin(
    id='hackernews',
    label='Hacker News',
    key_provider=None,
    search_sources=('hackernews',),
    search_specs=search_specs,
    balance_note='匿名 Hacker News 搜索无配额查询接口，不支持余额查询。',
)

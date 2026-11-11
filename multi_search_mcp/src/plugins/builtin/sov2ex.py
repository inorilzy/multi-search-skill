"""V2EX / SOV2EX provider declaration."""
from ..base import ProviderPlugin


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "sov2ex",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_sov2ex, q, cfg.counts["sov2ex"], timeout=ctx.timeout, deadline=ctx.deadline,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='sov2ex',
    label='V2EX / SOV2EX',
    key_provider=None,
    search_sources=('sov2ex',),
    search_specs=search_specs,
    balance_note='匿名 V2EX / SOV2EX 搜索无配额查询接口，不支持余额查询。',
)

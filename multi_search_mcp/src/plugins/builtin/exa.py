"""Exa provider declaration."""
from ..base import AuthMethod, ProviderPlugin, ScrapeBackendSpec


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
    balance_credential="exa_admin",
    balance_note='需要单独的 Team Management service key，查询能力待实现。',
    scrape_backends=(
        ScrapeBackendSpec("exa", "exa", True, dispatch="_scrape_exa", order=2),
    ),
)

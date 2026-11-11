"""Parallel provider declaration."""
from ..base import AuthMethod, ProviderPlugin


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "parallel",
            missing_message="missing PARALLEL_API_KEY",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_parallel, q, key, cfg.counts["parallel"], timeout=ctx.timeout, deadline=ctx.deadline,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='parallel',
    label='Parallel',
    key_provider='parallel',
    search_sources=('parallel',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "parallel"),
        AuthMethod("oauth", "浏览器登录（查余额用）", "parallel_account", "balance_only"),
    ),
    balance_credential="parallel_account",
    balance_note='需要 Account API 登录后查询余额，查询能力待实现。',
)

"""GitHub provider declaration."""
from ..base import AuthMethod, ProviderPlugin


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
    balance_note='搜索与代码搜索限额查询待实现，支持匿名查询。',
)

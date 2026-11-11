"""Twitter / X provider declaration."""
from ..base import AuthMethod, ProviderPlugin


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "twitter",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_twitter,
                q,
                cfg.counts["twitter"],
                cfg.keys.get("twitter") or cfg.keys.get("twitter_cookies", ""),
                timeout=ctx.timeout,
                deadline=ctx.deadline, publish_partial=ctx.publish_partial,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='twitter',
    label='Twitter / X',
    key_provider='twitter',
    search_sources=('twitter',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "Cookie 凭据", "twitter"),
    ),
    balance_note='Twitter / X 仅支持 Cookie 登录，搜索无余额查询接口。',
)

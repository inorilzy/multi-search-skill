"""百度千帆 provider declaration."""
from ..base import AuthMethod, ProviderPlugin


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "baidu",
            missing_message="missing BAIDU_QIANFAN_API_KEY / QIANFAN_API_KEY / APPBUILDER_API_KEY",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_baidu, q, key, cfg.counts["baidu"], timeout=ctx.timeout, deadline=ctx.deadline,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='baidu',
    label='百度千帆',
    key_provider='baidu',
    search_sources=('baidu',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "baidu"),
    ),
    balance_note='搜索 Key 无余额接口，免费额度无查询接口，现金余额需 AK/SK，暂不支持。',
)

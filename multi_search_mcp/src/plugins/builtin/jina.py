"""Jina AI provider declaration."""
from ..base import AuthMethod, ProviderPlugin, ScrapeBackendSpec


PLUGIN = ProviderPlugin(
    id='jina',
    label='Jina AI',
    key_provider='jina',
    auth_methods=(
        AuthMethod("api", "API Key", "jina"),
    ),
    balance_note='Token 余额查询待实现，使用未公开的 dashboard 接口。',
    scrape_backends=(
        ScrapeBackendSpec("jina_key", "jina", True, dispatch="_scrape_jina_key", order=0),
        ScrapeBackendSpec("jina_anon", "jina", False, supports_anonymous=True,
                          dispatch="_scrape_jina_anon", order=1),
        ScrapeBackendSpec("jina", "jina", False, supports_anonymous=True,
                          dispatch="_scrape_jina", order=0,
                          legacy_channels=("jina_anon", "jina_key")),
    ),
)

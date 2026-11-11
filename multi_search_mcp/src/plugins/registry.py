"""Deterministic built-in declarations; no discovery or external loading."""
from .base import ProviderPlugin, ScrapeBackendSpec
from .builtin import (
    baidu,
    brave,
    exa,
    firecrawl,
    github,
    hackernews,
    jina,
    parallel,
    serpapi,
    sov2ex,
    stackexchange,
    tavily,
    twitter,
)


def builtin_plugins() -> tuple[ProviderPlugin, ...]:
    """Return plugins in historical search-registry order (Jina is scrape-only).

    Read module attributes on every call so a later balance adapter can replace
    a frozen declaration without leaving a stale registry snapshot.
    """
    return (
        brave.PLUGIN, parallel.PLUGIN, baidu.PLUGIN, tavily.PLUGIN, exa.PLUGIN,
        serpapi.PLUGIN, firecrawl.PLUGIN, sov2ex.PLUGIN, github.PLUGIN,
        hackernews.PLUGIN, stackexchange.PLUGIN, twitter.PLUGIN, jina.PLUGIN,
    )


def get_plugin(id: str) -> ProviderPlugin:
    """Look up an exact plugin id; unknown ids raise KeyError."""
    for plugin in builtin_plugins():
        if plugin.id == id:
            return plugin
    raise KeyError(id)


def builtin_scrape_backends(*, legacy: bool = False) -> tuple[ScrapeBackendSpec, ...]:
    """Return channel declarations in their original chain or legacy-name order."""
    specs = (
        spec for plugin in builtin_plugins() for spec in plugin.scrape_backends
        if bool(spec.legacy_channels) == legacy
    )
    return tuple(sorted(specs, key=lambda spec: spec.order))

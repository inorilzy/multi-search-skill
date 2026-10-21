"""Test helper for building ``ScrapeContext`` values.

Production callers construct ``ScrapeContext`` directly (service.py passes
KeyManager-filtered candidates). Tests often need the same thing from plain
key strings, so this module keeps that convenience out of production code.
"""
from multi_search_mcp.src.scrape.scrape import ScrapeContext, keys_for_backend


_ALLOWED = {
    "backends", "deadline", "site_memory", "key_manager", "url_resolver",
    "scrape_chars", "timeout", "jina_prefer_keyed", "twitter_cookies",
    "primary",
}


def context(*, keys=None, **options):
    """Build a ScrapeContext from ``{backend: key-or-keys}`` plus options."""
    keys_by_backend = {
        backend: keys_for_backend(backend, value)
        for backend, value in (keys or {}).items()
    }
    unexpected = set(options) - _ALLOWED
    if unexpected:
        raise TypeError(f"unexpected context options: {sorted(unexpected)}")
    return ScrapeContext(keys_by_backend=keys_by_backend, **options)

"""Core-owned key-state and site-memory commands shared by every entry point.

The CLI is the product entry; the legacy Python adapters in ``tools.py`` call
these same functions. No entry point reimplements the SQLite reads/writes.
"""
from __future__ import annotations

from typing import Any

from ..support.backends import KNOWN_BACKENDS
from .key_state import SQLiteKeyManager
from .site_memory import SiteScraperMemory
from .state_store import StateStore


def key_status(provider: str | None = None, store: StateStore | None = None) -> list[dict[str, Any]]:
    """Return key-health rows, optionally scoped to one provider."""
    return SQLiteKeyManager(store or StateStore()).status_rows(provider)


def reset_key_state(
    provider: str | None = None,
    key_id: str | None = None,
    store: StateStore | None = None,
) -> int:
    """Reset matching key-health rows and return how many changed."""
    return SQLiteKeyManager(store or StateStore()).reset(provider=provider, key_id=key_id)


def site_scraper_stats(site: str | None = None, store: StateStore | None = None) -> list[dict[str, Any]]:
    """Return per-site scraper statistics, optionally scoped to one site key."""
    return SiteScraperMemory(store or StateStore()).stats(site)


def set_site_scraper_preference(
    site: str,
    scraper: str,
    priority: int | None = None,
    note: str | None = None,
    store: StateStore | None = None,
) -> dict[str, Any]:
    """Pin a scraper for one site key. Unknown backends fail before any write."""
    if scraper not in KNOWN_BACKENDS:
        raise ValueError(f"unknown scraper: {scraper!r}")
    SiteScraperMemory(store or StateStore()).set_preference(
        site, scraper, priority=priority, note=note,
    )
    return {"site": site, "scraper": scraper, "pinned": True, "priority": priority}


def reset_site_scraper_stats(site: str | None = None, store: StateStore | None = None) -> int:
    """Reset one site's stats/attempts, or every site when ``site`` is omitted."""
    return SiteScraperMemory(store or StateStore()).reset(site)

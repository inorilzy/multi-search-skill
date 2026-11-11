"""Canonical scrape-backend names shared by entry points and Core.

A scrape chain lists *channels*: one service reached one way. Jina and
Firecrawl each have a keyed and an anonymous channel, so the user can order
"use my key first" or "try the free channel first" explicitly. Exa and Tavily
only exist as keyed channels and keep their historical names.

The historical names ``jina`` and ``firecrawl`` stay accepted everywhere a
chain is read (settings, ``--backend``, site preferences) with their original
combined behavior, so saved settings keep behaving exactly as before. The
desktop shows them as their two channels (``LEGACY_BACKENDS``) and saves
channel names once the user edits the chain.
"""
from __future__ import annotations

from collections.abc import Iterable

# Selectable generic channels in the factory chain order: keyed Jina first for
# speed (anonymous Jina is often slow), then the free channel, then the paid
# fallbacks, with anonymous Firecrawl as the last resort.
KNOWN_BACKENDS = ("jina_key", "jina_anon", "exa", "tavily", "firecrawl_key", "firecrawl_anon")
DEFAULT_SCRAPE_CHAIN = KNOWN_BACKENDS
# Channels that cannot run without a configured key. Used to distinguish
# "no key configured" from "backend unknown" when a caller forces a list.
KEYED_BACKENDS = ("jina_key", "exa", "tavily", "firecrawl_key")
# The provider (credential pool and response ``via``) behind each channel.
BACKEND_PROVIDERS = {
    "jina_key": "jina", "jina_anon": "jina", "exa": "exa", "tavily": "tavily",
    "firecrawl_key": "firecrawl", "firecrawl_anon": "firecrawl",
}
# Historical single names and the channel order they used to run in: Jina was
# anonymous-first, Firecrawl keyed-first.
LEGACY_BACKENDS = {
    "jina": ("jina_anon", "jina_key"),
    "firecrawl": ("firecrawl_key", "firecrawl_anon"),
}
# Every name a chain, ``--backend`` or a site preference accepts.
ACCEPTED_BACKENDS = KNOWN_BACKENDS + tuple(LEGACY_BACKENDS)


def expand_backends(names: Iterable[str]) -> tuple[str, ...]:
    """Expand historical names into channels (desktop display); first position wins.

    Raises ``ValueError`` naming the first unknown entry.
    """
    chain: list[str] = []
    for name in names:
        if name in LEGACY_BACKENDS:
            channels = LEGACY_BACKENDS[name]
        elif name in KNOWN_BACKENDS:
            channels = (name,)
        else:
            raise ValueError(f"unknown scrape backend: {name}")
        chain.extend(channel for channel in channels if channel not in chain)
    return tuple(chain)


def backend_provider(name: str) -> str:
    """Provider behind a channel (or a historical name)."""
    return BACKEND_PROVIDERS.get(name, name)

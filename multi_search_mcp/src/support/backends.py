"""Canonical scrape-backend names shared by entry points and Core."""
from __future__ import annotations

# Selectable generic backends. Platform scrapers are selected by URL domain.
KNOWN_BACKENDS = ("jina", "exa", "tavily", "firecrawl")
# Keyed backends whose only requirement to run is a configured key. Used to
# distinguish "no key configured" from "backend unknown" when a caller forces
# a specific backend list.
KEYED_BACKENDS = ("exa", "tavily")

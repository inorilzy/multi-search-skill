"""Public service facade for search, fetch, scrape, read and diagnostics.

The implementation lives in ``core.*``. This module defines the public surface
and note the import-time aliases: pipelines look configuration and credentials
up through ``core.runtime``, so patching those names here no longer affects a
request. Tests should patch the owning module instead.

Fan-out capacity is deliberately per layer: query expansion (``_EXPAND_POOL``),
provider calls (``search.search_runner._SEARCH_POOL``) and body fetching
(``scrape.stage._SCRAPE_POOL``) each own an isolated ``BoundedDaemonExecutor``.
Sharing one pool across nested fan-out risks slot starvation and deadlock.
"""
from __future__ import annotations

from .core.body_fetch import run_fetch_source, run_read_source
from .core.diagnostics import doctor_data, list_sources
from .core.present import run_multi_search
from .core.requests import (
    FetchSourceRequest,
    MultiSearchRequest,
    ReadSourceRequest,
    ScrapeRequest,
    SearchWebRequest,
)
from .core.scrape_pipeline import run_scrape
from .core.search_pipeline import MAX_EXPAND_CONCURRENCY, run_search_web


__all__ = [
    "FetchSourceRequest",
    "MAX_EXPAND_CONCURRENCY",
    "MultiSearchRequest",
    "ReadSourceRequest",
    "ScrapeRequest",
    "SearchWebRequest",
    "doctor_data",
    "list_sources",
    "run_fetch_source",
    "run_multi_search",
    "run_read_source",
    "run_scrape",
    "run_search_web",
]

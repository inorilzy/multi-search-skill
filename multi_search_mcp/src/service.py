"""Public Core API facade.

The implementation is split by responsibility:

- ``support.requests``: typed request DTOs
- ``search.resolve``: planning (``SearchPlanRequest`` -> ``ResolvedSearchPlan``)
- ``search.candidates``: candidate search and provider diagnostics
- ``search_web``: search-and-fetch orchestration
- ``multi_search``: compatibility multi-search presentation
- ``scrape.fetch`` / ``scrape.service``: fetching and scraping
- ``read``: cache-only reads
- ``search.formatting``: response projections
- ``diagnostics``: source listing, doctor data and the config storage protocol
- ``state.runtime``: configuration, credential and managed-cookie assembly
- ``providers``: provider-specific helpers shared by searchers and scrapers

This module only re-exports that surface for CLI, tools, tests, and snapshot
capture. Keep it free of implementation logic. Pipelines look configuration and
credentials up through ``state.runtime``, so tests patch the owning module, not
the names re-exported here.

Fan-out capacity is deliberately per layer: query expansion, provider calls and
body fetching each own an isolated ``BoundedDaemonExecutor``. Sharing one pool
across nested fan-out risks slot starvation and deadlock.
"""
from __future__ import annotations

from .diagnostics import config_storage, doctor_data, keys_file_warnings, list_sources
from .multi_search import run_multi_search
from .read import run_read_source
from .scrape.fetch import run_fetch_source
from .scrape.service import run_scrape, run_scrape_raw
from .search.candidates import (
    query_failures,
    query_provider_status,
    run_search_candidates,
    summarize_key_status,
)
from .search.formatting import (
    DISPLAY_SNIPPET_CHARS,
    compact_text,
    compat_source_summaries,
    display_results,
    extract_source_briefs,
    extract_summaries,
    route_degradation,
    source_from_answer_source,
)
from .search.resolve import (
    COUNT_CAPS,
    DEFAULT_COUNTS,
    ResolvedSearchPlan,
    SearchPlanRequest,
    build_counts,
    resolve_active_sources,
    resolve_disabled_sources,
    resolve_search_plan,
)
from .search_web import run_search_web
from .state.key_state import summarize_status_rows
from .support.requests import (
    FetchSourceRequest,
    MultiSearchRequest,
    ReadSourceRequest,
    ScrapeRequest,
    SearchWebRequest,
)


__all__ = [
    "COUNT_CAPS",
    "DEFAULT_COUNTS",
    "DISPLAY_SNIPPET_CHARS",
    "FetchSourceRequest",
    "MultiSearchRequest",
    "ReadSourceRequest",
    "ResolvedSearchPlan",
    "ScrapeRequest",
    "SearchPlanRequest",
    "SearchWebRequest",
    "build_counts",
    "compact_text",
    "compat_source_summaries",
    "config_storage",
    "display_results",
    "doctor_data",
    "extract_source_briefs",
    "extract_summaries",
    "keys_file_warnings",
    "list_sources",
    "query_failures",
    "query_provider_status",
    "resolve_active_sources",
    "resolve_disabled_sources",
    "resolve_search_plan",
    "route_degradation",
    "run_fetch_source",
    "run_multi_search",
    "run_read_source",
    "run_scrape",
    "run_scrape_raw",
    "run_search_candidates",
    "run_search_web",
    "source_from_answer_source",
    "summarize_key_status",
    "summarize_status_rows",
]

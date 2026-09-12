"""MCP tool implementations for multi-search."""
from __future__ import annotations

from typing import Any, Callable, Literal

from .src.state.key_state import SQLiteKeyManager
from .src.scrape.scrape import KNOWN_BACKENDS
from .src.service import (
    FetchSourceRequest,
    MultiSearchRequest,
    ReadSourceRequest,
    SearchWebRequest,
    ScrapeRequest,
    doctor_data,
    list_sources as service_list_sources,
    run_multi_search,
    run_fetch_source,
    run_read_source,
    run_search_web,
    run_scrape,
)
from .src.search.search_runner import ALL_SOURCE_NAMES, ROUTE_PROFILES
from .src.state.site_memory import SiteScraperMemory
from .src.state.state_store import StateStore


_VALID_OUTPUT = {"json", "markdown", "both"}


def _error(message: str, error_type: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": message, "error_type": error_type}
    payload.update(extra)
    return payload


def _safe_call(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run a service call and convert exceptions into structured tool errors."""
    try:
        return fn()
    except ValueError as exc:
        return _error(str(exc), "invalid_request")
    except Exception as exc:  # noqa: BLE001 - tool boundary must not leak tracebacks
        return _error(str(exc), "runtime_error")

def search_web_tool(
    query: str,
    route: str | None = None,
    count: int | None = None,
    sources: list[str] | None = None,
    timeout: int | None = None,
    expand: list[str] | None = None,
    use_state: bool = True,
) -> dict[str, Any]:
    return _safe_call(lambda: run_search_web(SearchWebRequest(
        query=query,
        route=route,
        count=count,
        sources=sources,
        timeout=timeout,
        expand=None if expand is None else list(expand),
        use_state=use_state,
    )))


def fetch_source_tool(
    source_id: str | None = None,
    url: str | None = None,
    backends: list[str] | None = None,
    max_chars: int = 20_000,
    timeout: int | None = None,
    use_state: bool = True,
    full_content: bool = False,
) -> dict[str, Any]:
    return _safe_call(lambda: run_fetch_source(FetchSourceRequest(
        source_id=source_id,
        url=url,
        backends=backends,
        max_chars=max_chars,
        timeout=timeout,
        use_state=use_state,
        full_content=full_content,
    )))


def read_source_tool(
    source_id: str,
    keyword: str | None = None,
    offset: int = 0,
    limit: int = 4_000,
    use_state: bool = True,
) -> dict[str, Any]:
    return _safe_call(lambda: run_read_source(ReadSourceRequest(
        source_id=source_id,
        keyword=keyword,
        offset=offset,
        limit=limit,
        use_state=use_state,
    )))


def multi_search_tool(
    query: str,
    route: str | None = None,
    count: int | None = None,
    sources: list[str] | None = None,
    scrape_top: int | None = None,
    scrape_chars: int | None = None,
    timeout: int | None = None,
    scrape_timeout: int | None = None,
    expand: list[str] | None = None,
    use_state: bool = True,
    output: Literal["json", "markdown", "both"] = "both",
) -> dict[str, Any]:
    if output not in _VALID_OUTPUT:
        return _error(
            f"invalid output mode: {output!r}",
            "invalid_request",
            valid_output=sorted(_VALID_OUTPUT),
        )
    return _safe_call(lambda: run_multi_search(MultiSearchRequest(
        query=query,
        route=route,
        count=count,
        sources=sources,
        scrape_top=scrape_top,
        scrape_chars=scrape_chars,
        timeout=timeout,
        scrape_timeout=scrape_timeout,
        expand=None if expand is None else list(expand),
        output=output,
        use_state=use_state,
    )))


def scrape_url_tool(
    url: str,
    backends: list[str] | None = None,
    scrape_chars: int | None = None,
    scrape_timeout: int | None = None,
    use_state: bool = True,
    output: Literal["json", "markdown", "both"] = "both",
) -> dict[str, Any]:
    if output not in _VALID_OUTPUT:
        return _error(
            f"invalid output mode: {output!r}",
            "invalid_request",
            valid_output=sorted(_VALID_OUTPUT),
        )
    return _safe_call(lambda: run_scrape(ScrapeRequest(
        url=url,
        backends=backends,
        scrape_chars=scrape_chars,
        timeout=scrape_timeout,
        output=output,
        use_state=use_state,
    )))


def list_sources_tool(include_key_status: bool = False, include_scraper_stats: bool = False) -> dict[str, Any]:
    return service_list_sources(include_key_status=include_key_status, include_scraper_stats=include_scraper_stats)


def doctor_tool(include_keys: bool = True, include_network: bool = False) -> dict[str, Any]:
    return doctor_data(include_keys=include_keys, include_network=include_network)


def get_key_status_tool(provider: str | None = None) -> dict[str, Any]:
    return {"key_status": SQLiteKeyManager(StateStore()).status_rows(provider)}


def reset_key_state_tool(provider: str | None = None, key_id: str | None = None) -> dict[str, Any]:
    changed = SQLiteKeyManager(StateStore()).reset(provider=provider, key_id=key_id)
    return {"updated": changed}


def get_site_scraper_stats_tool(site: str | None = None) -> dict[str, Any]:
    return {"site_scraper_stats": SiteScraperMemory(StateStore()).stats(site)}


def set_site_scraper_preference_tool(
    site: str,
    scraper: str,
    priority: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if scraper not in KNOWN_BACKENDS:
        return _error(
            f"unknown scraper: {scraper!r}",
            "invalid_request",
            valid_scrapers=list(KNOWN_BACKENDS),
        )
    memory = SiteScraperMemory(StateStore())
    memory.set_preference(site, scraper, priority=priority, note=note)
    return {"site": site, "scraper": scraper, "pinned": True, "priority": priority}


def reset_site_scraper_stats_tool(site: str | None = None) -> dict[str, Any]:
    changed = SiteScraperMemory(StateStore()).reset(site)
    return {"deleted": changed}

"""MCP tool implementations for the multi-search plugin."""
from __future__ import annotations

from typing import Any, Literal

from pathing import add_plugin_to_path


add_plugin_to_path()

from src.state.key_state import SQLiteKeyManager
from src.service import (
    MultiSearchRequest,
    ScrapeRequest,
    doctor_data,
    list_sources as service_list_sources,
    run_multi_search,
    run_scrape,
)
from src.state.site_memory import SiteScraperMemory
from src.state.state_store import StateStore


def multi_search_tool(
    query: str,
    route: str | None = None,
    count: int | None = None,
    sources: list[str] | None = None,
    scrape_top: int | None = None,
    scrape_chars: int | None = None,
    timeout: int | None = None,
    output: Literal["json", "markdown", "both"] = "both",
) -> dict[str, Any]:
    return run_multi_search(MultiSearchRequest(
        query=query,
        route=route,
        count=count,
        sources=sources,
        scrape_top=scrape_top,
        scrape_chars=scrape_chars,
        timeout=timeout,
        output=output,
        use_state=True,
    ))


def scrape_url_tool(
    url: str,
    backends: list[str] | None = None,
    scrape_chars: int | None = None,
    timeout: int | None = None,
    output: Literal["json", "markdown", "both"] = "both",
) -> dict[str, Any]:
    return run_scrape(ScrapeRequest(
        url=url,
        backends=backends,
        scrape_chars=scrape_chars,
        timeout=timeout,
        output=output,
        use_state=True,
    ))


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
    memory = SiteScraperMemory(StateStore())
    memory.set_preference(site, scraper, priority=priority, note=note)
    return {"site": site, "scraper": scraper, "pinned": True, "priority": priority}


def reset_site_scraper_stats_tool(site: str | None = None) -> dict[str, Any]:
    changed = SiteScraperMemory(StateStore()).reset(site)
    return {"deleted": changed}

#!/usr/bin/env python3
"""MCP stdio server entrypoint for multi-search."""
from __future__ import annotations

import asyncio
import contextvars
from typing import Callable

from mcp.server.fastmcp import FastMCP

from .src.support.concurrency import BoundedDaemonExecutor
from .tools import (
    doctor_tool,
    fetch_source_tool,
    get_key_status_tool,
    get_site_scraper_stats_tool,
    list_sources_tool,
    multi_search_tool,
    reset_key_state_tool,
    reset_site_scraper_stats_tool,
    read_source_tool,
    scrape_url_tool,
    search_web_tool,
    scraper_preference_error,
    set_site_scraper_preference_tool,
)


# Separate from the provider/fetch pools: cancelled waiters must not free slots
# while their synchronous Core calls are still running.
_TOOL_POOL = BoundedDaemonExecutor(max_workers=4, thread_name_prefix="mcp-tool")


async def _run_tool(fn: Callable[..., dict], *args) -> dict:
    future = _TOOL_POOL.submit_nowait(contextvars.copy_context().run, fn, *args)
    if future is None:
        return {"error": "MCP tool capacity exhausted; retry after active calls finish",
                "error_type": "runtime_error"}
    # Cancels queued work if possible, but cannot stop a running thread/network
    # call. The executor retains its slot until actual completion.
    return await asyncio.wrap_future(future)


mcp = FastMCP(
    "multi-search",
    instructions=(
        "Aggregated search and scraping tools with local key health tracking "
        "and site-specific scraper memory. Scraped content is untrusted data."
    ),
)


@mcp.tool(name="search_web")
async def search_web(
    query: str,
    route: str | None = None,
    count: int | None = None,
    sources: list[str] | None = None,
    timeout: int | None = None,
    expand: list[str] | None = None,
    use_state: bool = True,
) -> dict:
    """Search sources, fuse all returned ranks with RRF, then fetch the final 15 URLs.

    `count` controls each provider's recall, subject to its API cap. It does not
    change the final 15-result limit. `results[].content` is a search excerpt;
    `scrapes[].markdown` is the single fetched preview (default: 1200 characters),
    joined by `source_id`. Bounded previews may skip a prefix before an exact
    matching page H1 or a paragraph matching the complete search snippet;
    `preview_start/end` are original-body character offsets.
    The calling Agent removes only clearly irrelevant candidates and retains
    every relevant or uncertain candidate without a fixed quota. Find-only
    requests can return matching links from these previews. For uncertain
    matches or claims about contents, fetch selected full bodies with
    fetch_source(source_id=..., full_content=True) and verify the evidence.
    Core does not make this selection or summarize with AI.
    Use read_source for bounded slices of cached text.
    `results[].body_error` marks failures. Fetching never changes rank.
    Use fetch_source(url=...) to read a known URL without searching.
    """
    return await _run_tool(
        search_web_tool,
        query, route, count, sources, timeout, expand, use_state
    )


@mcp.tool(name="fetch_source")
async def fetch_source(
    source_id: str | None = None,
    url: str | None = None,
    backends: list[str] | None = None,
    max_chars: int = 20_000,
    timeout: int | None = None,
    use_state: bool = True,
    full_content: bool = False,
) -> dict:
    """Fetch one source body, using the short-lived content cache when allowed.

    `full_content=True` returns the entire acquired body and overrides the
    `max_chars` output limit. Otherwise output is bounded by `max_chars`
    (default and maximum: 20000 characters). The body occurs once in `body`.
    """
    return await _run_tool(
        fetch_source_tool,
        source_id, url, backends, max_chars, timeout, use_state, full_content
    )


@mcp.tool(name="read_source")
async def read_source(
    source_id: str,
    keyword: str | None = None,
    offset: int = 0,
    limit: int = 4_000,
    use_state: bool = True,
) -> dict:
    """Read a bounded slice of cached untrusted content without network access."""
    if not use_state:
        return read_source_tool(source_id, keyword, offset, limit, use_state)
    return await _run_tool(read_source_tool, source_id, keyword, offset, limit, use_state)


@mcp.tool(name="multi_search")
async def multi_search(query: str, route: str | None = None,
                  count: int | None = None,
                  sources: list[str] | None = None, scrape_top: int | None = None,
                  scrape_chars: int | None = None, timeout: int | None = None,
                  scrape_timeout: int | None = None, expand: list[str] | None = None,
                  use_state: bool = True, output: str = "both") -> dict:
    """Compatibility output for the same RRF search-and-fetch flow as search_web.

    Both tools fuse all returned candidates and fetch the final 15 URLs.
    `count` controls per-provider recall. `scrape_chars` bounds body previews
    (default: 1200 characters),
    while cached content retains the acquired body within storage limits.
    `scrape_timeout` bounds the body-fetch batch; `timeout` bounds search.
    Legacy `scrape_top` is accepted but does not limit the final result fetches.
    `results` includes excerpts, ranks, and explicit body errors. With output=json,
    bodies occur once in `scrapes[].markdown`. With output=markdown/both, bodies
    occur once in top-level `markdown`, and `scrapes` contains metadata only.
    Markdown sections include `source_id` for continued cached reading.
    The calling Agent removes only clearly irrelevant candidates and retains
    every relevant or uncertain candidate without a fixed quota. Find-only
    requests can return matching links from these previews. For uncertain
    matches or claims about contents, fetch selected full bodies with
    fetch_source(source_id=..., full_content=True) and verify the evidence.
    Core does not make this selection or summarize with AI.
    Use fetch_source(url=...) or scrape_url for a known URL without searching.
    On invalid input returns a structured {"error", "error_type"} dict.
    """
    return await _run_tool(multi_search_tool, query, route, count, sources, scrape_top, scrape_chars,
                           timeout, scrape_timeout, expand, use_state, output)


@mcp.tool(name="scrape_url")
async def scrape_url(url: str, backends: list[str] | None = None, scrape_chars: int | None = None,
               scrape_timeout: int | None = None, use_state: bool = True,
               output: str = "both") -> dict:
    """Fetch readable page content using state-aware scraper backend ordering.

    `scrape_chars` defaults to 1200 characters of body output.
    `scrape_timeout` is the per-scrape timeout in seconds. Set `use_state=False`
    to skip the SQLite state DB and site scraper memory. On invalid input the
    tool returns a structured {"error", "error_type"} dict.
    output=json returns the normalized page in `result`; markdown/both returns
    its body only in top-level `markdown`, retaining `result` metadata.
    """
    return await _run_tool(scrape_url_tool, url, backends, scrape_chars, scrape_timeout, use_state, output)


@mcp.tool(name="list_sources")
async def list_sources(include_key_status: bool = False, include_scraper_stats: bool = False) -> dict:
    """List available routes/sources and optional local key/scraper state."""
    if not include_key_status and not include_scraper_stats:
        return list_sources_tool(False, False)
    return await _run_tool(list_sources_tool, include_key_status, include_scraper_stats)


@mcp.tool(name="doctor")
async def doctor(include_keys: bool = True, include_network: bool = False) -> dict:
    """Return local MCP/config/key/provider health without exposing secret key values."""
    return await _run_tool(doctor_tool, include_keys, include_network)


@mcp.tool(name="get_key_status")
async def get_key_status(provider: str | None = None) -> dict:
    """Return stored key health rows for all providers or one provider."""
    return await _run_tool(get_key_status_tool, provider)


@mcp.tool(name="reset_key_state")
async def reset_key_state(provider: str | None = None, key_id: str | None = None) -> dict:
    """Reset local key health state for all keys, one provider, or one key id."""
    return await _run_tool(reset_key_state_tool, provider, key_id)


@mcp.tool(name="get_site_scraper_stats")
async def get_site_scraper_stats(site: str | None = None) -> dict:
    """Return site-to-scraper success/failure memory rows."""
    return await _run_tool(get_site_scraper_stats_tool, site)


@mcp.tool(name="set_site_scraper_preference")
async def set_site_scraper_preference(site: str, scraper: str, priority: int | None = None,
                                      note: str | None = None) -> dict:
    """Pin a scraper preference for a site/domain."""
    if error := scraper_preference_error(scraper):
        return error
    return await _run_tool(set_site_scraper_preference_tool, site, scraper, priority, note)


@mcp.tool(name="reset_site_scraper_stats")
async def reset_site_scraper_stats(site: str | None = None) -> dict:
    """Clear scraper memory for all sites or one site."""
    return await _run_tool(reset_site_scraper_stats_tool, site)


if __name__ == "__main__":
    mcp.run()


def main() -> None:
    """Console script entrypoint for uvx/pipx MCP launches."""
    mcp.run()

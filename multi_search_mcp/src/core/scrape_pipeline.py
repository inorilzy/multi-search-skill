"""State-aware scrape execution and its public projection."""
from __future__ import annotations

import time

from ..scrape.scrape import ScrapeContext, scrape_url_smart
from ..scrape.scrapers.twitter import is_twitter_url
from ..search.resolve import _resolve_int, _resolve_nonnegative
from ..state.site_memory import SiteScraperMemory
from ..support.format import format_scrapes
from ..support.models import normalize_scrape_result
from ..state.keys import jina_config_keys
from . import runtime
from .requests import ScrapeRequest


def run_scrape(
    request: ScrapeRequest | dict,
    *,
    state_store=None,
    scraper=None,
    keys: dict | None = None,
    config: dict | None = None,
    url_resolver=None,
) -> dict:
    if isinstance(request, dict):
        request = ScrapeRequest(**request)
    if request.output not in {"json", "markdown", "both"}:
        raise ValueError(
            f"invalid output mode: {request.output!r}; valid: json, markdown, both"
        )
    result, updates, scrape_chars = run_scrape_raw(
        request, state_store=state_store, scraper=scraper, keys=keys,
        config=config, url_resolver=url_resolver,
    )
    response = {
        "url": request.url,
        "result": limit_scrape_row(result, scrape_chars),
        "site_scraper_updates": updates,
    }
    if request.output in {"markdown", "both"}:
        response["markdown"] = format_scrapes([result], max_chars=scrape_chars)
        response["result"].pop("markdown", None)
    return response


def run_scrape_raw(
    request: ScrapeRequest,
    *,
    state_store=None,
    scraper=None,
    keys: dict | None = None,
    config: dict | None = None,
    url_resolver=None,
    deadline: float | None = None,
    runtime_timeout: float | None = None,
) -> tuple[dict, list[dict], int]:
    """Execute shared state-aware scraping before applying a public projection."""
    resolved_config = runtime.load_config_safe(None) if config is None else dict(config)
    runtime_keys = runtime.load_runtime_keys(resolved_config) if keys is None else dict(keys)
    # Public timeout/config values stay integer seconds; the fetch stage passes
    # its already-resolved floating remainder through this private path.
    if runtime_timeout is None:
        timeout = _resolve_nonnegative(request.timeout, resolved_config, "scrape_timeout", 60)
    else:
        timeout = max(0.0, float(runtime_timeout))
    if deadline is None:
        deadline = time.monotonic() + timeout
    else:
        timeout = min(timeout, max(0.0, deadline - time.monotonic()))
    scrape_chars = max(1, _resolve_int(request.scrape_chars, resolved_config, "scrape_chars", 1200))
    store = (state_store or runtime.new_state_store()) if request.use_state else None
    key_manager = runtime.key_manager_for(store)
    site_memory = SiteScraperMemory(store) if store else None
    scraper_fn = scraper or scrape_url_smart
    ctx = ScrapeContext(
        keys_by_backend={
            "jina": key_manager.candidates("jina", jina_config_keys(runtime_keys.get("jina"))),
            "exa": key_manager.candidates("exa", runtime_keys.get("exa")),
            "firecrawl": key_manager.candidates("firecrawl", runtime_keys.get("firecrawl")),
            "tavily": key_manager.candidates("tavily", runtime_keys.get("tavily")),
        },
        deadline=deadline,
        site_memory=site_memory,
        key_manager=key_manager,
        url_resolver=url_resolver,
        scrape_chars=scrape_chars,
        timeout=timeout,
        backends=tuple(request.backends) if request.backends else None,
        **({"twitter_cookies": runtime_keys.get("twitter") or runtime_keys.get("twitter_cookies", "")}
           if is_twitter_url(request.url) else {}),
    )
    result = scraper_fn(request.url, ctx=ctx)
    result = normalize_scrape_result(result, url=request.url)
    return result, site_memory.consume_updates() if site_memory else [], scrape_chars


def limit_scrape_row(row: dict, max_chars: int) -> dict:
    limited = dict(row)
    markdown = limited.get("markdown")
    if isinstance(markdown, str) and len(markdown) > max_chars:
        limited["markdown"] = markdown[:max_chars]
        limited["truncated"] = True
    return limited

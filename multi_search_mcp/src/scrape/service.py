"""Public scrape service: one URL through the shared state-aware scraper."""
from __future__ import annotations

import time

from ..state import runtime
from ..state.key_state import BasicKeyManager, SQLiteKeyManager
from ..state.keys import jina_config_keys
from ..state.site_memory import SiteScraperMemory
from ..state.state_store import StateStore
from ..support.config import ConfigError, config_list, resolve_int, resolve_nonnegative
from ..support.format import format_scrapes
from ..support.models import normalize_scrape_result
from ..support.requests import ScrapeRequest
from .scrape import KNOWN_BACKENDS, scrape_url_smart
from .scrapers.twitter import is_twitter_url


def configured_scrape_backends(config: dict | None) -> tuple[str, ...]:
    """Resolve the shared ordered fallback chain used by scrape and fetch.

    Absent/null keeps jina → exa → tavily → firecrawl. An explicit empty list
    is an error; duplicates keep their first position.
    """
    config = config or {}
    if config.get("scrape_backends") is None:
        return KNOWN_BACKENDS
    chain = tuple(dict.fromkeys(config_list(config, "scrape_backends")))
    if not chain:
        raise ConfigError("scrape_backends requires at least one backend")
    if any(name not in KNOWN_BACKENDS for name in chain):
        raise ConfigError(f"unknown scrape backend; valid backends: {', '.join(KNOWN_BACKENDS)}")
    return chain


def run_scrape(
    request: ScrapeRequest | dict,
    *,
    state_store: StateStore | None = None,
    scraper=None,
    keys: dict | None = None,
    config: dict | None = None,
) -> dict:
    if isinstance(request, dict):
        request = ScrapeRequest(**request)
    if request.output not in {"json", "markdown", "both"}:
        raise ValueError(
            f"invalid output mode: {request.output!r}; valid: json, markdown, both"
        )
    result, updates, scrape_chars = run_scrape_raw(
        request, state_store=state_store, scraper=scraper, keys=keys,
        config=config,
    )
    response = {
        "url": request.url,
        "result": _limit_scrape_row(result, scrape_chars),
        "site_scraper_updates": updates,
    }
    if request.output in {"markdown", "both"}:
        response["markdown"] = format_scrapes([result], max_chars=scrape_chars)
        response["result"].pop("markdown", None)
    return response


def run_scrape_raw(
    request: ScrapeRequest,
    *,
    state_store: StateStore | None = None,
    scraper=None,
    keys: dict | None = None,
    config: dict | None = None,
    deadline: float | None = None,
    runtime_timeout: float | None = None,
) -> tuple[dict, list[dict], int]:
    """Execute shared state-aware scraping before applying a public projection."""
    resolved_config = runtime.load_config_safe(None) if config is None else dict(config)
    runtime_keys = runtime.load_runtime_keys(resolved_config) if keys is None else dict(keys)
    # Public timeout/config values stay integer seconds; the fetch stage passes
    # its already-resolved floating remainder through this private path.
    if runtime_timeout is None:
        timeout = resolve_nonnegative(request.timeout, resolved_config, "scrape_timeout", 60)
    else:
        timeout = max(0.0, float(runtime_timeout))
    if deadline is None:
        deadline = time.monotonic() + timeout
    else:
        timeout = min(timeout, max(0.0, deadline - time.monotonic()))
    scrape_chars = max(1, resolve_int(request.scrape_chars, resolved_config, "scrape_chars", 1200))
    store = (state_store or StateStore()) if request.use_state else None
    key_manager = SQLiteKeyManager(store) if store else BasicKeyManager()
    site_memory = SiteScraperMemory(store) if store else None
    scraper_fn = scraper or scrape_url_smart
    # An explicit request order is authoritative and fails eagerly on a missing
    # key; an unconfigured chain keeps the configured fallback order instead.
    explicit_backends = tuple(request.backends) if request.backends else None
    backends = explicit_backends or configured_scrape_backends(resolved_config)
    result = scraper_fn(
        request.url,
        timeout=timeout,
        deadline=deadline,
        backends=backends,
        strict_backends=explicit_backends is not None,
        jina_keys=[
            candidate.key
            for candidate in key_manager.candidates(
                "jina", jina_config_keys(runtime_keys.get("jina")),
            )
        ],
        exa_keys=[
            candidate.key
            for candidate in key_manager.candidates("exa", runtime_keys.get("exa"))
        ],
        firecrawl_keys=[
            candidate.key
            for candidate in key_manager.candidates("firecrawl", runtime_keys.get("firecrawl"))
        ],
        tavily_keys=[
            candidate.key
            for candidate in key_manager.candidates("tavily", runtime_keys.get("tavily"))
        ],
        site_memory=site_memory,
        key_manager=key_manager,
        scrape_chars=scrape_chars,
        **({"twitter_cookies": (
            runtime_keys.get("twitter_cookies_path")
            or runtime_keys.get("twitter")
            or runtime_keys.get("twitter_cookies", "")
        )} if is_twitter_url(request.url) else {}),
    )
    result = normalize_scrape_result(result, url=request.url)
    return result, site_memory.consume_updates() if site_memory else [], scrape_chars


def _limit_scrape_row(row: dict, max_chars: int) -> dict:
    limited = dict(row)
    markdown = limited.get("markdown")
    if isinstance(markdown, str) and len(markdown) > max_chars:
        limited["markdown"] = markdown[:max_chars]
        limited["truncated"] = True
    return limited

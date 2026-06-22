"""Reusable service layer shared by MCP tools and future CLI paths."""
from __future__ import annotations

import concurrent.futures
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .cache import JsonCache, make_scrape_cache_key
from .config import ConfigError, config_bool, config_list, load_config
from .dedup import deduplicate
from .format import format_results, format_scrapes
from .key_state import BasicKeyManager, SQLiteKeyManager
from .keys import count_jina_keys, load_keys
from .models import as_dicts
from .scrape import scrape_url_smart
from .scrape_planner import add_to_content_pool, plan_scrapes
from .search_runner import ROUTE_PROFILES, SearchRunner, SearchRunnerConfig, resolve_route
from .secrets import scrub_secrets
from .site_memory import SiteScraperMemory
from .state_store import StateStore


DEFAULT_COUNTS = {
    "brave": 10,
    "tavily": 10,
    "exa": 10,
    "github": 10,
    "hackernews": 10,
    "serpapi": 10,
    "youtube": 10,
    "bilibili": 10,
    "stackoverflow": 10,
    "firecrawl": 10,
    "zhihu": 10,
    "linuxdo": 10,
    "linuxdo_api": 10,
    "twitter": 10,
    "glm_web": 10,
    "deepseek_web": 10,
}

COUNT_CAPS = {
    "brave": 20,
    "tavily": 20,
    "exa": 100,
    "github": 100,
    "hackernews": 100,
    "serpapi": 100,
    "youtube": 50,
    "bilibili": 50,
    "stackoverflow": 100,
    "firecrawl": 100,
    "zhihu": 10,
    "linuxdo": 20,
    "linuxdo_api": 10,
    "twitter": 20,
    "glm_web": 30,
    "deepseek_web": 30,
}


@dataclass
class MultiSearchRequest:
    query: str
    route: str = "default"
    count: int | None = None
    sources: list[str] | None = None
    scrape_top: int = 30
    scrape_chars: int = 6000
    scrape_per_source: int = 6
    scrape_timeout: int = 60
    scrape_concurrency: int = 5
    timeout: int = 60
    output: str = "both"
    config_path: str | None = None
    expand: list[str] = field(default_factory=list)
    brief: bool = False
    verbose: bool = False
    title_url_only: bool = False
    use_state: bool = True


@dataclass
class ScrapeRequest:
    url: str
    backends: list[str] | None = None
    scrape_chars: int = 6000
    timeout: int = 60
    output: str = "both"
    use_state: bool = True


def run_multi_search(request: MultiSearchRequest | dict) -> dict:
    if isinstance(request, dict):
        request = MultiSearchRequest(**request)
    if not request.query:
        raise ValueError("query is required")
    config = _load_config_safe(request.config_path)
    route = request.route or str(config.get("type", "default"))
    if request.sources:
        source_names = set(request.sources)
    elif route in ROUTE_PROFILES:
        source_names = None
    else:
        raise ValueError(f"unknown route: {route}")

    keys = load_keys()
    counts = _build_counts(config, request.count)
    timeout = _nonnegative(request.timeout if request.timeout is not None else int(config.get("timeout", 60) or 60), 60)
    scrape_top = _nonnegative(request.scrape_top, 30)
    scrape_chars = max(1, int(request.scrape_chars or 6000))
    scrape_per_source = max(1, int(request.scrape_per_source or 6))
    scrape_timeout = _nonnegative(request.scrape_timeout, 60)
    scrape_concurrency = max(1, int(request.scrape_concurrency or 5))
    output_mode = request.output if request.output in {"json", "markdown", "both"} else "both"
    if route == "video":
        request.title_url_only = True
        scrape_top = 0

    from .main import build_provider_registry

    store = StateStore() if request.use_state else None
    key_manager = SQLiteKeyManager(store) if store else BasicKeyManager()
    site_memory = SiteScraperMemory(store) if store else None
    runner_config = SearchRunnerConfig(route, counts, timeout, str(config.get("serpapi_engine", "google_light")), keys)
    route_resolver = (lambda _route, lite=False: source_names or resolve_route(_route, lite=lite))
    runner = SearchRunner(runner_config, build_provider_registry(), route_resolver=route_resolver, key_manager=key_manager)

    queries_to_run = [request.query] + list(request.expand or config_list(config, "expand") or config_list(config, "expand_queries"))
    all_results: list[dict] = []
    if len(queries_to_run) == 1:
        all_results = runner.run(request.query)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries_to_run)) as pool:
            futures = {pool.submit(runner.run, q, idx > 0): q for idx, q in enumerate(queries_to_run)}
            for fut in concurrent.futures.as_completed(futures):
                q = futures[fut]
                try:
                    all_results.extend(fut.result())
                except Exception as exc:
                    all_results.append({"source": "multi-search", "error": f"query '{q}' failed: {scrub_secrets(exc, keys)}"})

    cache = JsonCache(
        str(config.get("cache_dir", ".cache/multi-search")),
        ttl_seconds=int(config.get("cache_ttl_seconds", 86400) or 86400),
        enabled=bool(config.get("cache_enabled", False)) and not bool(config.get("no_cache", False)),
    )
    scrape_result = _run_scrape_stage(
        all_results,
        keys=keys,
        cache=cache,
        scrape_top=scrape_top,
        scrape_per_source=scrape_per_source,
        scrape_timeout=scrape_timeout,
        scrape_concurrency=scrape_concurrency,
        site_memory=site_memory,
    )
    final_results, _ = deduplicate(
        scrape_result["with_content"] + scrape_result["final_without_content"] + scrape_result["passthrough"]
    )
    valid_count = _valid_result_count(final_results)
    markdown = ""
    if output_mode in {"markdown", "both"}:
        markdown = format_results(
            final_results,
            request.query,
            raw_counts=scrape_result["raw_counts"],
            brief=request.brief,
            verbose=request.verbose,
            title_url_only=request.title_url_only,
        )
        if scrape_top > 0:
            markdown += format_scrapes(scrape_result["scrapes"], max_chars=scrape_chars)

    errors = [row for row in as_dicts(final_results) + scrape_result["scrape_errors"] if row.get("error")]
    response = {
        "query": request.query,
        "route": route,
        "results": as_dicts(final_results),
        "scrapes": scrape_result["scrapes"],
        "provider_status": _provider_status(final_results),
        "key_status_summary": _summarize_key_status(key_manager.status_rows() if hasattr(key_manager, "status_rows") else []),
        "site_scraper_updates": site_memory.consume_updates() if site_memory else [],
        "errors": errors,
        "diagnostics": {
            "valid_result_count": valid_count,
            "raw_result_count": len(all_results),
            "scrape_candidate_count": len(scrape_result["items_to_scrape"]),
            "jina_keys_active_total": count_jina_keys(keys.get("jina")),
            "state_path": str(store.path) if store else None,
        },
    }
    if output_mode in {"markdown", "both"}:
        response["markdown"] = markdown
    return response


def run_scrape(request: ScrapeRequest | dict) -> dict:
    if isinstance(request, dict):
        request = ScrapeRequest(**request)
    keys = load_keys()
    store = StateStore() if request.use_state else None
    site_memory = SiteScraperMemory(store) if store else None
    result = scrape_url_smart(
        request.url,
        timeout=request.timeout,
        backends=tuple(request.backends) if request.backends else None,
        jina_keys=[],
        exa_keys=_key_list(keys.get("exa")),
        firecrawl_keys=_key_list(keys.get("firecrawl")),
        tavily_keys=_key_list(keys.get("tavily")),
        site_memory=site_memory,
    )
    response = {
        "url": request.url,
        "result": result,
        "site_scraper_updates": site_memory.consume_updates() if site_memory else [],
    }
    if request.output in {"markdown", "both"}:
        response["markdown"] = format_scrapes([result], max_chars=request.scrape_chars)
    return response


def list_sources(include_key_status: bool = False, include_scraper_stats: bool = False) -> dict:
    store = StateStore()
    response = {"routes": sorted(ROUTE_PROFILES), "sources": sorted({src for vals in ROUTE_PROFILES.values() for src in vals})}
    if include_key_status:
        response["key_status"] = SQLiteKeyManager(store).status_rows()
    if include_scraper_stats:
        response["site_scraper_stats"] = SiteScraperMemory(store).stats()
    return response


def doctor_data(include_keys: bool = True, include_network: bool = False) -> dict:
    keys = load_keys()
    store = StateStore()
    data = {
        "server": "multi-search-mcp",
        "state_path": str(store.path),
        "routes": sorted(ROUTE_PROFILES),
        "network_checked": bool(include_network),
    }
    if include_keys:
        data["configured_keys"] = {name: bool(value) for name, value in keys.items()}
        data["key_status"] = SQLiteKeyManager(store).status_rows()
        data["jina_keys_active_total"] = count_jina_keys(keys.get("jina"))
    return data


def _run_scrape_stage(all_results: list[dict], *, keys: dict, cache: JsonCache, scrape_top: int,
                      scrape_per_source: int, scrape_timeout: int, scrape_concurrency: int,
                      site_memory: SiteScraperMemory | None) -> dict:
    scrape_plan = plan_scrapes(all_results, keys=keys, scrape_top=scrape_top, scrape_per_source=scrape_per_source)
    scrape_errors: list[dict] = []
    content_pool = scrape_plan.content_pool
    if scrape_top > 0:
        scrape_top = min(scrape_top, 30)
        items_to_scrape = scrape_plan.items_to_scrape
        scrape_backends = scrape_plan.backend_order

        def timeout_row(item: dict) -> dict:
            return {"url": item.get("url", ""), "error": f"scrape timeout after {scrape_timeout}s"}

        if items_to_scrape and scrape_timeout <= 0:
            scrape_errors.extend(timeout_row(item) for item in items_to_scrape)
        elif items_to_scrape:
            task_queue: queue.Queue = queue.Queue()
            result_queue: queue.Queue = queue.Queue()
            deadline = time.monotonic() + scrape_timeout
            for plan_item in scrape_plan.plan_items:
                task_queue.put(plan_item)

            def worker() -> None:
                while True:
                    if time.monotonic() >= deadline:
                        return
                    try:
                        plan_item = task_queue.get_nowait()
                    except queue.Empty:
                        return
                    item = plan_item.item
                    try:
                        backends = list(scrape_backends)
                        if site_memory is not None:
                            backends = site_memory.reorder_backends(item["url"], backends)
                        cache_key = make_scrape_cache_key(item["url"], backends, {"primary": plan_item.primary_backend})
                        cached = cache.get("scrape", cache_key)
                        if cached is not None:
                            scrape_result = dict(cached)
                            scrape_result.setdefault("cache", "hit")
                        else:
                            pools = plan_item.key_pools
                            scrape_result = scrape_url_smart(
                                item["url"], timeout=30, primary=plan_item.primary_backend,
                                backends=tuple(backends), jina_keys=pools.jina, exa_keys=pools.exa,
                                firecrawl_keys=pools.firecrawl, tavily_keys=pools.tavily,
                                deadline=deadline, site_memory=site_memory,
                            )
                            if scrape_result and "error" not in scrape_result:
                                cache.set("scrape", cache_key, scrape_result)
                        result_queue.put((plan_item.index, item, scrape_result, None))
                    except Exception as exc:
                        result_queue.put((plan_item.index, item, None, exc))
                    finally:
                        task_queue.task_done()

            for _ in range(min(scrape_concurrency, len(items_to_scrape))):
                threading.Thread(target=worker, daemon=True).start()
            completed: set[int] = set()
            while len(completed) < len(items_to_scrape):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    i, item, scrape_result, error = result_queue.get(timeout=remaining)
                except queue.Empty:
                    break
                if i in completed:
                    continue
                completed.add(i)
                if error is not None:
                    scrape_errors.append({"url": item.get("url", ""), "error": scrub_secrets(error, keys)})
                elif scrape_result and scrape_result.get("error"):
                    scrape_errors.append(scrape_result)
                elif scrape_result:
                    add_to_content_pool(content_pool, scrape_result)
                else:
                    scrape_errors.append({"url": item.get("url", ""), "error": "empty scrape result"})
            for i, item in enumerate(items_to_scrape):
                if i not in completed:
                    scrape_errors.append(timeout_row(item))

    return {
        "with_content": scrape_plan.with_content,
        "final_without_content": scrape_plan.final_without_content,
        "passthrough": scrape_plan.passthrough,
        "raw_counts": scrape_plan.raw_counts,
        "items_to_scrape": scrape_plan.items_to_scrape,
        "scrape_errors": scrape_errors,
        "scrapes": list(content_pool.values()) + scrape_errors,
    }


def _build_counts(config: dict, global_count: int | None = None) -> dict[str, int]:
    counts_cfg = config.get("counts") if isinstance(config.get("counts"), dict) else {}
    configured_global = global_count if global_count is not None else config.get("count")
    counts = {}
    for source, default in DEFAULT_COUNTS.items():
        value = counts_cfg.get(source, config.get(f"{source}_count"))
        if value is None and configured_global is not None:
            value = configured_global
        if value is None:
            value = default
        counts[source] = max(1, min(int(value), COUNT_CAPS[source]))
    return counts


def _provider_status(results: list[dict]) -> list[dict]:
    rows = as_dicts(results)
    sources = sorted({row.get("source", "?") for row in rows})
    status = []
    for source in sources:
        source_rows = [row for row in rows if row.get("source") == source]
        errors = [row.get("error") for row in source_rows if row.get("error")]
        hits = len([row for row in source_rows if not row.get("error") and row.get("status") != "ok"])
        status.append({"source": source, "raw_hits": hits, "status": "error" if errors and not hits else "ok", "errors": errors})
    return status


def _summarize_key_status(rows: list[dict]) -> list[dict]:
    return [{
        "provider": row.get("provider"),
        "key_id": row.get("key_id"),
        "fingerprint": row.get("key_fingerprint"),
        "status": row.get("status"),
        "last_error_type": row.get("last_error_type"),
        "cooldown_until": row.get("cooldown_until"),
        "exhausted_until": row.get("exhausted_until"),
    } for row in rows]


def _valid_result_count(results: list[dict]) -> int:
    return len([
        row for row in as_dicts(results)
        if "error" not in row and row.get("status") != "ok"
        and row.get("source") not in {"tavily_answer", "serpapi_answer", "exa_answer", "glm_web_answer", "deepseek_web_answer"}
    ])


def _key_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str) and item]
    if isinstance(value, str):
        return [value]
    return []


def _load_config_safe(path: str | None) -> dict:
    try:
        return load_config(path)
    except ConfigError as exc:
        raise ValueError(str(exc)) from exc


def _nonnegative(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)

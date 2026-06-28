"""Scrape stage: turn search results into scraped content via the planner.

Extracted from ``service.py`` so the scrape orchestration (plan -> concurrent
fetch -> content writeback) is a self-contained unit instead of living inside
the request service god-object.
"""
from __future__ import annotations

import queue
import threading
import time

from ..support.dedup import _norm_url, apply_scraped_content
from ..support.models import as_dicts
from ..support.secrets import scrub_secrets
from ..state.site_memory import SiteScraperMemory
from .scrape import scrape_url_smart
from .scrape_planner import add_to_content_pool, plan_scrapes


def _backfill_scrape_title(scrape_result: dict, search_titles: dict[str, str]) -> None:
    """Replace a URL-as-title with the search-stage title for the same URL.

    Backends like Tavily extract do not return a page title, so they emit the
    URL as ``title``. When the search stage already has a real title for that
    URL, prefer it.
    """
    url = scrape_result.get("url") or ""
    title = scrape_result.get("title") or ""
    if title and title != url:
        return
    better = search_titles.get(_norm_url(url))
    if better:
        scrape_result["title"] = better


def run_scrape_stage(all_results: list[dict], *, keys: dict, scrape_top: int,
                     scrape_per_source: int, scrape_timeout: int, scrape_concurrency: int,
                     site_memory: SiteScraperMemory | None, key_manager=None,
                     scrape_url_timeout: int | None = None,
                     scrape_chars: int | None = None,
                     skip_summarized_sources: bool = False) -> dict:
    if scrape_url_timeout is None:
        scrape_url_timeout = scrape_timeout
    scrape_plan = plan_scrapes(
        all_results,
        keys=keys,
        scrape_top=scrape_top,
        scrape_per_source=scrape_per_source,
        key_manager=key_manager,
        skip_summarized_sources=skip_summarized_sources,
    )
    scrape_errors: list[dict] = []
    content_pool = scrape_plan.content_pool
    # Title fallback: several extract backends (e.g. Tavily) do not return a
    # page title, so they fall back to the URL. Reuse the search-stage title for
    # the same URL when the scrape result has none.
    search_titles = {
        _norm_url(row.get("url", "")): row.get("title")
        for row in as_dicts(all_results)
        if row.get("url") and row.get("title")
    }
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
                        pools = plan_item.key_pools
                        per_url_timeout = scrape_url_timeout
                        remaining = deadline - time.monotonic()
                        if remaining < per_url_timeout:
                            per_url_timeout = max(0, int(remaining))
                        scrape_result = scrape_url_smart(
                            item["url"], timeout=per_url_timeout, primary=plan_item.primary_backend,
                            backends=tuple(backends), jina_keys=pools.jina, exa_keys=pools.exa,
                            firecrawl_keys=pools.firecrawl, tavily_keys=pools.tavily,
                            deadline=deadline, site_memory=site_memory, key_manager=key_manager,
                            scrape_chars=scrape_chars,
                        )
                        if scrape_result and "error" not in scrape_result:
                            _backfill_scrape_title(scrape_result, search_titles)
                        result_queue.put((plan_item.index, item, scrape_result, None))
                    except Exception as exc:
                        result_queue.put((plan_item.index, item, None, exc))
                    finally:
                        task_queue.task_done()

            for _ in range(min(scrape_concurrency, len(scrape_plan.plan_items))):
                threading.Thread(target=worker, daemon=True).start()
            completed: set[int] = set()
            while len(completed) < len(scrape_plan.plan_items):
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
            for plan_item in scrape_plan.plan_items:
                if plan_item.index not in completed:
                    scrape_errors.append(timeout_row(plan_item.item))

    # Write freshly scraped content back onto the result records so JSON results,
    # markdown ranking, and the standalone scrapes view all see enriched rows
    # instead of leaving final_without_content as empty skeletons.
    apply_scraped_content(scrape_plan.final_without_content, content_pool)
    apply_scraped_content(scrape_plan.with_content, content_pool)

    return {
        "with_content": scrape_plan.with_content,
        "final_without_content": scrape_plan.final_without_content,
        "passthrough": scrape_plan.passthrough,
        "raw_counts": scrape_plan.raw_counts,
        "items_to_scrape": scrape_plan.items_to_scrape,
        "scrape_errors": scrape_errors,
        "scrapes": list(content_pool.values()) + scrape_errors,
    }

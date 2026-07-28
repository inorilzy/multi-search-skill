"""Scrape stage: turn search results into scraped content via the planner.

Extracted from ``service.py`` so the scrape orchestration (plan -> concurrent
fetch -> content writeback) is a self-contained unit instead of living inside
the request service god-object.
"""
from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from typing import Any

from ..support.dedup import _norm_url, apply_scraped_content
from ..support.concurrency import BoundedDaemonExecutor
from ..support.models import as_dicts
from ..support.secrets import scrub_secrets
from ..state.site_memory import SiteScraperMemory
from .scrape import scrape_url_smart
from .scrape_planner import add_to_content_pool, plan_scrapes


_SCRAPE_POOL = BoundedDaemonExecutor(
    max_workers=30,
    thread_name_prefix="multi-search-scrape",
)


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
            deadline = time.monotonic() + scrape_timeout
            request_limit = max(0, min(scrape_concurrency, len(scrape_plan.plan_items)))

            def scrape_plan_item(plan_item):
                item = plan_item.item
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
                return plan_item.index, item, scrape_result

            completed: set[int] = set()
            future_items: dict[Future, Any] = {}
            plan_iter = iter(scrape_plan.plan_items)

            def fill_active_workers() -> None:
                while len(future_items) < request_limit:
                    try:
                        plan_item = next(plan_iter)
                    except StopIteration:
                        return
                    future = _SCRAPE_POOL.submit_before(deadline, scrape_plan_item, plan_item)
                    if future is None:
                        return
                    future_items[future] = plan_item

            fill_active_workers()
            while future_items:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                done, _ = wait(
                    tuple(future_items),
                    timeout=remaining,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    break
                for future in done:
                    plan_item = future_items.pop(future)
                    item = plan_item.item
                    if plan_item.index in completed:
                        continue
                    completed.add(plan_item.index)
                    try:
                        _i, _item, scrape_result = future.result()
                    except Exception as exc:
                        scrape_errors.append({"url": item.get("url", ""), "error": scrub_secrets(exc, keys)})
                    else:
                        if scrape_result and scrape_result.get("error"):
                            scrape_errors.append(scrape_result)
                        elif scrape_result:
                            add_to_content_pool(content_pool, scrape_result)
                        else:
                            scrape_errors.append({"url": item.get("url", ""), "error": "empty scrape result"})
                fill_active_workers()
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

"""ScrapePlanner: decide which metadata-only URLs should be fetched."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dedup import _norm_url, deduplicate, result_to_scrape, split_by_content
from .keys import get_active_jina_keys, key_pool
from .models import as_dicts


PREFER_SCRAPE_SOURCES = {
    "brave", "serpapi", "github-repos", "firecrawl", "v2ex", "zhihu", "reddit", "hackernews", "stackoverflow",
}

VIDEO_SOURCES = {"youtube", "bilibili"}


@dataclass
class ScrapeKeyPools:
    jina: list[str] = field(default_factory=list)
    exa: list[str] = field(default_factory=list)
    firecrawl: list[str] = field(default_factory=list)
    tavily: list[str] = field(default_factory=list)


@dataclass
class ScrapePlanItem:
    index: int
    item: dict
    primary_backend: str
    key_pools: ScrapeKeyPools


@dataclass
class ScrapePlan:
    with_content: list[dict]
    final_without_content: list[dict]
    passthrough: list[dict]
    raw_counts: dict
    content_pool: dict[str, dict]
    scrape_candidates: list[dict]
    items_to_scrape: list[dict]
    source_quota: dict[str, int]
    backend_order: list[str]
    plan_items: list[ScrapePlanItem]


def has_preferred_scrape_source(item: dict) -> bool:
    sources = {item.get("source")}
    sources.update(item.get("also_from") or [])
    return bool(sources & PREFER_SCRAPE_SOURCES)


def is_video_result(item: dict) -> bool:
    sources = {item.get("source")}
    sources.update(item.get("also_from") or [])
    if sources & VIDEO_SOURCES:
        return True
    url = str(item.get("url") or "").lower()
    return any(host in url for host in ("youtube.com/", "youtu.be/", "bilibili.com/"))


def add_to_content_pool(content_pool: dict[str, dict], row: dict) -> None:
    if row.get("error") or not row.get("url"):
        return
    norm_url = _norm_url(row.get("url", ""))
    markdown = row.get("markdown") or ""
    if not markdown:
        return
    existing = content_pool.get(norm_url)
    if existing is None:
        content_pool[norm_url] = dict(row)
        return
    old_markdown = existing.get("markdown") or ""
    if len(markdown) > len(old_markdown):
        old_via = existing.get("via") or ""
        content_pool[norm_url] = dict(row)
        if old_via and old_via not in (content_pool[norm_url].get("via") or ""):
            content_pool[norm_url]["via"] = f"{content_pool[norm_url].get('via', '?')}, {old_via}"
    elif row.get("via") and row.get("via") not in (existing.get("via") or ""):
        existing["via"] = f"{existing.get('via', '?')}, {row['via']}"


def rotated_key_pool(pool: list[str], offset: int) -> list[str]:
    if not pool:
        return []
    shift = offset % len(pool)
    return pool[shift:] + pool[:shift]


def _primary_for(backends: list[str], index: int) -> str:
    return backends[index % len(backends)]


def build_scrape_backends(keys: dict) -> tuple[list[str], ScrapeKeyPools]:
    pools = ScrapeKeyPools(
        jina=get_active_jina_keys(keys.get("jina", "")),
        exa=key_pool(keys.get("exa", "")),
        firecrawl=key_pool(keys.get("firecrawl", "")),
        tavily=key_pool(keys.get("tavily", "")),
    )
    backends = ["jina"]
    if pools.exa:
        backends.append("exa")
    if pools.tavily:
        backends.append("tavily")
    if pools.firecrawl:
        backends.append("firecrawl")
    return backends, pools


def plan_scrapes(
    all_results: list[Any],
    *,
    keys: dict,
    scrape_top: int,
    scrape_per_source: int,
) -> ScrapePlan:
    rows = as_dicts(all_results)
    with_content, without_content, passthrough, raw_counts = split_by_content(rows)
    content_urls = {
        _norm_url(item.get("url", ""))
        for item in with_content
        if item.get("url") and item.get("source") != "twitter"
    }
    deduped_without_content, _ = deduplicate(without_content)
    final_without_content = deduped_without_content
    scrape_candidates = [
        item for item in deduped_without_content
        if item.get("url") and _norm_url(item.get("url", "")) not in content_urls
        and not is_video_result(item)
    ]
    content_pool: dict[str, dict] = {}
    for item in with_content:
        add_to_content_pool(content_pool, result_to_scrape(item))

    backend_order, base_pools = build_scrape_backends(keys)
    items_to_scrape: list[dict] = []
    source_quota: dict[str, int] = {}
    plan_items: list[ScrapePlanItem] = []
    if scrape_top > 0:
        candidates_for_scrape = sorted(
            scrape_candidates,
            key=lambda x: (
                0 if has_preferred_scrape_source(x) else 1,
                -(1 + len(x.get("also_from") or [])),
            ),
        )
        for item in candidates_for_scrape:
            src = item.get("source", "unknown")
            if source_quota.get(src, 0) >= scrape_per_source:
                continue
            source_quota[src] = source_quota.get(src, 0) + 1
            items_to_scrape.append(item)
            if len(items_to_scrape) >= min(scrape_top, 30):
                break

        for i, item in enumerate(items_to_scrape):
            plan_items.append(ScrapePlanItem(
                index=i,
                item=item,
                primary_backend=_primary_for(backend_order, i),
                key_pools=ScrapeKeyPools(
                    jina=rotated_key_pool(base_pools.jina, i),
                    exa=rotated_key_pool(base_pools.exa, i),
                    firecrawl=rotated_key_pool(base_pools.firecrawl, i),
                    tavily=rotated_key_pool(base_pools.tavily, i),
                ),
            ))

    return ScrapePlan(
        with_content=with_content,
        final_without_content=final_without_content,
        passthrough=passthrough,
        raw_counts=raw_counts,
        content_pool=content_pool,
        scrape_candidates=scrape_candidates,
        items_to_scrape=items_to_scrape,
        source_quota=source_quota,
        backend_order=backend_order,
        plan_items=plan_items,
    )

"""Scraper registry and adapter contracts.

The runtime still uses ``scrape_url_smart`` for fallback orchestration. This
registry makes scraper backends explicit so new backends can be added by
registering an adapter instead of changing CLI flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ...support.models import as_dict
from .exa import scrape_url_exa
from .firecrawl import scrape_url_firecrawl
from .jina import scrape_url_jina
from .reddit import scrape_url_reddit
from .tavily import scrape_url_tavily


@dataclass
class ScrapeContext:
    backend: str
    timeout: float = 30
    deadline: float | None = None
    keys: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScraperSpec:
    name: str
    public_name: str
    call: Callable[[str, ScrapeContext, str | None], dict | Any]
    key_name: str | None = None
    supports_anonymous: bool = False
    timeout_default: float = 30


def call_scraper(spec: ScraperSpec, url: str, context: ScrapeContext, key: str | None = None) -> dict:
    """Call a scraper adapter and normalize dataclass/dict results to dict."""
    return as_dict(spec.call(url, context, key))


def build_scraper_registry() -> dict[str, ScraperSpec]:
    return {
        "jina": ScraperSpec(
            name="jina",
            public_name="jina",
            key_name="jina",
            supports_anonymous=True,
            call=lambda url, ctx, key: scrape_url_jina(
                url,
                key or "",
                timeout=ctx.timeout,
                **ctx.options.get("jina", {}),
            ),
        ),
        "exa": ScraperSpec(
            name="exa",
            public_name="exa",
            key_name="exa",
            call=lambda url, ctx, key: scrape_url_exa(url, key or "", timeout=ctx.timeout),
        ),
        "tavily": ScraperSpec(
            name="tavily",
            public_name="tavily",
            key_name="tavily",
            call=lambda url, ctx, key: scrape_url_tavily(
                url,
                key or "",
                timeout=ctx.timeout,
                **ctx.options.get("tavily", {}),
            ),
        ),
        "firecrawl": ScraperSpec(
            name="firecrawl",
            public_name="firecrawl",
            key_name="firecrawl",
            call=lambda url, ctx, key: scrape_url_firecrawl(url, key or "", timeout=ctx.timeout),
        ),
        "reddit": ScraperSpec(
            name="reddit",
            public_name="old-reddit",
            call=lambda url, ctx, key: scrape_url_reddit(url, timeout=ctx.timeout),
        ),
    }


SCRAPER_REGISTRY = build_scraper_registry()

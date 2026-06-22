#!/usr/bin/env python3
"""Backward-compat shim for the multi-search CLI.

The real implementation lives in scripts/ (per Anthropic skill conventions).
Symbols are re-exported so existing imports keep working:

    import search
    search.search_brave(...)
    search.load_keys()
    search.main()
"""
import os
import sys

# Ensure `scripts` package is importable when this file is executed directly
# (e.g. `python search.py "query"` from the skill root).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from scripts.dedup import _norm_url, deduplicate
from scripts.format import format_results, format_scrapes
from scripts.http import urlopen_retry as _urlopen_retry
from scripts.keys import load_keys
from scripts.main import main
from scripts.models import ProviderError, ProviderStatus, ScrapeResult, SearchResult
from scripts.scrape import (
    _GH_REPO_RE,
    _rewrite_for_clean_scrape,
    scrape_url_exa,
    scrape_url_firecrawl,
    scrape_url_smart,
    scrape_url_tavily,
)
from scripts.cache import JsonCache, make_scrape_cache_key, make_search_cache_key
from scripts.capabilities import (
    PROVIDER_CAPABILITIES,
    AuthMode,
    OperationalProfile,
    OutputCapability,
    ProviderCapability,
    ProviderKind,
    ScrapeCapability,
    ScrapePolicy,
    SearchCapability,
    capability_table_rows,
    get_capability,
)
from scripts.scrape_planner import ScrapePlan, plan_scrapes
from scripts.service import MultiSearchRequest, ScrapeRequest, run_multi_search, run_scrape
from scripts.key_state import BasicKeyManager, SQLiteKeyManager
from scripts.site_memory import SiteScraperMemory
from scripts.state_store import StateStore
from scripts.scrapers.registry import SCRAPER_REGISTRY, ScrapeContext, ScraperSpec, call_scraper
from scripts.search_runner import ProviderSpec, SearchContext, SearchRunner, SearchRunnerConfig
from scripts.searchers.brave import search_brave
from scripts.searchers.bilibili import search_bilibili
from scripts.searchers.exa import search_exa
from scripts.searchers.firecrawl import search_firecrawl, search_reddit, search_v2ex
from scripts.searchers.github import search_github_repos
from scripts.searchers.hackernews import search_hackernews
from scripts.searchers.serpapi import search_serpapi
from scripts.searchers.stackoverflow import search_stackoverflow
from scripts.searchers.tavily import search_tavily
from scripts.searchers.twitter import search_twitter
from scripts.searchers.youtube import search_youtube
from scripts.searchers.zhihu import search_zhihu

scrape_url = scrape_url_smart

__all__ = [
    "_GH_REPO_RE",
    "_norm_url",
    "_rewrite_for_clean_scrape",
    "_urlopen_retry",
    "JsonCache",
    "AuthMode",
    "OperationalProfile",
    "OutputCapability",
    "PROVIDER_CAPABILITIES",
    "ProviderCapability",
    "ProviderError",
    "ProviderKind",
    "ProviderSpec",
    "ProviderStatus",
    "SCRAPER_REGISTRY",
    "ScrapeContext",
    "ScrapeCapability",
    "ScrapePlan",
    "ScrapePolicy",
    "ScrapeResult",
    "ScraperSpec",
    "SearchContext",
    "SearchCapability",
    "SearchResult",
    "SearchRunner",
    "SearchRunnerConfig",
    "BasicKeyManager",
    "SQLiteKeyManager",
    "SiteScraperMemory",
    "StateStore",
    "MultiSearchRequest",
    "ScrapeRequest",
    "call_scraper",
    "capability_table_rows",
    "deduplicate",
    "format_results",
    "format_scrapes",
    "get_capability",
    "load_keys",
    "main",
    "make_scrape_cache_key",
    "make_search_cache_key",
    "plan_scrapes",
    "run_multi_search",
    "run_scrape",
    "scrape_url",
    "scrape_url_exa",
    "scrape_url_firecrawl",
    "scrape_url_smart",
    "scrape_url_tavily",
    "search_brave",
    "search_bilibili",
    "search_exa",
    "search_firecrawl",
    "search_reddit",
    "search_v2ex",
    "search_zhihu",
    "search_github_repos",
    "search_hackernews",
    "search_serpapi",
    "search_stackoverflow",
    "search_tavily",
    "search_twitter",
    "search_youtube",
]


if __name__ == "__main__":
    main()

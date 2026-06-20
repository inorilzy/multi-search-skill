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
from scripts.scrape import (
    _GH_REPO_RE,
    _rewrite_for_clean_scrape,
    scrape_url_exa,
    scrape_url_firecrawl,
    scrape_url_smart,
    scrape_url_tavily,
)
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
    "deduplicate",
    "format_results",
    "format_scrapes",
    "load_keys",
    "main",
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

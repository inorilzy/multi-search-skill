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
    scrape_url_smart,
    scrape_url_tavily,
)
from scripts.sources.brave import search_brave
from scripts.sources.exa import search_exa
from scripts.sources.firecrawl import search_firecrawl
from scripts.sources.github import search_github_repos
from scripts.sources.serpapi import search_serpapi
from scripts.sources.tavily import search_tavily
from scripts.sources.twitter import search_twitter

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
    "scrape_url_smart",
    "scrape_url_tavily",
    "search_brave",
    "search_exa",
    "search_firecrawl",
    "search_github_repos",
    "search_serpapi",
    "search_tavily",
    "search_twitter",
]


if __name__ == "__main__":
    main()

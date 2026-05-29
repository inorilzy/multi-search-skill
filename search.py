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

from scripts.dedup import _norm_url, deduplicate  # noqa: F401,E402
from scripts.format import format_results, format_scrapes  # noqa: F401,E402
from scripts.http import urlopen_retry as _urlopen_retry  # noqa: F401,E402
from scripts.keys import load_keys  # noqa: F401,E402
from scripts.main import main  # noqa: F401,E402
from scripts.scrape import (  # noqa: F401,E402
    _GH_REPO_RE,
    _rewrite_for_clean_scrape,
    scrape_url_exa,
    scrape_url_firecrawl as scrape_url,
    scrape_url_jina,
    scrape_url_smart,
)
from scripts.sources.brave import search_brave  # noqa: F401,E402
from scripts.sources.exa import search_exa  # noqa: F401,E402
from scripts.sources.firecrawl import search_firecrawl  # noqa: F401,E402
from scripts.sources.github import search_github_repos  # noqa: F401,E402
from scripts.sources.hackernews import search_hackernews  # noqa: F401,E402
from scripts.sources.serpapi import search_serpapi  # noqa: F401,E402
from scripts.sources.stackoverflow import search_stackoverflow  # noqa: F401,E402
from scripts.sources.tavily import search_tavily  # noqa: F401,E402
from scripts.sources.twitter import search_twitter  # noqa: F401,E402


if __name__ == "__main__":
    main()

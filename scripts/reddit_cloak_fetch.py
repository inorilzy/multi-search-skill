r"""Debug CLI for the browser-backed Reddit content searcher.

Thin wrapper over ``multi_search_mcp.src.search.searchers.reddit_browser.search_reddit_browser``
so the script and the MCP provider share one implementation (no drift). Use it
to validate cookies/profile and measure latency outside the MCP.

Example:
    python scripts/reddit_cloak_fetch.py "playwright" \
        --cookie-export C:\path\to\reddit-cookie-export.json --count 10
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multi_search_mcp.src.search.searchers.reddit_browser import resolve_reddit_config, search_reddit_browser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Reddit search query")
    parser.add_argument("--cookie-export", help="Cookie LocalStorage Exporter JSON path")
    parser.add_argument("--profile", help="Persistent browser profile path")
    parser.add_argument("--count", type=int, default=10, help="Number of posts to fetch")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent post pages")
    parser.add_argument("--max-comments", type=int, default=8, help="Comments per post")
    parser.add_argument("--cards-only", action="store_true", help="Return search cards without bodies")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = {
        "cookie_export": args.cookie_export or "",
        "concurrency": args.concurrency,
        "max_comments": args.max_comments,
    }
    if args.profile:
        settings["profile"] = args.profile
    config = resolve_reddit_config(settings)

    started = time.perf_counter()
    rows = search_reddit_browser(
        args.query,
        args.count,
        config,
        want_content=not args.cards_only,
    )
    payload = {
        "query": args.query,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "count": len(rows),
        "results": rows,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()

"""CLI entry point: argparse + orchestration."""
import concurrent.futures
import sys

from .dedup import deduplicate
from .format import format_results, format_scrapes
from .keys import load_keys, pick_key
from .scrape import scrape_url_smart
from .sources.brave import search_brave
from .sources.exa import search_exa
from .sources.firecrawl import search_firecrawl
from .sources.github import search_github_repos
from .sources.hackernews import search_hackernews
from .sources.serpapi import search_serpapi
from .sources.stackoverflow import search_stackoverflow
from .sources.tavily import search_tavily
from .sources.twitter import search_twitter


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if not args:
        print("Usage: python search.py <query> [--type all|web|code|repos|...] [--count N]")
        print("       [--brave-count N] [--tavily-count N] [--exa-count N] [--github-count N]")
        print("       [--sg-count N] [--hn-count N] [--so-count N] [--baidu-count N]")
        print("       [--timeout N] [--scrape-top N] [--no-scrape] [--scrape-chars N]")
        sys.exit(1)

    query_parts: list = []
    search_type = "all"
    count = None
    brave_count = None
    tavily_count = None
    exa_count = None
    github_count = None
    hn_count = None
    so_count = None
    serpapi_count = None
    firecrawl_count = None
    twitter_count = None
    serpapi_engine = "google_light"
    global_timeout = 60
    scrape_top = 30
    scrape_chars = 2000
    scrape_per_source = 6
    expand_queries: list = []
    brief = False

    i = 0
    while i < len(args):
        if args[i] == "--type" and i + 1 < len(args):
            search_type = args[i + 1]
            i += 2
        elif args[i] == "--count" and i + 1 < len(args):
            try:
                count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--brave-count" and i + 1 < len(args):
            try: brave_count = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--tavily-count" and i + 1 < len(args):
            try: tavily_count = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--github-count" and i + 1 < len(args):
            try: github_count = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--exa-count" and i + 1 < len(args):
            try: exa_count = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--serpapi-count" and i + 1 < len(args):
            try: serpapi_count = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--serpapi-engine" and i + 1 < len(args):
            serpapi_engine = args[i + 1]
            i += 2
        elif args[i] == "--hn-count" and i + 1 < len(args):
            try: hn_count = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--so-count" and i + 1 < len(args):
            try: so_count = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--firecrawl-count" and i + 1 < len(args):
            try: firecrawl_count = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--twitter-count" and i + 1 < len(args):
            try: twitter_count = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--timeout" and i + 1 < len(args):
            try: global_timeout = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--brief":
            brief = True
            i += 1
        elif args[i] == "--scrape-top" and i + 1 < len(args):
            try: scrape_top = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--no-scrape":
            scrape_top = 0
            i += 1
        elif args[i] == "--scrape-chars" and i + 1 < len(args):
            try: scrape_chars = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--scrape-per-source" and i + 1 < len(args):
            try: scrape_per_source = int(args[i + 1])
            except ValueError: pass
            i += 2
        elif args[i] == "--expand":
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                expand_queries.append(args[i])
                i += 1
        else:
            query_parts.append(args[i])
            i += 1

    gc = count
    brave_count   = brave_count   if brave_count   is not None else (min(gc, 20)  if gc is not None else 10)
    tavily_count  = tavily_count  if tavily_count  is not None else (min(gc, 20)  if gc is not None else 10)
    exa_count     = exa_count     if exa_count     is not None else (min(gc, 100) if gc is not None else 10)
    github_count  = github_count  if github_count  is not None else (min(gc, 100) if gc is not None else 10)
    hn_count      = hn_count      if hn_count      is not None else (gc           if gc is not None else 10)
    so_count      = so_count      if so_count      is not None else (min(gc, 100) if gc is not None else 10)
    serpapi_count = serpapi_count if serpapi_count is not None else (min(gc, 20)  if gc is not None else 10)
    firecrawl_count = firecrawl_count if firecrawl_count is not None else (min(gc, 10) if gc is not None else 5)
    twitter_count = twitter_count if twitter_count is not None else (min(gc, 20) if gc is not None else 10)

    query = " ".join(query_parts)
    if not query:
        print("Error: query is required")
        sys.exit(1)

    keys = load_keys()

    def _run_search(q: str, lite: bool = False) -> list:
        _tasks: dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as _pool:
            if (lite or search_type in ("all", "web", "brave")) and "brave" in keys:
                _tasks["brave"] = _pool.submit(search_brave, q, keys["brave"], brave_count)
            if (lite or search_type in ("all", "web", "tavily")) and "tavily" in keys:
                _tasks["tavily"] = _pool.submit(search_tavily, q, pick_key(keys["tavily"]), tavily_count)
            if not lite and search_type in ("all", "web", "exa") and "exa" in keys:
                _tasks["exa"] = _pool.submit(search_exa, q, pick_key(keys["exa"]), exa_count)
            if not lite and search_type in ("all", "web", "serpapi", "google") and "serpapi" in keys:
                _tasks["serpapi"] = _pool.submit(search_serpapi, q, pick_key(keys["serpapi"]), serpapi_count, serpapi_engine)
            if not lite and search_type in ("all", "web", "firecrawl") and "firecrawl" in keys:
                _tasks["firecrawl"] = _pool.submit(search_firecrawl, q, pick_key(keys["firecrawl"]), firecrawl_count)
            if not lite and search_type in ("all", "repos", "github"):
                _tasks["github_repos"] = _pool.submit(search_github_repos, q, github_count, keys.get("github", ""))
            if not lite and search_type in ("all", "community", "hn", "hackernews"):
                _tasks["hackernews"] = _pool.submit(search_hackernews, q, hn_count)
            if not lite and search_type in ("all", "community", "so", "stackoverflow"):
                _tasks["stackoverflow"] = _pool.submit(search_stackoverflow, q, so_count)
            if not lite and search_type in ("all", "community", "twitter", "x"):
                _tasks["twitter"] = _pool.submit(search_twitter, q, twitter_count, keys.get("twitter") or keys.get("twitter_cookies", ""))
        _results: list = []
        for _name, _future in _tasks.items():
            try:
                _results.extend(_future.result(timeout=global_timeout))
            except Exception as e:
                _results.append({"source": _name, "error": str(e)})
        return _results

    queries_to_run = [query] + expand_queries
    q_label = f"{len(queries_to_run)} quer{'y' if len(queries_to_run) == 1 else 'ies'}"
    print(f"Searching {q_label} across sources...", file=sys.stderr)
    all_results: list = []

    if len(queries_to_run) == 1:
        all_results = _run_search(query)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries_to_run)) as outer_pool:
            outer_futures = {outer_pool.submit(_run_search, q, q != query): q for q in queries_to_run}
            for fut in concurrent.futures.as_completed(outer_futures):
                try:
                    all_results.extend(fut.result())
                except Exception:
                    pass

    deduped, raw_counts = deduplicate(all_results)
    valid_count = len([r for r in deduped if "error" not in r and r.get("source") not in ("tavily_answer", "serpapi_answer", "exa_answer")])
    print(f"Found {valid_count} unique results.", file=sys.stderr)

    output = format_results(deduped, query, raw_counts=raw_counts, brief=brief)

    if scrape_top > 0:
        scrape_top = min(scrape_top, 30)
        fc_key = pick_key(keys.get("firecrawl"))
        # exa/tavily already pre-fetch markdown during search; firecrawl /search does too.
        # Skip these as scrape candidates so we don't double-fetch.
        SKIP_SCRAPE_SOURCES: set[str] = {"exa", "tavily", "firecrawl"}
        PREFER_SCRAPE_SOURCES = {
            "brave", "serpapi", "hackernews", "stackoverflow",
            "github-repos", "twitter",
        }
        urls_to_scrape: list = []
        seen_urls: set = set()
        deduped_for_scrape = sorted(
            (
                it for it in deduped
                if "error" not in it
                and it.get("source") not in ("tavily_answer", "serpapi_answer", "exa_answer")
                and it.get("source") not in SKIP_SCRAPE_SOURCES
            ),
            key=lambda x: (
                0 if x.get("source") in PREFER_SCRAPE_SOURCES else 1,
                -(1 + len(x.get("also_from") or [])),
            ),
        )
        source_quota: dict = {}
        prefetched: dict[str, str] = {
            it["url"]: it["scraped_content"]
            for it in deduped
            if it.get("scraped_content") and it.get("url")
        }
        for item in deduped_for_scrape:
            if "error" in item:
                continue
            u = item.get("url", "")
            if not u or u in seen_urls:
                continue
            src = item.get("source", "unknown")
            if scrape_per_source > 0 and source_quota.get(src, 0) >= scrape_per_source:
                continue
            seen_urls.add(u)
            source_quota[src] = source_quota.get(src, 0) + 1
            if u not in prefetched:
                urls_to_scrape.append(u)
            if len(urls_to_scrape) + len(prefetched) >= scrape_top:
                break
        scrapes = []
        prefetched_meta = {it["url"]: it for it in deduped if it.get("url")}
        for u, content in prefetched.items():
            meta = prefetched_meta.get(u, {})
            scrapes.append({
                "url": u,
                "title": meta.get("title") or u,
                "via": meta.get("source", "prefetch"),
                "markdown": content,
                "length": len(content),
            })
        print(f"Scraping top {len(urls_to_scrape)} URL(s) ({len(prefetched)} pre-fetched by Tavily/Exa)...", file=sys.stderr)
        _jina_raw = keys.get("jina", "")
        jina_keys: list[str] = (
            [k for k in _jina_raw if k]
            if isinstance(_jina_raw, list)
            else ([_jina_raw] if _jina_raw else [])
        )
        # Allocation: first JINA_FIRST_N URLs -> Jina (free 20 RPM w/o key, higher w/ key);
        # remainder round-robin across tavily / exa / firecrawl.
        JINA_FIRST_N = 20
        SECONDARIES = ["tavily", "exa", "firecrawl"]
        tavily_scrape_key = pick_key(keys.get("tavily", ""))
        exa_scrape_key = pick_key(keys.get("exa", ""))

        def _primary_for(i: int) -> str:
            if i < JINA_FIRST_N:
                return "jina"
            return SECONDARIES[(i - JINA_FIRST_N) % len(SECONDARIES)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(urls_to_scrape) or 1)) as pool:
            futures = {
                pool.submit(
                    scrape_url_smart,
                    u,
                    fc_key,
                    25,
                    jina_keys[i % len(jina_keys)] if jina_keys else "",
                    exa_scrape_key,
                    tavily_scrape_key,
                    _primary_for(i),
                ): u
                for i, u in enumerate(urls_to_scrape)
            }
            for fut in concurrent.futures.as_completed(futures):
                try:
                    scrapes.append(fut.result(timeout=30))
                except Exception as e:
                    scrapes.append({"url": futures[fut], "error": str(e)})
            order = {u: i for i, u in enumerate(urls_to_scrape)}
            scrapes.sort(key=lambda s: order.get(s["url"], 999))
            output += format_scrapes(scrapes, max_chars=scrape_chars)

    print(output)


if __name__ == "__main__":
    main()

"""CLI entry point: argparse + orchestration."""
import concurrent.futures
import inspect
import queue
import sys
import threading
import time

from .config import ConfigError, load_config, config_bool, config_list
from .dedup import (
    _norm_url,
    deduplicate,
    result_to_scrape,
    split_by_content,
)
from .format import format_results, format_scrapes
from .keys import count_jina_keys, get_active_jina_keys, key_pool, load_keys
from .scrape import scrape_url_smart
from .secrets import scrub_secrets
from .sources.brave import search_brave
from .sources.exa import search_exa
from .sources.firecrawl import search_firecrawl
from .sources.github import search_github_repos
from .sources.serpapi import search_serpapi
from .sources.tavily import search_tavily
from .sources.twitter import search_twitter


ROUTE_PROFILES = {
    "default": {
        "brave", "tavily", "exa", "firecrawl", "serpapi",
        "github_repos", "twitter",
    },
    "lite": {"tavily", "exa"},
    "discussion": {"twitter"},
    "brave": {"brave"},
    "tavily": {"tavily"},
    "exa": {"exa"},
    "firecrawl": {"firecrawl"},
    "serpapi": {"serpapi"},
    "github": {"github_repos"},
    "twitter": {"twitter"},
}


PREFER_SCRAPE_SOURCES = {
    "brave", "serpapi", "github-repos", "firecrawl",
}


def _has_preferred_scrape_source(item: dict) -> bool:
    sources = {item.get("source")}
    sources.update(item.get("also_from") or [])
    return bool(sources & PREFER_SCRAPE_SOURCES)


def available_routes() -> list[str]:
    """Return valid --type choices."""
    return sorted(ROUTE_PROFILES)


def resolve_route(search_type: str, lite: bool = False) -> set[str]:
    if lite:
        return ROUTE_PROFILES["lite"]
    return ROUTE_PROFILES.get(search_type, set())


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if args == ["--doctor"]:
        from .doctor import doctor

        sys.exit(doctor())
    if not args:
        print("Usage: python search.py <query> [--type default|lite|discussion|...] [--count N]")
        print("       [--brave-count N] [--tavily-count N] [--exa-count N] [--github-count N]")
        print("       [--serpapi-count N]")
        print("       [--firecrawl-count N] [--twitter-count N]")
        print("       [--timeout N] [--scrape-top N] [--no-scrape] [--scrape-chars N]")
        print("       [--scrape-per-source N] [--scrape-timeout N] [--scrape-concurrency N]")
        print("       [--brief] [--verbose]")
        print("       [--config PATH]")
        print("       [--doctor]")
        sys.exit(1)

    def _fail(message: str) -> None:
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(2)

    def _value(option: str, idx: int) -> str:
        if idx + 1 >= len(args) or args[idx + 1].startswith("--"):
            _fail(f"{option} requires a value")
        return args[idx + 1]

    def _int_value(option: str, idx: int) -> int:
        raw = _value(option, idx)
        try:
            return int(raw)
        except ValueError:
            _fail(f"{option} requires an integer value, got '{raw}'")
        raise AssertionError("unreachable")

    def _nonnegative(value: int, option: str) -> int:
        if value < 0:
            _fail(f"{option} must be >= 0")
        return value

    def _positive(value: int, option: str) -> int:
        if value <= 0:
            _fail(f"{option} must be > 0")
        return value

    def _optional_positive(value: int | None, option: str) -> int | None:
        if value is not None and value <= 0:
            _fail(f"{option} must be > 0")
        return value

    def _strict_config_int(container: dict, key: str, default=None, label: str | None = None):
        if not isinstance(container, dict) or key not in container:
            return default
        value = container.get(key)
        if value is None:
            return None
        if isinstance(value, bool):
            _fail(f"{label or key} requires an integer value, got {value!r}")
        if isinstance(value, int):
            return value
        _fail(f"{label or key} requires an integer value, got {value!r}")

    def _strict_config_int_default(key: str, default: int) -> int:
        value = _strict_config_int(config, key, default, key)
        return default if value is None else value

    def _strict_source_count(source: str, default=None):
        counts = config.get("counts", {})
        if counts is None:
            counts = {}
        if not isinstance(counts, dict):
            _fail(f"counts requires an object, got {counts!r}")
        nested = _strict_config_int(counts, source, default, f"counts.{source}")
        return _strict_config_int(config, f"{source}_count", nested, f"{source}_count")

    config_path = None
    for j, arg in enumerate(args):
        if arg == "--config":
            config_path = _value("--config", j)
            break
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        _fail(str(exc))

    def _config_bool(key: str, default: bool = False) -> bool:
        try:
            return config_bool(config, key, default)
        except ConfigError as exc:
            _fail(str(exc))

    def _config_list(key: str) -> list[str]:
        try:
            return config_list(config, key)
        except ConfigError as exc:
            _fail(str(exc))

    query_parts: list = []
    search_type = str(config.get("type", "default"))
    count = _strict_config_int(config, "count", None, "count")
    brave_count = _strict_source_count("brave", None)
    tavily_count = _strict_source_count("tavily", None)
    exa_count = _strict_source_count("exa", None)
    github_count = _strict_source_count("github", None)
    serpapi_count = _strict_source_count("serpapi", None)
    firecrawl_count = _strict_source_count("firecrawl", None)
    twitter_count = _strict_source_count("twitter", None)
    serpapi_engine = str(config.get("serpapi_engine", "google_light"))
    if serpapi_engine not in {"google_light", "google"}:
        _fail("serpapi_engine must be 'google_light' or 'google'")
    global_timeout = _nonnegative(_strict_config_int_default("timeout", 60), "timeout")
    scrape_top = _nonnegative(_strict_config_int_default("scrape_top", 30), "scrape_top")
    if _config_bool("no_scrape", False):
        scrape_top = 0
    scrape_chars = _positive(_strict_config_int_default("scrape_chars", 6000), "scrape_chars")
    scrape_per_source = _positive(_strict_config_int_default("scrape_per_source", 6), "scrape_per_source")
    scrape_timeout = _nonnegative(_strict_config_int_default("scrape_timeout", 60), "scrape_timeout")
    scrape_concurrency = _positive(_strict_config_int_default("scrape_concurrency", 5), "scrape_concurrency")
    expand_queries: list = _config_list("expand") or _config_list("expand_queries")
    brief = _config_bool("brief", False)
    verbose = _config_bool("verbose", False)
    count_from_cli = False
    source_counts_from_cli: set[str] = set()
    expand_from_cli = False

    i = 0
    while i < len(args):
        if args[i] == "--type":
            search_type = _value("--type", i)
            i += 2
        elif args[i] == "--count":
            count = _positive(_int_value("--count", i), "--count")
            count_from_cli = True
            i += 2
        elif args[i] == "--brave-count":
            brave_count = _positive(_int_value("--brave-count", i), "--brave-count")
            source_counts_from_cli.add("brave")
            i += 2
        elif args[i] == "--tavily-count":
            tavily_count = _positive(_int_value("--tavily-count", i), "--tavily-count")
            source_counts_from_cli.add("tavily")
            i += 2
        elif args[i] == "--github-count":
            github_count = _positive(_int_value("--github-count", i), "--github-count")
            source_counts_from_cli.add("github")
            i += 2
        elif args[i] == "--exa-count":
            exa_count = _positive(_int_value("--exa-count", i), "--exa-count")
            source_counts_from_cli.add("exa")
            i += 2
        elif args[i] == "--serpapi-count":
            serpapi_count = _positive(_int_value("--serpapi-count", i), "--serpapi-count")
            source_counts_from_cli.add("serpapi")
            i += 2
        elif args[i] == "--serpapi-engine":
            serpapi_engine = _value("--serpapi-engine", i)
            if serpapi_engine not in {"google_light", "google"}:
                _fail("--serpapi-engine must be 'google_light' or 'google'")
            i += 2
        elif args[i] == "--firecrawl-count":
            firecrawl_count = _positive(_int_value("--firecrawl-count", i), "--firecrawl-count")
            source_counts_from_cli.add("firecrawl")
            i += 2
        elif args[i] == "--twitter-count":
            twitter_count = _positive(_int_value("--twitter-count", i), "--twitter-count")
            source_counts_from_cli.add("twitter")
            i += 2
        elif args[i] == "--timeout":
            global_timeout = _nonnegative(_int_value("--timeout", i), "--timeout")
            i += 2
        elif args[i] == "--brief":
            brief = True
            i += 1
        elif args[i] == "--verbose":
            verbose = True
            i += 1
        elif args[i] == "--scrape-top":
            scrape_top = _nonnegative(_int_value("--scrape-top", i), "--scrape-top")
            i += 2
        elif args[i] == "--no-scrape":
            scrape_top = 0
            i += 1
        elif args[i] == "--scrape-chars":
            scrape_chars = _positive(_int_value("--scrape-chars", i), "--scrape-chars")
            i += 2
        elif args[i] == "--scrape-per-source":
            scrape_per_source = _positive(_int_value("--scrape-per-source", i), "--scrape-per-source")
            i += 2
        elif args[i] == "--scrape-timeout":
            scrape_timeout = _nonnegative(_int_value("--scrape-timeout", i), "--scrape-timeout")
            i += 2
        elif args[i] == "--scrape-concurrency":
            scrape_concurrency = _positive(_int_value("--scrape-concurrency", i), "--scrape-concurrency")
            i += 2
        elif args[i] == "--config":
            _value("--config", i)
            i += 2
        elif args[i] == "--expand":
            if not expand_from_cli:
                expand_queries = []
                expand_from_cli = True
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                expand_queries.append(args[i])
                i += 1
        elif args[i].startswith("--"):
            print(f"Error: unknown option '{args[i]}'", file=sys.stderr)
            sys.exit(2)
        else:
            query_parts.append(args[i])
            i += 1

    if count_from_cli:
        if "brave" not in source_counts_from_cli:
            brave_count = None
        if "tavily" not in source_counts_from_cli:
            tavily_count = None
        if "exa" not in source_counts_from_cli:
            exa_count = None
        if "github" not in source_counts_from_cli:
            github_count = None
        if "serpapi" not in source_counts_from_cli:
            serpapi_count = None
        if "firecrawl" not in source_counts_from_cli:
            firecrawl_count = None
        if "twitter" not in source_counts_from_cli:
            twitter_count = None

    count = _optional_positive(count, "count")
    brave_count = _optional_positive(brave_count, "counts.brave / --brave-count")
    tavily_count = _optional_positive(tavily_count, "counts.tavily / --tavily-count")
    exa_count = _optional_positive(exa_count, "counts.exa / --exa-count")
    github_count = _optional_positive(github_count, "counts.github / --github-count")
    serpapi_count = _optional_positive(serpapi_count, "counts.serpapi / --serpapi-count")
    firecrawl_count = _optional_positive(firecrawl_count, "counts.firecrawl / --firecrawl-count")
    twitter_count = _optional_positive(twitter_count, "counts.twitter / --twitter-count")

    global_timeout = max(0, global_timeout if global_timeout is not None else 60)
    scrape_top = max(0, scrape_top if scrape_top is not None else 30)
    scrape_chars = max(1, scrape_chars if scrape_chars is not None else 6000)
    scrape_per_source = max(1, scrape_per_source if scrape_per_source is not None else 6)
    scrape_timeout = max(0, scrape_timeout if scrape_timeout is not None else 60)
    scrape_concurrency = max(1, scrape_concurrency if scrape_concurrency is not None else 5)

    gc = count
    brave_count   = brave_count   if brave_count   is not None else (min(gc, 20)  if gc is not None else 10)
    tavily_count  = tavily_count  if tavily_count  is not None else (min(gc, 20)  if gc is not None else 10)
    exa_count     = exa_count     if exa_count     is not None else (min(gc, 100) if gc is not None else 10)
    github_count  = github_count  if github_count  is not None else (min(gc, 100) if gc is not None else 10)
    serpapi_count = serpapi_count if serpapi_count is not None else (min(gc, 100)  if gc is not None else 10)
    firecrawl_count = firecrawl_count if firecrawl_count is not None else (min(gc, 10) if gc is not None else 5)
    twitter_count = twitter_count if twitter_count is not None else (min(gc, 20) if gc is not None else 10)

    # Hard-clamp per-source counts to provider/page-size or local conservative caps,
    # otherwise --brave-count 50 silently hits HTTP 400. Firecrawl is locally
    # capped at 10 to avoid unexpectedly large metadata searches.
    brave_count     = max(1, min(brave_count, 20))
    tavily_count    = max(1, min(tavily_count, 20))
    exa_count       = max(1, min(exa_count, 100))
    github_count    = max(1, min(github_count, 100))
    serpapi_count   = max(1, min(serpapi_count, 100))
    firecrawl_count = max(1, min(firecrawl_count, 10))
    twitter_count   = max(1, min(twitter_count, 20))

    query = " ".join(query_parts)
    if not query:
        print("Error: query is required")
        sys.exit(1)
    if search_type not in ROUTE_PROFILES:
        choices = ", ".join(available_routes())
        print(f"Error: unknown --type '{search_type}'. Available types: {choices}", file=sys.stderr)
        sys.exit(2)

    keys = load_keys()

    def _missing(source: str, message: str) -> list:
        return [{"source": source, "error": f"skipped: {message}"}]

    KEY_FALLBACK_PATTERNS = (
        "401", "403", "429", "unauthorized", "forbidden", "invalid api",
        "invalid key", "api key", "quota", "rate limit", "rate_limit",
        "too many requests", "limit exceeded", "exceeded your", "credits",
        "billing", "payment", "insufficient",
    )

    def _is_key_retryable_error(results: list) -> bool:
        error_rows = [r for r in results or [] if "error" in r]
        if not error_rows:
            return False
        msg = " ".join(str(r.get("error", "")) for r in error_rows).lower()
        return any(pattern in msg for pattern in KEY_FALLBACK_PATTERNS)

    def _call_optional_timeout(fn, *positional, timeout: float):
        try:
            params = inspect.signature(fn).parameters
            accepts_timeout = "timeout" in params
        except (TypeError, ValueError):
            accepts_timeout = False
        if accepts_timeout:
            return fn(*positional, timeout=timeout)
        return fn(*positional)

    def _run_keyed_source(source: str, key_value, call_with_key, deadline: float | None = None) -> list:
        candidates = key_pool(key_value)
        if not candidates:
            return _missing(source, "missing API key")
        last_results = []
        partial_rows = []
        for idx, candidate in enumerate(candidates):
            if deadline is not None and time.monotonic() >= deadline:
                break
            results = call_with_key(candidate) or []
            if not _is_key_retryable_error(results):
                if any("error" in r for r in results):
                    return partial_rows + results
                return results
            partial_rows.extend(r for r in results if "error" not in r)
            last_results = results
            if idx == len(candidates) - 1:
                break
        error_rows = [r for r in last_results if "error" in r]
        err = error_rows[0].get("error", "key pool exhausted") if error_rows else "key pool exhausted"
        err = scrub_secrets(err, key_value)
        exhausted = {"source": source, "error": f"key pool exhausted after {len(candidates)} key(s): {err}"}
        return partial_rows + [exhausted]

    def _run_search(q: str, lite: bool = False) -> list:
        _results: list = []
        _jobs: list[tuple[str, object]] = []
        source_names = resolve_route(search_type, lite=lite)
        timeout_seconds = max(0, global_timeout if global_timeout is not None else 60)
        source_deadline = time.monotonic() + timeout_seconds

        def _source_request_timeout(default: float) -> float:
            remaining = source_deadline - time.monotonic()
            if remaining <= 0:
                return 0.1
            return min(float(default), max(0.1, remaining))

        def _add_keyed(source: str, key_name: str, missing_message: str, call_with_key) -> None:
            key_value = keys.get(key_name)
            if key_value:
                _jobs.append((
                    source,
                    lambda source=source, key_value=key_value, call_with_key=call_with_key: _run_keyed_source(
                        source,
                        key_value,
                        call_with_key,
                        deadline=source_deadline,
                    ),
                ))
            else:
                _results.extend(_missing(source, missing_message))

        if "brave" in source_names:
            _add_keyed(
                "brave",
                "brave",
                "missing BRAVE_SEARCH_API_KEY / BRAVE_API_KEY",
                lambda api_key: _call_optional_timeout(
                    search_brave, q, api_key, brave_count, timeout=_source_request_timeout(15),
                ),
            )
        if "tavily" in source_names:
            _add_keyed(
                "tavily",
                "tavily",
                "missing TAVILY_API_KEY",
                lambda api_key: _call_optional_timeout(
                    search_tavily, q, api_key, tavily_count, timeout=_source_request_timeout(15),
                ),
            )
        if "exa" in source_names:
            _add_keyed(
                "exa",
                "exa",
                "missing EXA_API_KEY",
                lambda api_key: _call_optional_timeout(
                    search_exa, q, api_key, exa_count, timeout=_source_request_timeout(20),
                ),
            )
        if "serpapi" in source_names:
            _add_keyed(
                "serpapi",
                "serpapi",
                "missing SERPAPI_API_KEY / SERPAPI_KEY",
                lambda api_key: _call_optional_timeout(
                    search_serpapi,
                    q,
                    api_key,
                    serpapi_count,
                    serpapi_engine,
                    timeout=_source_request_timeout(20),
                ),
            )
        if "firecrawl" in source_names:
            _add_keyed(
                "firecrawl",
                "firecrawl",
                "missing FIRECRAWL_API_KEY",
                lambda api_key: _call_optional_timeout(
                    search_firecrawl, q, api_key, firecrawl_count, timeout=_source_request_timeout(60),
                ),
            )
        if "github_repos" in source_names:
            _jobs.append((
                "github-repos",
                lambda: _call_optional_timeout(
                    search_github_repos,
                    q,
                    github_count,
                    keys.get("github", ""),
                    timeout=_source_request_timeout(20),
                ),
            ))
        if "twitter" in source_names:
            _jobs.append((
                "twitter",
                lambda: _call_optional_timeout(
                    search_twitter,
                    q,
                    twitter_count,
                    keys.get("twitter") or keys.get("twitter_cookies", ""),
                    timeout=_source_request_timeout(20),
                ),
            ))

        if not _jobs:
            return _results
        if timeout_seconds <= 0:
            for _name, _ in _jobs:
                _results.append({"source": _name, "error": f"timeout after {timeout_seconds}s"})
            return _results

        _queue: queue.Queue = queue.Queue()

        def _worker(source: str, call) -> None:
            try:
                _queue.put((source, call(), None))
            except Exception as e:
                _queue.put((source, None, e))

        pending = {name for name, _ in _jobs}
        for _name, _call in _jobs:
            threading.Thread(target=_worker, args=(_name, _call), daemon=True).start()

        deadline = source_deadline
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                _name, source_results, error = _queue.get(timeout=remaining)
            except queue.Empty:
                break
            if _name not in pending:
                continue
            pending.remove(_name)
            if error is not None:
                _results.append({"source": _name, "error": scrub_secrets(error, keys)})
            elif source_results:
                _results.extend(source_results)
            else:
                _results.append({"source": _name, "status": "ok", "raw_hits": 0})

        for _name in sorted(pending):
            _results.append({"source": _name, "error": f"timeout after {timeout_seconds}s"})
        return _results

    queries_to_run = [query] + expand_queries
    q_label = f"{len(queries_to_run)} quer{'y' if len(queries_to_run) == 1 else 'ies'}"
    print(f"Searching {q_label} across sources...", file=sys.stderr)
    all_results: list = []

    if len(queries_to_run) == 1:
        all_results = _run_search(query)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries_to_run)) as outer_pool:
            outer_futures = {
                outer_pool.submit(_run_search, q, idx > 0): q
                for idx, q in enumerate(queries_to_run)
            }
            for fut in concurrent.futures.as_completed(outer_futures):
                q = outer_futures[fut]
                try:
                    all_results.extend(fut.result())
                except Exception as e:
                    all_results.append({
                        "source": "multi-search",
                        "error": f"query '{q}' failed: {scrub_secrets(e, keys)}",
                    })

    with_content, without_content, passthrough, raw_counts = split_by_content(all_results)
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
    ]
    scrape_errors: list = []
    content_pool: dict[str, dict] = {}

    def _add_to_content_pool(row: dict) -> None:
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

    for item in with_content:
        _add_to_content_pool(result_to_scrape(item))

    if scrape_top > 0:
        scrape_top = min(scrape_top, 30)
        candidates_for_scrape = sorted(
            scrape_candidates,
            key=lambda x: (
                0 if _has_preferred_scrape_source(x) else 1,
                -(1 + len(x.get("also_from") or [])),
            ),
        )
        items_to_scrape: list = []
        source_quota: dict = {}
        for item in candidates_for_scrape:
            src = item.get("source", "unknown")
            if source_quota.get(src, 0) >= scrape_per_source:
                continue
            source_quota[src] = source_quota.get(src, 0) + 1
            items_to_scrape.append(item)
            if len(items_to_scrape) >= scrape_top:
                break

        tavily_scrape_keys = key_pool(keys.get("tavily", ""))
        exa_scrape_keys = key_pool(keys.get("exa", ""))
        jina_keys_list = get_active_jina_keys(keys.get("jina", ""))
        scrape_backends = ["jina"]
        if exa_scrape_keys:
            scrape_backends.append("exa")
        if tavily_scrape_keys:
            scrape_backends.append("tavily")

        prefetch_count = len(content_pool)
        jina_active, jina_total = count_jina_keys(keys.get("jina", ""))
        print(
            f"Scraping top {len(items_to_scrape)} URL(s) "
            f"({prefetch_count} pre-fetched content item(s), "
            f"Jina keys active/total: {jina_active}/{jina_total})...",
            file=sys.stderr,
        )

        def _primary_for(i: int) -> str:
            return scrape_backends[i % len(scrape_backends)]

        def _rotated_key_pool(pool: list[str], offset: int) -> list[str]:
            if not pool:
                return []
            shift = offset % len(pool)
            return pool[shift:] + pool[:shift]

        def _scrape_timeout_row(item: dict) -> dict:
            return {
                "url": item.get("url", ""),
                "error": f"scrape timeout after {scrape_timeout}s",
            }

        if items_to_scrape and scrape_timeout <= 0:
            scrape_errors.extend(_scrape_timeout_row(item) for item in items_to_scrape)
        elif items_to_scrape:
            task_queue: queue.Queue = queue.Queue()
            result_queue: queue.Queue = queue.Queue()
            scrape_deadline = time.monotonic() + scrape_timeout
            for i, item in enumerate(items_to_scrape):
                task_queue.put((i, item))

            def _scrape_worker() -> None:
                while True:
                    if time.monotonic() >= scrape_deadline:
                        return
                    try:
                        i, item = task_queue.get_nowait()
                    except queue.Empty:
                        return
                    try:
                        result_queue.put((
                            i,
                            item,
                            scrape_url_smart(
                                item["url"],
                                timeout=25,
                                primary=_primary_for(i),
                                backends=tuple(scrape_backends),
                                jina_keys=_rotated_key_pool(jina_keys_list, i),
                                exa_keys=_rotated_key_pool(exa_scrape_keys, i),
                                tavily_keys=_rotated_key_pool(tavily_scrape_keys, i),
                                deadline=scrape_deadline,
                            ),
                            None,
                        ))
                    except Exception as e:
                        result_queue.put((i, item, None, e))
                    finally:
                        task_queue.task_done()

            worker_count = min(scrape_concurrency, len(items_to_scrape))
            for _ in range(worker_count):
                threading.Thread(target=_scrape_worker, daemon=True).start()

            completed: set[int] = set()
            while len(completed) < len(items_to_scrape):
                remaining = scrape_deadline - time.monotonic()
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
                    scrape_errors.append({
                        "url": item.get("url", ""),
                        "error": scrub_secrets(error, (jina_keys_list, exa_scrape_keys, tavily_scrape_keys)),
                    })
                elif scrape_result and scrape_result.get("error"):
                    scrape_errors.append(scrape_result)
                elif scrape_result:
                    _add_to_content_pool(scrape_result)
                else:
                    scrape_errors.append({
                        "url": item.get("url", ""),
                        "error": "empty scrape result",
                    })

            for i, item in enumerate(items_to_scrape):
                if i not in completed:
                    scrape_errors.append(_scrape_timeout_row(item))

    final_results, _ = deduplicate(with_content + final_without_content + passthrough)
    valid_count = len([
        r for r in final_results
        if "error" not in r
        and r.get("status") != "ok"
        and r.get("source") not in ("tavily_answer", "serpapi_answer", "exa_answer")
    ])
    print(f"Found {valid_count} unique results.", file=sys.stderr)
    output = format_results(final_results, query, raw_counts=raw_counts, brief=brief, verbose=verbose)
    if scrape_top > 0:
        scrapes = list(content_pool.values()) + scrape_errors
        output += format_scrapes(scrapes, max_chars=scrape_chars)

    print(output)


if __name__ == "__main__":
    main()

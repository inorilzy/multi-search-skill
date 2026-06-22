"""CLI entry point: argparse + orchestration."""
import concurrent.futures
import queue
import sys
import threading
import time

from .cache import JsonCache, make_scrape_cache_key
from .config import ConfigError, load_config, config_bool, config_list
from .dedup import (
    deduplicate,
)
from .format import format_results, format_scrapes
from .keys import count_jina_keys, load_keys
from .scrape import scrape_url_smart
from .scrape_planner import (
    add_to_content_pool,
    has_preferred_scrape_source,
    is_video_result,
    plan_scrapes,
)
from .secrets import scrub_secrets
from .search_runner import (
    ROUTE_PROFILES,
    ProviderSpec,
    SearchRunner,
    SearchRunnerConfig,
    available_routes,
    call_optional_timeout,
    resolve_route,
    run_keyed_source,
)
from .searchers.brave import search_brave
from .searchers.bilibili import search_bilibili
from .searchers.exa import search_exa
from .searchers.firecrawl import (
    search_firecrawl,
    search_linuxdo,
    search_reddit,
    search_v2ex,
    search_zhihu as search_zhihu_firecrawl,
)
from .searchers.github import search_github_repos
from .searchers.glm_web import search_glm_web
from .searchers.deepseek_web import search_deepseek_web
from .searchers.hackernews import search_hackernews
from .searchers.linuxdo import search_linuxdo_api
from .searchers.serpapi import search_serpapi
from .searchers.stackoverflow import search_stackoverflow
from .searchers.tavily import search_tavily
from .searchers.twitter import search_twitter
from .searchers.reddit import search_reddit_oauth
from .searchers.youtube import search_youtube
from .searchers.zhihu import search_zhihu


_has_preferred_scrape_source = has_preferred_scrape_source
_is_video_result = is_video_result


def build_provider_registry() -> dict[str, ProviderSpec]:
    """Build searcher registry from current module symbols.

    Tests and legacy callers often monkeypatch ``scripts.main.search_*``. Keeping
    this registry dynamic preserves that compatibility while moving fanout logic
    into SearchRunner.
    """
    return {
        "brave": ProviderSpec(
            name="brave", public_name="brave", key_name="brave",
            missing_message="missing BRAVE_SEARCH_API_KEY / BRAVE_API_KEY", timeout_default=15,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_brave, q, key, cfg.counts["brave"], timeout=ctx.timeout),
        ),
        "tavily": ProviderSpec(
            name="tavily", public_name="tavily", key_name="tavily",
            missing_message="missing TAVILY_API_KEY", timeout_default=15,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_tavily, q, key, cfg.counts["tavily"], timeout=ctx.timeout),
        ),
        "exa": ProviderSpec(
            name="exa", public_name="exa", key_name="exa",
            missing_message="missing EXA_API_KEY", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_exa, q, key, cfg.counts["exa"], timeout=ctx.timeout),
        ),
        "serpapi": ProviderSpec(
            name="serpapi", public_name="serpapi", key_name="serpapi",
            missing_message="missing SERPAPI_API_KEY / SERPAPI_KEY", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_serpapi, q, key, cfg.counts["serpapi"], cfg.serpapi_engine, timeout=ctx.timeout,
            ),
        ),
        "youtube": ProviderSpec(
            name="youtube", public_name="youtube", key_name="youtube",
            missing_message="missing YOUTUBE_API_KEY", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_youtube, q, key, cfg.counts["youtube"], timeout=ctx.timeout),
        ),
        "bilibili": ProviderSpec(
            name="bilibili", public_name="bilibili", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_bilibili, q, cfg.keys.get("bilibili", ""), cfg.counts["bilibili"], timeout=ctx.timeout,
            ),
        ),
        "firecrawl": ProviderSpec(
            name="firecrawl", public_name="firecrawl", key_name="firecrawl",
            missing_message="missing FIRECRAWL_API_KEY", timeout_default=60,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_firecrawl, q, key, cfg.counts["firecrawl"], timeout=ctx.timeout),
        ),
        "v2ex": ProviderSpec(
            name="v2ex", public_name="v2ex", key_name="firecrawl",
            missing_message="missing FIRECRAWL_API_KEY", timeout_default=60,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_v2ex, q, key, cfg.counts["firecrawl"], timeout=ctx.timeout),
        ),
        "linuxdo": ProviderSpec(
            name="linuxdo", public_name="linuxdo", key_name="firecrawl",
            missing_message="missing FIRECRAWL_API_KEY", timeout_default=60,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_linuxdo, q, key, cfg.counts["linuxdo"], timeout=ctx.timeout),
        ),
        "linuxdo_api": ProviderSpec(
            name="linuxdo_api", public_name="linuxdo-api", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_linuxdo_api, q, cfg.keys.get("linuxdo", ""), cfg.counts["linuxdo_api"], timeout=ctx.timeout,
            ),
        ),
        "reddit": ProviderSpec(
            name="reddit", public_name="reddit", key_name="firecrawl",
            missing_message="missing FIRECRAWL_API_KEY", timeout_default=60,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_reddit, q, key, cfg.counts["firecrawl"], timeout=ctx.timeout),
        ),
        "reddit_oauth": ProviderSpec(
            name="reddit_oauth", public_name="reddit-oauth", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_reddit_oauth, q, cfg.keys.get("reddit_token", ""), 10, timeout=ctx.timeout,
            ),
        ),
        "github_repos": ProviderSpec(
            name="github_repos", public_name="github-repos", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_github_repos, q, cfg.counts["github"], cfg.keys.get("github", ""), timeout=ctx.timeout,
            ),
        ),
        "hackernews": ProviderSpec(
            name="hackernews", public_name="hackernews", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_hackernews, q, cfg.counts["hackernews"], timeout=ctx.timeout),
        ),
        "stackoverflow": ProviderSpec(
            name="stackoverflow", public_name="stackoverflow", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_stackoverflow, q, cfg.counts["stackoverflow"], timeout=ctx.timeout),
        ),
        "twitter": ProviderSpec(
            name="twitter", public_name="twitter", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_twitter,
                q,
                cfg.counts["twitter"],
                cfg.keys.get("twitter") or cfg.keys.get("twitter_cookies", ""),
                timeout=ctx.timeout,
            ),
        ),
        "zhihu": ProviderSpec(name="zhihu", public_name="zhihu", timeout_default=60, call=_search_zhihu_with_fallback),
        "glm_web": ProviderSpec(
            name="glm_web", public_name="glm-web", timeout_default=120,
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_glm_web, q, cfg.counts["glm_web"], timeout=ctx.timeout),
        ),
        "deepseek_web": ProviderSpec(
            name="deepseek_web", public_name="deepseek-web", timeout_default=120,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_deepseek_web, q, cfg.counts["deepseek_web"], cfg.keys.get("deepseek_web"), timeout=ctx.timeout,
            ),
        ),
    }


def _search_zhihu_with_fallback(query, cfg, ctx, _key):
    if cfg.keys.get("zhihu"):
        return run_keyed_source(
            "zhihu",
            cfg.keys.get("zhihu"),
            lambda api_key: call_optional_timeout(search_zhihu, query, api_key, cfg.counts["zhihu"], timeout=min(ctx.timeout, 5)),
            deadline=ctx.deadline,
        )
    if cfg.keys.get("firecrawl"):
        return run_keyed_source(
            "zhihu",
            cfg.keys.get("firecrawl"),
            lambda api_key: call_optional_timeout(search_zhihu_firecrawl, query, api_key, cfg.counts["firecrawl"], timeout=ctx.timeout),
            deadline=ctx.deadline,
        )
    return [{"source": "zhihu", "error": "skipped: missing ZHIHU_ACCESS_SECRET / FIRECRAWL_API_KEY fallback"}]


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
        print("       [--serpapi-count N] [--youtube-count N] [--bilibili-count N]")
        print("       [--hackernews-count N] [--stackoverflow-count N]")
        print("       [--firecrawl-count N] [--zhihu-count N] [--twitter-count N]")
        print("       [--glm-web-count N] [--deepseek-web-count N]")
        print("       Routes include: default, lite, discussion, video, v2ex, zhihu, and single-source routes")
        print("       [--timeout N] [--scrape-top N] [--no-scrape] [--scrape-chars N]")
        print("       [--scrape-per-source N] [--scrape-timeout N] [--scrape-concurrency N]")
        print("       [--brief] [--verbose] [--title-url-only]")
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
    hackernews_count = _strict_source_count("hackernews", None)
    serpapi_count = _strict_source_count("serpapi", None)
    youtube_count = _strict_source_count("youtube", None)
    bilibili_count = _strict_source_count("bilibili", None)
    stackoverflow_count = _strict_source_count("stackoverflow", None)
    firecrawl_count = _strict_source_count("firecrawl", None)
    zhihu_count = _strict_source_count("zhihu", None)
    linuxdo_count = _strict_source_count("linuxdo", None)
    linuxdo_api_count = _strict_source_count("linuxdo_api", None)
    twitter_count = _strict_source_count("twitter", None)
    glm_web_count = _strict_source_count("glm_web", None)
    deepseek_web_count = _strict_source_count("deepseek_web", None)
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
    title_url_only = _config_bool("title_url_only", False)
    cache_enabled = _config_bool("cache_enabled", False)
    if _config_bool("no_cache", False):
        cache_enabled = False
    cache_ttl_seconds = _nonnegative(_strict_config_int_default("cache_ttl_seconds", 86400), "cache_ttl_seconds")
    cache_dir = str(config.get("cache_dir", ".cache/multi-search"))
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
        elif args[i] == "--youtube-count":
            youtube_count = _positive(_int_value("--youtube-count", i), "--youtube-count")
            source_counts_from_cli.add("youtube")
            i += 2
        elif args[i] == "--bilibili-count":
            bilibili_count = _positive(_int_value("--bilibili-count", i), "--bilibili-count")
            source_counts_from_cli.add("bilibili")
            i += 2
        elif args[i] == "--hackernews-count":
            hackernews_count = _positive(_int_value("--hackernews-count", i), "--hackernews-count")
            source_counts_from_cli.add("hackernews")
            i += 2
        elif args[i] == "--stackoverflow-count":
            stackoverflow_count = _positive(_int_value("--stackoverflow-count", i), "--stackoverflow-count")
            source_counts_from_cli.add("stackoverflow")
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
        elif args[i] == "--zhihu-count":
            zhihu_count = _positive(_int_value("--zhihu-count", i), "--zhihu-count")
            source_counts_from_cli.add("zhihu")
            i += 2
        elif args[i] == "--linuxdo-count":
            linuxdo_count = _positive(_int_value("--linuxdo-count", i), "--linuxdo-count")
            source_counts_from_cli.add("linuxdo")
            i += 2
        elif args[i] == "--linuxdo-api-count":
            linuxdo_api_count = _positive(_int_value("--linuxdo-api-count", i), "--linuxdo-api-count")
            source_counts_from_cli.add("linuxdo_api")
            i += 2
        elif args[i] == "--reddit-rss-count":
            i += 2
        elif args[i] == "--twitter-count":
            twitter_count = _positive(_int_value("--twitter-count", i), "--twitter-count")
            source_counts_from_cli.add("twitter")
            i += 2
        elif args[i] == "--glm-web-count":
            glm_web_count = _positive(_int_value("--glm-web-count", i), "--glm-web-count")
            source_counts_from_cli.add("glm_web")
            i += 2
        elif args[i] == "--deepseek-web-count":
            deepseek_web_count = _positive(_int_value("--deepseek-web-count", i), "--deepseek-web-count")
            source_counts_from_cli.add("deepseek_web")
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
        elif args[i] == "--title-url-only":
            title_url_only = True
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
        if "hackernews" not in source_counts_from_cli:
            hackernews_count = None
        if "serpapi" not in source_counts_from_cli:
            serpapi_count = None
        if "youtube" not in source_counts_from_cli:
            youtube_count = None
        if "bilibili" not in source_counts_from_cli:
            bilibili_count = None
        if "stackoverflow" not in source_counts_from_cli:
            stackoverflow_count = None
        if "firecrawl" not in source_counts_from_cli:
            firecrawl_count = None
        if "zhihu" not in source_counts_from_cli:
            zhihu_count = None
        if "linuxdo" not in source_counts_from_cli:
            linuxdo_count = None
        if "linuxdo_api" not in source_counts_from_cli:
            linuxdo_api_count = None
        if "twitter" not in source_counts_from_cli:
            twitter_count = None
        if "glm_web" not in source_counts_from_cli:
            glm_web_count = None
        if "deepseek_web" not in source_counts_from_cli:
            deepseek_web_count = None

    count = _optional_positive(count, "count")
    brave_count = _optional_positive(brave_count, "counts.brave / --brave-count")
    tavily_count = _optional_positive(tavily_count, "counts.tavily / --tavily-count")
    exa_count = _optional_positive(exa_count, "counts.exa / --exa-count")
    github_count = _optional_positive(github_count, "counts.github / --github-count")
    hackernews_count = _optional_positive(hackernews_count, "counts.hackernews / --hackernews-count")
    serpapi_count = _optional_positive(serpapi_count, "counts.serpapi / --serpapi-count")
    youtube_count = _optional_positive(youtube_count, "counts.youtube / --youtube-count")
    bilibili_count = _optional_positive(bilibili_count, "counts.bilibili / --bilibili-count")
    stackoverflow_count = _optional_positive(stackoverflow_count, "counts.stackoverflow / --stackoverflow-count")
    firecrawl_count = _optional_positive(firecrawl_count, "counts.firecrawl / --firecrawl-count")
    zhihu_count = _optional_positive(zhihu_count, "counts.zhihu / --zhihu-count")
    linuxdo_count = _optional_positive(linuxdo_count, "counts.linuxdo / --linuxdo-count")
    linuxdo_api_count = _optional_positive(linuxdo_api_count, "counts.linuxdo_api / --linuxdo-api-count")
    twitter_count = _optional_positive(twitter_count, "counts.twitter / --twitter-count")
    glm_web_count = _optional_positive(glm_web_count, "counts.glm_web / --glm-web-count")
    deepseek_web_count = _optional_positive(deepseek_web_count, "counts.deepseek_web / --deepseek-web-count")

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
    hackernews_count = hackernews_count if hackernews_count is not None else (min(gc, 100) if gc is not None else 10)
    serpapi_count = serpapi_count if serpapi_count is not None else (min(gc, 100)  if gc is not None else 10)
    youtube_count = youtube_count if youtube_count is not None else (min(gc, 50) if gc is not None else 10)
    bilibili_count = bilibili_count if bilibili_count is not None else (min(gc, 50) if gc is not None else 10)
    stackoverflow_count = stackoverflow_count if stackoverflow_count is not None else (min(gc, 100) if gc is not None else 10)
    firecrawl_count = firecrawl_count if firecrawl_count is not None else (min(gc, 100) if gc is not None else 10)
    zhihu_count = zhihu_count if zhihu_count is not None else (min(gc, 10) if gc is not None else 10)
    linuxdo_count = linuxdo_count if linuxdo_count is not None else (min(gc, 20) if gc is not None else 10)
    linuxdo_api_count = linuxdo_api_count if linuxdo_api_count is not None else (min(gc, 10) if gc is not None else 10)
    twitter_count = twitter_count if twitter_count is not None else (min(gc, 20) if gc is not None else 10)
    glm_web_count = glm_web_count if glm_web_count is not None else (min(gc, 30) if gc is not None else 10)
    deepseek_web_count = deepseek_web_count if deepseek_web_count is not None else (min(gc, 30) if gc is not None else 10)

    # Hard-clamp per-source counts to provider/page-size caps,
    # otherwise --brave-count 50 silently hits HTTP 400.
    brave_count     = max(1, min(brave_count, 20))
    tavily_count    = max(1, min(tavily_count, 20))
    exa_count       = max(1, min(exa_count, 100))
    github_count    = max(1, min(github_count, 100))
    hackernews_count = max(1, min(hackernews_count, 100))
    serpapi_count   = max(1, min(serpapi_count, 100))
    youtube_count   = max(1, min(youtube_count, 50))
    bilibili_count  = max(1, min(bilibili_count, 50))
    stackoverflow_count = max(1, min(stackoverflow_count, 100))
    firecrawl_count = max(1, min(firecrawl_count, 100))
    zhihu_count = max(1, min(zhihu_count, 10))
    twitter_count   = max(1, min(twitter_count, 20))
    glm_web_count   = max(1, min(glm_web_count, 30))
    deepseek_web_count = max(1, min(deepseek_web_count, 30))

    query = " ".join(query_parts)
    if not query:
        print("Error: query is required")
        sys.exit(1)
    if search_type not in ROUTE_PROFILES:
        choices = ", ".join(available_routes())
        print(f"Error: unknown --type '{search_type}'. Available types: {choices}", file=sys.stderr)
        sys.exit(2)
    if search_type == "video":
        title_url_only = True
        scrape_top = 0

    keys = load_keys()
    counts = {
        "brave": brave_count,
        "tavily": tavily_count,
        "exa": exa_count,
        "github": github_count,
        "hackernews": hackernews_count,
        "serpapi": serpapi_count,
        "youtube": youtube_count,
        "bilibili": bilibili_count,
        "stackoverflow": stackoverflow_count,
        "firecrawl": firecrawl_count,
        "zhihu": zhihu_count,
        "linuxdo": linuxdo_count,
        "linuxdo_api": linuxdo_api_count,
        "twitter": twitter_count,
        "glm_web": glm_web_count,
        "deepseek_web": deepseek_web_count,
    }
    runner_config = SearchRunnerConfig(
        route=search_type,
        counts=counts,
        timeout=global_timeout,
        serpapi_engine=serpapi_engine,
        keys=keys,
    )
    search_runner = SearchRunner(runner_config, build_provider_registry(), route_resolver=resolve_route)
    cache = JsonCache(cache_dir, ttl_seconds=cache_ttl_seconds, enabled=cache_enabled)
    queries_to_run = [query] + expand_queries
    q_label = f"{len(queries_to_run)} quer{'y' if len(queries_to_run) == 1 else 'ies'}"
    print(f"Searching {q_label} across sources...", file=sys.stderr)
    all_results: list = []

    if len(queries_to_run) == 1:
        all_results = search_runner.run(query)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries_to_run)) as outer_pool:
            outer_futures = {
                outer_pool.submit(search_runner.run, q, idx > 0): q
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

    scrape_plan = plan_scrapes(
        all_results,
        keys=keys,
        scrape_top=scrape_top,
        scrape_per_source=scrape_per_source,
    )
    with_content = scrape_plan.with_content
    final_without_content = scrape_plan.final_without_content
    passthrough = scrape_plan.passthrough
    raw_counts = scrape_plan.raw_counts
    scrape_errors: list = []
    content_pool: dict[str, dict] = scrape_plan.content_pool

    if scrape_top > 0:
        scrape_top = min(scrape_top, 30)
        items_to_scrape = scrape_plan.items_to_scrape
        scrape_backends = scrape_plan.backend_order
        prefetch_count = len(content_pool)
        jina_active, jina_total = count_jina_keys(keys.get("jina", ""))
        print(
            f"Scraping top {len(items_to_scrape)} URL(s) "
            f"({prefetch_count} pre-fetched content item(s), "
            f"Jina keys active/total: {jina_active}/{jina_total})...",
            file=sys.stderr,
        )

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
            for plan_item in scrape_plan.plan_items:
                task_queue.put(plan_item)

            def _scrape_worker() -> None:
                while True:
                    if time.monotonic() >= scrape_deadline:
                        return
                    try:
                        plan_item = task_queue.get_nowait()
                    except queue.Empty:
                        return
                    i = plan_item.index
                    item = plan_item.item
                    try:
                        cache_key = make_scrape_cache_key(
                            item["url"],
                            scrape_backends,
                            {"primary": plan_item.primary_backend},
                        )
                        cached = cache.get("scrape", cache_key)
                        if cached is not None:
                            scrape_result = dict(cached)
                            scrape_result.setdefault("cache", "hit")
                        else:
                            pools = plan_item.key_pools
                            scrape_result = scrape_url_smart(
                                item["url"],
                                timeout=30,
                                primary=plan_item.primary_backend,
                                backends=tuple(scrape_backends),
                                jina_keys=pools.jina,
                                exa_keys=pools.exa,
                                firecrawl_keys=pools.firecrawl,
                                tavily_keys=pools.tavily,
                                deadline=scrape_deadline,
                            )
                            if scrape_result and "error" not in scrape_result:
                                cache.set("scrape", cache_key, scrape_result)
                        result_queue.put((
                            i,
                            item,
                            scrape_result,
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
                        "error": scrub_secrets(
                            error,
                            keys,
                        ),
                    })
                elif scrape_result and scrape_result.get("error"):
                    scrape_errors.append(scrape_result)
                elif scrape_result:
                    add_to_content_pool(content_pool, scrape_result)
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
        and r.get("source") not in ("tavily_answer", "serpapi_answer", "exa_answer", "glm_web_answer", "deepseek_web_answer")
    ])
    print(f"Found {valid_count} unique results.", file=sys.stderr)
    output = format_results(
        final_results,
        query,
        raw_counts=raw_counts,
        brief=brief,
        verbose=verbose,
        title_url_only=title_url_only,
    )
    if scrape_top > 0:
        scrapes = list(content_pool.values()) + scrape_errors
        output += format_scrapes(scrapes, max_chars=scrape_chars)

    print(output)


if __name__ == "__main__":
    main()

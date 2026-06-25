"""Provider registry and zhihu fallback used by the search service."""
from ..support.cache import JsonCache, make_scrape_cache_key
from ..support.config import ConfigError, load_config, config_bool, config_list
from ..support.dedup import (
    deduplicate,
)
from ..support.format import format_results, format_scrapes
from ..state.keys import count_jina_keys, load_keys
from ..scrape.scrape import scrape_url_smart
from ..scrape.scrape_planner import (
    add_to_content_pool,
    has_preferred_scrape_source,
    is_video_result,
    plan_scrapes,
)
from ..support.secrets import scrub_secrets
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
from .searchers.baidu import search_baidu
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

    Tests and legacy callers often monkeypatch ``src.main.search_*``. Keeping
    this registry dynamic preserves that compatibility while moving fanout logic
    into SearchRunner.
    """
    return {
        "brave": ProviderSpec(
            name="brave", public_name="brave", key_name="brave",
            missing_message="missing BRAVE_SEARCH_API_KEY / BRAVE_API_KEY", timeout_default=15,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_brave, q, key, cfg.counts["brave"], timeout=ctx.timeout, search_depth=cfg.search_depth,
            ),
        ),
        "baidu": ProviderSpec(
            name="baidu", public_name="baidu", key_name="baidu",
            missing_message="missing BAIDU_QIANFAN_API_KEY / QIANFAN_API_KEY / APPBUILDER_API_KEY",
            timeout_default=60,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_baidu, q, key, cfg.counts["baidu"], cfg.search_depth, timeout=ctx.timeout,
            ),
        ),
        "tavily": ProviderSpec(
            name="tavily", public_name="tavily", key_name="tavily",
            missing_message="missing TAVILY_API_KEY", timeout_default=15,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_tavily, q, key, cfg.counts["tavily"], timeout=ctx.timeout, search_depth=cfg.search_depth,
            ),
        ),
        "exa": ProviderSpec(
            name="exa", public_name="exa", key_name="exa",
            missing_message="missing EXA_API_KEY", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_exa, q, key, cfg.counts["exa"], timeout=ctx.timeout, search_depth=cfg.search_depth,
            ),
        ),
        "serpapi": ProviderSpec(
            name="serpapi", public_name="serpapi", key_name="serpapi",
            missing_message="missing SERPAPI_API_KEY / SERPAPI_KEY", timeout_default=20,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_serpapi, q, key, cfg.counts["serpapi"], cfg.serpapi_engine,
                timeout=ctx.timeout, search_depth=cfg.search_depth,
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
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_firecrawl, q, key, cfg.counts["firecrawl"], timeout=ctx.timeout, search_depth=cfg.search_depth,
            ),
        ),
        "v2ex": ProviderSpec(
            name="v2ex", public_name="v2ex", key_name="firecrawl",
            missing_message="missing FIRECRAWL_API_KEY", timeout_default=60,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_v2ex, q, key, cfg.counts["firecrawl"], timeout=ctx.timeout, search_depth=cfg.search_depth,
            ),
        ),
        "linuxdo": ProviderSpec(
            name="linuxdo", public_name="linuxdo", key_name="firecrawl",
            missing_message="missing FIRECRAWL_API_KEY", timeout_default=60,
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_linuxdo, q, key, cfg.counts["linuxdo"], timeout=ctx.timeout, search_depth=cfg.search_depth,
            ),
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
            lambda api_key: call_optional_timeout(
                search_zhihu_firecrawl, query, api_key, cfg.counts["firecrawl"],
                timeout=ctx.timeout, search_depth=cfg.search_depth,
            ),
            deadline=ctx.deadline,
        )
    return [{"source": "zhihu", "error": "skipped: missing ZHIHU_ACCESS_SECRET / FIRECRAWL_API_KEY fallback"}]



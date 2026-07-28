"""Provider registry and zhihu fallback used by the search service."""
from .capabilities import AuthMode, get_capability
from .search_runner import (
    ProviderSpec,
    call_optional_timeout,
    run_keyed_source,
)
from .searchers.baidu import search_baidu
from .searchers.brave import search_brave
from .searchers.bilibili import search_bilibili
from .searchers.exa import search_exa
from .searchers.firecrawl import (
    search_firecrawl,
    search_linuxdo,
    search_v2ex,
    search_zhihu as search_zhihu_firecrawl,
)
from .searchers.github import search_github_repos
from .searchers.glm_web import search_glm_web
from .searchers.deepseek_web import search_deepseek_web
from .searchers.hackernews import search_hackernews
from .searchers.linuxdo import search_linuxdo_api
from .searchers.reddit_browser import search_reddit_browser
from .searchers.serpapi import search_serpapi
from .searchers.stackoverflow import search_stackoverflow
from .searchers.tavily import search_tavily
from .searchers.twitter import search_twitter
from .searchers.youtube import search_youtube
from .searchers.zhihu import search_zhihu


# The official Zhihu API is fast when it works but hangs hard when credentials
# are stale; cap its timeout aggressively so a bad zhihu key cannot eat the
# whole search-stage deadline before the Firecrawl fallback can run.
ZHIHU_OFFICIAL_API_TIMEOUT = 5


def _capability_metadata(name: str) -> tuple[str, str | None, int]:
    cap = get_capability(name)
    if cap.timeout_default is None:
        raise ValueError(f"{name} is missing capability.timeout_default")
    # SearchRunner only knows one preflight key gate. Reuse capability key_name
    # only for strictly-required API-key providers so optional/cookie/fallback
    # providers keep their current runtime behavior.
    key_name = cap.operation.key_name if cap.operation.auth_mode == AuthMode.API_KEY else None
    return cap.public_name, key_name, cap.timeout_default


def _provider_spec(
    name: str,
    call,
    *,
    missing_message: str = "missing API key",
) -> ProviderSpec:
    public_name, key_name, timeout_default = _capability_metadata(name)
    return ProviderSpec(
        name=name,
        public_name=public_name,
        key_name=key_name,
        missing_message=missing_message,
        timeout_default=timeout_default,
        call=call,
    )


def build_provider_registry() -> dict[str, ProviderSpec]:
    """Build searcher registry from current module symbols.

    Build from current module symbols so tests and callers can monkeypatch a
    provider function without rebuilding a static registry at import time.
    """
    return {
        "brave": _provider_spec(
            "brave",
            missing_message="missing BRAVE_SEARCH_API_KEY / BRAVE_API_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_brave, q, key, cfg.counts["brave"], timeout=ctx.timeout,
            ),
        ),
        "baidu": _provider_spec(
            "baidu",
            missing_message="missing BAIDU_QIANFAN_API_KEY / QIANFAN_API_KEY / APPBUILDER_API_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_baidu, q, key, cfg.counts["baidu"], timeout=ctx.timeout,
            ),
        ),
        "tavily": _provider_spec(
            "tavily",
            missing_message="missing TAVILY_API_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_tavily, q, key, cfg.counts["tavily"], timeout=ctx.timeout, want_content=cfg.want_content,
            ),
        ),
        "exa": _provider_spec(
            "exa",
            missing_message="missing EXA_API_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_exa, q, key, cfg.counts["exa"], timeout=ctx.timeout, want_content=cfg.want_content,
            ),
        ),
        "serpapi": _provider_spec(
            "serpapi",
            missing_message="missing SERPAPI_API_KEY / SERPAPI_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_serpapi, q, key, cfg.counts["serpapi"], cfg.serpapi_engine,
                timeout=ctx.timeout,
            ),
        ),
        "youtube": _provider_spec(
            "youtube",
            missing_message="missing YOUTUBE_API_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_youtube, q, key, cfg.counts["youtube"], timeout=ctx.timeout),
        ),
        "bilibili": _provider_spec(
            "bilibili",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_bilibili, q, cfg.keys.get("bilibili", ""), cfg.counts["bilibili"], timeout=ctx.timeout,
            ),
        ),
        "firecrawl": _provider_spec(
            "firecrawl",
            missing_message="missing FIRECRAWL_API_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_firecrawl, q, key, cfg.counts["firecrawl"], timeout=ctx.timeout, want_content=cfg.want_content,
            ),
        ),
        "v2ex": _provider_spec(
            "v2ex",
            missing_message="missing FIRECRAWL_API_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_v2ex, q, key, cfg.counts["firecrawl"], timeout=ctx.timeout,
            ),
        ),
        "linuxdo": _provider_spec(
            "linuxdo",
            missing_message="missing FIRECRAWL_API_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_linuxdo, q, key, cfg.counts["linuxdo"], timeout=ctx.timeout,
            ),
        ),
        "linuxdo_api": _provider_spec(
            "linuxdo_api",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_linuxdo_api, q, cfg.keys.get("linuxdo", ""), cfg.counts["linuxdo_api"], timeout=ctx.timeout,
            ),
        ),
        "github_repos": _provider_spec(
            "github_repos",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_github_repos, q, cfg.counts["github"], cfg.keys.get("github", ""), timeout=ctx.timeout,
            ),
        ),
        "hackernews": _provider_spec(
            "hackernews",
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_hackernews, q, cfg.counts["hackernews"], timeout=ctx.timeout),
        ),
        "stackoverflow": _provider_spec(
            "stackoverflow",
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_stackoverflow, q, cfg.counts["stackoverflow"], timeout=ctx.timeout),
        ),
        "twitter": _provider_spec(
            "twitter",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_twitter,
                q,
                cfg.counts["twitter"],
                cfg.keys.get("twitter") or cfg.keys.get("twitter_cookies", ""),
                timeout=ctx.timeout,
            ),
        ),
        "reddit_browser": _provider_spec(
            "reddit_browser",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_reddit_browser,
                q,
                cfg.counts["reddit_browser"],
                cfg.keys.get("reddit_browser") or {},
                timeout=ctx.timeout,
                want_content=True,
            ),
        ),
        "zhihu": _provider_spec("zhihu", call=_search_zhihu_with_fallback),
        "glm_web": _provider_spec(
            "glm_web",
            call=lambda q, cfg, ctx, key: call_optional_timeout(search_glm_web, q, cfg.counts["glm_web"], timeout=ctx.timeout),
        ),
        "deepseek_web": _provider_spec(
            "deepseek_web",
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
            lambda api_key: call_optional_timeout(search_zhihu, query, api_key, cfg.counts["zhihu"], timeout=min(ctx.timeout, ZHIHU_OFFICIAL_API_TIMEOUT)),
            deadline=ctx.deadline,
        )
    if cfg.keys.get("firecrawl"):
        return run_keyed_source(
            "zhihu",
            cfg.keys.get("firecrawl"),
            lambda api_key: call_optional_timeout(
                search_zhihu_firecrawl, query, api_key, cfg.counts["firecrawl"],
                timeout=ctx.timeout,
            ),
            deadline=ctx.deadline,
        )
    return [{"source": "zhihu", "error": "skipped: missing ZHIHU_ACCESS_SECRET / FIRECRAWL_API_KEY fallback"}]



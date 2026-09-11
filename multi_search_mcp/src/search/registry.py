"""Provider registry used by the search service."""
from .capabilities import AuthMode, get_capability
from .search_runner import (
    ProviderSpec,
    call_optional_timeout,
)
from .searchers.baidu import search_baidu
from .searchers.brave import search_brave
from .searchers.exa import search_exa
from .searchers.firecrawl import search_firecrawl
from .searchers.github import search_github_repos
from .searchers.hackernews import search_hackernews
from .searchers.linuxdo import search_linuxdo_api
from .searchers.parallel import search_parallel
from .searchers.serpapi import search_serpapi
from .searchers.stackoverflow import search_stackoverflow
from .searchers.tavily import search_tavily
from .searchers.twitter import search_twitter
from .searchers.v2ex import search_v2ex


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
        "parallel": _provider_spec(
            "parallel",
            missing_message="missing PARALLEL_API_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_parallel, q, key, cfg.counts["parallel"], timeout=ctx.timeout,
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
                deadline=ctx.deadline, publish_partial=ctx.publish_partial,
            ),
        ),
        "firecrawl": _provider_spec(
            "firecrawl",
            missing_message="missing FIRECRAWL_API_KEY",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_firecrawl, q, key, cfg.counts["firecrawl"], timeout=ctx.timeout, want_content=cfg.want_content,
            ),
        ),
        "linuxdo_api": _provider_spec(
            "linuxdo_api",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_linuxdo_api, q, cfg.keys.get("linuxdo", ""), cfg.counts["linuxdo_api"], timeout=ctx.timeout,
            ),
        ),
        "v2ex": _provider_spec(
            "v2ex",
            call=lambda q, cfg, ctx, key: call_optional_timeout(
                search_v2ex, q, cfg.counts["v2ex"], timeout=ctx.timeout,
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
                deadline=ctx.deadline, publish_partial=ctx.publish_partial,
            ),
        ),
    }

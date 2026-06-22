"""Provider capability contracts for searchers and scrapers.

This module is descriptive for now: it gives the architecture one normalized
place to answer questions such as "can this provider search?", "does it return
full content?", and "should ScrapePlanner treat its URLs as candidates?".
Runtime registries still live in ``search_runner`` and ``scrapers.registry``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProviderKind(str, Enum):
    SEARCHER = "searcher"
    CONTENT_SEARCHER = "content_searcher"
    ANSWER_SEARCHER = "answer_searcher"
    SCRAPER = "scraper"
    PLATFORM_SEARCHER = "platform_searcher"
    VIDEO_SEARCHER = "video_searcher"


class AuthMode(str, Enum):
    NONE = "none"
    API_KEY = "api_key"
    OPTIONAL_API_KEY = "optional_api_key"
    COOKIE = "cookie"
    TOKEN_OR_CLI = "token_or_cli"
    MIXED = "mixed"


class ScrapePolicy(str, Enum):
    NONE = "none"
    PREFETCH = "prefetch"
    CANDIDATE = "candidate"
    SKIP = "skip"
    SCRAPER = "scraper"


@dataclass(frozen=True)
class SearchCapability:
    can_search: bool = False
    supports_domain_filter: bool = False
    supports_query_syntax: bool = False
    supports_pagination: bool = False
    supports_sort: bool = False
    max_count: int | None = None


@dataclass(frozen=True)
class ScrapeCapability:
    can_scrape: bool = False
    supports_markdown: bool = False
    supports_text: bool = False
    supports_html: bool = False
    supports_site_policy: bool = False
    max_timeout_seconds: int | None = None


@dataclass(frozen=True)
class OutputCapability:
    returns_urls: bool = False
    returns_snippet: bool = False
    returns_content: bool = False
    returns_answer: bool = False
    returns_platform_metadata: bool = False
    returns_scores: bool = False
    returns_engagement: bool = False


@dataclass(frozen=True)
class OperationalProfile:
    auth_mode: AuthMode = AuthMode.NONE
    key_name: str | None = None
    quota_sensitive: bool = False
    rate_limit_sensitive: bool = False
    requires_dependency: str | None = None
    risk_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderCapability:
    name: str
    public_name: str
    kind: ProviderKind
    search: SearchCapability = field(default_factory=SearchCapability)
    scrape: ScrapeCapability = field(default_factory=ScrapeCapability)
    output: OutputCapability = field(default_factory=OutputCapability)
    operation: OperationalProfile = field(default_factory=OperationalProfile)
    scrape_policy: ScrapePolicy = ScrapePolicy.NONE
    best_for: tuple[str, ...] = ()
    notes: str = ""

    def table_row(self) -> dict[str, object]:
        """Return a flat row suitable for Markdown/table rendering."""
        return {
            "provider": self.public_name,
            "name": self.name,
            "kind": self.kind.value,
            "can_search": self.search.can_search,
            "can_scrape": self.scrape.can_scrape,
            "returns_urls": self.output.returns_urls,
            "returns_snippet": self.output.returns_snippet,
            "returns_content": self.output.returns_content,
            "returns_answer": self.output.returns_answer,
            "supports_domain_filter": self.search.supports_domain_filter,
            "auth_mode": self.operation.auth_mode.value,
            "key_name": self.operation.key_name or "",
            "scrape_policy": self.scrape_policy.value,
            "best_for": ", ".join(self.best_for),
        }


def _op(
    auth_mode: AuthMode,
    key_name: str | None = None,
    *,
    quota_sensitive: bool = False,
    rate_limit_sensitive: bool = False,
    requires_dependency: str | None = None,
    risk_notes: tuple[str, ...] = (),
) -> OperationalProfile:
    return OperationalProfile(
        auth_mode=auth_mode,
        key_name=key_name,
        quota_sensitive=quota_sensitive,
        rate_limit_sensitive=rate_limit_sensitive,
        requires_dependency=requires_dependency,
        risk_notes=risk_notes,
    )


PROVIDER_CAPABILITIES: dict[str, ProviderCapability] = {
    "brave": ProviderCapability(
        name="brave",
        public_name="brave",
        kind=ProviderKind.SEARCHER,
        search=SearchCapability(can_search=True, supports_query_syntax=True, supports_pagination=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True),
        operation=_op(AuthMode.API_KEY, "brave", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("broad web search", "fresh URLs"),
    ),
    "tavily": ProviderCapability(
        name="tavily",
        public_name="tavily",
        kind=ProviderKind.CONTENT_SEARCHER,
        search=SearchCapability(can_search=True, supports_domain_filter=True, supports_pagination=True),
        scrape=ScrapeCapability(can_scrape=True, supports_markdown=True, supports_text=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_content=True, returns_answer=True),
        operation=_op(AuthMode.API_KEY, "tavily", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.PREFETCH,
        best_for=("search with extracted content", "answer-style summaries"),
    ),
    "exa": ProviderCapability(
        name="exa",
        public_name="exa",
        kind=ProviderKind.CONTENT_SEARCHER,
        search=SearchCapability(can_search=True, supports_domain_filter=True, supports_query_syntax=True),
        scrape=ScrapeCapability(can_scrape=True, supports_text=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_content=True, returns_scores=True),
        operation=_op(AuthMode.API_KEY, "exa", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.PREFETCH,
        best_for=("semantic web search", "content retrieval"),
    ),
    "firecrawl": ProviderCapability(
        name="firecrawl",
        public_name="firecrawl",
        kind=ProviderKind.SEARCHER,
        search=SearchCapability(can_search=True, supports_domain_filter=True),
        scrape=ScrapeCapability(can_scrape=True, supports_markdown=True, supports_html=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True),
        operation=_op(AuthMode.API_KEY, "firecrawl", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("domain-constrained search", "fallback scraping"),
    ),
    "serpapi": ProviderCapability(
        name="serpapi",
        public_name="serpapi",
        kind=ProviderKind.ANSWER_SEARCHER,
        search=SearchCapability(can_search=True, supports_query_syntax=True, supports_pagination=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_answer=True),
        operation=_op(AuthMode.API_KEY, "serpapi", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("Google SERP metadata", "knowledge graph snippets"),
    ),
    "glm_web": ProviderCapability(
        name="glm_web",
        public_name="glm-web",
        kind=ProviderKind.ANSWER_SEARCHER,
        search=SearchCapability(can_search=True, max_count=30),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_content=True, returns_answer=True),
        operation=_op(
            AuthMode.OPTIONAL_API_KEY,
            "glm_web",
            rate_limit_sensitive=True,
            requires_dependency="local glm2api service",
            risk_notes=("Reverse-engineered web API behavior may change without notice.",),
        ),
        scrape_policy=ScrapePolicy.PREFETCH,
        best_for=("GLM native web-search answers", "Chinese web search with citations"),
        notes="Calls a local OpenAI-compatible glm2api endpoint and reads GLM web_search_results.",
    ),
    "deepseek_web": ProviderCapability(
        name="deepseek_web",
        public_name="deepseek-web",
        kind=ProviderKind.ANSWER_SEARCHER,
        search=SearchCapability(can_search=True, max_count=30),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_answer=True),
        operation=_op(
            AuthMode.COOKIE,
            "deepseek_web",
            rate_limit_sensitive=True,
            risk_notes=("Reverse-engineered web API behavior may change without notice.",),
        ),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("DeepSeek native web-search answers", "search answers with citations"),
        notes="Calls chat.deepseek.com web APIs directly with user token/cookies and search_enabled=true.",
    ),
    "github_repos": ProviderCapability(
        name="github_repos",
        public_name="github-repos",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_query_syntax=True, supports_sort=True, supports_pagination=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True, returns_scores=True, returns_engagement=True),
        operation=_op(AuthMode.OPTIONAL_API_KEY, "github", rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("repository discovery", "stars and repo metadata"),
        notes="Repository URLs are later rewritten toward README-friendly scrape targets.",
    ),
    "twitter": ProviderCapability(
        name="twitter",
        public_name="twitter",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True),
        output=OutputCapability(returns_urls=True, returns_content=True, returns_platform_metadata=True, returns_engagement=True),
        operation=_op(AuthMode.COOKIE, "twitter", rate_limit_sensitive=True, requires_dependency="twscrape"),
        scrape_policy=ScrapePolicy.PREFETCH,
        best_for=("social discussion", "tweet text"),
    ),
    "youtube": ProviderCapability(
        name="youtube",
        public_name="youtube",
        kind=ProviderKind.VIDEO_SEARCHER,
        search=SearchCapability(can_search=True, supports_pagination=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True, returns_engagement=True),
        operation=_op(AuthMode.API_KEY, "youtube", quota_sensitive=True),
        scrape_policy=ScrapePolicy.SKIP,
        best_for=("video discovery",),
    ),
    "bilibili": ProviderCapability(
        name="bilibili",
        public_name="bilibili",
        kind=ProviderKind.VIDEO_SEARCHER,
        search=SearchCapability(can_search=True, supports_pagination=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True, returns_engagement=True),
        operation=_op(AuthMode.OPTIONAL_API_KEY, "bilibili", rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.SKIP,
        best_for=("Chinese video discovery",),
    ),
    "v2ex": ProviderCapability(
        name="v2ex",
        public_name="v2ex",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_domain_filter=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True),
        operation=_op(AuthMode.API_KEY, "firecrawl", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("V2EX discussions",),
    ),
    "linuxdo": ProviderCapability(
        name="linuxdo",
        public_name="linuxdo",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_domain_filter=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True),
        operation=_op(AuthMode.API_KEY, "firecrawl", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("Linux Do discussions through Firecrawl search",),
    ),
    "linuxdo_api": ProviderCapability(
        name="linuxdo_api",
        public_name="linuxdo-api",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_pagination=True),
        output=OutputCapability(returns_urls=True, returns_content=True, returns_platform_metadata=True, returns_engagement=True),
        operation=_op(AuthMode.COOKIE, "linuxdo", rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.PREFETCH,
        best_for=("Linux Do API/cookie results",),
    ),
    "reddit": ProviderCapability(
        name="reddit",
        public_name="reddit",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_domain_filter=True),
        scrape=ScrapeCapability(can_scrape=True, supports_markdown=True, supports_text=True, supports_site_policy=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True),
        operation=_op(AuthMode.API_KEY, "firecrawl", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("Reddit threads through Firecrawl search",),
        notes="The same registry name is also used by the old-reddit scraper backend.",
    ),
    "reddit_oauth": ProviderCapability(
        name="reddit_oauth",
        public_name="reddit-oauth",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_pagination=True),
        output=OutputCapability(returns_urls=True, returns_content=True, returns_platform_metadata=True, returns_engagement=True),
        operation=_op(AuthMode.TOKEN_OR_CLI, "reddit_token", rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.PREFETCH,
        best_for=("Reddit API thread discovery",),
    ),
    "hackernews": ProviderCapability(
        name="hackernews",
        public_name="hackernews",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_pagination=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True, returns_engagement=True),
        operation=_op(AuthMode.NONE, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("Hacker News discussions",),
    ),
    "stackoverflow": ProviderCapability(
        name="stackoverflow",
        public_name="stackoverflow",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_pagination=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True, returns_scores=True),
        operation=_op(AuthMode.NONE, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("Stack Overflow Q&A",),
    ),
    "zhihu": ProviderCapability(
        name="zhihu",
        public_name="zhihu",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_domain_filter=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True),
        operation=_op(AuthMode.MIXED, "zhihu", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        best_for=("Zhihu answers and articles",),
        notes="Uses Zhihu credentials when available and Firecrawl domain search as fallback.",
    ),
    "jina": ProviderCapability(
        name="jina",
        public_name="jina",
        kind=ProviderKind.SCRAPER,
        scrape=ScrapeCapability(can_scrape=True, supports_markdown=True, supports_text=True, supports_site_policy=True),
        output=OutputCapability(returns_content=True),
        operation=_op(AuthMode.OPTIONAL_API_KEY, "jina", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.SCRAPER,
        best_for=("general URL to Markdown", "anonymous fallback"),
    ),
}


def get_capability(name: str) -> ProviderCapability:
    return PROVIDER_CAPABILITIES[name]


def capability_table_rows(names: list[str] | tuple[str, ...] | None = None) -> list[dict[str, object]]:
    selected = names or tuple(sorted(PROVIDER_CAPABILITIES))
    return [PROVIDER_CAPABILITIES[name].table_row() for name in selected]

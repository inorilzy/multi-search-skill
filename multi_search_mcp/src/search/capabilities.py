"""Provider capability contracts for searchers and scrapers.

The contracts describe provider output, fetch policy, retention, and
operator-facing capability tables. Runtime provider registries still live in
``search.registry`` and the scraper modules.
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
class RetentionPolicy:
    """Conservative local retention contract for provider-derived data."""

    persist_search_result: bool = True
    persist_content: bool = True
    persist_body: bool = True
    max_ttl_seconds: int = 60 * 60


DEFAULT_RETENTION_POLICY = RetentionPolicy()


@dataclass(frozen=True)
class ProviderCapability:
    name: str
    public_name: str
    kind: ProviderKind
    search: SearchCapability = field(default_factory=SearchCapability)
    scrape: ScrapeCapability = field(default_factory=ScrapeCapability)
    output: OutputCapability = field(default_factory=OutputCapability)
    operation: OperationalProfile = field(default_factory=OperationalProfile)
    retention: RetentionPolicy = field(default_factory=RetentionPolicy)
    scrape_policy: ScrapePolicy = ScrapePolicy.NONE
    # ``count_key`` is the key a provider's ProviderSpec actually reads from
    # ``cfg.counts[...]``. It is usually ``name``, but github_repos reads
    # ``counts["github"]``. Scrapers have no count -> None.
    count_key: str | None = None
    # Per-source search timeout used by the runtime registry. Scrapers do not
    # run in the search registry, so they leave this None.
    timeout_default: int | None = None
    best_for: tuple[str, ...] = ()
    notes: str = ""

    def table_row(self) -> dict[str, object]:
        """Return a flat row suitable for Markdown/table rendering."""
        # Product-facing aliases keep the capability table aligned with the
        # normalized result contract without breaking older field names.
        returns_summary = self.output.returns_answer
        returns_title = self.search.can_search and self.output.returns_urls
        returns_url = self.output.returns_urls
        returns_result_content = self.output.returns_snippet
        returns_prefetched_body = self.output.returns_content and self.scrape_policy == ScrapePolicy.PREFETCH
        return {
            "provider": self.public_name,
            "name": self.name,
            "kind": self.kind.value,
            "can_search": self.search.can_search,
            "can_scrape": self.scrape.can_scrape,
            "returns_summary": returns_summary,
            "returns_title": returns_title,
            "returns_url": returns_url,
            "returns_result_content": returns_result_content,
            "returns_prefetched_body": returns_prefetched_body,
            "returns_urls": self.output.returns_urls,
            "returns_snippet": self.output.returns_snippet,
            "returns_content": self.output.returns_content,
            "returns_answer": self.output.returns_answer,
            "supports_domain_filter": self.search.supports_domain_filter,
            "auth_mode": self.operation.auth_mode.value,
            "key_name": self.operation.key_name or "",
            "scrape_policy": self.scrape_policy.value,
            "persist_search_result": self.retention.persist_search_result,
            "persist_content": self.retention.persist_content,
            "persist_body": self.retention.persist_body,
            "max_retention_ttl_seconds": self.retention.max_ttl_seconds,
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
    "baidu": ProviderCapability(
        name="baidu",
        public_name="baidu",
        kind=ProviderKind.ANSWER_SEARCHER,
        search=SearchCapability(can_search=True, supports_pagination=True, max_count=50),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_answer=True, returns_scores=True),
        operation=_op(AuthMode.API_KEY, "baidu", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        count_key="baidu",
        timeout_default=60,
        best_for=("Baidu AI Search summaries", "Chinese web search with citations"),
        notes="Uses Qianfan web_summary without enable_full_content; reference content is a summary, not a page body.",
    ),
    "brave": ProviderCapability(
        name="brave",
        public_name="brave",
        kind=ProviderKind.SEARCHER,
        search=SearchCapability(can_search=True, supports_query_syntax=True, supports_pagination=True, max_count=20),
        output=OutputCapability(returns_urls=True, returns_snippet=True),
        operation=_op(AuthMode.API_KEY, "brave", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        count_key="brave",
        timeout_default=15,
        best_for=("broad web search", "fresh URLs"),
    ),
    "parallel": ProviderCapability(
        name="parallel",
        public_name="parallel",
        kind=ProviderKind.SEARCHER,
        search=SearchCapability(can_search=True, max_count=20),
        output=OutputCapability(returns_urls=True, returns_snippet=True),
        operation=_op(AuthMode.API_KEY, "parallel", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        count_key="parallel",
        timeout_default=15,
        best_for=("semantic web search", "dense source excerpts"),
        notes="Uses the GA /v1/search endpoint in fast mode; excerpts are not full page bodies.",
    ),
    "tavily": ProviderCapability(
        name="tavily",
        public_name="tavily",
        kind=ProviderKind.CONTENT_SEARCHER,
        search=SearchCapability(can_search=True, supports_domain_filter=True, supports_pagination=True, max_count=20),
        scrape=ScrapeCapability(can_scrape=True, supports_markdown=True, supports_text=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_content=True, returns_answer=True),
        operation=_op(AuthMode.API_KEY, "tavily", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.PREFETCH,
        count_key="tavily",
        timeout_default=15,
        best_for=("search with extracted content", "answer-style summaries"),
    ),
    "exa": ProviderCapability(
        name="exa",
        public_name="exa",
        kind=ProviderKind.CONTENT_SEARCHER,
        search=SearchCapability(can_search=True, supports_domain_filter=True, supports_query_syntax=True, max_count=100),
        scrape=ScrapeCapability(can_scrape=True, supports_text=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_content=True, returns_scores=True),
        operation=_op(AuthMode.API_KEY, "exa", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.PREFETCH,
        count_key="exa",
        timeout_default=20,
        best_for=("semantic web search", "content retrieval"),
    ),
    "firecrawl": ProviderCapability(
        name="firecrawl",
        public_name="firecrawl",
        kind=ProviderKind.SEARCHER,
        search=SearchCapability(can_search=True, supports_domain_filter=True, max_count=100),
        scrape=ScrapeCapability(can_scrape=True, supports_markdown=True, supports_html=True),
        output=OutputCapability(returns_urls=True, returns_snippet=True),
        operation=_op(AuthMode.API_KEY, "firecrawl", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        count_key="firecrawl",
        timeout_default=60,
        best_for=("domain-constrained search", "fallback scraping"),
    ),
    "serpapi": ProviderCapability(
        name="serpapi",
        public_name="serpapi",
        kind=ProviderKind.ANSWER_SEARCHER,
        search=SearchCapability(can_search=True, supports_query_syntax=True, supports_pagination=True, max_count=100),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_answer=True),
        operation=_op(AuthMode.API_KEY, "serpapi", quota_sensitive=True, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        count_key="serpapi",
        timeout_default=20,
        best_for=("Google SERP metadata", "knowledge graph snippets"),
    ),
    "github_repos": ProviderCapability(
        name="github_repos",
        public_name="github-repos",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_query_syntax=True, supports_sort=True, supports_pagination=True, max_count=100),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True, returns_scores=True, returns_engagement=True),
        operation=_op(AuthMode.OPTIONAL_API_KEY, "github", rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        count_key="github",
        timeout_default=20,
        best_for=("repository discovery", "stars and repo metadata"),
        notes="Repository URLs are later rewritten toward README-friendly scrape targets.",
    ),
    "twitter": ProviderCapability(
        name="twitter",
        public_name="twitter",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, max_count=20),
        output=OutputCapability(returns_urls=True, returns_content=True, returns_platform_metadata=True, returns_engagement=True),
        operation=_op(AuthMode.COOKIE, "twitter", rate_limit_sensitive=True, requires_dependency="twikit-ng"),
        scrape_policy=ScrapePolicy.PREFETCH,
        count_key="twitter",
        timeout_default=20,
        best_for=("social discussion", "tweet text"),
    ),
    "v2ex": ProviderCapability(
        name="v2ex",
        public_name="v2ex",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, max_count=50),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True, returns_scores=True, returns_engagement=True),
        operation=_op(AuthMode.NONE, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        count_key="v2ex",
        timeout_default=20,
        best_for=("V2EX topic search via SOV2EX",),
        notes="Anonymous third-party SOV2EX index; highlights supply snippets, selected topic URLs are fetched after RRF ranking.",
    ),
    "hackernews": ProviderCapability(
        name="hackernews",
        public_name="hackernews",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_pagination=True, max_count=100),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True, returns_engagement=True),
        operation=_op(AuthMode.NONE, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        count_key="hackernews",
        timeout_default=20,
        best_for=("Hacker News discussions",),
    ),
    "stackoverflow": ProviderCapability(
        name="stackoverflow",
        public_name="stackoverflow",
        kind=ProviderKind.PLATFORM_SEARCHER,
        search=SearchCapability(can_search=True, supports_pagination=True, max_count=100),
        output=OutputCapability(returns_urls=True, returns_snippet=True, returns_platform_metadata=True, returns_scores=True),
        operation=_op(AuthMode.NONE, rate_limit_sensitive=True),
        scrape_policy=ScrapePolicy.CANDIDATE,
        count_key="stackoverflow",
        timeout_default=20,
        best_for=("Stack Overflow Q&A",),
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


def get_capability_optional(name: str) -> ProviderCapability | None:
    return PROVIDER_CAPABILITIES.get(normalize_provider_name(name))


def retention_policy_for_sources(names: list[str] | tuple[str, ...]) -> RetentionPolicy:
    policies = []
    for name in names:
        capability = get_capability_optional(name)
        policies.append(
            capability.retention if capability is not None else DEFAULT_RETENTION_POLICY
        )
    if not policies:
        policies = [DEFAULT_RETENTION_POLICY]
    return RetentionPolicy(
        persist_search_result=all(policy.persist_search_result for policy in policies),
        persist_content=all(policy.persist_content for policy in policies),
        persist_body=all(policy.persist_body for policy in policies),
        max_ttl_seconds=max(
            1, min(int(policy.max_ttl_seconds) for policy in policies)
        ),
    )


def normalize_provider_name(name: str) -> str:
    normalized = str(name or "").replace("-", "_")
    if normalized in PROVIDER_CAPABILITIES:
        return normalized
    if normalized.endswith("_answer"):
        base = normalized[: -len("_answer")]
        if base in PROVIDER_CAPABILITIES:
            return base
    for internal, capability in PROVIDER_CAPABILITIES.items():
        if capability.public_name.replace("-", "_") == normalized:
            return internal
    return normalized


def capability_table_rows(names: list[str] | tuple[str, ...] | None = None) -> list[dict[str, object]]:
    selected = names or tuple(sorted(PROVIDER_CAPABILITIES))
    return [PROVIDER_CAPABILITIES[name].table_row() for name in selected]

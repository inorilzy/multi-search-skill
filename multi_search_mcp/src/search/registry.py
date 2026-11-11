"""Provider registry used by the search service."""
from ..plugins.registry import builtin_plugins
from .capabilities import get_capability
from .search_runner import (
    ProviderSpec,
    call_optional_timeout,
)
from .searchers.baidu import search_baidu
from .searchers.brave import search_brave
from .searchers.exa import search_exa
from .searchers.firecrawl import search_firecrawl
from .searchers.github import search_github_code, search_github_repos
from .searchers.hackernews import search_hackernews
from .searchers.parallel import search_parallel
from .searchers.serpapi import search_serpapi
from .searchers.stackoverflow import search_stackoverflow
from .searchers.tavily import search_tavily
from .searchers.twitter import search_twitter
from .searchers.sov2ex import search_sov2ex


def _capability_metadata(name: str) -> tuple[str, str | None, int, bool]:
    cap = get_capability(name)
    if cap.timeout_default is None:
        raise ValueError(f"{name} is missing capability.timeout_default")
    key_name = cap.operation.key_name if cap.operation.uses_api_key_pool else None
    return cap.public_name, key_name, cap.timeout_default, cap.operation.requires_api_key


def _provider_spec(
    name: str,
    call,
    *,
    missing_message: str = "missing API key",
) -> ProviderSpec:
    public_name, key_name, timeout_default, key_required = _capability_metadata(name)
    return ProviderSpec(
        name=name,
        public_name=public_name,
        key_name=key_name,
        key_required=key_required,
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
        spec.name: spec
        for plugin in builtin_plugins()
        if plugin.search_specs is not None
        for spec in plugin.search_specs()
    }

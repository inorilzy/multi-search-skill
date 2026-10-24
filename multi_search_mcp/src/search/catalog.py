"""Machine-readable source, route, alias, and environment catalog.

This module is the single source of truth for the names the Python core, the
CLI, and the desktop share. ``multi-search sources --format json`` exposes it,
and ``scripts/export_source_catalog.py`` renders the checked-in desktop
artifacts from it. Desktop code must not hand-copy these lists again.

Source labels, descriptions, and display marks live here too because the
desktop renders them next to the same names; keeping one catalog prevents a
renamed source from leaving a stale label behind.
"""
from __future__ import annotations

from typing import Any

from ..state.keys import CREDENTIAL_STORE_PROVIDERS, KEY_ENV_PAIRS
from .capabilities import PROVIDER_CAPABILITIES
from .search_runner import (
    ALL_SOURCE_NAMES,
    ROUTE_ALIASES,
    ROUTE_PROFILES,
    ROUTE_SOURCE_ORDER,
    SOURCE_ALIASES,
)

SCHEMA_VERSION = 1

# Credential resolution order in ``state.keys.load_keys``. Environment
# variables win over the Windows credential store, which wins over the legacy
# JSON keys file.
KEY_RESOLUTION_ORDER = ("env", "credential_store", "keys_file")
# ``load_keys`` walks each provider's env aliases in declaration order and
# assigns every non-empty value, so the last non-empty alias wins.
ENV_ALIAS_PRIORITY = "last_non_empty_wins"

# Stable order for CLI/desktop display. Keyed sources first, then keyless
# search sources, then scrape-only backends. ``build_source_catalog`` fails if a
# provider is added without updating this list, so drift is loud rather than
# silent.
SOURCE_DISPLAY_ORDER = (
    "baidu",
    "brave",
    "parallel",
    "tavily",
    "exa",
    "firecrawl",
    "serpapi",
    "github_repos",
    "hackernews",
    "stackoverflow",
    "sov2ex",
    "twitter",
    "jina",
)

SOURCE_LABELS = {
    "baidu": "Baidu AI 搜索",
    "brave": "Brave 搜索",
    "parallel": "Parallel",
    "tavily": "Tavily",
    "exa": "Exa",
    "firecrawl": "Firecrawl",
    "serpapi": "SerpAPI",
    "github_repos": "GitHub 仓库",
    "hackernews": "Hacker News",
    "stackoverflow": "Stack Overflow",
    "sov2ex": "V2EX",
    "twitter": "Twitter / X",
    "jina": "Jina Reader",
}

SOURCE_DESCRIPTIONS = {
    "baidu": "强大的中文搜索能力，适合中文内容检索。",
    "brave": "注重隐私的搜索引擎，提供独立索引的网络搜索结果。",
    "parallel": "AI 驱动的搜索，整合多源信息。",
    "tavily": "面向 LLM 的搜索 API，提供实时网络信息。",
    "exa": "面向开发者的搜索 API，擅长语义搜索。",
    "firecrawl": "将网页转为结构化数据，适合内容抓取与分析。",
    "serpapi": "聚合多搜索引擎的 API 服务。",
    "github_repos": "搜索 GitHub 上的开源项目、代码和文档。",
    "hackernews": "搜索技术社区 Hacker News 的讨论。",
    "stackoverflow": "搜索 Stack Overflow 的技术问答。",
    "sov2ex": "搜索 V2EX 中文技术社区的讨论。",
    "twitter": "通过本机 Cookie 文件搜索 Twitter / X。",
    "jina": "额外网页正文抓取后端。",
}

SOURCE_MARKS = {
    "baidu": "du",
    "brave": "B",
    "parallel": "P",
    "tavily": "t",
    "exa": "X",
    "firecrawl": "f",
    "serpapi": "S",
    "github_repos": "GH",
    "hackernews": "Y",
    "stackoverflow": "≋",
    "sov2ex": "V₂",
    "twitter": "𝕏",
    "jina": "J",
}

ROUTE_LABELS = {
    "default": "默认（网页综合）",
    "fast": "快速",
    "all": "全部",
    "social": "社交（Twitter）",
    "dev": "开发者（Stack Overflow / GitHub / Hacker News）",
}

_ENV_BY_KEY: dict[str, list[str]] = {}
for _env_name, _key_name in KEY_ENV_PAIRS:
    _ENV_BY_KEY.setdefault(_key_name, []).append(_env_name)


def _env_names(source_name: str, key_provider: str) -> list[str]:
    """Env aliases for one source, in ``KEY_ENV_PAIRS`` application order."""
    for candidate in (key_provider, source_name, f"{source_name}_cookies"):
        if candidate in _ENV_BY_KEY:
            return list(_ENV_BY_KEY[candidate])
    return []


def _aliases_for(source_name: str) -> list[str]:
    return sorted(alias for alias, target in SOURCE_ALIASES.items() if target == source_name)


def _routes_for(source_name: str) -> list[str]:
    return [route for route in ROUTE_SOURCE_ORDER if source_name in ROUTE_PROFILES[route]]


def _source_entry(name: str) -> dict[str, Any]:
    capability = PROVIDER_CAPABILITIES[name]
    key_provider = capability.operation.key_name or name
    return {
        "name": name,
        "public_name": capability.public_name,
        "label": SOURCE_LABELS[name],
        "description": SOURCE_DESCRIPTIONS[name],
        "mark": SOURCE_MARKS[name],
        "kind": capability.kind.value,
        "searchable": name in ALL_SOURCE_NAMES,
        "aliases": _aliases_for(name),
        "key_provider": key_provider,
        "keyed": key_provider in CREDENTIAL_STORE_PROVIDERS,
        "cookie": name == "twitter",
        "env": _env_names(name, key_provider),
        "routes": _routes_for(name),
        "max_count": capability.search.max_count,
    }


def _route_entry(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "label": ROUTE_LABELS[name],
        "aliases": sorted(alias for alias, target in ROUTE_ALIASES.items() if target == name),
        "sources": list(ROUTE_SOURCE_ORDER[name]),
    }


def build_source_catalog() -> dict[str, Any]:
    """Return the shared catalog. Deterministic: safe to snapshot in artifacts."""
    expected = set(PROVIDER_CAPABILITIES)
    missing = sorted(expected - set(SOURCE_DISPLAY_ORDER))
    stale = sorted(set(SOURCE_DISPLAY_ORDER) - expected)
    if missing or stale:
        raise RuntimeError(
            "source display order is out of sync with PROVIDER_CAPABILITIES "
            f"(missing: {missing or 'none'}; stale: {stale or 'none'})"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "key_resolution": {
            "order": list(KEY_RESOLUTION_ORDER),
            "env_alias_priority": ENV_ALIAS_PRIORITY,
            "description": (
                "Environment variables override the Windows credential store, which "
                "overrides ~/.search-keys.json. Within one provider the env aliases are "
                "applied in listed order and the last non-empty value wins."
            ),
        },
        "env": {
            "alias_priority": ENV_ALIAS_PRIORITY,
            "providers": {key: list(names) for key, names in _ENV_BY_KEY.items()},
        },
        "credential_store_providers": list(CREDENTIAL_STORE_PROVIDERS),
        "source_aliases": dict(sorted(SOURCE_ALIASES.items())),
        "sources": [_source_entry(name) for name in SOURCE_DISPLAY_ORDER],
        "routes": [_route_entry(name) for name in ROUTE_SOURCE_ORDER],
    }

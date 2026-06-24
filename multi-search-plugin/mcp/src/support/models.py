"""Shared data contracts for search, scraping, and provider diagnostics.

The CLI still accepts and emits dictionaries for backward compatibility. These
models make the contract explicit while letting older searcher/scraper adapters
continue returning plain dict rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _without_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def as_dict(row: Any) -> dict:
    """Return a mutable dict for model or dict rows."""
    if hasattr(row, "to_dict"):
        return row.to_dict()
    return dict(row)


def as_dicts(rows: list[Any] | tuple[Any, ...]) -> list[dict]:
    return [as_dict(row) for row in rows]


@dataclass
class SearchResult:
    source: str
    title: str = ""
    url: str = ""
    description: str = ""
    scraped_content: str = ""
    also_from: list[str] = field(default_factory=list)
    stars: int | None = None
    score: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "scraped_content": self.scraped_content,
            "also_from": list(self.also_from),
            "stars": self.stars,
            "score": self.score,
        }
        data = _without_none(data)
        data.update(self.raw)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SearchResult":
        known = {
            "source", "title", "url", "description", "scraped_content",
            "also_from", "stars", "score",
        }
        return cls(
            source=str(data.get("source", "")),
            title=str(data.get("title", "") or ""),
            url=str(data.get("url", "") or ""),
            description=str(data.get("description", "") or ""),
            scraped_content=str(data.get("scraped_content", "") or ""),
            also_from=list(data.get("also_from") or []),
            stars=data.get("stars"),
            score=data.get("score"),
            raw={key: value for key, value in data.items() if key not in known},
        )


@dataclass
class ScrapeResult:
    url: str
    title: str = ""
    markdown: str = ""
    length: int | None = None
    via: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {
            "url": self.url,
            "title": self.title,
            "markdown": self.markdown,
            "length": self.length if self.length is not None else len(self.markdown),
            "via": self.via,
        }
        data.update(self.raw)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ScrapeResult":
        known = {"url", "title", "markdown", "length", "via"}
        return cls(
            url=str(data.get("url", "") or ""),
            title=str(data.get("title", "") or ""),
            markdown=str(data.get("markdown", "") or ""),
            length=data.get("length"),
            via=str(data.get("via", "") or ""),
            raw={key: value for key, value in data.items() if key not in known},
        )


@dataclass
class ProviderStatus:
    source: str
    status: str = "ok"
    raw_hits: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {"source": self.source, "status": self.status, "raw_hits": self.raw_hits}
        data.update(self.raw)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ProviderStatus":
        known = {"source", "status", "raw_hits"}
        return cls(
            source=str(data.get("source", "") or ""),
            status=str(data.get("status", "ok") or "ok"),
            raw_hits=int(data.get("raw_hits", 0) or 0),
            raw={key: value for key, value in data.items() if key not in known},
        )


@dataclass
class ProviderError:
    source: str
    error: str
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {"source": self.source, "error": self.error}
        data.update(self.raw)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ProviderError":
        known = {"source", "error"}
        return cls(
            source=str(data.get("source", "") or ""),
            error=str(data.get("error", "") or ""),
            raw={key: value for key, value in data.items() if key not in known},
        )

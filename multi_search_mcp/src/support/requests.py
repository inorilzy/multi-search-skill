"""Public request types shared by the service, CLI, tools, and snapshot capture.

Keeping these dataclasses in the support layer lets every caller use an
explicit type instead of duck-typed namespaces, without creating an upward
dependency back into ``service``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MultiSearchRequest:
    query: str
    route: str | None = None
    count: int | None = None
    sources: list[str] | None = None
    scrape_chars: int | None = None
    scrape_timeout: int | None = None
    scrape_concurrency: int | None = None
    timeout: int | None = None
    output: str = "both"
    config_path: str | None = None
    expand: list[str] | None = None
    use_state: bool = True


@dataclass
class ScrapeRequest:
    url: str
    backends: list[str] | None = None
    scrape_chars: int | None = None
    timeout: int | None = None
    output: str = "both"
    use_state: bool = True


@dataclass
class SearchWebRequest:
    query: str
    route: str | None = None
    count: int | None = None
    sources: list[str] | None = None
    timeout: int | None = None
    config_path: str | None = None
    expand: list[str] | None = None
    use_state: bool = True
    # Candidate-only mode: fuse ranked search hits and stop. No page body is
    # fetched and no body cache entry is written, so a caller that only needs
    # provider status (the desktop's "test key") spends exactly one search budget.
    no_fetch: bool = False


@dataclass
class FetchSourceRequest:
    source_id: str | None = None
    url: str | None = None
    backends: list[str] | None = None
    max_chars: int = 20_000
    timeout: int | None = None
    config_path: str | None = None
    use_state: bool = True
    full_content: bool = False


@dataclass
class ReadSourceRequest:
    source_id: str
    keyword: str | None = None
    offset: int = 0
    limit: int = 4_000
    use_state: bool = True

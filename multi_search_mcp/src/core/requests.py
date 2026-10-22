"""Public request DTOs accepted by every service entry point.

Entry points accept either these dataclasses or plain dictionaries; the
constructors stay permissive so the CLI can forward argparse values directly.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MultiSearchRequest:
    query: str
    route: str | None = None
    count: int | None = None
    sources: list[str] | None = None
    scrape_top: int | None = None
    scrape_chars: int | None = None
    scrape_per_source: int | None = None
    scrape_timeout: int | None = None
    scrape_concurrency: int | None = None
    timeout: int | None = None
    output: str = "both"
    config_path: str | None = None
    expand: list[str] | None = None
    brief: bool = False
    verbose: bool = False
    title_url_only: bool = False
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
    no_scrape: bool = False


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

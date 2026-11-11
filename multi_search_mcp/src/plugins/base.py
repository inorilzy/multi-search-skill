"""Contracts shared by built-in provider plugins and their callers."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from ..support import http as support_http

if TYPE_CHECKING:
    from ..search.search_runner import ProviderSpec


@dataclass(frozen=True)
class AuthMethod:
    type: Literal["api", "oauth"]
    label: str
    credential: str
    purpose: Literal["search_key", "balance_only"] = "search_key"


@dataclass(frozen=True)
class BalanceReport:
    """Public diagnostics only: callers supply fingerprints and scrub messages."""

    provider: str
    status: Literal["ok", "unsupported", "needs_credential", "error"]
    scope: Literal["key", "team", "account"] = "key"
    unit: Literal["credits", "tokens", "searches", "usd", "requests"] = "requests"
    remaining: int | float | None = None
    limit: int | float | None = None
    used: int | float | None = None
    resets_at: str | None = None
    period: str | None = None
    key_fingerprint: str | None = None
    error_kind: str | None = None
    message: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BalanceContext:
    """One request budget and an injectable ``urlopen_retry``-compatible adapter.

    ``deadline`` uses time.monotonic(), like search and scrape contexts. Use
    ``open(request)`` so both real and fake HTTP calls receive the same budget.
    The response follows urllib's context-manager/read protocol.
    """

    timeout: float = 10.0
    deadline: float | None = None
    http: Callable[..., Any] = field(default_factory=lambda: support_http.urlopen_retry)

    def remaining_timeout(self) -> float:
        if self.deadline is None:
            return max(0.0, float(self.timeout))
        return max(0.0, min(float(self.timeout), self.deadline - time.monotonic()))

    def open(self, request, *, retries: int = 2):
        timeout = self.remaining_timeout()
        if timeout <= 0:
            raise TimeoutError("balance request deadline exceeded")
        return self.http(request, timeout=timeout, retries=retries, deadline=self.deadline)


@dataclass(frozen=True)
class ScrapeBackendSpec:
    """Channel metadata; dispatch names resolve in the historical scrape module.

    ``order`` preserves the factory chain independently of search/plugin order.
    Nonempty ``legacy_channels`` marks a historical combined backend and records
    its expansion order for settings and desktop callers.
    """

    name: str
    key_provider: str
    key_required: bool
    supports_anonymous: bool = False
    dispatch: str = ""
    order: int = 0
    legacy_channels: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderPlugin:
    id: str
    label: str
    key_provider: str | None
    search_sources: tuple[str, ...] = ()
    scrape_channels: tuple[str, ...] = ()
    auth_methods: tuple[AuthMethod, ...] = ()
    # Adapters may return one report or a list when the vendor exposes several
    # independent quotas (Tavily key/account, GitHub search/code_search).
    balance: Callable[[str, BalanceContext], BalanceReport | list[BalanceReport]] | None = None
    balance_note: str = ""
    balance_ttl_seconds: int = 300
    balance_credential: str | None = None
    search_specs: Callable[[], tuple[ProviderSpec, ...]] | None = None
    scrape_backends: tuple[ScrapeBackendSpec, ...] = ()

    def __post_init__(self) -> None:
        if self.balance_credential is None:
            object.__setattr__(self, "balance_credential", self.key_provider)
        if not self.scrape_channels:
            object.__setattr__(self, "scrape_channels", tuple(spec.name for spec in self.scrape_backends))

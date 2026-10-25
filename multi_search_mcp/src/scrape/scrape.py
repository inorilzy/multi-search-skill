"""URL scraping with platform domain dispatch and generic page backends.

A scrape call is described by :class:`ScrapeContext`: it carries the credential
pool, deadline, site memory and per-call options. ``scrape_url_smart`` still
accepts the historical keyword arguments so callers that predate the context keep
working while the tree migrates.
"""
from __future__ import annotations

import ipaddress
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..state.key_state import KeyCandidate, key_fingerprint, key_id_for
from ..state.site_memory import ScrapeAttempt
from ..support.auth import is_key_retryable_error
from ..support.models import normalize_scrape_result
from ..support.url_security import (
    UrlSecurityError,
    _ensure_public_ip,
    validate_scrape_url,
)
from .scrapers import _DEFAULT_SCRAPE_TIMEOUT_SECONDS
from .scrapers.exa import scrape_url_exa
from .scrapers.firecrawl import scrape_url_firecrawl
from .scrapers.jina import (
    jina_anonymous_cooling_down,
    scrape_url_jina,
)
from .scrapers.tavily import scrape_url_tavily
from .scrapers.reddit import is_reddit_url, scrape_url_reddit
from .scrapers.twitter import is_twitter_url, scrape_url_twitter, validate_twitter_url
from .url_classify import is_zhihu_blocked_text, is_zhihu_url


# Backwards-compatible module aliases: the anonymous Jina cooldown is patched
# by existing tests through this module, so keep the historical private names
# bound here while importing only the public scraper API.
_jina_anonymous_cooling_down = jina_anonymous_cooling_down

# Rate-limit metadata emitted by the scrapers; the credential classifier reads
# the shared ``kind`` taxonomy once it lands.
_ERROR_KIND_RATE_LIMIT = "rate_limit"


# ---------------------------------------------------------------------------
# Backend metadata table — the single source of truth for the generic scrape
# plane. Add a new generic backend by appending one row plus a dispatch entry
# below.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScrapeBackendSpec:
    """Static description of a generic content-fetch backend."""

    name: str
    # Provider id used to key the credential pool / key_state identity.
    key_provider: str
    # True means the backend cannot run without a usable key in the pool.
    key_required: bool
    # Optional keyed-channel preference flags interpreted by the dispatcher.
    supports_anonymous: bool = False


_SCRAPE_BACKENDS: tuple[ScrapeBackendSpec, ...] = (
    ScrapeBackendSpec("jina", key_provider="jina", key_required=False, supports_anonymous=True),
    ScrapeBackendSpec("exa", key_provider="exa", key_required=True),
    ScrapeBackendSpec("tavily", key_provider="tavily", key_required=True),
    ScrapeBackendSpec("firecrawl", key_provider="firecrawl", key_required=False),
)

_BACKEND_BY_NAME = {spec.name: spec for spec in _SCRAPE_BACKENDS}

# Selectable generic backends. Platform scrapers are still picked by URL domain.
KNOWN_BACKENDS = tuple(spec.name for spec in _SCRAPE_BACKENDS)
# Backends that require a configured key. Used to distinguish "no key
# configured" from "backend unknown" when a caller forces an explicit list.
KEYED_BACKENDS = tuple(spec.name for spec in _SCRAPE_BACKENDS if spec.key_required)


DEFAULT_SCRAPE_POLICY = {
    "name": "default",
    "backends": KNOWN_BACKENDS,
    "jina": {},
    "tavily": {},
    "blocked": None,
}

SCRAPE_POLICIES = (
    {
        "name": "zhihu",
        "match": is_zhihu_url,
        "jina": {"respond_with": "text"},
        "tavily": {"content_format": "text"},
        "blocked": is_zhihu_blocked_text,
    },
)


def _resolve_scrape_policy(url: str, backends: list[str] | tuple[str, ...] | None = None) -> dict:
    """Return the scrape policy for *url*, keeping default markdown behavior unless overridden."""
    enabled = list(backends or DEFAULT_SCRAPE_POLICY["backends"])
    policy = {
        "name": DEFAULT_SCRAPE_POLICY["name"],
        "backends": enabled,
        "jina": dict(DEFAULT_SCRAPE_POLICY["jina"]),
        "tavily": dict(DEFAULT_SCRAPE_POLICY["tavily"]),
        "blocked": DEFAULT_SCRAPE_POLICY["blocked"],
    }
    for candidate in SCRAPE_POLICIES:
        if not candidate["match"](url):
            continue
        if backends is None and candidate.get("backends"):
            # No caller-supplied order: adopt the policy's full preferred order.
            enabled = list(candidate["backends"])
        else:
            # Caller supplied an explicit backend order (e.g. the search
            # orchestrator). Keep that order but make sure policy-mandated
            # fallbacks are still appended so URL-specific behavior is not
            # silently dropped.
            for backend in candidate.get("ensure_backends", ()):
                if backend not in enabled:
                    enabled.append(backend)
        policy["name"] = candidate["name"]
        policy["backends"] = enabled
        policy["jina"].update(candidate.get("jina", {}))
        policy["tavily"].update(candidate.get("tavily", {}))
        policy["blocked"] = candidate.get("blocked")
        break
    return policy


def _key_candidates(single_key: str = "", keys: list[str] | tuple[str, ...] | None = None) -> list[str]:
    if keys is not None:
        return [str(key) for key in keys if key]
    return [single_key] if single_key else []


def _key_candidates_from(value: Any) -> list[str]:
    """Normalize a key source to a list of credential strings."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    return [str(value)]


def _candidate_for(provider: str, key: str) -> KeyCandidate:
    return KeyCandidate(key=key, key_id=key_id_for(provider, key), fingerprint=key_fingerprint(key))


def keys_for_backend(provider: str, value: Any) -> list[KeyCandidate]:
    """Build unfiltered key candidates for one backend.

    Callers with a state store pass ``KeyManager.candidates(...)`` results
    instead; this helper covers stateless/test callers that just need
    ``ScrapeContext.keys_by_backend`` populated.
    """
    return [_candidate_for(provider, key) for key in _key_candidates_from(value)]


@dataclass
class ScrapeContext:
    """Carrier for everything a single scrape call needs.

    ``keys_by_backend`` maps each generic backend to its filtered key
    candidates (already passed through ``KeyManager.candidates``). Other fields
    are shared infrastructure or per-call options.
    """

    keys_by_backend: dict[str, list[KeyCandidate]] = field(default_factory=dict)
    deadline: float | None = None
    site_memory: Any = None
    key_manager: Any = None
    url_resolver: Any = None
    scrape_chars: int | None = None
    timeout: float = _DEFAULT_SCRAPE_TIMEOUT_SECONDS
    jina_prefer_keyed: bool = False
    twitter_cookies: Any = ""
    primary: str | None = None
    backends: tuple[str, ...] | list[str] | None = None
    # True only for caller-forced backend lists (``--backend``): configuration
    # chains skip keyless backends at runtime instead of failing eagerly.
    strict_backends: bool = False

    def keys_for(self, backend: str) -> list[KeyCandidate]:
        return list(self.keys_by_backend.get(backend) or [])

    def remaining_timeout(self) -> float:
        if self.deadline is None:
            return float(self.timeout)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            return 0.0
        return min(float(self.timeout), remaining)


def _is_target_failure(result: dict) -> bool:
    """True when the failure came from the target page, not the credential."""
    return result.get("origin") == "target" or result.get("error_origin") == "target"


def _result_is_rate_limited(result: dict) -> bool:
    return bool(result.get("rate_limited")) or result.get("kind") == _ERROR_KIND_RATE_LIMIT


def _record_key_result(
    provider: str, candidate: KeyCandidate, result: dict, key_manager,
) -> None:
    # A target-page failure is neutral to credential health, including any
    # auth failure another in-flight request may already have recorded.
    if key_manager is None or _is_target_failure(result):
        return
    key_manager.record_result(provider, candidate, key_manager.classify_result(provider, result))


def _scrape_with_key_candidates(
    provider: str,
    candidates: list[KeyCandidate],
    call: Callable[[str], dict],
    *,
    deadline: float | None = None,
    key_manager=None,
) -> dict | None:
    """Run ``call`` against each candidate; return the first non-error row or the
    last error row. Iteration stops when the failure is not key-retryable."""
    last: dict | None = None
    for candidate in candidates:
        if deadline is not None and time.monotonic() >= deadline:
            break
        if key_manager is not None:
            key_manager.record_use(provider, candidate)
        result = call(candidate.key)
        if not isinstance(result, dict):
            return result
        _record_key_result(provider, candidate, result, key_manager)
        last = result
        if "error" not in result:
            return result
        if not is_key_retryable_error(result):
            return result
    return last


def _scrape_with_optional_key_pool(
    provider: str,
    candidates: list[KeyCandidate],
    call: Callable[[str], dict],
    *,
    deadline: float | None = None,
    key_manager=None,
) -> dict | None:
    """For backends that tolerate an anonymous call when no key is configured."""
    if candidates:
        return _scrape_with_key_candidates(
            provider, candidates, call, deadline=deadline, key_manager=key_manager,
        )
    if deadline is not None and time.monotonic() >= deadline:
        return None
    return call("")


def _validate_delegated_url(url: str, *, deadline: float | None = None) -> str:
    """Validate a URL handed to a third-party fetch service.

    The provider resolves the URL on its own network, so a local DNS check adds
    no SSRF protection and wrongly rejects fake-IP/TUN routing (a local proxy
    answering 198.18.0.0/15). Everything decidable without DNS is still
    enforced: http(s) only, a host, no embedded credentials, no localhost, and
    no literal non-public IP destination.
    """
    candidate = str(url or "").strip()
    label = "scrape URL"
    try:
        parts = urllib.parse.urlsplit(candidate)
        hostname = parts.hostname
    except ValueError as exc:
        raise UrlSecurityError(f"{label} is not a valid URL: {exc}") from exc
    scheme = (parts.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise UrlSecurityError(
            f"{label} uses unsupported URL scheme: {parts.scheme or '<missing>'}"
        )
    host = (hostname or "").lower().rstrip(".")
    if not host:
        raise UrlSecurityError(f"{label} is missing host")
    if parts.username is not None or parts.password is not None:
        raise UrlSecurityError(f"{label} must not include credentials")
    if deadline is not None and deadline - time.monotonic() <= 0:
        raise UrlSecurityError(f"{label} deadline exceeded")
    if host == "localhost" or host.endswith(".localhost"):
        raise UrlSecurityError(f"unsafe {label}: localhost is not allowed")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return candidate
    _ensure_public_ip(literal, label=label, resolved=False)
    return candidate


def _prepare_scrape_target(
    url: str, *, resolver=None, deadline: float | None = None,
) -> tuple[str, str]:
    """Validate a generic (delegated) scrape target without local DNS.

    ``resolver`` is accepted for signature compatibility but intentionally
    unused: only locally fetched paths (Reddit, direct HTTP) resolve the host.
    """
    del resolver
    safe_url = _validate_delegated_url(url, deadline=deadline)
    return safe_url, safe_url


# ---------------------------------------------------------------------------
# Per-backend dispatchers. Each takes ``(target, ctx, policy)`` and returns the
# backend's dict row, or None when the backend is not currently invocable
# (e.g. cooldown without any usable key).
# ---------------------------------------------------------------------------


def _scrape_jina(target: str, ctx: ScrapeContext, policy: dict) -> dict | None:
    candidates = ctx.keys_for("jina")

    def _scrape_anonymous() -> dict:
        call_timeout = ctx.remaining_timeout()
        if call_timeout <= 0:
            return {"url": target, "error": "scrape deadline exceeded"}
        if _jina_anonymous_cooling_down():
            return {
                "url": target,
                "error": "Jina: anonymous rate limit cooldown active",
                "rate_limited": True,
                "kind": _ERROR_KIND_RATE_LIMIT,
                "origin": "provider",
            }
        # scrape_url_jina records an anonymous rate limit itself; record it in
        # exactly one place so a cooldown is never applied twice.
        return scrape_url_jina(
            target, "", timeout=call_timeout, **policy["jina"],
        )

    def _scrape_keyed(key: str) -> dict:
        call_timeout = ctx.remaining_timeout()
        if call_timeout <= 0:
            return {"url": target, "error": "scrape deadline exceeded"}
        return scrape_url_jina(
            target, key, timeout=call_timeout,
            skip_anonymous=True, **policy["jina"],
        )

    keyed_pool = lambda: _scrape_with_key_candidates(  # noqa: E731
        "jina", candidates, _scrape_keyed,
        deadline=ctx.deadline, key_manager=ctx.key_manager,
    )

    # No keys configured: anonymous channel is the only option.
    if not candidates:
        return _scrape_anonymous()

    # With keys present, "white-label first" stays the default to conserve paid
    # quota; ``jina_prefer_keyed`` flips to keyed-first for users who want to
    # bypass the shared anonymous quota entirely.
    if ctx.jina_prefer_keyed:
        keyed = keyed_pool()
        if keyed is not None and "error" not in keyed:
            return keyed
        return keyed if keyed is not None else _scrape_anonymous()

    anon = _scrape_anonymous()
    if "error" not in anon:
        return anon
    if not _result_is_rate_limited(anon):
        return anon
    keyed = keyed_pool()
    return keyed if keyed is not None else anon


def _scrape_tavily(target: str, ctx: ScrapeContext, policy: dict) -> dict | None:
    candidates = ctx.keys_for("tavily")

    def _call_one(key: str) -> dict:
        call_timeout = ctx.remaining_timeout()
        if call_timeout <= 0:
            return {"url": target, "error": "scrape deadline exceeded"}
        options = policy["tavily"]
        if options:
            return scrape_url_tavily(
                target, key, timeout=call_timeout, deadline=ctx.deadline, **options,
            )
        return scrape_url_tavily(target, key, timeout=call_timeout, deadline=ctx.deadline)

    return _scrape_with_key_candidates(
        "tavily", candidates, _call_one,
        deadline=ctx.deadline, key_manager=ctx.key_manager,
    )


def _scrape_exa(target: str, ctx: ScrapeContext, policy: dict) -> dict | None:
    candidates = ctx.keys_for("exa")

    def _call_one(key: str) -> dict:
        call_timeout = ctx.remaining_timeout()
        if call_timeout <= 0:
            return {"url": target, "error": "scrape deadline exceeded"}
        return scrape_url_exa(
            target, key, timeout=call_timeout, max_chars=ctx.scrape_chars,
        )

    return _scrape_with_key_candidates(
        "exa", candidates, _call_one,
        deadline=ctx.deadline, key_manager=ctx.key_manager,
    )


def _scrape_firecrawl(target: str, ctx: ScrapeContext, policy: dict) -> dict | None:
    candidates = ctx.keys_for("firecrawl")

    def _call_one(key: str) -> dict:
        call_timeout = ctx.remaining_timeout()
        if call_timeout <= 0:
            return {"url": target, "error": "scrape deadline exceeded"}
        return scrape_url_firecrawl(target, key, timeout=call_timeout)

    return _scrape_with_optional_key_pool(
        "firecrawl", candidates, _call_one,
        deadline=ctx.deadline, key_manager=ctx.key_manager,
    )


_SCRAPE_DISPATCH: dict[str, Callable[[str, ScrapeContext, dict], dict | None]] = {
    "jina": _scrape_jina,
    "tavily": _scrape_tavily,
    "exa": _scrape_exa,
    "firecrawl": _scrape_firecrawl,
}


_LEGACY_OPTION_KEYS = frozenset({
    "timeout", "primary", "backends", "deadline", "site_memory", "key_manager",
    "scrape_chars", "jina_prefer_keyed", "twitter_cookies", "url_resolver",
    "jina_key", "jina_keys", "exa_key", "exa_keys", "firecrawl_key",
    "firecrawl_keys", "tavily_key", "tavily_keys", "strict_backends",
})


def _legacy_context(options: dict) -> ScrapeContext:
    """Translate the pre-context keyword arguments into a ``ScrapeContext``."""
    unknown = set(options) - _LEGACY_OPTION_KEYS
    if unknown:
        name = sorted(unknown)[0]
        raise TypeError(f"scrape_url_smart() got an unexpected keyword argument {name!r}")
    backends = options.get("backends")

    def candidates(provider: str, single: Any, many: Any) -> list[KeyCandidate]:
        return [
            _candidate_for(provider, key)
            for key in _key_candidates(str(single or ""), many)
        ]

    return ScrapeContext(
        keys_by_backend={
            "jina": candidates("jina", options.get("jina_key"), options.get("jina_keys")),
            "exa": candidates("exa", options.get("exa_key"), options.get("exa_keys")),
            "firecrawl": candidates(
                "firecrawl", options.get("firecrawl_key"), options.get("firecrawl_keys"),
            ),
            "tavily": candidates("tavily", options.get("tavily_key"), options.get("tavily_keys")),
        },
        deadline=options.get("deadline"),
        site_memory=options.get("site_memory"),
        key_manager=options.get("key_manager"),
        url_resolver=options.get("url_resolver"),
        scrape_chars=options.get("scrape_chars"),
        timeout=options.get("timeout", _DEFAULT_SCRAPE_TIMEOUT_SECONDS),
        jina_prefer_keyed=bool(options.get("jina_prefer_keyed", False)),
        twitter_cookies=options.get("twitter_cookies", ""),
        primary=options.get("primary"),
        backends=tuple(backends) if backends is not None else None,
        # A caller-forced backend list must fail eagerly on a missing key; a
        # configured fallback chain skips keyless backends at runtime instead.
        strict_backends=bool(options.get("strict_backends", backends is not None)),
    )


def scrape_url_smart(url: str, ctx: ScrapeContext | None = None, **options) -> dict:
    """Dispatch platform URLs to their scrapers; use generic backends otherwise.

    ``ctx`` carries keys, deadline, site memory, resolver and per-call options;
    omitted means the historical keyword arguments are used to build one.
    """
    if ctx is None:
        ctx = _legacy_context(options)
    elif options:
        name = sorted(options)[0]
        raise TypeError(f"scrape_url_smart() got an unexpected keyword argument {name!r}")
    return _scrape_with_context(url, ctx)


def _scrape_with_context(url: str, ctx: ScrapeContext) -> dict:
    backends = list(ctx.backends) if ctx.backends is not None else None
    if backends is not None:
        for backend in backends:
            if backend not in _BACKEND_BY_NAME:
                return normalize_scrape_result({"error": f"unknown scrape backend: {backend}"}, url=url)

    # Domain dispatch precedes generic key/backend selection, including when
    # callers pass a generic backend list for platform URLs.
    if is_reddit_url(url) or is_twitter_url(url):
        backend = "reddit" if is_reddit_url(url) else "twitter"
        try:
            if backend == "twitter":
                safe_url = validate_twitter_url(url)
            else:
                # Reddit post URLs are parsed for an id; the request itself goes
                # to fixed Reddit endpoints. The shared URL policy still runs so
                # credentials and non-public destinations are rejected.
                safe_url = validate_scrape_url(
                    url, resolver=ctx.url_resolver, deadline=ctx.deadline,
                )
        except ValueError as exc:
            return normalize_scrape_result({"error": str(exc)}, url=url, via=backend)
        started = time.monotonic()
        if backend == "twitter":
            result = scrape_url_twitter(
                safe_url, cookies=ctx.twitter_cookies, timeout=ctx.timeout,
                deadline=ctx.deadline, url_resolver=ctx.url_resolver,
            )
        else:
            result = scrape_url_reddit(
                safe_url, timeout=ctx.timeout, deadline=ctx.deadline,
                url_resolver=ctx.url_resolver,
            )
        result = normalize_scrape_result(result, url=safe_url, via=backend)
        if ctx.site_memory is not None:
            ctx.site_memory.record_attempt(ScrapeAttempt(
                url=safe_url, scraper=backend, success="error" not in result,
                content_length=len(result.get("markdown") or ""),
                error_message=result.get("error"),
                elapsed_ms=int((time.monotonic() - started) * 1000),
            ))
        return result

    # When a caller forces an explicit backend list, surface configuration
    # mistakes eagerly instead of letting them collapse into the generic
    # "no scrape backend available" at the end.
    if backends is not None and ctx.strict_backends:
        for backend in backends:
            spec = _BACKEND_BY_NAME[backend]
            if spec.key_required and not ctx.keys_for(backend):
                return normalize_scrape_result(
                    {"error": f"missing key for backend: {backend}"}, url=url, via=backend,
                )

    try:
        # Generic backends delegate the fetch to a third-party service, which
        # resolves the URL from its own network. Only literal local
        # destinations are meaningful here; see _validate_delegated_url.
        safe_url, scrape_target = _prepare_scrape_target(
            url, resolver=ctx.url_resolver, deadline=ctx.deadline,
        )
    except UrlSecurityError as exc:
        return normalize_scrape_result({"error": str(exc)}, url=url)

    policy = _resolve_scrape_policy(safe_url, backends)

    enabled = list(policy["backends"])
    # Honor an explicit per-URL ``primary`` for load spreading: lift it to the
    # front before site memory reorders. When omitted, a caller-supplied backend
    # order remains authoritative.
    if ctx.primary in enabled:
        enabled = [ctx.primary] + [backend for backend in enabled if backend != ctx.primary]
    if ctx.site_memory is not None:
        enabled = ctx.site_memory.reorder_backends(url, enabled)
    order = list(enabled)
    last: dict | None = None
    for backend in order:
        if ctx.deadline is not None and time.monotonic() >= ctx.deadline:
            break
        started = time.monotonic()
        dispatch = _SCRAPE_DISPATCH.get(backend)
        if dispatch is None:
            continue
        result = dispatch(scrape_target, ctx, policy)
        if result is None:
            continue
        result = normalize_scrape_result(result, url=safe_url, via=backend)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        last = result
        blocked = policy["blocked"]
        if blocked and blocked(result.get("markdown") or ""):
            last = normalize_scrape_result({
                "error": f"{backend}: {policy['name'].title()} blocked content fetch",
            }, url=safe_url, via=backend)
            if ctx.site_memory is not None:
                ctx.site_memory.record_attempt(ScrapeAttempt(
                    url=safe_url,
                    scraper=backend,
                    success=False,
                    content_length=0,
                    error_type="blocked",
                    error_message=last["error"],
                    elapsed_ms=elapsed_ms,
                ))
            continue
        if "error" not in result:
            result["url"] = safe_url
            if ctx.site_memory is not None:
                ctx.site_memory.record_attempt(ScrapeAttempt(
                    url=safe_url,
                    scraper=backend,
                    success=True,
                    content_length=len(result.get("markdown") or ""),
                    elapsed_ms=elapsed_ms,
                ))
            return result
        if ctx.site_memory is not None:
            ctx.site_memory.record_attempt(ScrapeAttempt(
                url=safe_url,
                scraper=backend,
                success=False,
                content_length=len(result.get("markdown") or ""),
                error_message=str(result.get("error") or ""),
                elapsed_ms=elapsed_ms,
            ))
    return last or normalize_scrape_result({"error": "no scrape backend available"}, url=safe_url)

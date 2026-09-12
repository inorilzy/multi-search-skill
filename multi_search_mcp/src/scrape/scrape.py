"""URL scraping with Reddit domain dispatch and generic page backends."""
import time

from ..support.auth import is_key_retryable_error
from ..support.models import normalize_scrape_result
from ..support.url_security import (
    UrlSecurityError,
    validate_scrape_url,
)
from ..state.key_state import KeyCandidate, key_fingerprint, key_id_for
from .scrapers import _DEFAULT_SCRAPE_TIMEOUT_SECONDS
from .scrapers.exa import scrape_url_exa
from .scrapers.firecrawl import scrape_url_firecrawl
from .scrapers.jina import (
    _jina_anonymous_cooling_down,
    _record_jina_anonymous_rate_limit,
    _reset_jina_anonymous_rate_limit,
    scrape_url_jina,
)
from .scrapers.tavily import scrape_url_tavily
from .scrapers.reddit import is_reddit_url, scrape_url_reddit
from .url_classify import is_zhihu_blocked_text, is_zhihu_url
from ..state.site_memory import ScrapeAttempt


# Selectable generic backends. Reddit is selected exclusively by URL domain.
KNOWN_BACKENDS = ("jina", "exa", "tavily", "firecrawl")
# Keyed backends whose only requirement to run is a configured key. Used to
# distinguish "no key configured" from "backend unknown" when a caller forces
# a specific backend list.
KEYED_BACKENDS = ("exa", "tavily")


DEFAULT_SCRAPE_POLICY = {
    "name": "default",
    "backends": ("jina", "exa", "tavily", "firecrawl"),
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
            # fallbacks are still
            # appended so URL-specific behavior is not silently dropped.
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


def _is_key_retryable_error(result: dict) -> bool:
    return is_key_retryable_error(result)


def _candidate_for(provider: str, key: str) -> KeyCandidate:
    return KeyCandidate(key=key, key_id=key_id_for(provider, key), fingerprint=key_fingerprint(key))


def _record_key_result(provider: str, key: str, result: dict, key_manager) -> None:
    if key_manager is None:
        return
    candidate = _candidate_for(provider, key)
    key_manager.record_result(provider, candidate, key_manager.classify_result(provider, result))


def _scrape_with_key_pool(provider: str, keys: list[str], call, deadline: float | None = None, key_manager=None) -> dict | None:
    last: dict | None = None
    for key in keys:
        if deadline is not None and time.monotonic() >= deadline:
            break
        if key_manager is not None:
            key_manager.record_use(provider, _candidate_for(provider, key))
        result = call(key)
        _record_key_result(provider, key, result, key_manager)
        last = result
        if "error" not in result:
            return result
        if not _is_key_retryable_error(result):
            return result
    return last


def _scrape_with_optional_key_pool(provider: str, keys: list[str], call, deadline: float | None = None, key_manager=None) -> dict | None:
    if keys:
        return _scrape_with_key_pool(provider, keys, call, deadline=deadline, key_manager=key_manager)
    if deadline is not None and time.monotonic() >= deadline:
        return None
    return call("")


def _prepare_scrape_target(url: str, *, resolver=None) -> tuple[str, str]:
    safe_url = validate_scrape_url(url, resolver=resolver)
    return safe_url, safe_url


def scrape_url_smart(url: str, firecrawl_key: str | None = None,
                     timeout: int = _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
                     exa_key: str = "", tavily_key: str = "",
                     primary: str | None = None,
                     *,
                     backends: list[str] | tuple[str, ...] | None = None,
                     jina_key: str = "",
                     jina_keys: list[str] | tuple[str, ...] | None = None,
                     exa_keys: list[str] | tuple[str, ...] | None = None,
                     firecrawl_keys: list[str] | tuple[str, ...] | None = None,
                     tavily_keys: list[str] | tuple[str, ...] | None = None,
                     deadline: float | None = None,
                     site_memory=None,
                     key_manager=None,
                     scrape_chars: int | None = None,
                     jina_prefer_keyed: bool = False,
                     url_resolver=None) -> dict:
    """Dispatch Reddit URLs to eddrit; otherwise use the generic backend order."""

    def _remaining_timeout() -> float:
        if deadline is None:
            return float(timeout)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 0.0
        return min(float(timeout), max(0.1, remaining))

    if backends is not None:
        for backend in backends:
            if backend not in KNOWN_BACKENDS:
                return normalize_scrape_result({"error": f"unknown scrape backend: {backend}"}, url=url)

    # Domain dispatch precedes generic key/backend selection, including when
    # callers pass a generic backend list for Reddit URLs.
    if is_reddit_url(url):
        try:
            safe_url = validate_scrape_url(url, resolver=url_resolver)
        except UrlSecurityError as exc:
            return normalize_scrape_result({"error": str(exc)}, url=url, via="reddit")
        started = time.monotonic()
        result = scrape_url_reddit(safe_url, timeout=timeout, deadline=deadline, url_resolver=url_resolver)
        result = normalize_scrape_result(result, url=safe_url, via="reddit")
        if site_memory is not None:
            site_memory.record_attempt(ScrapeAttempt(
                url=safe_url, scraper="reddit", success="error" not in result,
                content_length=len(result.get("markdown") or ""),
                error_message=result.get("error"),
                elapsed_ms=int((time.monotonic() - started) * 1000),
            ))
        return result

    # When a caller forces an explicit backend list, surface configuration
    # mistakes eagerly instead of letting them collapse into the generic
    # "no scrape backend available" at the end.
    if backends is not None:
        key_pool_for = {
            "exa": _key_candidates(exa_key, exa_keys),
            "tavily": _key_candidates(tavily_key, tavily_keys),
            "firecrawl": _key_candidates(firecrawl_key or "", firecrawl_keys),
        }
        for backend in backends:
            if backend in KEYED_BACKENDS and not key_pool_for[backend]:
                return normalize_scrape_result({"error": f"missing key for backend: {backend}"}, url=url, via=backend)

    try:
        safe_url, scrape_target = _prepare_scrape_target(url, resolver=url_resolver)
    except UrlSecurityError as exc:
        return normalize_scrape_result({"error": str(exc)}, url=url)

    policy = _resolve_scrape_policy(safe_url, backends)

    def _call(backend: str) -> dict | None:
        call_timeout = _remaining_timeout()
        if call_timeout <= 0:
            return {"url": scrape_target, "error": "scrape deadline exceeded"}
        if backend == "jina":
            key_pool = list(jina_keys or ([] if not jina_key else [jina_key]))

            def _scrape_anonymous() -> dict:
                if _jina_anonymous_cooling_down():
                    return {
                        "url": scrape_target,
                        "error": "Jina: anonymous rate limit cooldown active",
                        "rate_limited": True,
                    }
                result = scrape_url_jina(scrape_target, "", timeout=_remaining_timeout(), **policy["jina"])
                if "error" in result and result.get("rate_limited"):
                    _record_jina_anonymous_rate_limit()
                return result

            def _scrape_keyed(key: str) -> dict:
                return scrape_url_jina(
                    scrape_target,
                    key,
                    timeout=_remaining_timeout(),
                    skip_anonymous=True,
                    **policy["jina"],
                )

            keyed_pool = lambda: _scrape_with_key_pool(  # noqa: E731
                "jina", key_pool, _scrape_keyed, deadline=deadline, key_manager=key_manager,
            )

            # No keys configured: anonymous channel is the only option.
            if not key_pool:
                return _scrape_anonymous()

            # With keys present, "white-label first" stays the default to conserve
            # paid quota; ``jina_prefer_keyed`` flips to keyed-first for users who
            # want to bypass the shared anonymous quota entirely.
            if jina_prefer_keyed:
                keyed = keyed_pool()
                if keyed is not None and "error" not in keyed:
                    return keyed
                return keyed if keyed is not None else _scrape_anonymous()

            anon = _scrape_anonymous()
            if "error" not in anon:
                return anon
            if not anon.get("rate_limited"):
                return anon
            keyed = keyed_pool()
            return keyed if keyed is not None else anon
        if backend == "tavily":
            candidates = _key_candidates(tavily_key, tavily_keys)
            def _scrape_tavily(key: str) -> dict:
                tavily_options = policy["tavily"]
                if tavily_options:
                    return scrape_url_tavily(
                        scrape_target,
                        key,
                        timeout=_remaining_timeout(),
                        deadline=deadline,
                        **tavily_options,
                    )
                return scrape_url_tavily(scrape_target, key, timeout=_remaining_timeout(), deadline=deadline)
            return _scrape_with_key_pool(
                "tavily",
                candidates,
                _scrape_tavily,
                deadline=deadline,
                key_manager=key_manager,
            )
        if backend == "exa":
            candidates = _key_candidates(exa_key, exa_keys)
            return _scrape_with_key_pool(
                "exa",
                candidates,
                lambda key: scrape_url_exa(scrape_target, key, timeout=_remaining_timeout(), max_chars=scrape_chars),
                deadline=deadline,
                key_manager=key_manager,
            )
        if backend == "firecrawl":
            candidates = _key_candidates(firecrawl_key or "", firecrawl_keys)
            return _scrape_with_optional_key_pool(
                "firecrawl",
                candidates,
                lambda key: scrape_url_firecrawl(scrape_target, key, timeout=_remaining_timeout()),
                deadline=deadline,
                key_manager=key_manager,
            )
        return None

    enabled = list(policy["backends"])
    # Honor an explicit per-URL ``primary`` for load spreading: lift it to the
    # front before site memory reorders. When omitted, a caller-supplied backend
    # order remains authoritative. With ``use_state=True`` (the default)
    # ``site_memory`` is non-None, so previously the primary was dropped and
    # every URL collapsed onto ``enabled[0]``. Site memory still wins for pinned
    # or learned backends because its ranking outranks the input order, only
    # using this order as the tie-breaker for cold sites.
    if primary in enabled:
        enabled = [primary] + [backend for backend in enabled if backend != primary]
    if site_memory is not None:
        enabled = site_memory.reorder_backends(url, enabled)
    order = list(enabled)
    last: dict | None = None
    for backend in order:
        if deadline is not None and time.monotonic() >= deadline:
            break
        started = time.monotonic()
        result = _call(backend)
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
            if site_memory is not None:
                site_memory.record_attempt(ScrapeAttempt(
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
            if site_memory is not None:
                site_memory.record_attempt(ScrapeAttempt(
                    url=safe_url,
                    scraper=backend,
                    success=True,
                    content_length=len(result.get("markdown") or ""),
                    elapsed_ms=elapsed_ms,
                ))
            return result
        if site_memory is not None:
            site_memory.record_attempt(ScrapeAttempt(
                url=safe_url,
                scraper=backend,
                success=False,
                content_length=len(result.get("markdown") or ""),
                error_message=str(result.get("error") or ""),
                elapsed_ms=elapsed_ms,
            ))
    return last or normalize_scrape_result({"error": "no scrape backend available"}, url=safe_url)

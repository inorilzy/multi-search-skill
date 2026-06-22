"""URL scraping orchestration via Jina / Exa / Tavily / Firecrawl."""
import time

from ..support.auth import is_key_retryable_error
from ..state.keys import (
    get_active_jina_keys,
    mark_jina_exhausted_persistent,
    mark_jina_exhausted_runtime,
)
from .scrapers import (
    _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
    _GH_REPO_RE,
    _rewrite_for_clean_scrape,
)
from .scrapers.exa import scrape_url_exa
from .scrapers.firecrawl import scrape_url_firecrawl
from .scrapers.jina import (
    _jina_anonymous_cooling_down,
    _record_jina_anonymous_rate_limit,
    _reset_jina_anonymous_rate_limit,
    scrape_url_jina,
)
from .scrapers.reddit import (
    is_old_reddit_url,
    is_reddit_blocked_text,
    is_reddit_url,
    scrape_url_reddit,
)
from .scrapers.tavily import scrape_url_tavily
from .scrapers.zhihu import is_zhihu_blocked_text, is_zhihu_url
from ..state.site_memory import ScrapeAttempt


DEFAULT_SCRAPE_POLICY = {
    "name": "default",
    "backends": ("jina", "exa", "tavily", "firecrawl"),
    "jina": {},
    "tavily": {},
    "blocked": None,
}

SCRAPE_POLICIES = (
    {
        "name": "old-reddit",
        "match": is_old_reddit_url,
        "backends": ("tavily", "jina", "exa", "firecrawl", "reddit"),
        "blocked": is_reddit_blocked_text,
    },
    {
        "name": "reddit",
        "match": is_reddit_url,
        "backends": ("jina", "tavily", "exa", "firecrawl", "reddit"),
        "blocked": is_reddit_blocked_text,
    },
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
            enabled = list(candidate["backends"])
        else:
            for backend in reversed(candidate.get("prepend_backends", ())):
                if backend not in enabled:
                    enabled.insert(0, backend)
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


def _scrape_with_key_pool(keys: list[str], call, deadline: float | None = None) -> dict | None:
    last: dict | None = None
    for key in keys:
        if deadline is not None and time.monotonic() >= deadline:
            break
        result = call(key)
        last = result
        if "error" not in result:
            return result
        if not _is_key_retryable_error(result):
            return result
    return last


def scrape_url_smart(url: str, firecrawl_key: str | None = None,
                     timeout: int = _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
                     exa_key: str = "", tavily_key: str = "",
                     primary: str = "jina",
                     *,
                     backends: list[str] | tuple[str, ...] | None = None,
                     jina_key: str = "",
                     jina_keys: list[str] | tuple[str, ...] | None = None,
                     exa_keys: list[str] | tuple[str, ...] | None = None,
                     firecrawl_keys: list[str] | tuple[str, ...] | None = None,
                     tavily_keys: list[str] | tuple[str, ...] | None = None,
                     deadline: float | None = None,
                     site_memory=None) -> dict:
    """Scrape `url` starting with `primary` backend, falling back through the others."""

    def _remaining_timeout() -> float:
        if deadline is None:
            return float(timeout)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 0.0
        return min(float(timeout), max(0.1, remaining))

    policy = _resolve_scrape_policy(url, backends)

    def _call(backend: str) -> dict | None:
        scrape_url = _rewrite_for_clean_scrape(url)
        call_timeout = _remaining_timeout()
        if call_timeout <= 0:
            return {"url": scrape_url, "error": "scrape deadline exceeded"}
        if backend == "jina":
            key_pool = list(jina_keys or ([] if not jina_key else [jina_key]))
            if not key_pool:
                if _jina_anonymous_cooling_down():
                    return {
                        "url": scrape_url,
                        "error": "Jina: anonymous rate limit cooldown active",
                        "rate_limited": True,
                    }
                return scrape_url_jina(scrape_url, "", timeout=call_timeout, **policy["jina"])

            if _jina_anonymous_cooling_down():
                result = {
                    "url": scrape_url,
                    "error": "Jina: anonymous rate limit cooldown active",
                    "rate_limited": True,
                }
            else:
                result = scrape_url_jina(scrape_url, "", timeout=call_timeout, **policy["jina"])
                if "error" not in result:
                    return result
                if result.get("rate_limited"):
                    _record_jina_anonymous_rate_limit()
                if not result.get("rate_limited"):
                    return result

            last = result
            for key in key_pool:
                key_timeout = _remaining_timeout()
                if key_timeout <= 0:
                    break
                if not get_active_jina_keys([key]):
                    continue
                keyed = scrape_url_jina(
                    scrape_url,
                    key,
                    timeout=key_timeout,
                    skip_anonymous=True,
                    **policy["jina"],
                )
                last = keyed
                if "error" not in keyed:
                    return keyed
                if keyed.get("key_exhausted") or keyed.get("exhausted"):
                    mark_jina_exhausted_runtime(key)
                    mark_jina_exhausted_persistent(key)
                    continue
                if keyed.get("rate_limited"):
                    continue
                return keyed
            return last
        if backend == "reddit":
            return scrape_url_reddit(scrape_url, timeout=call_timeout)
        if backend == "tavily":
            candidates = _key_candidates(tavily_key, tavily_keys)
            def _scrape_tavily(key: str) -> dict:
                tavily_options = policy["tavily"]
                if tavily_options:
                    return scrape_url_tavily(
                        scrape_url,
                        key,
                        timeout=_remaining_timeout(),
                        **tavily_options,
                    )
                return scrape_url_tavily(scrape_url, key, timeout=_remaining_timeout())
            return _scrape_with_key_pool(
                candidates,
                _scrape_tavily,
                deadline=deadline,
            )
        if backend == "exa":
            candidates = _key_candidates(exa_key, exa_keys)
            return _scrape_with_key_pool(
                candidates,
                lambda key: scrape_url_exa(scrape_url, key, timeout=_remaining_timeout()),
                deadline=deadline,
            )
        if backend == "firecrawl":
            candidates = _key_candidates(firecrawl_key or "", firecrawl_keys)
            return _scrape_with_key_pool(
                candidates,
                lambda key: scrape_url_firecrawl(scrape_url, key, timeout=_remaining_timeout()),
                deadline=deadline,
            )
        return None

    enabled = list(policy["backends"])
    if site_memory is not None:
        enabled = site_memory.reorder_backends(url, enabled)
    order = []
    if primary in enabled and primary not in order:
        order.append(primary)
    order += [backend for backend in enabled if backend not in order]
    last: dict | None = None
    for backend in order:
        if deadline is not None and time.monotonic() >= deadline:
            break
        started = time.monotonic()
        result = _call(backend)
        if result is None:
            continue
        elapsed_ms = int((time.monotonic() - started) * 1000)
        last = result
        blocked = policy["blocked"]
        if blocked and blocked(result.get("markdown") or ""):
            last = {
                "url": url,
                "error": f"{backend}: {policy['name'].title()} blocked content fetch",
            }
            if site_memory is not None:
                site_memory.record_attempt(ScrapeAttempt(
                    url=url,
                    scraper=backend,
                    success=False,
                    content_length=0,
                    error_type="blocked",
                    error_message=last["error"],
                    elapsed_ms=elapsed_ms,
                ))
            continue
        if "error" not in result:
            result["url"] = url
            if site_memory is not None:
                site_memory.record_attempt(ScrapeAttempt(
                    url=url,
                    scraper=backend,
                    success=True,
                    content_length=len(result.get("markdown") or ""),
                    elapsed_ms=elapsed_ms,
                ))
            return result
        if site_memory is not None:
            site_memory.record_attempt(ScrapeAttempt(
                url=url,
                scraper=backend,
                success=False,
                content_length=len(result.get("markdown") or ""),
                error_message=str(result.get("error") or ""),
                elapsed_ms=elapsed_ms,
            ))
    return last or {"url": url, "error": "no scrape backend available"}

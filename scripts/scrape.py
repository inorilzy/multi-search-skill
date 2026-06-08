"""URL scraping via Jina / Exa / Tavily.

GitHub repo root URLs are rewritten to raw README to avoid nav/chrome noise.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .http import urlopen_retry
from .keys import (
    get_active_jina_keys,
    mark_jina_exhausted_persistent,
    mark_jina_exhausted_runtime,
)
from .secrets import scrub_secrets


_GH_REPO_RE = re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s#?]+)/?$")
_JINA_KEY_INFO_URL = "https://dash.jina.ai/api/v1/api_key/fe_user"
_JINA_ANON_COOLDOWN_SECONDS = 60.0
_JINA_ANON_RATE_LIMITED_UNTIL = 0.0
_JINA_ANON_LOCK = threading.Lock()
_KEY_RETRY_PATTERNS = (
    "401", "403", "429", "unauthorized", "forbidden", "invalid api",
    "invalid key", "api key", "quota", "rate limit", "rate_limit",
    "too many requests", "limit exceeded", "exceeded your", "credits",
    "billing", "payment", "insufficient",
)


def _safe_http_url(url: str) -> str | None:
    """Reject non-http(s) URLs (javascript:, file:, gopher:, ...) before we hand
    them to a fetcher. Returns the URL unchanged if safe, else None."""
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return url


def _rewrite_for_clean_scrape(url: str) -> str:
    """Rewrite GitHub repo root URLs to raw README to avoid nav/chrome noise."""
    m = _GH_REPO_RE.match(url)
    if m:
        owner, repo = m.group(1), m.group(2).removesuffix(".git")
        return f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
    return url


def _key_candidates(single_key: str = "", keys: list[str] | tuple[str, ...] | None = None) -> list[str]:
    if keys is not None:
        return [str(k) for k in keys if k]
    return [single_key] if single_key else []


def _is_key_retryable_error(result: dict) -> bool:
    if "error" not in result:
        return False
    msg = str(result.get("error", "")).lower()
    return any(pattern in msg for pattern in _KEY_RETRY_PATTERNS)


def _jina_anonymous_cooling_down(now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    with _JINA_ANON_LOCK:
        return current < _JINA_ANON_RATE_LIMITED_UNTIL


def _record_jina_anonymous_rate_limit(now: float | None = None) -> None:
    global _JINA_ANON_RATE_LIMITED_UNTIL
    current = time.monotonic() if now is None else now
    with _JINA_ANON_LOCK:
        _JINA_ANON_RATE_LIMITED_UNTIL = max(
            _JINA_ANON_RATE_LIMITED_UNTIL,
            current + _JINA_ANON_COOLDOWN_SECONDS,
        )


def _reset_jina_anonymous_rate_limit() -> None:
    global _JINA_ANON_RATE_LIMITED_UNTIL
    with _JINA_ANON_LOCK:
        _JINA_ANON_RATE_LIMITED_UNTIL = 0.0


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


def scrape_url_exa(url: str, api_key: str, timeout: int = 25) -> dict:
    """Fetch page content via Exa /contents API. Returns full text."""
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}
    payload = json.dumps({
        "urls": [url],
        "text": {"maxCharacters": 8000},
    }).encode()
    req = urllib.request.Request(
        "https://api.exa.ai/contents",
        data=payload,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        statuses = data.get("statuses") or []
        if statuses and statuses[0].get("status") != "success":
            status = statuses[0].get("status", "unknown")
            error = statuses[0].get("error") or {}
            detail = ""
            if isinstance(error, dict):
                detail = error.get("tag") or error.get("message") or ""
                if error.get("httpStatusCode"):
                    detail = f"{detail} ({error['httpStatusCode']})" if detail else str(error["httpStatusCode"])
            elif error:
                detail = str(error)
            msg = f"Exa status: {status}" + (f": {detail}" if detail else "")
            return {"url": url, "error": scrub_secrets(msg, api_key)}
        results = data.get("results") or []
        if not results:
            return {"url": url, "error": "Exa: no results returned"}
        r = results[0]
        text = r.get("text") or ""
        if not text.strip():
            return {"url": url, "error": "Exa: empty content"}
        markdown = text
        return {
            "url": url,
            "title": r.get("title") or url,
            "markdown": markdown,
            "length": len(markdown),
            "via": "exa",
        }
    except Exception as e:
        return {"url": url, "error": f"Exa: {scrub_secrets(e, api_key)}"}


def scrape_url_tavily(url: str, api_key: str, timeout: int = 25) -> dict:
    """Fetch page content via Tavily /extract API."""
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}
    payload = json.dumps({
        "urls": [url],
        "extract_depth": "basic",
        "format": "markdown",
    }).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/extract",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        results = data.get("results") or []
        if not results:
            failed = data.get("failed_results") or []
            msg = failed[0].get("error", "no content") if failed else "no results"
            return {"url": url, "error": f"Tavily: {scrub_secrets(msg, api_key)}"}
        r = results[0]
        md = r.get("raw_content") or ""
        if not md:
            return {"url": url, "error": "Tavily: empty content"}
        return {
            "url": url,
            "title": url,
            "markdown": md,
            "length": len(md),
            "via": "tavily",
        }
    except Exception as e:
        return {"url": url, "error": f"Tavily: {scrub_secrets(e, api_key)}"}


def _jina_request(url: str, api_key: str = "") -> urllib.request.Request:
    headers = {
        "Accept": "application/json",
        "X-Respond-With": "markdown",
        "User-Agent": "Mozilla/5.0 multi-search/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    reader_url = "https://r.jina.ai/" + urllib.parse.quote(url, safe="")
    return urllib.request.Request(reader_url, headers=headers)


def _jina_rate_limited(status_code: int | None, message: str) -> bool:
    text = message.lower()
    return (
        status_code in (402, 429)
        or "rate limit" in text
        or "rate-limit" in text
        or "quota" in text
        or "too many requests" in text
        or "rpm" in text
        or "insufficient balance" in text
        or "insufficient_balance" in text
        or "credits" in text
        or "payment required" in text
    )


def _jina_key_total_balance(api_key: str, timeout: int = 10) -> float | None:
    if not api_key:
        return None
    url = _JINA_KEY_INFO_URL + "?" + urllib.parse.urlencode({"api_key": api_key})
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 multi-search/1.0",
        },
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    wallet = data.get("wallet")
    if not isinstance(wallet, dict) and isinstance(data.get("data"), dict):
        wallet = data["data"].get("wallet")
    if not isinstance(wallet, dict):
        return None
    balance = wallet.get("total_balance")
    if isinstance(balance, bool):
        return None
    if isinstance(balance, (int, float)):
        return float(balance)
    if isinstance(balance, str):
        try:
            return float(balance.strip())
        except ValueError:
            return None
    return None


def _jina_key_balance_exhausted(api_key: str, timeout: int = 10) -> bool:
    balance = _jina_key_total_balance(api_key, timeout=timeout)
    return balance is not None and balance <= 0


def _jina_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", "replace")
    except Exception:
        body = ""
    if body:
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                return data.get("message") or data.get("detail") or body
        except Exception:
            pass
        return body
    return str(exc)


def scrape_url_jina(
    url: str,
    api_key: str = "",
    timeout: int = 25,
    skip_anonymous: bool = False,
) -> dict:
    """Fetch page content via Jina Reader.

    Jina is tried anonymously first. If the anonymous request is rate-limited
    and a key is configured, retry once with Bearer auth. Set
    ``skip_anonymous`` when a caller is already rotating a key pool.
    """
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}

    secrets = api_key
    last_error = ""
    rate_limited = False
    key_exhausted = False
    if skip_anonymous:
        attempts = (api_key,) if api_key else ()
    else:
        attempts = ("", api_key) if api_key else ("",)
    for key in attempts:
        try:
            with urlopen_retry(_jina_request(url, key), timeout=timeout) as resp:
                data = json.loads(resp.read())
            page = data.get("data") if isinstance(data, dict) else data
            if not isinstance(page, dict):
                return {"url": url, "error": "Jina: invalid response"}
            markdown = page.get("content") or page.get("text") or ""
            if not markdown:
                msg = page.get("warning") or data.get("message") or "empty content"
                return {"url": url, "error": f"Jina: {scrub_secrets(msg, secrets)}"}
            return {
                "url": url,
                "title": page.get("title") or url,
                "markdown": markdown,
                "length": len(markdown),
                "via": "jina",
            }
        except urllib.error.HTTPError as e:
            msg = _jina_error_message(e)
            last_error = f"HTTP {e.code}: {msg}"
            limited = _jina_rate_limited(e.code, msg)
            if limited:
                rate_limited = True
                if not key:
                    _record_jina_anonymous_rate_limit()
                if key and _jina_key_balance_exhausted(key, timeout=min(timeout, 10)):
                    key_exhausted = True
            try:
                e.close()
            except Exception:
                pass
            if key or not api_key or not limited:
                break
        except Exception as e:
            last_error = str(e)
            break
    if not attempts:
        last_error = "no Jina key available"
    result = {"url": url, "error": f"Jina: {scrub_secrets(last_error, secrets)}"}
    if rate_limited:
        result["rate_limited"] = True
    if key_exhausted:
        result["key_exhausted"] = True
        result["exhausted"] = True
    return result


def scrape_url_smart(url: str, firecrawl_key: str | None = None,
                     timeout: int = 25,
                     exa_key: str = "", tavily_key: str = "",
                     primary: str = "jina",
                     *,
                     backends: list[str] | tuple[str, ...] | None = None,
                     jina_key: str = "",
                     jina_keys: list[str] | tuple[str, ...] | None = None,
                     exa_keys: list[str] | tuple[str, ...] | None = None,
                     tavily_keys: list[str] | tuple[str, ...] | None = None,
                     deadline: float | None = None) -> dict:
    """Scrape `url` starting with `primary` backend, falling back through the others.

    By default this uses Jina + Exa + Tavily.

    ``firecrawl_key`` is kept as the old positional slot for callers that used
    ``scrape_url_smart(url, firecrawl_key, timeout, exa_key, tavily_key, primary)``.
    Firecrawl scraping is no longer a backend.
    """
    def _remaining_timeout() -> float:
        if deadline is None:
            return float(timeout)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 0.0
        return min(float(timeout), max(0.1, remaining))

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
                return scrape_url_jina(scrape_url, "", timeout=call_timeout)

            if _jina_anonymous_cooling_down():
                result = {
                    "url": scrape_url,
                    "error": "Jina: anonymous rate limit cooldown active",
                    "rate_limited": True,
                }
            else:
                result = scrape_url_jina(scrape_url, "", timeout=call_timeout)
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
                keyed = scrape_url_jina(scrape_url, key, timeout=key_timeout, skip_anonymous=True)
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
        if backend == "tavily":
            candidates = _key_candidates(tavily_key, tavily_keys)
            return _scrape_with_key_pool(
                candidates,
                lambda key: scrape_url_tavily(scrape_url, key, timeout=_remaining_timeout()),
                deadline=deadline,
            )
        if backend == "exa":
            candidates = _key_candidates(exa_key, exa_keys)
            return _scrape_with_key_pool(
                candidates,
                lambda key: scrape_url_exa(scrape_url, key, timeout=_remaining_timeout()),
                deadline=deadline,
            )
        return None

    enabled = list(backends or ("jina", "exa", "tavily"))
    order = ([primary] if primary in enabled else []) + [b for b in enabled if b != primary]
    last: dict | None = None
    for backend in order:
        if deadline is not None and time.monotonic() >= deadline:
            break
        r = _call(backend)
        if r is None:
            continue
        last = r
        if "error" not in r:
            # Restore the original URL so output links stay canonical
            # (e.g. GitHub repo root, not raw README).
            r["url"] = url
            return r
    return last or {"url": url, "error": "no scrape backend available"}

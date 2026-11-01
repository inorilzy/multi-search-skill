"""Jina-backed URL scraping."""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ...support.http import read_error_body, read_limited, urlopen_retry
from ...support.secrets import scrub_secrets
from . import (
    _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
    _JINA_REMOVE_SELECTOR,
    _safe_http_url,
    error_fields,
)


_JINA_ANON_COOLDOWN_SECONDS = 60.0
_JINA_ANON_RATE_LIMITED_UNTIL = 0.0
_JINA_ANON_LOCK = threading.Lock()


def _jina_anonymous_cooling_down(now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    with _JINA_ANON_LOCK:
        return current < _JINA_ANON_RATE_LIMITED_UNTIL


def _record_jina_anonymous_rate_limit(now: float | None = None, seconds: float | None = None) -> None:
    """Pause anonymous reads; ``seconds`` is the server's retryAfter when given."""
    global _JINA_ANON_RATE_LIMITED_UNTIL
    current = time.monotonic() if now is None else now
    wait = _JINA_ANON_COOLDOWN_SECONDS if not seconds or seconds <= 0 else min(float(seconds), 3600.0)
    with _JINA_ANON_LOCK:
        _JINA_ANON_RATE_LIMITED_UNTIL = max(_JINA_ANON_RATE_LIMITED_UNTIL, current + wait)


def _reset_jina_anonymous_rate_limit() -> None:
    global _JINA_ANON_RATE_LIMITED_UNTIL
    with _JINA_ANON_LOCK:
        _JINA_ANON_RATE_LIMITED_UNTIL = 0.0


# Public names for the handful of callers that should not reach into the
# module's private surface; the private names stay the patchable seam.
jina_anonymous_cooling_down = _jina_anonymous_cooling_down
record_jina_anonymous_rate_limit = _record_jina_anonymous_rate_limit
reset_jina_anonymous_rate_limit = _reset_jina_anonymous_rate_limit


def _jina_request(
    url: str,
    api_key: str = "",
    timeout: int | float = _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
    respond_with: str = "markdown",
    extra_headers: dict | None = None,
) -> urllib.request.Request:
    headers = {
        "Accept": "application/json",
        "X-Respond-With": respond_with,
        "X-Timeout": str(int(max(1.0, min(float(timeout), 180.0)))),
        "X-Remove-Selector": _JINA_REMOVE_SELECTOR,
        "X-Retain-Images": "none",
        "X-Retain-Media": "none",
        "User-Agent": "Mozilla/5.0 multi-search/1.0",
    }
    if extra_headers:
        headers.update(extra_headers)
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


# docs/jina/openapi.json: 402 is TierFeatureConstraintError (status 40202, a
# feature the key's tier lacks) or InsufficientBalanceError (40203). Only the
# latter means the key is out of balance.
_JINA_TIER_FEATURE_STATUS = 40202
_JINA_BALANCE_STATUS = 40203


def _jina_quota_exhausted(status_code: int | None, message: str, app_status: int | None = None) -> bool:
    """True when the error indicates the *key* is out of quota/balance."""
    if app_status == _JINA_TIER_FEATURE_STATUS:
        return False
    if app_status == _JINA_BALANCE_STATUS:
        return True
    text = message.lower()
    return (
        status_code == 402
        or "insufficient balance" in text
        or "insufficient_balance" in text
        or "payment required" in text
        or "credits" in text
        or "quota" in text
    )


def _jina_error_payload(exc: urllib.error.HTTPError) -> tuple[str, dict]:
    """``(message, parsed body)`` for a Jina HTTP error."""
    try:
        body = read_error_body(exc).decode("utf-8", "replace")
    except Exception:
        body = ""
    if body:
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                return str(data.get("message") or data.get("detail") or body), data
        except Exception:
            pass
        return body, {}
    return str(exc), {}


def _jina_error_message(exc: urllib.error.HTTPError) -> str:
    return _jina_error_payload(exc)[0]


def scrape_url_jina(
    url: str,
    api_key: str = "",
    timeout: int = _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
    skip_anonymous: bool = False,
    respond_with: str = "markdown",
    extra_headers: dict | None = None,
    deadline: float | None = None,
) -> dict:
    """Fetch page content via Jina Reader."""
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}

    if deadline is not None:
        timeout = min(float(timeout), max(0.0, deadline - time.monotonic()))
    secrets = api_key
    last_error = ""
    rate_limited = False
    key_exhausted = False
    # ``kind`` is the upstream credential signal; quota_exhausted is reserved for
    # the keyed channel and outranks a generic rate_limit.
    kind = ""
    if skip_anonymous:
        attempts = (api_key,) if api_key else ()
    else:
        attempts = ("", api_key) if api_key else ("",)
    for key in attempts:
        try:
            with urlopen_retry(
                _jina_request(
                    url,
                    key,
                    timeout=timeout,
                    respond_with=respond_with,
                    extra_headers=extra_headers,
                ),
                timeout=timeout,
            ) as resp:
                data = json.loads(read_limited(resp))
            page = data.get("data") if isinstance(data, dict) else data
            if not isinstance(page, dict):
                return {"url": url, "error": "Jina: invalid response"}
            markdown = page.get("content") or page.get("text") or ""
            if not markdown:
                message = page.get("warning") or data.get("message") or "empty content"
                return {"url": url, "error": f"Jina: {scrub_secrets(message, secrets)}"}
            if (
                (page.get("title") or "").strip().casefold() == "just a moment..."
                and "## performing security verification" in markdown.casefold()
                and "this website uses a security service to protect against malicious bots." in markdown.casefold()
            ):
                return {"url": url, "error": "Jina: blocked by website security verification"}
            return {
                "url": url,
                "title": page.get("title") or url,
                "markdown": markdown,
                "length": len(markdown),
                "via": "jina",
            }
        except urllib.error.HTTPError as exc:
            message, body = _jina_error_payload(exc)
            app_status = body.get("status") if isinstance(body.get("status"), int) else None
            last_error = f"HTTP {exc.code}: {message}"
            if exc.code == 402 and app_status == _JINA_TIER_FEATURE_STATUS:
                # A tier/feature restriction: the key is fine, do not rotate it out.
                kind = "provider"
                try:
                    exc.close()
                except Exception:
                    pass
                break
            limited = _jina_rate_limited(exc.code, message)
            if limited:
                rate_limited = True
                if not key:
                    retry_after = body.get("retryAfter")
                    _record_jina_anonymous_rate_limit(
                        seconds=float(retry_after) if isinstance(retry_after, (int, float)) else None,
                    )
                    kind = kind or "rate_limit"
                # Classify exhaustion from the error itself instead of issuing a
                # blocking balance-API round-trip; the key-state store (and the
                # caller) only need to know this key is out of quota.
                elif _jina_quota_exhausted(exc.code, message, app_status):
                    key_exhausted = True
                    kind = "quota_exhausted"
                else:
                    kind = kind or "rate_limit"
            try:
                exc.close()
            except Exception:
                pass
            if key or not api_key or not limited:
                break
        except Exception as exc:
            last_error = str(exc)
            break
    if not attempts:
        last_error = "no Jina key available"
    result = {"url": url, "error": f"Jina: {scrub_secrets(last_error, secrets)}"}
    if rate_limited:
        result["rate_limited"] = True
    if key_exhausted:
        result["key_exhausted"] = True
        result["exhausted"] = True
    if kind:
        result.update(error_fields(kind=kind, origin="provider"))
    return result

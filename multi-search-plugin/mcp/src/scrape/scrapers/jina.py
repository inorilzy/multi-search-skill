"""Jina-backed URL scraping."""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ...support.http import urlopen_retry
from ...state.keys import (
    mark_jina_exhausted_persistent,
    mark_jina_exhausted_runtime,
)
from ...support.secrets import scrub_secrets
from . import (
    _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
    _JINA_KEY_INFO_URL,
    _JINA_REMOVE_SELECTOR,
    _safe_http_url,
)


_JINA_ANON_COOLDOWN_SECONDS = 60.0
_JINA_ANON_RATE_LIMITED_UNTIL = 0.0
_JINA_ANON_LOCK = threading.Lock()


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
    timeout: int = _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
    skip_anonymous: bool = False,
    respond_with: str = "markdown",
    extra_headers: dict | None = None,
) -> dict:
    """Fetch page content via Jina Reader."""
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
                data = json.loads(resp.read())
            page = data.get("data") if isinstance(data, dict) else data
            if not isinstance(page, dict):
                return {"url": url, "error": "Jina: invalid response"}
            markdown = page.get("content") or page.get("text") or ""
            if not markdown:
                message = page.get("warning") or data.get("message") or "empty content"
                return {"url": url, "error": f"Jina: {scrub_secrets(message, secrets)}"}
            return {
                "url": url,
                "title": page.get("title") or url,
                "markdown": markdown,
                "length": len(markdown),
                "via": "jina",
            }
        except urllib.error.HTTPError as exc:
            message = _jina_error_message(exc)
            last_error = f"HTTP {exc.code}: {message}"
            limited = _jina_rate_limited(exc.code, message)
            if limited:
                rate_limited = True
                if not key:
                    _record_jina_anonymous_rate_limit()
                if key and _jina_key_balance_exhausted(key, timeout=min(timeout, 10)):
                    key_exhausted = True
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
    return result

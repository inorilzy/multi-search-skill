"""Firecrawl-backed URL scraping."""
import json
import urllib.error
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets
from . import _DEFAULT_SCRAPE_TIMEOUT_SECONDS, _safe_http_url


_FIRECRAWL_ERROR_BODY_LIMIT = 4096
# Firecrawl documents SCRAPE_SSL_ERROR as a target-page certificate failure.
# Keep this set narrow: broad site/infrastructure codes do not prove that the
# provider key is healthy, but they also do not prove that the target failed.
_FIRECRAWL_TARGET_ERROR_CODES = frozenset({"SCRAPE_SSL_ERROR"})
_FIRECRAWL_HTTP_ERROR_TYPES = {
    401: "invalid",
    403: "invalid",
    402: "quota_exhausted",
    429: "rate_limit",
}


def _error_code(data: dict | None) -> str:
    code = data.get("code") if isinstance(data, dict) else None
    return code.strip().upper() if isinstance(code, str) else ""


def _error_detail(data: dict | None, fallback: str) -> str:
    if not isinstance(data, dict):
        return fallback
    detail = data.get("error") or data.get("message") or fallback
    if isinstance(detail, (dict, list)):
        return json.dumps(detail, ensure_ascii=False)
    return str(detail)


def _error_result(
    url: str,
    *,
    api_key: str,
    data: dict | None = None,
    status_code: int | None = None,
    fallback: str = "request failed",
) -> dict:
    code = _error_code(data)
    detail = _error_detail(data, fallback)
    if code:
        detail = f"{code}: {detail}"
    if status_code is not None and isinstance(data, dict):
        detail = f"HTTP {status_code}: {detail}"
    result = {"url": url, "error": f"Firecrawl: {scrub_secrets(detail, api_key)}"}
    if status_code in _FIRECRAWL_HTTP_ERROR_TYPES:
        result.update(error_origin="provider", error_type=_FIRECRAWL_HTTP_ERROR_TYPES[status_code])
    elif code in _FIRECRAWL_TARGET_ERROR_CODES:
        result.update(error_origin="target", error_type="target")
    elif status_code is not None:
        result.update(error_origin="provider", error_type="error")
    return result


def _read_http_error_payload(exc: urllib.error.HTTPError) -> dict | None:
    raw = b""
    try:
        raw = exc.read(_FIRECRAWL_ERROR_BODY_LIMIT)
    except Exception:
        return None
    finally:
        try:
            exc.close()
        except Exception:
            pass
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except (TypeError, ValueError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def scrape_url_firecrawl(url: str, api_key: str = "", timeout: int = _DEFAULT_SCRAPE_TIMEOUT_SECONDS) -> dict:
    """Fetch main page markdown via Firecrawl /v2/scrape."""
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "timeout": int(max(1.0, min(float(timeout), 60.0)) * 1000),
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v2/scrape",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        if not isinstance(data, dict):
            return {"url": url, "error": "Firecrawl: invalid response"}
        if data.get("success") is False:
            return _error_result(url, api_key=api_key, data=data)
        page = data.get("data")
        if not isinstance(page, dict):
            return {"url": url, "error": "Firecrawl: invalid response"}
        markdown = page.get("markdown") or page.get("content") or page.get("text") or ""
        if not markdown.strip():
            warning = page.get("warning") or "empty content"
            return {"url": url, "error": f"Firecrawl: {scrub_secrets(warning, api_key)}"}
        metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
        title = page.get("title") or metadata.get("title") or metadata.get("ogTitle") or url
        return {
            "url": url,
            "title": title,
            "markdown": markdown,
            "length": len(markdown),
            "via": "firecrawl",
        }
    except urllib.error.HTTPError as exc:
        data = _read_http_error_payload(exc)
        return _error_result(
            url,
            api_key=api_key,
            data=data,
            status_code=exc.code,
            fallback=str(exc),
        )
    except Exception as exc:
        return {"url": url, "error": f"Firecrawl: {scrub_secrets(exc, api_key)}"}

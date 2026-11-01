"""Firecrawl-backed URL scraping."""
import json
import time
import urllib.error
import urllib.request

from ...support.http import read_limited, urlopen_retry
from ...support.secrets import scrub_secrets
from . import _DEFAULT_SCRAPE_TIMEOUT_SECONDS, _safe_http_url, error_fields


_FIRECRAWL_ERROR_BODY_LIMIT = 4096
# Target-page failures that say nothing about the key. SCRAPE_SSL_ERROR is
# still returned in practice for broken target certificates although the
# current errors page (docs/firecrawl/errors.md) no longer lists it;
# UNSUPPORTED_SITE is the documented 403 for sites Firecrawl will not scrape.
_FIRECRAWL_TARGET_ERROR_CODES = frozenset({"SCRAPE_SSL_ERROR", "UNSUPPORTED_SITE"})
# docs/firecrawl/errors.md. 403 is a permission/feature refusal (or an
# unsupported site, handled by code/message below), not a bad key; 408 is the
# target page taking longer than the requested timeout.
FIRECRAWL_HTTP_ERROR_KINDS = {
    401: "invalid",
    402: "quota_exhausted",
    403: "provider",
    408: "target",
    429: "rate_limit",
}
_FIRECRAWL_HTTP_ERROR_KINDS = FIRECRAWL_HTTP_ERROR_KINDS


def firecrawl_error_kind(status_code: int | None, data, detail: str = "") -> str | None:
    """Kind from Firecrawl's documented status codes and error ``code`` values."""
    code = _error_code(data)
    text = (detail or "").lower()
    if code in _FIRECRAWL_TARGET_ERROR_CODES or "do not support this site" in text:
        return "target"
    if status_code is None:
        return None
    return _FIRECRAWL_HTTP_ERROR_KINDS.get(status_code)


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
    kind = firecrawl_error_kind(status_code, data, detail)
    if kind == "target":
        result.update(error_fields(kind="target", origin="target"))
    elif kind:
        result.update(error_fields(kind=kind, origin="provider"))
    elif status_code is not None:
        result.update(error_fields(kind="error", origin="provider"))
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


def scrape_url_firecrawl(url: str, api_key: str = "", timeout: int = _DEFAULT_SCRAPE_TIMEOUT_SECONDS, deadline: float | None = None) -> dict:
    """Fetch main page markdown via Firecrawl /v2/scrape."""
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}
    if deadline is not None:
        timeout = min(float(timeout), max(0.0, deadline - time.monotonic()))
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
            data = json.loads(read_limited(resp))
        if not isinstance(data, dict):
            return {"url": url, "error": "Firecrawl: invalid response"}
        if data.get("success") is False:
            return _error_result(url, api_key=api_key, data=data)
        page = data.get("data")
        if not isinstance(page, dict):
            return {"url": url, "error": "Firecrawl: invalid response"}
        markdown = page.get("markdown") or ""
        metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
        target_status = metadata.get("statusCode")
        if isinstance(target_status, int) and target_status >= 400:
            # The scrape ran but the target page itself answered with an error.
            detail = metadata.get("error") or f"target page returned HTTP {target_status}"
            return {
                "url": url, "error": f"Firecrawl: {scrub_secrets(detail, api_key)}",
                **error_fields(kind="target", origin="target"),
            }
        if not markdown.strip():
            warning = page.get("warning") or "empty content"
            return {"url": url, "error": f"Firecrawl: {scrub_secrets(warning, api_key)}"}
        title = metadata.get("title") or metadata.get("ogTitle") or url
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

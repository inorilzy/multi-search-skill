"""Firecrawl-backed URL scraping."""
import json
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets
from . import _DEFAULT_SCRAPE_TIMEOUT_SECONDS, _safe_http_url


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
        if data.get("success") is False:
            error = data.get("error") or data.get("message") or "request failed"
            if isinstance(error, dict):
                error = json.dumps(error, ensure_ascii=False)
            return {"url": url, "error": f"Firecrawl: {scrub_secrets(error, api_key)}"}
        page = data.get("data") if isinstance(data, dict) else data
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
    except Exception as exc:
        return {"url": url, "error": f"Firecrawl: {scrub_secrets(exc, api_key)}"}

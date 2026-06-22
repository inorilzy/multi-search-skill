"""Tavily-backed URL scraping."""
import json
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets
from . import _DEFAULT_SCRAPE_TIMEOUT_SECONDS, _safe_http_url


def scrape_url_tavily(
    url: str,
    api_key: str,
    timeout: int = _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
    content_format: str = "markdown",
) -> dict:
    """Fetch page content via Tavily /extract API."""
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}

    def _extract(depth: str) -> dict:
        payload = json.dumps({
            "urls": [url],
            "extract_depth": depth,
            "format": content_format,
            "timeout": max(1.0, min(float(timeout), 60.0)),
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
        with urlopen_retry(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def _parse(data: dict, depth: str) -> dict:
        results = data.get("results") or []
        if not results:
            failed = data.get("failed_results") or []
            message = failed[0].get("error", "no content") if failed else "no results"
            return {"url": url, "error": f"Tavily {depth}: {scrub_secrets(message, api_key)}"}
        result = results[0]
        markdown = result.get("raw_content") or ""
        if not markdown:
            return {"url": url, "error": f"Tavily {depth}: empty content"}
        return {
            "url": url,
            "title": url,
            "markdown": markdown,
            "length": len(markdown),
            "via": "tavily",
        }

    try:
        advanced = _parse(_extract("advanced"), "advanced")
        if "error" not in advanced:
            return advanced
        basic = _parse(_extract("basic"), "basic")
        if "error" not in basic:
            return basic
        return {
            "url": url,
            "error": f"{advanced['error']}; fallback {basic['error']}",
        }
    except Exception as exc:
        return {"url": url, "error": f"Tavily: {scrub_secrets(exc, api_key)}"}

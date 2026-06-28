"""Exa-backed URL scraping."""
import json
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets
from . import _DEFAULT_SCRAPE_TIMEOUT_SECONDS, _safe_http_url


_EXA_DEFAULT_MAX_CHARS = 8000


def scrape_url_exa(url: str, api_key: str, timeout: int = _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
                   max_chars: int | None = None) -> dict:
    """Fetch page content via Exa /contents API. Returns full text."""
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}
    char_cap = _EXA_DEFAULT_MAX_CHARS if not max_chars or max_chars <= 0 else int(max_chars)
    payload = json.dumps({
        "urls": [url],
        "text": {"maxCharacters": char_cap},
        "maxAgeHours": 0,
        "livecrawlTimeout": int(max(1.0, min(float(timeout), 60.0)) * 1000),
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
        result = results[0]
        text = result.get("text") or ""
        if not text.strip():
            return {"url": url, "error": "Exa: empty content"}
        return {
            "url": url,
            "title": result.get("title") or url,
            "markdown": text,
            "length": len(text),
            "via": "exa",
        }
    except Exception as exc:
        return {"url": url, "error": f"Exa: {scrub_secrets(exc, api_key)}"}

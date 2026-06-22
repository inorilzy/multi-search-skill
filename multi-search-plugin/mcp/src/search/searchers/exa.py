"""Exa.ai search with full text."""
import json
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets


def search_exa(query: str, api_key: str, count: int = 10, timeout: float = 20) -> list:
    """Search via Exa.ai with full text.

    Uses type=auto (router; 'neural' is deprecated per Exa docs).
    Requests contents.text for actual page content. Highlights, summary, and
    output synthesis are intentionally not enabled by default.
    """
    payload = json.dumps({
        "query": query,
        "numResults": count,
        "type": "auto",
        "contents": {
            "text": {"maxCharacters": 8000},
        },
    }).encode()
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=payload,
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://dashboard.exa.ai",
            "Referer": "https://dashboard.exa.ai/",
        },
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "exa", "error": scrub_secrets(e, api_key)}]
    items = []
    for r in data.get("results", []):
        text = (r.get("text") or "").strip()
        result = {
            "source": "exa",
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": text[:300],
        }
        if text:
            result["scraped_content"] = text
        items.append(result)
    return items

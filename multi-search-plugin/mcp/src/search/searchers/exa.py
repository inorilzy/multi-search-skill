"""Exa.ai search with full text."""
import json
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets


def search_exa(
    query: str,
    api_key: str,
    count: int = 10,
    timeout: float = 20,
    search_depth: str = "normal",
) -> list:
    """Search via Exa.ai with full text.

    Uses Exa's latency/quality search types. Fast and normal use highlights,
    while deep asks for fuller text for downstream evidence review.
    """
    depth = (search_depth or "normal").lower()
    exa_type = {"fast": "fast", "deep": "deep"}.get(depth, "auto")
    contents = (
        {"text": {"maxCharacters": 8000}, "highlights": True}
        if depth == "deep"
        else {"highlights": True}
    )
    payload = json.dumps({
        "query": query,
        "numResults": count,
        "type": exa_type,
        "contents": contents,
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
        highlights = r.get("highlights") or []
        if isinstance(highlights, str):
            highlights_text = highlights
        else:
            highlights_text = "\n\n".join(str(item) for item in highlights if item)
        description = (text or highlights_text or r.get("summary") or "").strip()
        result = {
            "source": "exa",
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": description[:300],
            "search_depth": depth,
            "provider_depth": exa_type,
        }
        if text:
            result["scraped_content"] = text
        elif highlights_text:
            result["scraped_content"] = highlights_text
        items.append(result)
    return items

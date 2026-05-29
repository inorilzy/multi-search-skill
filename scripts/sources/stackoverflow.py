"""Stack Overflow search via Stack Exchange API."""
import gzip
import json
import urllib.parse

from ..http import urlopen_retry


def search_stackoverflow(query: str, count: int = 10) -> list:
    """Search Stack Overflow via Stack Exchange API (free, no auth needed for basic access)."""
    url = (
        "https://api.stackexchange.com/2.3/search/advanced?"
        + urllib.parse.urlencode({
            "q": query,
            "site": "stackoverflow",
            "sort": "relevance",
            "order": "desc",
            "pagesize": count,
            "filter": "default",
        })
    )
    try:
        with urlopen_retry(url, timeout=15) as resp:
            raw = resp.read()
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
            data = json.loads(raw)
    except Exception as e:
        return [{"source": "stackoverflow", "error": str(e)}]
    items = []
    for item in data.get("items", []):
        answered = "✅" if item.get("is_answered") else "❓"
        items.append({
            "source": "stackoverflow",
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "description": f"{answered} score:{item.get('score', 0)} answers:{item.get('answer_count', 0)}",
        })
    return items

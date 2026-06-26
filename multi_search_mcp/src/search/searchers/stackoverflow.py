"""Stack Overflow question search via the Stack Exchange API."""
import html
import json
import urllib.parse
import urllib.request

from ...support.http import urlopen_retry


def search_stackoverflow(query: str, count: int = 10, timeout: float = 20) -> list:
    """Search Stack Overflow questions by relevance."""
    params = {
        "order": "desc",
        "sort": "relevance",
        "q": query,
        "site": "stackoverflow",
        "pagesize": max(1, count),
    }
    url = "https://api.stackexchange.com/2.3/search/advanced?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "multi-search/1.0"},
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "stackoverflow", "error": str(e)[:300]}]

    if data.get("error_message"):
        return [{"source": "stackoverflow", "error": str(data["error_message"])[:300]}]

    items = []
    for result in data.get("items") or []:
        if not isinstance(result, dict):
            continue
        title = html.unescape(result.get("title") or "")
        url_value = result.get("link") or ""
        tags = result.get("tags") or []
        stats = [
            f"score {result.get('score', 0)}",
            f"{result.get('answer_count', 0)} answers",
            f"{result.get('view_count', 0)} views",
        ]
        if result.get("is_answered"):
            stats.append("answered")
        if tags:
            stats.append("tags: " + ", ".join(str(tag) for tag in tags[:5]))
        items.append({
            "source": "stackoverflow",
            "title": title or url_value or "(no title)",
            "url": url_value,
            "description": " · ".join(stats),
        })
    return items

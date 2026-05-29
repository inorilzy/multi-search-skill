"""Tavily Search API."""
import json
import urllib.request

from ..http import urlopen_retry


def search_tavily(query: str, api_key: str, max_results: int = 10) -> list:
    """Call Tavily Search API."""
    payload = json.dumps(
        {
            "query": query,
            "max_results": max_results,
            "api_key": api_key,
            "include_answer": "advanced",
            "include_raw_content": "markdown",
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "tavily", "error": str(e)}]

    results = []
    for item in data.get("results", []):
        result = {
            "source": "tavily",
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": (item.get("content") or "")[:300],
        }
        raw = item.get("raw_content") or ""
        if raw:
            result["scraped_content"] = raw
        results.append(result)
    if data.get("answer"):
        results.insert(0, {"source": "tavily_answer", "answer": data["answer"]})
    return results

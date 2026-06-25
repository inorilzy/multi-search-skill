"""Tavily Search API."""
import json
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets


def search_tavily(
    query: str,
    api_key: str,
    max_results: int = 10,
    timeout: float = 15,
    search_depth: str = "normal",
) -> list:
    """Call Tavily Search API."""
    depth = (search_depth or "normal").lower()
    if depth == "fast":
        tavily_depth = "fast"
        include_answer: bool | str = False
        include_raw_content: bool | str = False
    elif depth == "deep":
        tavily_depth = "advanced"
        include_answer = "advanced"
        include_raw_content = "markdown"
    else:
        tavily_depth = "basic"
        include_answer = "basic"
        include_raw_content = False

    body = {
        "query": query,
        "max_results": max_results,
        "search_depth": tavily_depth,
        "include_answer": include_answer,
        "include_raw_content": include_raw_content,
        "include_usage": True,
    }
    if tavily_depth == "advanced":
        body["chunks_per_source"] = 3
    payload = json.dumps(
        body
    ).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "tavily", "error": scrub_secrets(e, api_key)}]

    results = []
    for item in data.get("results", []):
        result = {
            "source": "tavily",
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": (item.get("content") or "")[:300],
            "search_depth": depth,
            "provider_depth": tavily_depth,
        }
        raw = item.get("raw_content") or ""
        if raw:
            result["scraped_content"] = raw
        results.append(result)
    if data.get("answer"):
        results.insert(0, {"source": "tavily_answer", "answer": data["answer"]})
    return results

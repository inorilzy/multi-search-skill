"""SerpAPI (Google) search."""
import json
import urllib.parse
import urllib.request

from ..http import urlopen_retry
from ..secrets import scrub_secrets


def _scrub(msg: str, api_key: str = "") -> str:
    return scrub_secrets(msg, api_key, limit=300)


def search_serpapi(
    query: str,
    api_key: str,
    count: int = 10,
    engine: str = "google_light",
    timeout: float = 20,
) -> list:
    """Call SerpAPI to fetch SERP results.
    Default engine: google_light — 3x faster, 250 searches/month free (vs 100 for regular google).
    Switch to engine='google' for full knowledge_graph / shopping / things_to_know etc.
    """
    results = []
    target_count = max(1, count)
    page_size = 10
    organic_count = 0

    def _return_error(message: str) -> list:
        error = {"source": "serpapi", "error": _scrub(message, api_key)}
        return results + [error] if results else [error]

    for start in range(0, target_count, page_size):
        if organic_count >= target_count:
            break
        params = {
            "engine": engine,
            "q": query,
            "output": "json",
            "api_key": api_key,
        }
        if start:
            params["start"] = start
        if engine in ("google", "google_light"):
            params["hl"] = "en"
            params["gl"] = "us"
        url = "https://serpapi.com/search?" + urllib.parse.urlencode(params)
        try:
            with urlopen_retry(url, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            return _return_error(str(scrub_secrets(e, api_key)))
        if data.get("error"):
            return _return_error(str(data["error"]))

        if start == 0:
            kg = data.get("knowledge_graph") or {}
            if kg.get("description"):
                results.append({
                    "source": "serpapi_answer",
                    "answer": f"[{kg.get('title', '')}] {kg['description']}",
                })
        organic = data.get("organic_results") or []
        if not organic:
            break
        for item in organic:
            if organic_count >= target_count:
                break
            results.append({
                "source": "serpapi",
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "description": (item.get("snippet") or "")[:300],
            })
            organic_count += 1
    return results

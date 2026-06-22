"""GLM web search via a local glm2api-compatible endpoint."""
import json
import os
import urllib.request

from ..http import urlopen_retry
from ..secrets import scrub_secrets


DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_MODEL = "glm-4.6-search"


def _snippet(item: dict) -> str:
    text = item.get("snippet") or item.get("text") or ""
    return str(text).strip()[:300]


def search_glm_web(
    query: str,
    max_results: int = 10,
    timeout: float = 120,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> list:
    """Call GLM's web-search model through glm2api and return source rows."""
    base_url = (base_url or os.getenv("GLM_WEB_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    model = model or os.getenv("GLM_WEB_MODEL") or DEFAULT_MODEL
    api_key = api_key or os.getenv("GLM_WEB_API_KEY") or ""
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": f"{query}\n\n请使用联网搜索，返回可靠网页来源。",
                }
            ],
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "glm-web", "error": scrub_secrets(e, [api_key, base_url])}]

    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        return [{"source": "glm-web", "error": f"unexpected glm-web response: {scrub_secrets(e, [api_key, base_url])}"}]

    results = []
    answer = message.get("content")
    if answer:
        results.append({"source": "glm_web_answer", "answer": answer})

    for item in (message.get("web_search_results") or [])[:max_results]:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or ""
        if not url:
            continue
        text = item.get("text") or ""
        result = {
            "source": "glm-web",
            "title": item.get("title") or url,
            "url": url,
            "description": _snippet(item),
        }
        if text:
            result["scraped_content"] = text
        if item.get("time"):
            result["time"] = item.get("time")
        if item.get("host_name"):
            result["host_name"] = item.get("host_name")
        results.append(result)
    return results

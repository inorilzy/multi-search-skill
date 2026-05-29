"""Exa.ai search with highlights + summary + full text + synthesized answer."""
import json
import urllib.request

from ..http import urlopen_retry


def search_exa(query: str, api_key: str, count: int = 10) -> list:
    """Search via Exa.ai with highlights + summary + synthesized answer.

    Uses type=auto (router; 'neural' is deprecated per Exa docs).
    Requests contents.text + highlights + summary, plus a top-level
    outputSchema=text for a global synthesized answer with grounding.
    """
    payload = json.dumps({
        "query": query,
        "numResults": count,
        "type": "auto",
        "contents": {
            "text": {"maxCharacters": 8000},
            "highlights": True,
            "summary": True,
        },
        "outputSchema": {
            "type": "text",
            "description": "A concise synthesized answer to the user's query, based on the search results.",
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
        with urlopen_retry(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "exa", "error": str(e)}]
    items = []
    for r in data.get("results", []):
        highlights = r.get("highlights") or []
        highlight_text = " [...] ".join(highlights) if highlights else ""
        summary = (r.get("summary") or "").strip()
        text = (r.get("text") or "").strip()
        description = summary or highlight_text or text
        result = {
            "source": "exa",
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": description[:300],
        }
        if text:
            result["scraped_content"] = text
        else:
            full = []
            if summary:
                full.append(summary)
            if highlight_text:
                full.append(highlight_text)
            if full:
                result["scraped_content"] = "\n\n".join(full)
        items.append(result)
    output = data.get("output") or {}
    answer = output.get("content") if isinstance(output.get("content"), str) else ""
    if answer:
        items.insert(0, {"source": "exa_answer", "answer": answer})
    return items

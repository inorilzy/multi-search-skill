"""Exa.ai search with full text."""
import json
import urllib.error
import urllib.request

from ...support.http import read_limited, urlopen_retry
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets

# docs/exa/error-codes.md: 401 bad key, 402 credits exhausted, 403 feature or
# policy refusal (the key itself is fine), 429 over the QPS limit.
EXA_HTTP_ERROR_KINDS = {
    401: "invalid",
    402: "quota_exhausted",
    403: "provider",
    429: "rate_limit",
}


def search_exa(
    query: str,
    api_key: str,
    count: int = 10,
    timeout: float = 20,
    want_content: bool = False,
    deadline: float | None = None,
) -> list:
    """Search via Exa.ai.

    ``want_content`` returns full webpage text inline; otherwise only relevant
    highlight snippets are returned.
    """
    exa_type = "auto"
    contents = {"text": True} if want_content else {"highlights": True}
    payload = json.dumps({
        "query": query,
        "numResults": count,
        "type": exa_type,
        "contents": contents,
    }).encode()
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=payload,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout, deadline=deadline) as resp:
            data = json.loads(read_limited(resp))
    except urllib.error.HTTPError as e:
        return [http_error_row("exa", e, secret=api_key, kinds=EXA_HTTP_ERROR_KINDS)]
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
        description = (text or highlights_text).strip()
        result = {
            "source": "exa",
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": description[:300],
        }
        if text:
            result["scraped_content"] = text
            result["content_kind"] = "body"
        elif highlights_text:
            result["scraped_content"] = highlights_text
            result["content_kind"] = "excerpt"
        else:
            result["content_kind"] = "metadata"
        items.append(result)
    return items

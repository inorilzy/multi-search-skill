"""SerpAPI (Google) search."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from ...support.http import read_limited, urlopen_retry
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets

# Google Light returns a fixed 10 organic results per page. Only the first page
# is fetched: later pages add little and each costs a search credit.
SERPAPI_PAGE_SIZE = 10
# docs/serpapi/api-status-and-error-codes.md
_SERPAPI_HTTP_ERROR_KINDS = {401: "invalid", 403: "invalid", 429: "rate_limit"}


def _serpapi_refine(status: int, data, detail: str) -> str | None:
    # 429 means either the hourly throughput limit or "Your account has run out
    # of searches." Only the latter is an exhausted quota.
    if status == 429 and "run out of searches" in (detail or "").lower():
        return "quota_exhausted"
    return None


def _scrub(msg: str, api_key: str = "") -> str:
    return scrub_secrets(msg, api_key, limit=300)


def _answer_box_text(answer_box: dict) -> str:
    for key in ("answer", "snippet", "snippet_highlighted_words", "list"):
        value = answer_box.get(key)
        if isinstance(value, list):
            value = "\n".join(str(item) for item in value if item)
        if value:
            title = answer_box.get("title") or answer_box.get("type") or "Answer Box"
            return f"[{title}] {value}"
    return ""


def search_serpapi(
    query: str,
    api_key: str,
    count: int = 10,
    engine: str = "google_light",
    timeout: float = 20,
    search_depth: str = "normal",
    *,
    deadline: float | None = None,
    publish_partial: Callable[[list], None] | None = None,
) -> list:
    """Call SerpAPI to fetch SERP results.
    Default engine: google_light — 3x faster, 250 searches/month free (vs 100 for regular google).
    Switch to engine='google' for full knowledge_graph / shopping / things_to_know etc.

    Only the first page (at most 10 results) is requested. The request shares
    the caller's deadline; timeout caps it.
    """
    if deadline is None:
        deadline = time.monotonic() + timeout
    results = []
    depth = (search_depth or "normal").lower()
    engine = "google_light" if depth == "fast" else engine
    target_count = max(1, min(int(count), SERPAPI_PAGE_SIZE))
    page_size = SERPAPI_PAGE_SIZE
    organic_count = 0

    def _return_error(message: str) -> list:
        error = {"source": "serpapi", "error": _scrub(message, api_key)}
        return results + [error] if results else [error]

    for start in range(0, target_count, page_size):
        if organic_count >= target_count:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _return_error("SerpAPI search deadline exceeded")
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
            with urlopen_retry(url, timeout=min(timeout, remaining)) as resp:
                data = json.loads(read_limited(resp))
        except urllib.error.HTTPError as e:
            row = http_error_row(
                "serpapi", e, secret=api_key, kinds=_SERPAPI_HTTP_ERROR_KINDS,
                refine=_serpapi_refine,
            )
            return results + [row] if results else [row]
        except Exception as e:
            return _return_error(str(scrub_secrets(e, api_key)))
        if data.get("error"):
            # A query Google answers with nothing is still a successful search:
            # SerpApi reports search_metadata.status == "Success" alongside an
            # "error" message (serpapi.com/api-status-and-error-codes).
            if (data.get("search_metadata") or {}).get("status") == "Success":
                break
            message = str(data["error"])
            kind = _serpapi_refine(429, data, message) or (
                "invalid" if "invalid api key" in message.lower() else None
            )
            if kind is None:
                return _return_error(message)
            row = {"source": "serpapi", "error": _scrub(message, api_key), "kind": kind,
                   "error_type": kind, "origin": "provider", "error_origin": "provider"}
            return results + [row] if results else [row]

        if start == 0:
            # answer_box is only documented for engine=google, not google_light.
            answer_box = (data.get("answer_box") or {}) if engine == "google" else {}
            answer_text = _answer_box_text(answer_box)
            if answer_text:
                results.append({
                    "source": "serpapi_answer",
                    "answer": answer_text,
                    "answer_type": "answer_box",
                    "content_kind": "answer",
                })
            kg = data.get("knowledge_graph") or {}
            if kg.get("description"):
                results.append({
                    "source": "serpapi_answer",
                    "answer": f"[{kg.get('title', '')}] {kg['description']}",
                    "answer_type": "knowledge_graph",
                    "content_kind": "answer",
                })
        organic = data.get("organic_results") or []
        if not organic:
            break
        for item in organic:
            if organic_count >= target_count:
                break
            description = (item.get("snippet") or "")[:300]
            results.append({
                "source": "serpapi",
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "description": description,
                "content_kind": "excerpt" if description else "metadata",
                "search_depth": depth,
                "provider_depth": engine,
            })
            organic_count += 1
        if publish_partial is not None:
            publish_partial(list(results))
    return results

"""SerpAPI (Google) search."""
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

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


# Google sometimes serves result links as its own redirect (``/url?q=CAES...`` or
# ``/goto?url=CAES...``) and SerpApi passes them through as ``link``. The CAES token is
# opaque, so the only way to the destination is the redirect's ``Location`` header.
# Such a link cannot merge with the same page from other providers, so resolve it.
_GOOGLE_REDIRECT_HOSTS = {"google.com", "www.google.com"}
_GOOGLE_REDIRECT_PATHS = {"/url", "/goto"}
_REDIRECT_RESOLVE_TIMEOUT = 5.0
_REFRESH_PAGE_LIMIT = 256 * 1024
_META_REFRESH = re.compile(r'<meta\b[^>]*\bcontent="(\d+)\s*;\s*url=([^"]+)"', re.IGNORECASE)
_GOTO_WAIT = 2.0


class _KeepRedirect(urllib.request.BaseHandler):
    """Answer a 3xx with the response itself, so its ``Location`` can be read without following it."""

    handler_order = 100  # ahead of the shared redirect handler

    def http_error_302(self, req, fp, code, msg, headers):
        return fp

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _is_google_redirect(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme in ("http", "https") and parts.hostname in _GOOGLE_REDIRECT_HOSTS \
        and parts.path in _GOOGLE_REDIRECT_PATHS


def _destination(url: str) -> str | None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme in ("http", "https") and parts.hostname and not _is_google_redirect(url):
        return url
    return None


def _redirect_hop(url: str, deadline: float) -> tuple[str, str]:
    """One request without following it: (Location, page). An HTTP error answers ("", "")."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("redirect resolution deadline exceeded")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen_retry(
            request, timeout=min(_REDIRECT_RESOLVE_TIMEOUT, remaining),
            deadline=deadline, extra_handlers=(_KeepRedirect(),),
        ) as resp:
            location = resp.headers.get("Location") or ""
            page = "" if location else read_limited(resp, _REFRESH_PAGE_LIMIT).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        error.close()
        return "", ""
    return location, page


def _resolve_google_redirect(url: str, deadline: float) -> str:
    """The destination of a Google redirect link; any other link, or a failure, keeps ``url``."""
    if not _is_google_redirect(url):
        return url
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    for name in ("q", "url"):
        plain = _destination((query.get(name) or [""])[0])
        if plain:
            return plain
    try:
        # Google answers either with a 302 to the destination, or with a 200 page whose meta
        # refresh points at a ``/goto`` hop. That hop answers 400 at first; measured, most
        # accept after ~2 s and the rest only after 8-23 s. Wait once, then keep the link
        # rather than hold the whole search for the slow ones.
        location, page = _redirect_hop(url, deadline)
        refresh = None if location else _META_REFRESH.search(page)
        if refresh:
            delay, hop = int(refresh.group(1)), urllib.parse.urljoin(url, html.unescape(refresh.group(2)))
            if not _is_google_redirect(hop):
                return _destination(hop) or url
            wait = min(_GOTO_WAIT, delay)
            if time.monotonic() + wait >= deadline:
                return url
            time.sleep(wait)
            location, _page = _redirect_hop(hop, deadline)
    except Exception:
        return url
    return (_destination(urllib.parse.urljoin(url, location)) or url) if location else url


def _resolve_links(rows: list[dict], deadline: float) -> None:
    pending = [row for row in rows if _is_google_redirect(row.get("url", ""))]
    if not pending:
        return
    with ThreadPoolExecutor(max_workers=len(pending)) as pool:
        for row, target in zip(pending, pool.map(lambda row: _resolve_google_redirect(row["url"], deadline), pending)):
            row["url"] = target


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
        page_rows = []
        for item in organic:
            if organic_count >= target_count:
                break
            description = (item.get("snippet") or "")[:300]
            page_rows.append({
                "source": "serpapi",
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "description": description,
                "content_kind": "excerpt" if description else "metadata",
                "search_depth": depth,
                "provider_depth": engine,
            })
            organic_count += 1
        _resolve_links(page_rows, deadline)
        results.extend(page_rows)
        if publish_partial is not None:
            publish_partial(list(results))
    return results

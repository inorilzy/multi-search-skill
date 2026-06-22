"""URL normalization, content splitting, and cross-source deduplication."""
import urllib.parse

from .models import as_dict, as_dicts


ANSWER_SOURCES = {"tavily_answer", "serpapi_answer", "exa_answer", "glm_web_answer", "deepseek_web_answer"}
MIN_USEFUL_WEB_CONTENT_CHARS = 300


def _norm_url(url: str) -> str:
    """Normalize URL for dedup: force https, lowercase host, strip trailing slash, remove UTM/tracking params."""
    try:
        parts = urllib.parse.urlparse(url.strip())
        scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
        qs = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        qs = {k: v for k, v in qs.items()
              if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref", "source"))}
        new_query = urllib.parse.urlencode(qs, doseq=True)
        path = parts.path.rstrip("/") or "/"
        return urllib.parse.urlunparse((scheme, parts.netloc.lower(), path, parts.params, new_query, ""))
    except Exception:
        return url


def _raw_counts(results: list) -> dict:
    raw_counts: dict = {}
    for item in results:
        if (item.get("status") == "ok"
                or "error" in item
                or item.get("source") in ANSWER_SOURCES):
            continue
        src = item.get("source", "?")
        raw_counts[src] = raw_counts.get(src, 0) + 1
    return raw_counts


def is_usable_web_content(content: str, min_chars: int = MIN_USEFUL_WEB_CONTENT_CHARS) -> bool:
    """Return whether content is substantial enough to stand in for webpage text."""
    return len((content or "").strip()) >= min_chars


def _is_passthrough(item: dict) -> bool:
    return (
        item.get("status") == "ok"
        or "error" in item
        or item.get("source") in ANSWER_SOURCES
        or not item.get("url")
    )


def split_by_content(results: list) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Split raw search results into content-bearing and metadata-only rows."""
    results = as_dicts(results)
    with_content: list[dict] = []
    without_content: list[dict] = []
    passthrough: list[dict] = []

    for item in results:
        if _is_passthrough(item):
            passthrough.append(item)
            continue
        content = item.get("scraped_content") or ""
        if item.get("source") == "twitter":
            # Twitter discussion content is independent of webpage body;
            # any non-empty scraped_content counts as "has content".
            if content:
                with_content.append(item)
            else:
                without_content.append(item)
        else:
            # For web sources, short/empty content should not satisfy
            # "already has content" — otherwise it blocks richer scraping.
            if is_usable_web_content(content):
                with_content.append(item)
            else:
                without_content.append(item)

    return with_content, without_content, passthrough, _raw_counts(results)


def result_to_scrape(item: dict) -> dict:
    item = as_dict(item)
    content = item.get("scraped_content") or ""
    return {
        "url": item.get("url", ""),
        "title": item.get("title") or item.get("url", ""),
        "via": f"{item.get('source', '?')}:prefetch",
        "markdown": content,
        "length": len(content),
    }


def deduplicate(results: list) -> tuple:
    """Remove duplicate URLs, keeping first occurrence. Returns (deduped, source_counts_raw).

    source_counts_raw counts each source's contribution BEFORE dedup, so users
    see that Brave/Tavily both returned a URL even if only one is shown.
    Each kept item also gets an 'also_from' list of other sources that returned the same URL.
    """
    results = as_dicts(results)
    raw_counts = _raw_counts(results)

    seen: dict = {}
    deduped: list = []
    for item in results:
        url = item.get("url", "")
        if item.get("status") == "ok":
            deduped.append(item)
            continue
        if not url:
            deduped.append(item)
            continue
        norm = _norm_url(url)
        if norm not in seen:
            seen[norm] = len(deduped)
            item = dict(item)
            item["also_from"] = []
            deduped.append(item)
        else:
            existing = deduped[seen[norm]]
            other_src = item.get("source", "?")
            if other_src != existing.get("source") and other_src not in existing.get("also_from", []):
                existing.setdefault("also_from", []).append(other_src)
            # Promote richer fields from later occurrences so we don't lose
            # pre-fetched content / longer descriptions / star counts just because
            # a snippet-only source happened to return the URL first.
            for fld in ("scraped_content", "description"):
                new_val = item.get(fld) or ""
                old_val = existing.get(fld) or ""
                if len(new_val) > len(old_val):
                    existing[fld] = new_val
            if item.get("stars") and not existing.get("stars"):
                existing["stars"] = item["stars"]
            if (item.get("title") and len(item["title"]) > len(existing.get("title") or "")):
                existing["title"] = item["title"]
    return deduped, raw_counts

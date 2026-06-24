"""URL normalization, content splitting, and cross-source deduplication."""
import urllib.parse

from .models import as_dict, as_dicts


ANSWER_SOURCES = {"tavily_answer", "serpapi_answer", "exa_answer", "glm_web_answer", "deepseek_web_answer"}
MIN_USEFUL_WEB_CONTENT_CHARS = 300

# When the same URL is returned by multiple sources, prefer the source that is
# authoritative for that host as the canonical `source` (the others move to
# also_from). Without this the canonical source is just whoever returned the URL
# first, so a GitHub repo could be attributed to "brave" instead of "github-repos".
CANONICAL_SOURCE_BY_HOST = {
    "github.com": "github-repos",
    "stackoverflow.com": "stackoverflow",
    "news.ycombinator.com": "hackernews",
    "reddit.com": "reddit",
    "zhihu.com": "zhihu",
    "v2ex.com": "v2ex",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "bilibili.com": "bilibili",
}


def _canonical_source_for_url(url: str) -> str | None:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    return CANONICAL_SOURCE_BY_HOST.get(host)


def _prefer_canonical(existing: dict, candidate_source: str, url: str) -> None:
    """If candidate_source is the authoritative source for this URL's host and
    the row isn't already canonical, swap it in as the row's `source` and demote
    the previous source into also_from."""
    preferred = _canonical_source_for_url(url)
    if not preferred or candidate_source != preferred:
        return
    current = existing.get("source")
    if current == preferred:
        return
    if current and current not in existing.get("also_from", []):
        existing.setdefault("also_from", []).append(current)
    existing["source"] = preferred
    if preferred in existing.get("also_from", []):
        existing["also_from"] = [s for s in existing["also_from"] if s != preferred]

# Exact tracking-parameter names to drop during URL normalization. Prefix
# matching on "ref"/"source" used to also delete meaningful params like
# ref_id / reference / source_id, collapsing distinct URLs into one and
# silently dropping results. Only utm_* keeps prefix semantics.
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "yclid",
    "ref", "ref_src", "source",
}


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in TRACKING_PARAMS


def _norm_url(url: str) -> str:
    """Normalize URL for dedup: force https, lowercase host, strip trailing slash, remove UTM/tracking params."""
    try:
        parts = urllib.parse.urlparse(url.strip())
        scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
        qs = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        qs = {k: v for k, v in qs.items() if not _is_tracking_param(k)}
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


def apply_scraped_content(rows: list, content_pool: dict) -> None:
    """Write scraped markdown from content_pool back onto matching result rows.

    content_pool is keyed by _norm_url(url) -> {"markdown", "via", ...}. For each
    row whose normalized URL has pooled content, promote that content onto the
    row's ``scraped_content`` (only when it is longer than what the row already
    has) and flag the row with ``scraped=True`` / ``scrape_via``. This keeps the
    final result records and the standalone ``scrapes`` view in sync instead of
    leaving JSON rows as empty skeletons.
    """
    if not content_pool:
        return
    for row in rows:
        url = row.get("url") if isinstance(row, dict) else getattr(row, "url", "")
        if not url:
            continue
        pooled = content_pool.get(_norm_url(url))
        if not pooled:
            continue
        markdown = pooled.get("markdown") or ""
        if not markdown:
            continue
        existing = row.get("scraped_content") or ""
        if len(markdown) > len(existing):
            row["scraped_content"] = markdown
        row["scraped"] = True
        if pooled.get("via"):
            row["scrape_via"] = pooled["via"]


def consensus_weight(item: dict) -> int:
    """Number of sources that agreed on a URL (1 + cross-source duplicates)."""
    return 1 + len(item.get("also_from") or [])


def rank_results(results: list) -> list:
    """Order results by consensus + enrichment so a single ranking is shared by
    JSON output, markdown rendering, and provider status.

    Sort key (descending priority):
      1. errors sink to the bottom
      2. rows enriched with scraped content first (strongest quality signal)
      3. higher consensus weight (more sources agreed)
      4. longer scraped content
      5. higher star count
    Ties preserve insertion order (Python sort is stable).
    """
    rows = as_dicts(results)

    def _key(item: dict):
        is_error = "error" in item
        has_content = bool(item.get("scraped_content"))
        content_len = len((item.get("scraped_content") or ""))
        stars = item.get("stars") or 0
        return (
            0 if is_error else 1,
            1 if has_content else 0,
            consensus_weight(item),
            content_len,
            stars,
        )

    return sorted(rows, key=_key, reverse=True)


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
            # Let an authoritative source for this host claim the canonical slot
            # even if a generic search engine returned the URL first.
            _prefer_canonical(existing, other_src, url)
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

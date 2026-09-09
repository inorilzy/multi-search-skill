"""URL normalization, content splitting, and cross-source deduplication."""
import urllib.parse

from ..search.capabilities import content_kind_blocks_scrape, infer_content_kind
from .models import (
    ANSWER_SOURCES,
    CONTENT_KIND_ANSWER,
    as_dict,
    as_dicts,
    content_kind_priority,
    is_empty_result,
)
# Re-exported here for existing callers.
from .urlutil import _norm_url

# When the same URL is returned by multiple sources, prefer the source that is
# authoritative for that host as the canonical `source` (the others move to
# also_from). Without this the canonical source is just whoever returned the URL
# first, so a GitHub repo could be attributed to "brave" instead of "github-repos".
CANONICAL_SOURCE_BY_HOST = {
    "github.com": "github-repos",
    "stackoverflow.com": "stackoverflow",
    "news.ycombinator.com": "hackernews",
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

def _raw_counts(results: list) -> dict:
    raw_counts: dict = {}
    for item in results:
        if (is_empty_result(item)
                or "error" in item
                or item.get("source") in ANSWER_SOURCES):
            continue
        src = item.get("source", "?")
        raw_counts[src] = raw_counts.get(src, 0) + 1
    return raw_counts


def _is_passthrough(item: dict) -> bool:
    kind = infer_content_kind(item)
    return (
        is_empty_result(item)
        or "error" in item
        or item.get("source") in ANSWER_SOURCES
        or kind == CONTENT_KIND_ANSWER
        or not item.get("url")
    )


def _canonical_source(source: str) -> str:
    # Public source names may use hyphens while internal names use underscores;
    # fold both so they compare equal.
    return str(source or "").replace("-", "_")


def _answer_provider_sources(results: list[dict]) -> set[str]:
    """Sources that returned a synthesized answer/summary this search.

    ``tavily_answer`` -> ``tavily``. Used to skip scraping the
    concrete URLs of any source that already provided a summary, while still
    scraping sources (github/stackoverflow/...) that returned URLs only.
    """
    providers: set[str] = set()
    for item in results:
        src = item.get("source")
        if src in ANSWER_SOURCES and not item.get("error"):
            providers.add(_canonical_source(str(src)[: -len("_answer")]))
    return providers


def split_by_content(
    results: list,
    skip_summarized_sources: bool = False,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Split raw search results into content-bearing and metadata-only rows.

    When ``skip_summarized_sources`` is true, a normal result is
    treated as already having content if its source provided an answer/summary
    row, so its URL is not scraped. Sources without a summary are unaffected.
    """
    results = as_dicts(results)
    summarized = _answer_provider_sources(results) if skip_summarized_sources else set()
    with_content: list[dict] = []
    without_content: list[dict] = []
    passthrough: list[dict] = []

    for item in results:
        item["content_kind"] = infer_content_kind(item)
        if _is_passthrough(item):
            passthrough.append(item)
            continue
        if summarized and _canonical_source(item.get("source")) in summarized:
            # This source already returned a summary, so accept it
            # as content-bearing and skip scraping its concrete URLs.
            with_content.append(item)
        elif content_kind_blocks_scrape(item.get("source", ""), item["content_kind"]):
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
        "content_kind": infer_content_kind(item),
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
        elif not existing:
            row["scraped_content"] = markdown
        row["content_kind"] = pooled.get("content_kind") or "body"
        row["scraped"] = True
        if pooled.get("via"):
            row["scrape_via"] = pooled["via"]


def consensus_weight(item: dict) -> int:
    """Number of sources that agreed on a URL (1 + cross-source duplicates)."""
    if item.get("providers"):
        return len(set(item["providers"]))
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

    # Fused search results keep their RRF order after fetching and rendering.
    # Body size, fetch errors, and platform popularity must not rerank them.
    candidates = [row for row in rows if not row.get("error")]
    if candidates and all("rrf_score" in row for row in candidates):
        return sorted(rows, key=lambda row: (
            bool(row.get("error")),
            -float(row.get("rrf_score") or 0),
            str(row.get("canonical_url") or row.get("url") or ""),
        ))

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
        if is_empty_result(item):
            deduped.append(item)
            continue
        if not url:
            deduped.append(item)
            continue
        norm = _norm_url(url)
        if norm not in seen:
            seen[norm] = len(deduped)
            item = dict(item)
            item["content_kind"] = infer_content_kind(item)
            item["also_from"] = []
            deduped.append(item)
        else:
            existing = deduped[seen[norm]]
            other_src = item.get("source", "?")
            existing_kind = infer_content_kind(existing)
            item_kind = infer_content_kind(item)
            if other_src != existing.get("source") and other_src not in existing.get("also_from", []):
                existing.setdefault("also_from", []).append(other_src)
            # Let an authoritative source for this host claim the canonical slot
            # even if a generic search engine returned the URL first.
            _prefer_canonical(existing, other_src, url)
            # Promote richer fields from later occurrences so we don't lose
            # pre-fetched content / longer descriptions / star counts just because
            # a snippet-only source happened to return the URL first.
            new_content = item.get("scraped_content") or ""
            old_content = existing.get("scraped_content") or ""
            if new_content and (
                content_kind_priority(item_kind) > content_kind_priority(existing_kind)
                or len(new_content) > len(old_content)
            ):
                existing["scraped_content"] = new_content
            new_desc = item.get("description") or ""
            old_desc = existing.get("description") or ""
            if len(new_desc) > len(old_desc):
                existing["description"] = new_desc
            if content_kind_priority(item_kind) > content_kind_priority(existing_kind):
                existing["content_kind"] = item_kind
            if item.get("stars") and not existing.get("stars"):
                existing["stars"] = item["stars"]
            if (item.get("title") and len(item["title"]) > len(existing.get("title") or "")):
                existing["title"] = item["title"]
    return deduped, raw_counts

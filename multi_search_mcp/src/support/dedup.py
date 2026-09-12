"""Presentation ranking for fused results and compatibility rows."""
from .models import as_dicts
# Re-exported here for existing callers.
from .urlutil import _norm_url


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

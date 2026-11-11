"""Response notices and final result ordering for the candidate-search seam.

Truncation messages and upstream warnings describe a successful response with
reduced coverage.  They travel in a row's ``notice`` field, never in ``error``,
so provider status, outcome, and key health keep counting only real failures.
The final-ordering helper lives here as well to keep the candidate module under
its structural line limit.
"""
from __future__ import annotations

from .candidate import diversify_by_site


def notice_row(source: str, message: str) -> dict:
    """A provider row that informs without counting as an error."""
    return {"source": str(source), "notice": str(message)}


def collect_notices(query_runs: list[tuple[str, list[dict]]]) -> list[dict]:
    """Return distinct notices with their query and source, in stable order."""
    notices: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for query, rows in query_runs:
        for row in rows:
            text = str(row.get("notice") or "")
            if not text:
                continue
            identity = (query, str(row.get("source") or "?"), text)
            if identity in seen:
                continue
            seen.add(identity)
            notices.append({"source": identity[1], "query": query, "notice": text})
    return notices


def finalize_results(hits: list[dict], limit: int) -> list[dict]:
    """Apply the site cap without putting a scored hit behind unscored fillers."""
    scored = [hit for hit in hits if hit.get("relevance_score") is not None]
    unscored = [hit for hit in hits if hit.get("relevance_score") is None]
    ordered = diversify_by_site(scored, limit)
    if len(ordered) < limit:
        ordered += diversify_by_site(unscored, limit - len(ordered))
    return ordered


def search_outcome(provider_status: list[dict], errors: list[dict], results: list[dict]) -> str:
    """Business outcome shared by the CLI, service and desktop adapters.

    Notices never appear in ``errors`` or provider status, so a response whose
    only extra rows are notices still reports ``success``.
    """
    if provider_status and all(row.get("status") == "error" for row in provider_status):
        return "failed"
    if errors:
        return "partial"
    return "success" if results else "empty"

"""Candidate-search normalization and ranking helpers."""
from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any

from ..support.models import ANSWER_SOURCES, content_kind_priority, is_empty_result, search_content
from ..support.urlutil import _is_tracking_param
from .query_policy import QueryFusionPolicy


RRF_RANK_CONSTANT = 40
SEARCH_RESULT_LIMIT = 15
SEARCH_HIT_CONTENT_CHARS = 1200


def canonicalize_url(url: str) -> str:
    """Return a conservative URL identity for search-result fusion.

    HTTP and HTTPS stay distinct. Only syntax-level equivalences and known
    tracking parameters are normalized; unknown business parameters remain.
    """
    value = str(url or "").strip()
    try:
        parts = urllib.parse.urlsplit(value)
        scheme = parts.scheme.lower()
        hostname = (parts.hostname or "").lower()
        if not scheme or not hostname:
            return value

        host = f"[{hostname}]" if ":" in hostname else hostname
        try:
            port = parts.port
        except ValueError:
            return value
        if port is not None and not (
            (scheme == "http" and port == 80)
            or (scheme == "https" and port == 443)
        ):
            host = f"{host}:{port}"

        userinfo = ""
        if parts.username is not None:
            userinfo = urllib.parse.quote(parts.username, safe="")
            if parts.password is not None:
                userinfo += ":" + urllib.parse.quote(parts.password, safe="")
            userinfo += "@"

        query = [
            (key, item)
            for key, item in urllib.parse.parse_qsl(
                parts.query, keep_blank_values=True
            )
            if not _is_tracking_param(key)
        ]
        # Stable key sorting keeps repeated business parameters in their
        # original order (servers may interpret the first or last value).
        query.sort(key=lambda pair: pair[0])
        return urllib.parse.urlunsplit(
            (
                scheme,
                userinfo + host,
                parts.path or "/",
                urllib.parse.urlencode(query, doseq=True),
                "",
            )
        )
    except (TypeError, ValueError):
        return value


def make_source_id(response_id: str, canonical_url: str) -> str:
    digest = hashlib.sha256(
        f"{response_id}\0{canonical_url}".encode("utf-8")
    ).hexdigest()
    return f"src_{digest[:20]}"


def _compact(value: Any, limit: int = SEARCH_HIT_CONTENT_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _candidate_rows(query: str, rows: list[dict]) -> dict[str, dict[str, dict]]:
    """Return one deterministic row per provider/canonical URL."""
    grouped: dict[str, dict[str, dict]] = {}
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            str(row.get("source") or ""),
            int(row["provider_rank"]) if row.get("provider_rank") else float("inf"),
            canonicalize_url(str(row.get("url") or "")),
            str(row.get("title") or ""),
        ),
    )
    inferred_ranks: dict[str, int] = {}
    for row in ordered:
        source = str(row.get("source") or "")
        url = str(row.get("url") or "")
        if (
            not source
            or not url
            or source in ANSWER_SOURCES
            or row.get("error")
            or is_empty_result(row)
        ):
            continue
        inferred_ranks[source] = inferred_ranks.get(source, 0) + 1
        rank = int(row.get("provider_rank") or inferred_ranks[source])
        if rank < 1:
            continue
        canonical_url = canonicalize_url(url)
        if not canonical_url:
            continue
        row["provider_rank"] = rank
        row["_query"] = query
        existing = grouped.setdefault(source, {}).get(canonical_url)
        if existing is None or rank < int(existing["provider_rank"]):
            grouped[source][canonical_url] = row
    return grouped


def _public_hit(
    *,
    response_id: str,
    canonical_url: str,
    contributions: list[tuple[str, dict]],
    score: float,
    query_ranks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    contributions = sorted(
        contributions,
        key=lambda item: (
            int(item[1]["provider_rank"]),
            item[0],
            str(item[1].get("title") or ""),
        ),
    )
    primary_source, representative = contributions[0]
    content_rows = []
    for provider, row in contributions:
        content = search_content(row)
        if content.snippet.strip():
            content_rows.append((provider, row, content))
    if content_rows:
        _content_provider, _content_row, content = sorted(
            content_rows,
            key=lambda item: (
                -content_kind_priority(item[2].snippet_kind),
                -len(item[2].snippet),
                int(item[1]["provider_rank"]),
                item[0],
            ),
        )[0]
        content_text = content.snippet
        content_kind = content.snippet_kind
    else:
        content_text = ""
        content_kind = "metadata"
    provider_ranks = []
    for provider, row in sorted(
        contributions,
        key=lambda item: (item[0], str(item[1].get("_query") or "")),
    ):
        rank = {
            "provider": provider,
            "query": str(row.get("_query") or ""),
            "rank": int(row["provider_rank"]),
        }
        if row.get("score") is not None:
            rank["native_score"] = row["score"]
        provider_ranks.append(rank)

    body_available = any(
        bool(search_content(row).body)
        or bool(row.get("body_available"))
        for _, row in contributions
    )
    published_at = next(
        (
            row.get(key)
            for _, row in contributions
            for key in ("published_at", "published_date", "date", "created_at")
            if row.get(key)
        ),
        None,
    )
    source_id = make_source_id(response_id, canonical_url)
    hit = {
        "source_id": source_id,
        "title": str(representative.get("title") or representative.get("url") or ""),
        "url": str(representative.get("url") or canonical_url),
        "canonical_url": canonical_url,
        "content": _compact(content_text),
        "content_kind": content_kind,
        "published_at": published_at,
        "source": primary_source,
        "providers": sorted({provider for provider, _ in contributions}),
        "provider_ranks": provider_ranks,
        "rrf_score": score,
        "body_available": body_available,
        "content_ref": source_id,
        "untrusted_content": True,
    }
    if query_ranks is not None:
        hit["query_ranks"] = query_ranks
        if any("is_primary" in rank for rank in query_ranks):
            hit["primary_query_hit"] = any(rank["is_primary"] for rank in query_ranks)
            hit["variant_support_count"] = sum(not rank["is_primary"] for rank in query_ranks)
    return hit


def _fuse_one_query(
    query: str, rows: list[dict]
) -> tuple[dict[str, list[tuple[str, dict]]], dict[str, float], list[str]]:
    provider_rows = _candidate_rows(query, rows)
    by_url: dict[str, list[tuple[str, dict]]] = {}
    scores: dict[str, float] = {}
    for provider in sorted(provider_rows):
        for canonical_url, row in provider_rows[provider].items():
            by_url.setdefault(canonical_url, []).append((provider, row))
            scores[canonical_url] = scores.get(canonical_url, 0.0) + (
                1.0 / (RRF_RANK_CONSTANT + int(row["provider_rank"]))
            )
    ordered_urls = sorted(by_url, key=lambda url: (-scores[url], url))
    return by_url, scores, ordered_urls


def fuse_search_results(
    query_runs: list[tuple[str, list[dict]]],
    *,
    response_id: str,
    limit: int = SEARCH_RESULT_LIMIT,
    primary_query: str | None = None,
    query_policy: QueryFusionPolicy | None = None,
) -> list[dict[str, Any]]:
    """Fuse provider rankings, then fuse query-angle rankings when expanded."""
    if not query_runs:
        return []
    policy = query_policy or QueryFusionPolicy()
    weights = None
    if policy.mode == "weighted":
        if primary_query is None:
            raise ValueError("weighted fusion requires primary_query")
        weights = policy.weights([query for query, _rows in query_runs], primary_query)
    per_query = [
        (query, *_fuse_one_query(query, rows)) for query, rows in query_runs
    ]
    if len(per_query) == 1:
        _query, by_url, provider_scores, ordered_urls = per_query[0]
        return [
            _public_hit(
                response_id=response_id,
                canonical_url=url,
                contributions=by_url[url],
                score=provider_scores[url],
            )
            for url in ordered_urls[: max(0, int(limit))]
        ]

    contributions: dict[str, list[tuple[str, dict]]] = {}
    query_ranks: dict[str, list[dict[str, Any]]] = {}
    scores: dict[str, float] = {}
    for query, by_url, _provider_scores, ordered_urls in per_query:
        for rank, canonical_url in enumerate(ordered_urls, start=1):
            contributions.setdefault(canonical_url, []).extend(by_url[canonical_url])
            weight = weights[query] if weights is not None else 1.0
            contribution = weight / (RRF_RANK_CONSTANT + rank)
            query_rank: dict[str, Any] = {"query": query, "rank": rank}
            if weights is not None:
                query_rank.update(weight=weight, contribution=contribution,
                                  is_primary=query == primary_query)
            query_ranks.setdefault(canonical_url, []).append(query_rank)
            scores[canonical_url] = scores.get(canonical_url, 0.0) + contribution
    ordered_urls = sorted(contributions, key=lambda url: (-scores[url], url))
    return [
        _public_hit(
            response_id=response_id,
            canonical_url=url,
            contributions=contributions[url],
            score=scores[url],
            query_ranks=query_ranks[url],
        )
        for url in ordered_urls[: max(0, int(limit))]
    ]

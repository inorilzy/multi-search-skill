"""Opt-in JSONL debug log for one CLI invocation (search, fetch, read).

Disabled unless ``--debug-log PATH`` or ``MULTI_SEARCH_DEBUG_LOG`` is set, so
normal runs never write it. ``MULTI_SEARCH_DEBUG_LOG=1`` uses
``~/.multi-search/logs/debug.jsonl``; any other non-false value is a path.

Each line is one event tagged with ``run_id``. Writes are best effort: a log
failure must never change a search result. Every string is scrubbed with the
same redaction rules as user-visible errors plus the runtime key values, and
credentials are never passed in as fields.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .secrets import _iter_secret_strings, scrub_secrets


ENV_VAR = "MULTI_SEARCH_DEBUG_LOG"
BODY_CHARS_ENV_VAR = "MULTI_SEARCH_DEBUG_LOG_BODY_CHARS"
DEFAULT_BODY_CHARS = 2_000
SNIPPET_CHARS = 500
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}

_lock = threading.Lock()
_path: Path | None = None
_run_id = ""
_started = 0.0
_secrets: set[str] = set()


def default_path() -> Path:
    return Path.home() / ".multi-search" / "logs" / "debug.jsonl"


def configure(path: str | None = None) -> Path | None:
    """Start a new run; an explicit path wins over the environment."""
    global _path, _run_id, _started
    raw = path if path is not None else os.environ.get(ENV_VAR, "")
    value = str(raw).strip()
    with _lock:
        if value.lower() in _FALSE:
            _path = None
        elif value.lower() in _TRUE:
            _path = default_path()
        else:
            _path = Path(value).expanduser()
        _run_id = f"run_{uuid.uuid4().hex[:12]}"
        _started = time.monotonic()
        _secrets.clear()
        return _path


def disable() -> None:
    global _path
    with _lock:
        _path = None
        _secrets.clear()


def enabled() -> bool:
    return _path is not None


def add_secrets(values: Any) -> None:
    """Register runtime credential values so they are redacted from every line."""
    if _path is None:
        return
    with _lock:
        _secrets.update(_iter_secret_strings(values))


def body_chars() -> int:
    try:
        return max(0, int(os.environ.get(BODY_CHARS_ENV_VAR, DEFAULT_BODY_CHARS)))
    except ValueError:
        return DEFAULT_BODY_CHARS


def clip(text: Any, limit: int = SNIPPET_CHARS) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"…(+{len(text) - limit} chars)"


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def event(kind: str, **fields: Any) -> None:
    path = _path
    if path is None:
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "run_id": _run_id,
        "t_ms": elapsed_ms(_started),
        "thread": threading.current_thread().name,
        "event": kind,
        **fields,
    }
    try:
        with _lock:
            secrets = tuple(_secrets)
        line = json.dumps(_scrub(record, secrets), ensure_ascii=False, default=str)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
    except Exception:  # noqa: BLE001 - diagnostics must never break a search
        pass


def _scrub(value: Any, secrets: tuple[str, ...]) -> Any:
    # Scrub each string, not the serialized line: the redaction regexes could
    # otherwise consume JSON quotes and corrupt the record.
    if isinstance(value, str):
        return scrub_secrets(value, secrets, limit=len(value) + 64)
    if isinstance(value, dict):
        return {str(key): _scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_scrub(item, secrets) for item in value]
    return value


def row_summary(row: dict, *, snippet_chars: int = SNIPPET_CHARS) -> dict:
    """A provider row or SearchHit without credentials or full bodies."""
    out = {
        key: row.get(key)
        for key in (
            "source", "provider_rank", "title", "url", "error", "error_type",
            "providers", "rrf_score", "relevance_score", "source_id", "content_kind",
        )
        if row.get(key) is not None
    }
    snippet = row.get("content") or row.get("snippet") or row.get("description")
    if snippet:
        out["snippet"] = clip(snippet, snippet_chars)
    return out


def log_search_response(response: dict, started: float) -> None:
    """What the caller receives: ranked hits with snippets and body previews."""
    if not enabled():
        return
    previews = {
        row.get("source_id"): row for row in response.get("scrapes") or []
    }
    results = []
    for rank, hit in enumerate(response.get("results") or [], 1):
        row = {"rank": rank, **row_summary(hit)}
        for key in ("body_available", "body_backend", "body_truncated", "body_error"):
            if key in hit:
                row[key] = hit[key]
        page = previews.get(hit.get("source_id"))
        if page and page.get("markdown"):
            row["body_preview"] = clip(page["markdown"], body_chars())
        results.append(row)
    event(
        "search_response",
        elapsed_ms=elapsed_ms(started),
        query=response.get("query"),
        route=response.get("route"),
        outcome=response.get("outcome"),
        ranking={key: response.get(key) for key in ("mode_requested", "mode_used", "fallback_reason")},
        result_count=len(results),
        results=results,
        errors=response.get("errors"),
        provider_status=response.get("provider_status"),
    )


def log_fetch(source_id, url, started, *, how, backend, body=None, error=None, **extra) -> None:
    fields = {
        "source_id": source_id or None, "url": url, "how": how, "backend": backend,
        "elapsed_ms": elapsed_ms(started), **extra,
    }
    if error is not None:
        fields["error"] = error
    if body is not None:
        fields["content_length"] = len(body)
        fields["body_preview"] = clip(body, body_chars())
    event("fetch_source", **fields)


def log_query_plan(request, expand, query_plan, query_policy, weights) -> None:
    """The caller (e.g. an agent) rewrites the user's question into ``query``
    plus ``expand`` variants; record what reached Core and what Core actually
    runs after trimming and de-duplicating the variants."""
    event(
        "query_plan",
        query=request.query,
        expand_input=list(expand or []),
        expand_from="request" if request.expand is not None else "config" if expand else None,
        primary_query=query_plan.primary_query,
        variants=list(query_plan.variants),
        executed_queries=list(query_plan.queries),
        duplicate_count=query_plan.duplicate_count,
        discarded_blank_count=query_plan.discarded_blank_count,
        fusion=query_policy.to_dict(),
        weights=weights,
    )


def log_route(request, plan, base_sources, active_sources) -> None:
    event(
        "route",
        requested_route=request.route,
        resolved_route=plan.route,
        requested_sources=list(request.sources or []),
        route_sources=sorted(base_sources),
        disabled_sources=sorted(plan.disabled_sources),
        active_sources=sorted(active_sources),
        per_provider_counts=plan.effective_counts,
        search_timeout_s=plan.timeout,
        serpapi_engine=plan.serpapi_engine,
        use_state=request.use_state,
    )


def timed_query(run, query: str, *, deadline: float) -> list[dict]:
    started = time.monotonic()
    rows = run(query, deadline=deadline)
    event(
        "query_done", query=query, elapsed_ms=elapsed_ms(started), row_count=len(rows),
        hit_count=sum(1 for row in rows if row.get("url") and not row.get("error")),
        error_count=sum(1 for row in rows if row.get("error")),
    )
    return rows


def log_fusion(hits: list[dict], raw_row_count: int, started: float) -> None:
    event(
        "search_stage_done", elapsed_ms=elapsed_ms(started),
        raw_row_count=raw_row_count, fused_candidate_count=len(hits),
    )
    if enabled():
        event("fusion", candidates=[
            {"rank": index, **row_summary(hit), "provider_ranks": hit.get("provider_ranks")}
            for index, hit in enumerate(hits, 1)
        ])


def log_rerank(hits: list[dict], meta: dict, started: float) -> None:
    event(
        "rerank", elapsed_ms=elapsed_ms(started), **meta,
        order=[
            {"rank": index, "url": hit.get("url"), "relevance_score": hit.get("relevance_score")}
            for index, hit in enumerate(hits, 1)
        ],
    )

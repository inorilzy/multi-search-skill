"""Explicit evaluation capture and offline replay through the production fusion seam."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .candidate import RRF_RANK_CONSTANT, SEARCH_RESULT_LIMIT, fuse_search_results
from .capabilities import retention_policy_for_sources
from .query_plan import build_query_plan
from ..support.config import load_config
from ..support.models import ANSWER_SOURCES, as_dicts, search_content
from ..support.secrets import scrub_secrets


SCHEMA_VERSION = 2
FUSION_ALGORITHM = {
    "algorithm": "two_level_rrf", "rank_constant": RRF_RANK_CONSTANT, "rank_window": None,
}
# Only fields consumed by candidate fusion or its diagnostic filters are retained.
ROW_FIELDS = frozenset({
    "source", "title", "url", "provider_rank", "score", "description", "content",
    "content_kind", "body_available", "published_at", "published_date", "date",
    "created_at", "error", "status", "_empty", "raw_hits",
})


def _expiry(snapshot: dict) -> float:
    value = snapshot.get("expires_at")
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError("snapshot is missing a finite numeric retention expiry")
    return float(value)


def _sanitize(value: Any, secrets: dict) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(https?://)[^\s/@]+@", r"\1<redacted>@", value, flags=re.I)
        value = re.sub(r"((?:password|secret|signature|access_token|cookie)=)[^&\s]+", r"\1<redacted>", value, flags=re.I)
        return scrub_secrets(value, secrets, limit=len(value) + 100)
    return value


def _content_replay_projection(snapshot: dict) -> dict:
    """Keep every input except snippet text, including its eligibility and kind."""
    projected = copy.deepcopy(snapshot)
    for run in projected["query_runs"]:
        for row in run["rows"]:
            interpreted = search_content(row)
            for field in ("description", "content"):
                if field in row and isinstance(row[field], str):
                    row[field] = "<text>"
            row["_snippet_projection"] = (
                bool(interpreted.snippet.strip()), interpreted.snippet_kind,
                bool(interpreted.body),
            )
    return projected


def _fusion_projection(snapshot: dict) -> list:
    runs = [(run["query"], run["rows"]) for run in snapshot["query_runs"]]
    limit = sum(len(rows) for _, rows in runs)
    return [
        [{key: value for key, value in hit.items() if key != "content"}
         for hit in fuse_search_results(selected, response_id=snapshot["response_id"], limit=limit)]
        for selected in ([runs] + [[run] for run in runs])
    ]


def _proof_digest(snapshot: dict) -> str:
    payload = {key: value for key, value in snapshot.items() if key != "sanitized_content_proof"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def capture_snapshot(request, *, expand: list[str], providers=None, keys=None, config=None) -> dict:
    """Capture only an explicitly supplied question and explicitly chosen variants.

    Provider wrappers count actual attempts (including key retries). The Core
    observer supplies the post-timeout, post-retry rows and original provider ranks.
    """
    from ..service import MultiSearchRequest, SearchWebRequest, _run_search_candidates
    from ..state.keys import load_keys
    from .registry import build_provider_registry
    from .resolve import resolve_search_plan

    request = SearchWebRequest(**request) if isinstance(request, dict) else request
    logical = build_query_plan(request.query, expand)
    request = replace(request, expand=list(logical.variants), use_state=False)
    config = dict(load_config(request.config_path) if config is None else config)
    config.update(expand=[], expand_queries=[])
    keys = load_keys() if keys is None else dict(keys)
    providers = build_provider_registry() if providers is None else providers
    plan = resolve_search_plan(MultiSearchRequest(
        query=request.query, route=request.route, count=request.count,
        sources=request.sources, timeout=request.timeout, scrape_top=0,
    ), config)
    attempts: list[dict] = []
    lock = Lock()
    observed = []

    def observe(query_runs):
        observed.extend(copy.deepcopy(query_runs))

    def wrap(spec):
        def call(query, runner_config, context, key):
            attempt = {"provider": spec.public_name, "query": query, "elapsed_seconds": None, "status": "running"}
            with lock:
                attempts.append(attempt)
            start = time.perf_counter()
            try:
                result = spec.call(query, runner_config, context, key)
                errors = [row["error"] for row in as_dicts(result or []) if row.get("error")]
                with lock:
                    attempt["status"] = "error" if errors else "ok"
                    retention = retention_policy_for_sources([spec.public_name])
                    attempt["errors"] = (
                        _sanitize(errors, keys) if retention.persist_search_result and retention.persist_content
                        else ["provider diagnostic omitted by retention policy"] if errors else []
                    )
                return result
            except Exception:
                with lock:
                    attempt["status"] = "exception"
                raise
            finally:
                with lock:
                    attempt["elapsed_seconds"] = time.perf_counter() - start
        return replace(spec, call=call)

    captured_at = time.time()
    start = time.perf_counter()
    actual = _run_search_candidates(
        request, providers={name: wrap(spec) for name, spec in providers.items()},
        keys=keys, config=config, query_runs_observer=observe,
    )
    elapsed = time.perf_counter() - start
    if [query for query, _rows in observed] != list(logical.queries):
        raise ValueError("Core did not capture the complete logical query set")
    runs = []
    ttl = []
    unavailable = sorted(set(actual["diagnostics"]["active_sources"]) - set(providers))
    for query, rows in observed:
        retained = []
        restrictions = []
        for row in rows:
            retention = retention_policy_for_sources([str(row.get("source") or "")])
            ttl.append(retention.max_ttl_seconds)
            if not retention.persist_search_result:
                restrictions.append({"provider": row.get("source"), "reason": "search_result_retention_forbidden"})
                continue
            saved = {key: copy.deepcopy(value) for key, value in row.items() if key in ROW_FIELDS}
            saved["body_available"] = bool(search_content(row).body or row.get("body_available"))
            if not retention.persist_content:
                saved.pop("content", None)
                saved.pop("description", None)
                if saved.get("error"):
                    saved["error"] = "provider diagnostic omitted by retention policy"
                restrictions.append({"provider": row.get("source"), "reason": "content_retention_forbidden"})
            retained.append(saved)
        runs.append({"query": query, "rows": retained, "retained_row_count": len(retained), "restrictions": restrictions, "captured": True})
    with lock:
        recorded_attempts = copy.deepcopy(attempts)
    errors = []
    for error in actual["errors"]:
        retention = retention_policy_for_sources([error["source"]])
        errors.append(dict(error, error="provider diagnostic omitted by retention policy")
                      if not retention.persist_search_result or not retention.persist_content else error)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "fusion": dict(FUSION_ALGORITHM),
        "data_origin": "capture",
        "response_id": actual["response_id"],
        "primary_query": logical.primary_query,
        "variants": list(logical.variants),
        "captured_at": datetime.fromtimestamp(captured_at, timezone.utc).isoformat(),
        "expires_at": captured_at + min(ttl or [3600]),
        "execution": {
            "route": plan.route, "active_sources": actual["diagnostics"]["active_sources"],
            "count": request.count if request.count is not None else int(plan.route_defaults["count"]),
            "result_limit": SEARCH_RESULT_LIMIT,
            "provider_counts": plan.effective_counts, "timeout": plan.timeout,
            "serpapi_engine": plan.serpapi_engine, "expand": list(logical.variants),
            "expansion_origin": "explicit_capture_argument", "use_state": False,
            "unavailable_providers": unavailable,
            "query_fusion": copy.deepcopy(config.get("query_fusion") or {"mode": "equal"}),
        },
        "query_runs": runs,
        "collection": {
            "elapsed_seconds": elapsed, "provider_attempt_count": len(recorded_attempts),
            "provider_attempts": sorted(recorded_attempts, key=lambda item: (item["query"], item["provider"])),
            "price": None, "price_status": "unknown",
            "errors": errors,
        },
    }
    sanitized = _sanitize(snapshot, keys)
    content_only = (
        _content_replay_projection(snapshot) == _content_replay_projection(sanitized)
        and _fusion_projection(snapshot) == _fusion_projection(sanitized)
    )
    sanitized["credentials_redacted"] = sanitized != snapshot
    if content_only:
        sanitized["sanitized_content_proof"] = {"version": 1, "sha256": _proof_digest(sanitized)}
    return sanitized


def replay_snapshot(snapshot: dict, *, mode: str = "equal", omit_variants=(), limit=None, query_policy=None, fidelity="exact") -> dict:
    """Replay retained provider rows; no registry, provider, keys or networking needed."""
    start = time.perf_counter()
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported snapshot schema_version")
    if snapshot.get("fusion") != FUSION_ALGORITHM:
        raise ValueError("unsupported snapshot fusion algorithm")
    if fidelity not in {"exact", "sanitized_content"}:
        raise ValueError("fidelity must be exact or sanitized_content")
    if fidelity == "exact" and snapshot.get("credentials_redacted"):
        raise ValueError("snapshot required credential redaction; exact replay unavailable")
    if fidelity == "sanitized_content":
        proof = snapshot.get("sanitized_content_proof")
        if (not isinstance(proof, dict) or proof.get("version") != 1
                or proof.get("sha256") != _proof_digest(snapshot)):
            raise ValueError("snapshot lacks valid capture proof for sanitized_content replay")
    if _expiry(snapshot) <= time.time():
        raise ValueError("snapshot expired or missing retention expiry")
    try:
        logical = build_query_plan(snapshot["primary_query"], snapshot["variants"])
        stored_runs = snapshot["query_runs"]
        count = snapshot["execution"]["result_limit"] if limit is None else limit
        response_id = snapshot["response_id"]
    except (KeyError, TypeError) as exc:
        raise ValueError("snapshot is missing required replay data") from exc
    if snapshot["execution"].get("unavailable_providers"):
        raise ValueError("snapshot has unavailable provider data")
    if mode not in {"primary", "equal", "weighted"}:
        raise ValueError("mode must be primary, equal or weighted")
    omitted = set(omit_variants)
    if omitted - set(logical.variants):
        raise ValueError("omit_variants must name captured variants, never the primary query")
    if [run.get("query") for run in stored_runs] != list(logical.queries):
        raise ValueError("snapshot query data is missing, duplicated or not canonical")
    selected = [logical.primary_query] if mode == "primary" else [query for query in logical.queries if query not in omitted]
    runs = []
    for run in stored_runs:
        if run["query"] not in selected:
            continue
        if run.get("captured") is not True or "rows" not in run or "restrictions" not in run:
            raise ValueError("snapshot is missing captured provider data")
        if run["restrictions"]:
            raise ValueError("source retention restricts exact replay of selected query")
        if run.get("retained_row_count") != len(run["rows"]):
            raise ValueError("snapshot provider rows are missing")
        for row in run["rows"]:
            if row.get("url") and not row.get("error") and row.get("source") not in ANSWER_SOURCES and not row.get("provider_rank"):
                raise ValueError("snapshot candidate is missing its original provider rank")
        runs.append((run["query"], run["rows"]))
    options = {}
    if mode == "weighted":
        if query_policy is None or query_policy.mode != "weighted":
            raise ValueError("weighted replay requires an explicit query_policy")
        options = {"primary_query": logical.primary_query, "query_policy": query_policy}
    results = fuse_search_results(runs, response_id=response_id, limit=count, **options)
    return {
        "mode": mode, "fidelity": fidelity, "queries": selected, "limit": count, "results": results,
        "data_origin": snapshot.get("data_origin"), "expires_at": snapshot["expires_at"],
        "collection": snapshot.get("collection"),
        "offline_replay_seconds": time.perf_counter() - start,
    }


def compare_snapshot(snapshot: dict, *, mode="equal", omit_variants=(), limit=None, query_policy=None, fidelity="exact") -> dict:
    """Compare to primary-only, or compare ablation to the full query strategy."""
    baseline = replay_snapshot(snapshot, mode=mode if omit_variants else "primary", limit=limit, query_policy=query_policy, fidelity=fidelity)
    candidate = replay_snapshot(snapshot, mode=mode, omit_variants=omit_variants, limit=limit, query_policy=query_policy, fidelity=fidelity)
    before = {hit["canonical_url"]: rank for rank, hit in enumerate(baseline["results"], 1)}
    after = {hit["canonical_url"]: rank for rank, hit in enumerate(candidate["results"], 1)}
    return {
        "baseline": baseline, "candidate": candidate,
        "difference": {
            "added": [url for url in after if url not in before],
            "lost": [url for url in before if url not in after],
            "rank_changes": [
                {"canonical_url": url, "before": before[url], "after": after[url]}
                for url in after if url in before and before[url] != after[url]
            ],
        },
    }


def write_snapshot(snapshot: dict, path: str | Path) -> None:
    """Write a captured snapshot; refuse overwriting an existing evaluation."""
    if _expiry(snapshot) <= time.time():
        raise ValueError("cannot persist an expired snapshot")
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def load_snapshot(path: str | Path) -> dict:
    """Read a snapshot and remove expired retained content when encountered."""
    path = Path(path)
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported snapshot schema_version")
    if snapshot.get("fusion") != FUSION_ALGORITHM:
        raise ValueError("unsupported snapshot fusion algorithm")
    if _expiry(snapshot) <= time.time():
        path.unlink()
        raise ValueError("snapshot expired; retained snapshot file removed")
    return snapshot

"""Read-only local web viewer for the per-run debug logs (``logs serve``).

Data shaping lives here in Python so it is testable; the page in
``log_viewer_page`` only renders the JSON returned by ``/api/runs``.
The server binds to loopback, accepts only loopback Host headers (DNS
rebinding), never writes, and serves log text as data under a strict CSP.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .support import debug_log


DEFAULT_PORT = 8765
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_RUN_ID_RE = re.compile(r"^run_[0-9a-f]{12}$")


def default_sources() -> list[Path]:
    return [debug_log.runs_dir()]


def _files(sources: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for source in sources:
        if source.is_dir():
            files.extend(item for item in source.glob("*.jsonl") if item.is_file())
        elif source.is_file():
            files.append(source)
    return files


def load_runs(sources: Iterable[Path]) -> dict[str, list[dict]]:
    """Group every readable event by ``run_id``; malformed lines are skipped."""
    runs: dict[str, list[dict]] = {}
    for path in _files(sources):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and isinstance(event.get("run_id"), str):
                runs.setdefault(event["run_id"], []).append(event)
    for events in runs.values():
        events.sort(key=lambda event: (event.get("t_ms") or 0, event.get("ts") or ""))
    return runs


def _first(events: list[dict], kind: str) -> dict:
    return next((event for event in events if event.get("event") == kind), {})


def _all(events: list[dict], kind: str) -> list[dict]:
    return [event for event in events if event.get("event") == kind]


def summarize_run(run_id: str, events: list[dict]) -> dict:
    request = _first(events, "cli_request")
    parameters = request.get("parameters") or {}
    response = _first(events, "search_response")
    exit_event = _first(events, "cli_exit")
    route = _first(events, "route")
    return {
        "run_id": run_id,
        "ts": min((str(event.get("ts") or "") for event in events), default=""),
        "command": request.get("command") or parameters.get("command"),
        "query": parameters.get("query") or parameters.get("url") or parameters.get("source_id"),
        "route": route.get("resolved_route"),
        "outcome": response.get("outcome") or exit_event.get("outcome")
        or ("failed" if exit_event.get("exit_code") else None),
        "elapsed_ms": exit_event.get("elapsed_ms") or response.get("elapsed_ms"),
        "result_count": response.get("result_count"),
        "error": exit_event.get("error"),
        "complete": bool(exit_event),
    }


def list_runs(runs: dict[str, list[dict]], limit: int = 500) -> list[dict]:
    rows = [summarize_run(run_id, events) for run_id, events in runs.items()]
    rows.sort(key=lambda row: row["ts"], reverse=True)
    return rows[:limit]


def _providers(events: list[dict]) -> list[dict]:
    attempts: dict[tuple, list[dict]] = {}
    for attempt in _all(events, "provider_attempt"):
        attempts.setdefault((attempt.get("query"), attempt.get("source")), []).append({
            key: attempt.get(key)
            for key in ("t_ms", "elapsed_ms", "keyed", "timeout_s", "row_count", "errors", "error")
        })
    rows = []
    for result in _all(events, "provider_result"):
        key = (result.get("query"), result.get("source"))
        rows.append({
            key_name: result.get(key_name)
            for key_name in ("query", "source", "elapsed_ms", "status", "hit_count", "errors", "rows", "t_ms")
        } | {"attempts": attempts.get(key, [])})
    return rows


def _ranking(events: list[dict]) -> dict:
    fusion = _first(events, "fusion").get("candidates") or []
    rerank = _first(events, "rerank")
    response = _first(events, "search_response")
    # source_id is the per-response identity of a fused hit; two hits can share
    # a display URL, so URL is only the fallback for older traces.
    def identity(row: dict) -> Any:
        return row.get("source_id") or row.get("url")

    rrf_rank = {identity(row): row.get("rank") for row in fusion}
    by_identity = {identity(row): row for row in fusion}
    final = response.get("results") or fusion
    rows = []
    for index, row in enumerate(final, 1):
        merged = {**by_identity.get(identity(row), {}), **row}
        rows.append({
            "final_rank": index,
            "rrf_rank": rrf_rank.get(identity(row)),
            **{key: merged.get(key) for key in (
                "title", "url", "source", "providers", "provider_ranks", "rrf_score",
                "relevance_score", "snippet", "body_available", "body_backend",
                "body_truncated", "body_error", "body_preview",
            )},
        })
    return {
        "mode_requested": rerank.get("mode_requested") or (response.get("ranking") or {}).get("mode_requested"),
        "mode_used": rerank.get("mode_used") or (response.get("ranking") or {}).get("mode_used"),
        "fallback_reason": rerank.get("fallback_reason") or (response.get("ranking") or {}).get("fallback_reason"),
        "rerank_ms": rerank.get("elapsed_ms"),
        "fused_count": len(fusion),
        "rows": rows,
    }


def _fetches(events: list[dict], order: list[str]) -> list[dict]:
    pages: dict[str, dict] = {}

    def page(url: Any) -> dict:
        return pages.setdefault(str(url or "?"), {
            "url": str(url or "?"), "chain": None, "attempts": [], "key_attempts": [], "result": None,
        })

    for event in events:
        kind = event.get("event")
        if kind == "scrape_chain":
            page(event.get("url"))["chain"] = event
        elif kind == "scrape_attempt":
            page(event.get("url"))["attempts"].append(event)
        elif kind == "scrape_key_attempt":
            page(event.get("url"))["key_attempts"].append(event)
        elif kind in {"fetch_source", "fetch_failed"}:
            page(event.get("url"))["result"] = event
    # A fetch still running at the stage deadline is abandoned before it can
    # log a result or a backend outcome; reconstruct both from what did log.
    done = _first(events, "fetch_stage_done")
    failures = {str(row.get("url")): row.get("error") for row in done.get("failures") or []}
    for item in pages.values():
        attempted = {attempt.get("backend") for attempt in item["attempts"]}
        for backend in dict.fromkeys(key.get("backend") for key in item["key_attempts"]):
            if backend in attempted:
                continue
            keys = [key for key in item["key_attempts"] if key.get("backend") == backend]
            item["attempts"].append({
                "backend": backend, "status": "timeout" if done else "running",
                "elapsed_ms": sum(int(key.get("elapsed_ms") or 0) for key in keys),
                "error": keys[-1].get("error"),
            })
        if item["result"] is None and done:
            started = (item["chain"] or {}).get("t_ms")
            item["result"] = {
                "event": "fetch_timeout", "url": item["url"], "t_ms": done.get("t_ms"),
                "elapsed_ms": (done.get("t_ms") or 0) - started if started is not None else None,
                "error": failures.get(item["url"]) or "fetch stage ended before this page finished",
            }
    rank = {url: index for index, url in enumerate(order)}
    return sorted(pages.values(), key=lambda item: (rank.get(item["url"], len(rank)), item["url"]))


def build_detail(run_id: str, events: list[dict]) -> dict:
    ranking = _ranking(events)
    response = _first(events, "search_response")
    return {
        "summary": summarize_run(run_id, events),
        "request": _first(events, "cli_request"),
        "route": _first(events, "route"),
        "query_plan": _first(events, "query_plan"),
        "queries": _all(events, "query_done"),
        "providers": _providers(events),
        "ranking": ranking,
        "fetch_stage": {
            "start": _first(events, "fetch_stage_start"),
            "done": _first(events, "fetch_stage_done"),
        },
        "fetches": _fetches(events, [str(row.get("url")) for row in ranking["rows"]]),
        "stages": {
            "search_ms": _first(events, "search_stage_done").get("elapsed_ms"),
            "rerank_ms": ranking["rerank_ms"],
            "fetch_ms": _first(events, "fetch_stage_done").get("elapsed_ms"),
            "total_ms": _first(events, "cli_exit").get("elapsed_ms") or response.get("elapsed_ms"),
        },
        "errors": response.get("errors") or [],
        "exit": _first(events, "cli_exit"),
        "events": events,
    }


class _Handler(BaseHTTPRequestHandler):
    sources: list[Path] = []
    server_version = "multi-search-logs"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        pass  # Request lines would echo queries into the terminal.

    def _loopback_host(self) -> bool:
        host = self.headers.get("Host") or ""
        try:
            hostname = urlsplit(f"//{host}").hostname or ""
        except ValueError:
            return False
        return hostname.lower() in _LOOPBACK_HOSTS

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        from . import log_viewer_page as page

        if not self._loopback_host():
            self._send(403, b"forbidden host", "text/plain; charset=utf-8")
            return
        path = urlsplit(self.path).path
        if path == "/":
            self._send(200, page.HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/app.js":
            self._send(200, page.SCRIPT.encode("utf-8"), "text/javascript; charset=utf-8")
        elif path == "/app.css":
            self._send(200, page.STYLE.encode("utf-8"), "text/css; charset=utf-8")
        elif path == "/api/runs":
            self._json({"sources": [str(item) for item in self.sources],
                        "runs": list_runs(load_runs(self.sources))})
        elif path.startswith("/api/runs/") and _RUN_ID_RE.match(path.rsplit("/", 1)[1]):
            run_id = path.rsplit("/", 1)[1]
            events = load_runs(self.sources).get(run_id)
            if events is None:
                self._json({"error": "run not found"}, 404)
            else:
                self._json(build_detail(run_id, events))
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")


def make_server(sources: list[Path], port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Bind to loopback only; there is deliberately no host option."""
    handler = type("LogViewerHandler", (_Handler,), {"sources": list(sources)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server

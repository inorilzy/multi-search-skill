"""Thin CLI over the shared multi-search core service layer."""
from __future__ import annotations

import argparse
import io
import json
import sys
from collections.abc import Sequence
from typing import Any, TextIO

from .src.service import (
    FetchSourceRequest,
    ReadSourceRequest,
    SearchWebRequest,
    doctor_data,
    run_fetch_source,
    run_read_source,
    run_search_web,
)
from .src.support.format import format_scrapes
from .src.state.key_state import SQLiteKeyManager
from .src.state.state_store import StateStore


OUTPUT_FORMATS = ("json", "human", "markdown")


class CLIUsageError(ValueError):
    """Raised for invalid CLI usage after parsing."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - exercised via main()
        raise CLIUsageError(message)


def _add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default="json",
        help="output format (default: json)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="multi-search", description="Thin CLI for the shared multi-search core.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="RRF search followed by body fetches for the final 15 URLs")
    search_parser.add_argument("query")
    search_parser.add_argument("--route")
    search_parser.add_argument("--source", action="append", dest="sources", default=[])
    search_parser.add_argument("--count", type=int, help="per-provider recall count; final output is at most 15")
    search_parser.add_argument("--timeout", type=int)
    search_parser.add_argument("--expand", action="append", default=None)
    _add_format_argument(search_parser)
    search_parser.set_defaults(handler=_handle_search)

    fetch_parser = subparsers.add_parser("fetch", help="fetch one source body")
    fetch_parser.add_argument("source_id", nargs="?")
    fetch_parser.add_argument("--url")
    fetch_parser.add_argument("--backend", action="append", dest="backends", default=[])
    fetch_parser.add_argument("--max-chars", type=int, default=20_000)
    fetch_parser.add_argument("--timeout", type=int)
    fetch_parser.add_argument(
        "--full-content", action="store_true",
        help="return the entire acquired body, overriding --max-chars",
    )
    _add_format_argument(fetch_parser)
    fetch_parser.set_defaults(handler=_handle_fetch)

    read_parser = subparsers.add_parser("read", help="read cached content for one source")
    read_parser.add_argument("source_id")
    read_parser.add_argument("--keyword")
    read_parser.add_argument("--offset", type=int, default=0)
    read_parser.add_argument("--limit", type=int, default=4_000)
    _add_format_argument(read_parser)
    read_parser.set_defaults(handler=_handle_read)

    doctor_parser = subparsers.add_parser("doctor", help="show local config and key health")
    doctor_parser.add_argument("--network", action="store_true", help="probe public Hacker News and GitHub API connectivity (5s total budget)")
    doctor_parser.add_argument("--no-keys", action="store_true")
    _add_format_argument(doctor_parser)
    doctor_parser.set_defaults(handler=_handle_doctor)

    keys_parser = subparsers.add_parser("keys", help="inspect or reset key health state")
    keys_subparsers = keys_parser.add_subparsers(dest="keys_command", required=True)

    keys_status_parser = keys_subparsers.add_parser("status", help="show key health rows")
    keys_status_parser.add_argument("--provider")
    _add_format_argument(keys_status_parser)
    keys_status_parser.set_defaults(handler=_handle_keys_status)

    keys_reset_parser = keys_subparsers.add_parser("reset", help="reset key health rows")
    keys_reset_parser.add_argument("--provider")
    keys_reset_parser.add_argument("--key-id")
    _add_format_argument(keys_reset_parser)
    keys_reset_parser.set_defaults(handler=_handle_keys_reset)

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        payload = args.handler(args)
        _write_payload(payload, args.format, stdout)
        if args.command == "search":
            statuses = payload.get("provider_status") or []
            if statuses and all(row.get("status") == "error" for row in statuses):
                stderr.write("error: all selected search providers failed\n")
                return 1
        if args.command == "doctor" and (
            payload.get("config_error") or payload.get("keys_error")
            or payload.get("network_ok") is False
        ):
            stderr.write("error: doctor found configuration, key, or network failures\n")
            return 1
        return 0
    except CLIUsageError as exc:
        stderr.write(f"usage error: {exc}\n")
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary should be explicit and terse
        stderr.write(f"error: {exc}\n")
        return 1


def entrypoint() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, io.TextIOWrapper) and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors=stream.errors)
    raise SystemExit(main())


def _handle_search(args: argparse.Namespace) -> dict[str, Any]:
    return run_search_web(
        SearchWebRequest(
            query=args.query,
            route=args.route,
            count=args.count,
            sources=list(args.sources or []),
            timeout=args.timeout,
            expand=None if args.expand is None else list(args.expand),
        )
    )


def _handle_fetch(args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.source_id) == bool(args.url):
        raise CLIUsageError("provide exactly one of source_id or --url")
    return run_fetch_source(
        FetchSourceRequest(
            source_id=args.source_id,
            url=args.url,
            backends=list(args.backends or []),
            max_chars=args.max_chars,
            timeout=args.timeout,
            full_content=args.full_content,
        )
    )


def _handle_read(args: argparse.Namespace) -> dict[str, Any]:
    return run_read_source(
        ReadSourceRequest(
            source_id=args.source_id,
            keyword=args.keyword,
            offset=args.offset,
            limit=args.limit,
        )
    )


def _handle_doctor(args: argparse.Namespace) -> dict[str, Any]:
    return doctor_data(include_keys=not args.no_keys, include_network=args.network)


def _handle_keys_status(args: argparse.Namespace) -> dict[str, Any]:
    manager = SQLiteKeyManager(StateStore())
    return {"key_status": manager.status_rows(args.provider)}


def _handle_keys_reset(args: argparse.Namespace) -> dict[str, Any]:
    manager = SQLiteKeyManager(StateStore())
    return {"updated": manager.reset(provider=args.provider, key_id=args.key_id)}


def _write_payload(payload: Any, output_format: str, stream: TextIO) -> None:
    if output_format == "json":
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif output_format == "human":
        stream.write(_render_human(payload))
    elif output_format == "markdown":
        stream.write(_render_markdown(payload))
    else:  # pragma: no cover - argparse constrains values
        raise CLIUsageError(f"unsupported format: {output_format}")
    stream.write("\n")


def _render_human(payload: Any) -> str:
    if _is_search_payload(payload):
        return _render_search(payload, markdown=False)
    if isinstance(payload, dict) and set(payload) == {"key_status"} and isinstance(payload["key_status"], list):
        rows = ["key_status:"]
        rows.extend(_render_key_rows(payload["key_status"], markdown=False))
        return "\n".join(rows)
    if isinstance(payload, dict) and "content" in payload:
        lines = _render_mapping(payload)
        lines.append("content:")
        lines.append(str(payload.get("content") or ""))
        return "\n".join(lines)
    return "\n".join(_render_mapping(payload))


def _render_markdown(payload: Any) -> str:
    if _is_search_payload(payload):
        return _render_search(payload, markdown=True)
    if isinstance(payload, dict) and set(payload) == {"key_status"} and isinstance(payload["key_status"], list):
        rows = ["# Key Status", ""]
        rows.extend(_render_key_rows(payload["key_status"], markdown=True))
        return "\n".join(rows).rstrip()
    if isinstance(payload, dict) and "content" in payload:
        lines = ["# Content", ""]
        lines.extend(f"- {line}" for line in _render_mapping(payload))
        lines.append("")
        lines.append("```text")
        lines.append(str(payload.get("content") or ""))
        lines.append("```")
        return "\n".join(lines)
    lines = ["# Output", ""]
    lines.extend(f"- {line}" for line in _render_mapping(payload))
    return "\n".join(lines)


def _render_search(payload: dict[str, Any], *, markdown: bool) -> str:
    if isinstance(payload.get("markdown"), str):
        return payload["markdown"]
    query = str(payload.get("query") or "")
    route = str(payload.get("route") or "")
    results = payload.get("display_results") or payload.get("results") or []
    bodies = format_scrapes(payload.get("scrapes") or [], max_chars=20_000)
    errors = payload.get("errors") or []
    failures = ""
    if errors:
        lines = ["", "## Errors" if markdown else "errors:"]
        for error in errors:
            query_label = f" ({error['query']})" if error.get("query") else ""
            lines.append(f"- {error.get('source', '?')}{query_label}: {error.get('error', '')}")
        failures = "\n".join(lines)
    if markdown:
        lines = ["# Search", ""]
        lines.append(f"- query: {query}")
        if route:
            lines.append(f"- route: {route}")
        lines.append("")
        if not results:
            lines.append("_No results_")
            return "\n".join(lines) + bodies + failures
        for item in results:
            title = str(item.get("title") or item.get("url") or "")
            url = str(item.get("url") or "")
            source = str(item.get("source") or "")
            snippet = str(
                item.get("content") or item.get("snippet") or item.get("description") or ""
            ).strip()
            lines.append(f"- {title} [{source}]")
            if url:
                lines.append(f"  {url}")
            if snippet:
                lines.append(f"  {snippet}")
        return "\n".join(lines) + bodies + failures

    lines = [f"query: {query}"]
    if route:
        lines.append(f"route: {route}")
    if not results:
        lines.append("results: none")
        return "\n".join(lines) + bodies + failures
    lines.append("results:")
    for item in results:
        title = str(item.get("title") or item.get("url") or "")
        url = str(item.get("url") or "")
        source = str(item.get("source") or "")
        snippet = str(
            item.get("content") or item.get("snippet") or item.get("description") or ""
        ).strip()
        lines.append(f"- [{source}] {title}")
        if url:
            lines.append(f"  {url}")
        if snippet:
            lines.append(f"  {snippet}")
    return "\n".join(lines) + bodies + failures


def _is_search_payload(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and "query" in payload
        and isinstance(payload.get("results"), list)
    )


def _render_key_rows(rows: list[dict[str, Any]], *, markdown: bool) -> list[str]:
    if not rows:
        return ["_No key rows_" if markdown else "none"]
    rendered = []
    for row in rows:
        provider = row.get("provider")
        key_id = row.get("key_id")
        status = row.get("status")
        if markdown:
            rendered.append(f"- {provider} {key_id}: {status}")
        else:
            rendered.append(f"- {provider} {key_id}: {status}")
    return rendered


def _render_mapping(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return [str(payload)]
    rows = []
    for key in sorted(payload):
        value = payload[key]
        if key == "content":
            continue
        rows.append(f"{key}: {_stringify(value)}")
    return rows


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


if __name__ == "__main__":
    entrypoint()

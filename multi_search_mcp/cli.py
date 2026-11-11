"""Thin CLI over the shared multi-search core service layer."""
from __future__ import annotations

import argparse
import io
import importlib.metadata
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
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
from .src.state.operations import (
    key_status,
    reset_key_state,
    reset_site_scraper_stats,
    set_site_scraper_preference,
    site_scraper_stats,
)
from .src.support import debug_log
from .src.support.backends import KNOWN_BACKENDS
from .src.support.format import format_scrapes, ranking_mode_label
from .src.support.secrets import scrub_secrets


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


def _add_debug_log_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--debug-log", metavar="PATH",
        help=(
            "append this run's detailed JSONL trace (parameters, query plan, "
            "route, per-provider timings and results, fetch chain) to PATH "
            "even when the debug_log setting is off; the desktop switch writes "
            "~/.multi-search/logs/runs/ files read by `logs serve`; "
            f"{debug_log.ENV_VAR}=1/0 overrides the setting"
        ),
    )


def _bounded_int(minimum: int, maximum: int | None):
    """argparse type: an integer within [minimum, maximum], else a usage error."""
    def parse(raw: str) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise argparse.ArgumentTypeError(f"expected an integer, got {raw!r}") from None
        if value < minimum or (maximum is not None and value > maximum):
            bounds = f"{minimum}-{maximum}" if maximum is not None else f"{minimum} or more"
            raise argparse.ArgumentTypeError(f"must be {bounds}, got {value}")
        return value

    parse.__name__ = "integer"
    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="multi-search", description="Thin CLI for the shared multi-search core.")
    try:
        installed_version = importlib.metadata.version("multi-search-mcp")
    except importlib.metadata.PackageNotFoundError:
        installed_version = "uninstalled"
    parser.add_argument("--version", action="version", version=f"multi-search {installed_version}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser(
        "search",
        help="RRF search followed by body fetches for the final 15 URLs",
        description=(
            "RRF search followed by body fetches for the final 15 URLs. "
            "Put options first and pass the query after `--` "
            "(`multi-search search [options] -- <query>`) so a query that starts "
            "with `-` is never read as an option."
        ),
    )
    search_parser.add_argument(
        "query",
        help="search text; use `search [options] -- <query>` when it may start with `-`",
    )
    search_parser.add_argument("--route")
    search_parser.add_argument("--source", action="append", dest="sources", default=[])
    search_parser.add_argument("--count", type=int, help="per-provider recall count; final output is at most 15")
    search_parser.add_argument("--timeout", type=int)
    search_parser.add_argument("--expand", action="append", default=None)
    search_parser.add_argument(
        "--no-fetch", action="store_true",
        help="candidates only: fuse ranked hits but never fetch page bodies or write the body cache",
    )
    search_parser.add_argument(
        "--rerank", action="store_true",
        help=(
            "reorder the fused RRF candidates with a System One scoring model "
            "before the body-fetch stage (ranking.mode=rrf_model); on any "
            "model failure the complete RRF order is kept and the response "
            "reports mode_used/fallback_reason. The key is read from "
            "SYSTEMONE_API_KEY or the 'systemone' entry of ~/.multi-search/keys.json"
        ),
    )
    search_parser.add_argument(
        "--rerank-base-url", metavar="URL",
        help="System One base URL for --rerank (ranking.base_url), e.g. http://127.0.0.1:3425/v1",
    )
    search_parser.add_argument(
        "--rerank-model", metavar="MODEL",
        help="System One model for --rerank (ranking.model)",
    )
    search_parser.add_argument(
        "--no-state", action="store_true",
        help="skip SQLite key rotation, content cache, and site memory (clean test/debug runs)",
    )
    _add_debug_log_argument(search_parser)
    _add_format_argument(search_parser)
    search_parser.set_defaults(handler=_handle_search)

    fetch_parser = subparsers.add_parser("fetch", help="fetch one source body")
    fetch_parser.add_argument("source_id", nargs="?")
    fetch_parser.add_argument("--url")
    fetch_parser.add_argument(
        "--url-file",
        metavar="PATH",
        help="read the URL from a UTF-8 file, or from stdin with '-'",
    )
    fetch_parser.add_argument("--backend", action="append", dest="backends", default=[])
    fetch_parser.add_argument(
        "--max-chars", type=_bounded_int(1, None), default=20_000,
        help="preview size in characters, at least 1; values above 20000 use 20000 (default 20000)",
    )
    fetch_parser.add_argument("--timeout", type=int)
    fetch_parser.add_argument(
        "--full-content", action="store_true",
        help="return the entire acquired body, overriding --max-chars",
    )
    fetch_parser.add_argument(
        "--no-state", action="store_true",
        help="skip SQLite key rotation and the content cache (clean test/debug runs)",
    )
    _add_debug_log_argument(fetch_parser)
    _add_format_argument(fetch_parser)
    fetch_parser.set_defaults(handler=_handle_fetch)

    read_parser = subparsers.add_parser("read", help="read cached content for one source")
    read_parser.add_argument("source_id")
    read_parser.add_argument("--keyword")
    read_parser.add_argument(
        "--offset", type=_bounded_int(0, None), default=0,
        help="character offset, 0 or more (relative to the match with --keyword)",
    )
    read_parser.add_argument(
        "--limit", type=_bounded_int(1, None), default=4_000,
        help="characters to return, at least 1; values above 8000 use 8000 (default 4000)",
    )
    read_parser.add_argument(
        "--no-state", action="store_true",
        help="read without the shared content cache (clean test/debug runs)",
    )
    _add_format_argument(read_parser)
    read_parser.set_defaults(handler=_handle_read)

    doctor_parser = subparsers.add_parser("doctor", help="show local config and key health")
    doctor_parser.add_argument("--network", action="store_true", help="probe public Hacker News and GitHub API connectivity (5s total budget)")
    doctor_parser.add_argument("--no-keys", action="store_true")
    _add_format_argument(doctor_parser)
    doctor_parser.set_defaults(handler=_handle_doctor)

    sources_parser = subparsers.add_parser(
        "sources",
        help="print the shared source, route, alias, and env catalog (JSON by default)",
    )
    sources_parser.add_argument(
        "--key-status", "--include-key-status", dest="key_status", action="store_true",
        help="include current key-health rows from the shared state store",
    )
    sources_parser.add_argument(
        "--scraper-stats", "--include-scraper-stats", dest="scraper_stats", action="store_true",
        help="include per-site scraper statistics from the shared state store",
    )
    _add_format_argument(sources_parser)
    sources_parser.set_defaults(handler=_handle_sources)

    routes_parser = subparsers.add_parser(
        "routes",
        help="list the routes the current settings define, with the default route",
    )
    _add_format_argument(routes_parser)
    routes_parser.set_defaults(handler=_handle_routes)

    keys_parser = subparsers.add_parser("keys", help="inspect or reset key health state")
    keys_subparsers = keys_parser.add_subparsers(dest="keys_command", required=True)

    keys_status_parser = keys_subparsers.add_parser("status", help="show key health rows")
    keys_status_parser.add_argument("--provider")
    _add_format_argument(keys_status_parser)
    keys_status_parser.set_defaults(handler=_handle_keys_status)

    keys_reset_parser = keys_subparsers.add_parser("reset", help="reset key health rows")
    keys_reset_parser.add_argument("--provider")
    keys_reset_parser.add_argument("--key-id")
    keys_reset_parser.add_argument(
        "--all", action="store_true",
        help="confirm resetting all key health rows; cannot be combined with selectors",
    )
    _add_format_argument(keys_reset_parser)
    keys_reset_parser.set_defaults(handler=_handle_keys_reset)

    site_parser = subparsers.add_parser(
        "site", help="inspect or edit per-site scraper statistics and preferences",
    )
    site_subparsers = site_parser.add_subparsers(dest="site_command", required=True)

    site_stats_parser = site_subparsers.add_parser("stats", help="show scraper statistics for one site or all sites")
    site_stats_parser.add_argument("site", nargs="?")
    _add_format_argument(site_stats_parser)
    site_stats_parser.set_defaults(handler=_handle_site_stats)

    site_preference_parser = site_subparsers.add_parser(
        "set-preference", help="pin a scraper for one site key",
    )
    site_preference_parser.add_argument("site")
    site_preference_parser.add_argument("scraper", choices=KNOWN_BACKENDS)
    site_preference_parser.add_argument("--priority", type=int)
    site_preference_parser.add_argument("--note")
    _add_format_argument(site_preference_parser)
    site_preference_parser.set_defaults(handler=_handle_site_set_preference)

    site_reset_parser = site_subparsers.add_parser(
        "reset", help="reset scraper statistics for one site or all sites",
    )
    site_reset_parser.add_argument("site", nargs="?")
    _add_format_argument(site_reset_parser)
    site_reset_parser.set_defaults(handler=_handle_site_reset)

    logs_parser = subparsers.add_parser(
        "logs", help="browse the per-run search traces in a local web page",
    )
    logs_subparsers = logs_parser.add_subparsers(dest="logs_command", required=True)
    logs_serve_parser = logs_subparsers.add_parser(
        "serve", help="serve a read-only trace viewer on 127.0.0.1 until Ctrl+C",
    )
    logs_serve_parser.add_argument("--port", type=_bounded_int(0, 65535), default=8765,
                                   help="local port (default 8765; 0 picks a free port)")
    logs_serve_parser.add_argument(
        "--path", action="append", default=None, metavar="PATH",
        help="trace file or directory to read instead of ~/.multi-search/logs/runs (repeatable)",
    )
    logs_serve_parser.add_argument("--open", action="store_true", help="open the page in the browser")
    _add_format_argument(logs_serve_parser)
    logs_serve_parser.set_defaults(handler=_handle_logs_serve)
    logs_list_parser = logs_subparsers.add_parser("list", help="list recorded runs, newest first")
    logs_list_parser.add_argument("--limit", type=_bounded_int(1, None), default=20)
    logs_list_parser.add_argument("--path", action="append", default=None, metavar="PATH")
    _add_format_argument(logs_list_parser)
    logs_list_parser.set_defaults(handler=_handle_logs_list)

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
    args = None
    started = time.monotonic()
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    try:
        args = parser.parse_args(raw_argv)
        if args.command in {"search", "fetch"}:
            debug_log.configure(getattr(args, "debug_log", None), setting=_debug_log_setting())
        else:
            debug_log.disable()
        debug_log.event(
            "cli_request", command=args.command, argv=raw_argv,
            parameters={
                key: value for key, value in vars(args).items()
                if key not in {"handler", "debug_log"}
            },
        )
        payload = args.handler(args)
        _write_payload(payload, args.format, stdout)
        if args.command == "search":
            debug_log.event(
                "cli_exit", elapsed_ms=debug_log.elapsed_ms(started),
                outcome=payload.get("outcome"),
                exit_code=1 if payload.get("outcome") == "failed" else 0,
            )
        elif args.command == "fetch":
            debug_log.event("cli_exit", elapsed_ms=debug_log.elapsed_ms(started), exit_code=0)
        if args.command == "search" and payload.get("outcome") == "failed":
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
        # The last line of defence for secrets: a provider or store error that
        # embeds a key, token, or cookie is redacted before it reaches stdout/stderr.
        message = scrub_secrets(exc, limit=2000)
        debug_log.event(
            "cli_exit", elapsed_ms=debug_log.elapsed_ms(started), exit_code=1,
            error=message, error_class=type(exc).__name__,
        )
        if args is not None:
            _write_payload({
                "error": message,
                "error_type": "invalid_request" if isinstance(exc, ValueError) else "runtime_error",
            }, args.format, stdout)
        stderr.write(f"error: {message}\n")
        return 1
    finally:
        # The trace belongs to this one invocation; a later in-process call
        # (tests, Python callers) must not append to it.
        debug_log.disable()


def _debug_log_setting() -> bool:
    """The desktop's "记录搜索详情" switch (`debug_log` in the shared settings)."""
    from .src.state import runtime

    try:
        return runtime.load_config_safe(None).get("debug_log") is True
    except Exception:  # noqa: BLE001 - the command itself reports a broken config
        return False


def entrypoint() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, io.TextIOWrapper) and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors=stream.errors)
    raise SystemExit(main())


def _ranking_override(args: argparse.Namespace) -> dict[str, Any] | None:
    """Map --rerank/--rerank-base-url/--rerank-model onto the ``ranking`` override.

    ``None`` (no flags) preserves today's behavior exactly: the config decides
    and pure RRF remains the default. A base URL or model without
    ``--rerank`` is a usage error — it would otherwise look like it did
    something while the request stayed in pure-RRF mode. Missing values fall
    back to the config; core rejects an enabled rerank with neither.
    """
    base_url = getattr(args, "rerank_base_url", None)
    model = getattr(args, "rerank_model", None)
    if not getattr(args, "rerank", False):
        if base_url is not None or model is not None:
            raise CLIUsageError("--rerank-base-url/--rerank-model require --rerank")
        return None
    ranking: dict[str, Any] = {"mode": "rrf_model"}
    if base_url is not None:
        ranking["base_url"] = base_url.strip()
    if model is not None:
        ranking["model"] = model.strip()
    return ranking


def _handle_search(args: argparse.Namespace) -> dict[str, Any]:
    ranking = _ranking_override(args)
    request = SearchWebRequest(
        query=args.query,
        route=args.route,
        count=args.count,
        sources=list(args.sources or []),
        timeout=args.timeout,
        expand=None if args.expand is None else list(args.expand),
        no_fetch=bool(args.no_fetch),
        use_state=not args.no_state,
        ranking=ranking,
    )
    # Core builds the reranker from the merged config + override policy.
    payload = run_search_web(request)
    # The core owns the business outcome; the CLI only maps it to an exit code.
    # Derive it here only for a payload that predates the core field.
    if "outcome" not in payload:
        statuses = payload.get("provider_status") or []
        payload["outcome"] = (
            "failed" if statuses and all(row.get("status") == "error" for row in statuses)
            else "partial" if payload.get("errors")
            else "success" if payload.get("results") else "empty"
        )
    return payload


def _read_url_file(path: str) -> str:
    """Read one URL without letting the shell see or interpret it."""
    if path == "-":
        stream = sys.stdin
        buffer = getattr(stream, "buffer", None)
        try:
            raw = buffer.read().decode("utf-8-sig") if buffer is not None else stream.read()
        except UnicodeDecodeError as exc:
            raise CLIUsageError(f"cannot decode --url-file from stdin as UTF-8: {exc}") from exc
    else:
        try:
            raw = Path(path).expanduser().read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise CLIUsageError(f"cannot read --url-file: {exc}") from exc
    url = raw.strip()
    if not url:
        raise CLIUsageError("--url-file is empty")
    if "\n" in url or "\r" in url:
        raise CLIUsageError("--url-file must contain exactly one URL")
    return url


def _handle_fetch(args: argparse.Namespace) -> dict[str, Any]:
    provided = [
        name for name, present in (
            ("source_id", bool(args.source_id)),
            ("--url", bool(args.url)),
            ("--url-file", args.url_file is not None),
        ) if present
    ]
    if len(provided) != 1:
        raise CLIUsageError("provide exactly one of source_id, --url, or --url-file")
    url = args.url if args.url_file is None else _read_url_file(args.url_file)
    return run_fetch_source(
        FetchSourceRequest(
            source_id=args.source_id,
            url=url,
            backends=list(args.backends or []),
            max_chars=args.max_chars,
            timeout=args.timeout,
            full_content=args.full_content,
            use_state=not args.no_state,
        )
    )


def _handle_read(args: argparse.Namespace) -> dict[str, Any]:
    return run_read_source(
        ReadSourceRequest(
            source_id=args.source_id,
            keyword=args.keyword,
            offset=args.offset,
            limit=args.limit,
            use_state=not args.no_state,
        )
    )


def _handle_doctor(args: argparse.Namespace) -> dict[str, Any]:
    return doctor_data(include_keys=not args.no_keys, include_network=args.network)


def _handle_sources(args: argparse.Namespace) -> dict[str, Any]:
    # Imported lazily so the light search CLI paths do not grow their import graph.
    from .src.search.catalog import build_configured_source_catalog
    from .src.support.config import load_config

    catalog = build_configured_source_catalog(load_config())
    if args.key_status:
        catalog["key_status"] = key_status()
    if args.scraper_stats:
        catalog["site_scraper_stats"] = site_scraper_stats()
    return catalog


def _handle_routes(args: argparse.Namespace) -> dict[str, Any]:
    from .src.search.resolve import describe_configured_routes
    from .src.support.config import load_config

    return describe_configured_routes(load_config())


def _handle_keys_status(args: argparse.Namespace) -> dict[str, Any]:
    return {"key_status": key_status(args.provider)}


def _handle_keys_reset(args: argparse.Namespace) -> dict[str, Any]:
    # Confirm the scope before entering the shared operation (and opening a DB).
    if args.all and (args.provider is not None or args.key_id is not None):
        raise CLIUsageError("--all cannot be combined with --provider or --key-id")
    if not (args.all or args.provider or args.key_id):
        raise CLIUsageError("keys reset requires --all or a --provider/--key-id selection")
    return {"updated": reset_key_state(provider=args.provider, key_id=args.key_id)}


def _handle_site_stats(args: argparse.Namespace) -> dict[str, Any]:
    return {"site_scraper_stats": site_scraper_stats(args.site)}


def _handle_site_set_preference(args: argparse.Namespace) -> dict[str, Any]:
    return set_site_scraper_preference(
        args.site, args.scraper, priority=args.priority, note=args.note,
    )


def _handle_site_reset(args: argparse.Namespace) -> dict[str, Any]:
    return {"deleted": reset_site_scraper_stats(args.site)}


def _log_sources(args: argparse.Namespace) -> list[Path]:
    from .src.log_viewer import default_sources

    return [Path(item).expanduser() for item in args.path] if args.path else default_sources()


def _handle_logs_list(args: argparse.Namespace) -> dict[str, Any]:
    from .src.log_viewer import list_runs, load_runs

    sources = _log_sources(args)
    return {"sources": [str(item) for item in sources],
            "runs": list_runs(load_runs(sources), limit=args.limit)}


def _handle_logs_serve(args: argparse.Namespace) -> dict[str, Any]:
    from .src.log_viewer import make_server

    sources = _log_sources(args)
    try:
        server = make_server(sources, args.port)
    except OSError as exc:
        raise RuntimeError(f"cannot listen on 127.0.0.1:{args.port}: {exc}") from exc
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    sys.stderr.write(f"multi-search logs: serving {url} (Ctrl+C to stop)\n")
    sys.stderr.flush()
    if args.open:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"url": url, "stopped": True}


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
    if _is_routes_payload(payload):
        return _render_routes(payload, markdown=False)
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
    if _is_routes_payload(payload):
        return _render_routes(payload, markdown=True)
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


def _relevance_suffix(item: Any) -> str:
    """Render ``relevance_score`` only when the model actually scored the row.

    ``None`` (unscored or a pure-RRF response) renders as nothing — a ``0``
    would pretend the model judged the row irrelevant.
    """
    if not isinstance(item, dict):
        return ""
    score = item.get("relevance_score")
    if score is None:
        return ""
    try:
        return f" (relevance: {float(score):.3f})"
    except (TypeError, ValueError):
        return ""


def _render_search(payload: dict[str, Any], *, markdown: bool) -> str:
    if isinstance(payload.get("markdown"), str):
        return payload["markdown"]
    query = str(payload.get("query") or "")
    route = str(payload.get("route") or "")
    results = payload.get("display_results") or payload.get("results") or []
    bodies = format_scrapes(payload.get("scrapes") or [], max_chars=20_000)
    errors = payload.get("errors") or []
    ranking_line = f"ranking: {ranking_mode_label(payload)}"
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
        if payload.get("outcome"):
            lines.append(f"- outcome: {payload['outcome']}")
        if route:
            lines.append(f"- route: {route}")
        lines.append(f"- {ranking_line}")
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
            lines.append(f"- {title} [{source}]{_relevance_suffix(item)}")
            if url:
                lines.append(f"  {url}")
            if snippet:
                lines.append(f"  {snippet}")
        return "\n".join(lines) + bodies + failures

    lines = [f"query: {query}"]
    if payload.get("outcome"):
        lines.append(f"outcome: {payload['outcome']}")
    if route:
        lines.append(f"route: {route}")
    lines.append(ranking_line)
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
        lines.append(f"- [{source}] {title}{_relevance_suffix(item)}")
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


def _is_routes_payload(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and {"default_route", "aliases", "routes"} <= set(payload)
        and isinstance(payload.get("routes"), list)
    )


def _render_routes(payload: dict[str, Any], *, markdown: bool) -> str:
    default_route = str(payload.get("default_route") or "")
    aliases = payload.get("aliases") or {}
    alias_names = ", ".join(f"{alias} -> {target}" for alias, target in sorted(aliases.items()))
    routes = payload.get("routes") or []
    lines: list[str] = []
    if markdown:
        lines.append("# Routes")
        lines.append("")
        lines.append(f"Default route: `{default_route}`")
        if alias_names:
            lines.append(f"Aliases: {alias_names}")
        lines.append("")
        if not routes:
            lines.append("_No routes_")
            return "\n".join(lines)
        lines.append("| Route | Default | Description | Sources |")
        lines.append("| --- | --- | --- | --- |")
        for route in routes:
            is_default = "yes" if route.get("is_default") else ""
            sources = ", ".join(str(source) for source in route.get("sources") or [])
            lines.append(
                f"| `{_table_cell(route.get('id'))}` | {is_default} | "
                f"{_table_cell(_route_summary(route))} | {_table_cell(sources)} |"
            )
        return "\n".join(lines)

    lines.append(f"default_route: {default_route}")
    if alias_names:
        lines.append(f"aliases: {alias_names}")
    if not routes:
        lines.append("routes: none")
        return "\n".join(lines)
    lines.append("routes:")
    for route in routes:
        marker = " (default)" if route.get("is_default") else ""
        sources = ", ".join(str(source) for source in route.get("sources") or []) or "none"
        lines.append(f"- {route.get('id')}{marker}: {_route_summary(route)}")
        lines.append(f"  sources: {sources}")
    return "\n".join(lines)


def _route_summary(route: dict[str, Any]) -> str:
    """Describe when to use a route; fall back to its label when it has no description."""
    description = route.get("description")
    if isinstance(description, str) and description:
        return description
    return str(route.get("label") or "")


def _table_cell(value: Any) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ").strip()


def _render_key_rows(rows: list[dict[str, Any]], *, markdown: bool) -> list[str]:
    if not rows:
        return ["_No key rows_" if markdown else "none"]
    rendered = []
    for row in rows:
        provider = row.get("provider")
        key_id = row.get("key_id")
        status = row.get("status")
        # Manual opt-out is independent of the health status: an ``active`` row
        # can still be unusable, so the human line must say why.
        marker = '（手动禁用）' if row.get("manually_disabled") else ''
        if markdown:
            rendered.append(f"- {provider} {key_id}: {status}{marker}")
        else:
            rendered.append(f"- {provider} {key_id}: {status}{marker}")
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

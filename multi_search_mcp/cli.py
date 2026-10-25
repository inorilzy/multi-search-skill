"""Thin CLI over the shared multi-search core service layer."""
from __future__ import annotations

import argparse
import io
import importlib.metadata
import json
import sys
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
            "reorder the fused RRF candidates with the configured reranker "
            "profile before the body-fetch stage (ranking.mode=rrf_model); "
            "on any model failure the complete RRF order is kept and the "
            "response reports mode_used/fallback_reason"
        ),
    )
    search_parser.add_argument(
        "--rerank-profile",
        metavar="PROFILE",
        help=(
            "reranker profile id for --rerank "
            "(ranking.reranker_profile_id); the only built-in profile is "
            "'jev_default' — an unknown value is a usage error, not a silent fallback"
        ),
    )
    search_parser.add_argument(
        "--no-state", action="store_true",
        help="skip SQLite key rotation, content cache, and site memory (clean test/debug runs)",
    )
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

    migrate_parser = subparsers.add_parser(
        "migrate-legacy",
        help="preview or apply an explicit migration of legacy search keys into the credential store",
    )
    migrate_subparsers = migrate_parser.add_subparsers(dest="migrate_command", required=True)
    migrate_plan_parser = migrate_subparsers.add_parser("plan", help="masked preview of the legacy keys file")
    migrate_plan_parser.add_argument("--keys-file", required=True)
    _add_format_argument(migrate_plan_parser)
    migrate_plan_parser.set_defaults(handler=_handle_migrate_plan)

    migrate_apply_parser = migrate_subparsers.add_parser(
        "apply", help="apply an approved plan; the request file names approved providers and conflict choices"
    )
    migrate_apply_parser.add_argument("--keys-file", required=True)
    migrate_apply_parser.add_argument("--request", required=True, help="JSON file with approved, choices, plan_token")
    _add_format_argument(migrate_apply_parser)
    migrate_apply_parser.set_defaults(handler=_handle_migrate_apply)

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
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        payload = args.handler(args)
        _write_payload(payload, args.format, stdout)
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
        if args is not None:
            _write_payload({
                "error": message,
                "error_type": "invalid_request" if isinstance(exc, ValueError) else "runtime_error",
            }, args.format, stdout)
        stderr.write(f"error: {message}\n")
        return 1


def entrypoint() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, io.TextIOWrapper) and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors=stream.errors)
    raise SystemExit(main())


def _ranking_override(args: argparse.Namespace) -> dict[str, Any] | None:
    """Map --rerank/--rerank-profile onto the request ``ranking`` override.

    ``None`` (no flags) preserves today's behavior exactly: the config decides
    and pure RRF remains the default. A profile without ``--rerank`` is a
    usage error — it would otherwise look like it did something while the
    request stayed in pure-RRF mode.
    """
    profile = getattr(args, "rerank_profile", None)
    if profile is not None:
        # The profile registry is owned by core; the CLI only maps an unknown
        # id to a usage error (exit 2) instead of core's ConfigError (exit 1).
        from .src.search.rerank import RERANKER_PROFILES

        if profile not in RERANKER_PROFILES:
            raise CLIUsageError(
                f"unknown rerank profile: {profile!r} "
                f"(known: {', '.join(sorted(RERANKER_PROFILES))})"
            )
    if not getattr(args, "rerank", False):
        if profile is not None:
            raise CLIUsageError("--rerank-profile requires --rerank")
        return None
    ranking: dict[str, Any] = {"mode": "rrf_model"}
    if profile is not None:
        ranking["reranker_profile_id"] = profile
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
    from .src.search.catalog import build_source_catalog

    catalog = build_source_catalog()
    if args.key_status:
        catalog["key_status"] = key_status()
    if args.scraper_stats:
        catalog["site_scraper_stats"] = site_scraper_stats()
    return catalog


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


def _migration_store():
    from .src.support.credential_store import default_store

    return default_store()


def _handle_migrate_plan(args: argparse.Namespace) -> dict[str, Any]:
    from .src.support import legacy_migration

    plan = legacy_migration.plan_migration(Path(args.keys_file).expanduser(), _migration_store())
    # Digests stay in-process; the caller gets an opaque token that changes if either side changes.
    visible = {k: v for k, v in plan.items() if k not in ("source_digest", "store_digest")}
    visible["plan_token"] = legacy_migration.plan_token(plan)
    return visible


def _handle_migrate_apply(args: argparse.Namespace) -> dict[str, Any]:
    from .src.support import legacy_migration

    keys_file = Path(args.keys_file).expanduser()
    store = _migration_store()
    request = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
    plan = legacy_migration.plan_migration(keys_file, store)
    if request.get("plan_token") != legacy_migration.plan_token(plan):
        raise CLIUsageError("the migration plan changed since preview; run the preview again")
    return legacy_migration.apply_migration(
        keys_file,
        store,
        plan,
        approved=list(request.get("approved", [])),
        choices=dict(request.get("choices", {})),
    )


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

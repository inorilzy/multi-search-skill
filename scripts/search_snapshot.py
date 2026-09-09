"""Maintainer-only snapshot capture/replay; never reads user search history."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multi_search_mcp.src.search.snapshots import (  # noqa: E402
    capture_snapshot, compare_snapshot, load_snapshot, replay_snapshot, write_snapshot,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture", help="Live provider calls for one explicitly supplied question")
    capture.add_argument("--query", required=True)
    expansion = capture.add_mutually_exclusive_group(required=True)
    expansion.add_argument("--variant", action="append")
    expansion.add_argument("--no-expand", action="store_true")
    capture.add_argument("--source", action="append", required=True)
    capture.add_argument("--count", type=int, default=10)
    capture.add_argument("--timeout", type=int)
    capture.add_argument("--config")
    capture.add_argument("--output", required=True)
    fixture = sub.add_parser("fixture", help="Materialize synthetic fixed data via the real Core; no network")
    fixture.add_argument("--input", default="docs/examples/search-snapshot.json")
    fixture.add_argument("--output", required=True)
    for name in ("replay", "compare"):
        command = sub.add_parser(name)
        command.add_argument("snapshot")
        command.add_argument("--mode", choices=["primary", "equal", "weighted"], default="equal")
        command.add_argument("--omit-variant", action="append", default=[])
        command.add_argument("--limit", type=int)
        command.add_argument("--primary-weight", type=float)
        command.add_argument("--variant-budget", type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            snapshot = capture_snapshot({
                "query": args.query, "sources": args.source, "count": args.count,
                "timeout": args.timeout, "config_path": args.config,
            }, expand=args.variant or [])
            write_snapshot(snapshot, args.output)
            result = {"snapshot": args.output, "expires_at": snapshot["expires_at"], "collection": snapshot["collection"]}
        elif args.command == "fixture":
            from multi_search_mcp.src.search.search_runner import ProviderSpec

            fixture_data = json.loads(Path(args.input).read_text(encoding="utf-8"))
            if fixture_data.get("data_origin") != "synthetic_fixture":
                raise ValueError("fixture input must declare synthetic_fixture")
            provider = fixture_data["provider"]
            def call(query, *_):
                return copy.deepcopy(fixture_data["rows_by_query"][query])
            snapshot = capture_snapshot({
                "query": fixture_data["primary_query"], "sources": [provider], "count": fixture_data["count"],
            }, expand=fixture_data["variants"], providers={provider: ProviderSpec(provider, provider, call)}, keys={}, config={})
            snapshot["data_origin"] = "synthetic_fixture"
            snapshot["collection"]["measurement_scope"] = "injected_fixture_calls_only"
            write_snapshot(snapshot, args.output)
            result = {"snapshot": args.output, "data_origin": "synthetic_fixture", "expires_at": snapshot["expires_at"]}
        else:
            policy = None
            if args.mode == "weighted":
                from multi_search_mcp.src.search.query_policy import QueryFusionPolicy

                policy = QueryFusionPolicy(mode="weighted", primary_weight=args.primary_weight, variant_budget=args.variant_budget)
            elif args.primary_weight is not None or args.variant_budget is not None:
                raise ValueError("weight arguments require --mode weighted")
            operation = compare_snapshot if args.command == "compare" else replay_snapshot
            result = operation(load_snapshot(args.snapshot), mode=args.mode, omit_variants=args.omit_variant, limit=args.limit, query_policy=policy)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

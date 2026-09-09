"""Prepare blinded labels and validate explicit review policies; never selects a default automatically."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multi_search_mcp.src.search.evaluation import (  # noqa: E402
    evaluate_heldout, freeze_candidate, freeze_development, load_artifact, prepare_review, summarize_review, write_artifact,
)
from multi_search_mcp.src.search.snapshots import load_snapshot  # noqa: E402


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("snapshot")
    prepare.add_argument("--question", required=True, help="One question object JSON")
    prepare.add_argument("--prompt-id", required=True)
    prepare.add_argument("--policy-specs", required=True, help="Explicit weighted experiment list JSON")
    prepare.add_argument("--seed", type=int, default=0)
    prepare.add_argument("--fidelity", choices=["exact", "sanitized_content"], default="exact")
    prepare.add_argument("--blind", required=True)
    prepare.add_argument("--private", required=True)
    prepare.add_argument("--markdown", help="Optional read-only blank review worksheet")
    summarize = commands.add_parser("summarize")
    summarize.add_argument("private")
    summarize.add_argument("review")
    summarize.add_argument("--output", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--report", action="append", required=True)
    candidate = commands.add_parser("freeze-candidate", help="Fix an experiment without development quality approval")
    candidate.add_argument("--development-decision", required=True)
    candidate.add_argument("--retrieval-config", required=True)
    for command in (freeze, candidate):
        command.add_argument("--selection", required=True)
        command.add_argument("--versions", required=True)
        command.add_argument("--thresholds", required=True)
        command.add_argument("--question-set", required=True)
        command.add_argument("--output", required=True)
    heldout = commands.add_parser("heldout")
    heldout.add_argument("freeze")
    heldout.add_argument("--report", action="append", required=True)
    heldout.add_argument("--versions", required=True)
    heldout.add_argument("--question-set", required=True)
    heldout.add_argument("--output", required=True)
    heldout.add_argument("--allow-candidate", action="store_true", help="Evaluate a candidate experiment without release approval")
    for command in (summarize, freeze, candidate, heldout):
        command.add_argument("--review-policy", choices=["human_only", "allow_ai"], default="human_only")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            blind, private = prepare_review(load_snapshot(args.snapshot), read_json(args.question), args.prompt_id, read_json(args.policy_specs), seed=args.seed, fidelity=args.fidelity)
            for path in [args.blind, args.private, *([args.markdown] if args.markdown else [])]:
                if Path(path).exists():
                    raise ValueError(f"output already exists: {path}")
            write_artifact(blind, args.blind)
            write_artifact(private, args.private)
            if args.markdown:
                def cell(value):
                    return str(value).replace("|", "\\|").replace("\n", " ")
                lines = [f"# {cell(blind['question'])}", f"Expiry (Unix seconds): {blind['expires_at']}",
                         "Reviewer / reviewed_at / reviewer_kind: pending. Submit labels in the JSON packet.",
                         "", "| Candidate | URL | Title / snippet | Label | Rationale / checked evidence | Original material / repost |",
                         "|---|---|---|---|---|---|"]
                lines += [f"| {row['candidate_id']} | {cell(row['url'])} | {cell(row['title'])}: {cell(row['snippet'])} | pending | | |" for row in blind["candidates"]]
                with Path(args.markdown).open("x", encoding="utf-8") as stream:
                    stream.write("\n".join(lines) + "\n")
            result = {"status": "not_passed", "blind": args.blind, "private": args.private, "expires_at": blind["expires_at"], "reason": "review is pending"}
        elif args.command == "summarize":
            result = summarize_review(load_artifact(args.private), load_artifact(args.review), review_policy=args.review_policy)
            write_artifact(result, args.output)
        elif args.command == "freeze":
            result = freeze_development([load_artifact(path) for path in args.report], read_json(args.selection), read_json(args.versions), read_json(args.thresholds), read_json(args.question_set), review_policy=args.review_policy)
            write_artifact(result, args.output)
        elif args.command == "freeze-candidate":
            result = freeze_candidate(read_json(args.development_decision), read_json(args.selection), read_json(args.versions), read_json(args.thresholds), read_json(args.question_set), read_json(args.retrieval_config), review_policy=args.review_policy)
            write_artifact(result, args.output)
        else:
            result = evaluate_heldout(load_artifact(args.freeze), [load_artifact(path) for path in args.report], versions=read_json(args.versions), question_set=read_json(args.question_set), review_policy=args.review_policy, allow_candidate=args.allow_candidate)
            write_artifact(result, args.output)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

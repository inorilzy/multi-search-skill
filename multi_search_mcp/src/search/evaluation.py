"""Offline review artifacts with explicit reviewer provenance and frozen holdout checks."""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from .candidate import canonicalize_url
from .query_plan import build_query_plan
from .query_policy import QueryFusionPolicy
from .snapshots import replay_snapshot
from ..support.models import ANSWER_SOURCES, is_empty_result


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _live(value):
    expiry = value.get("expires_at")
    if isinstance(expiry, bool) or not isinstance(expiry, (float, int)) or not math.isfinite(expiry) or expiry <= time.time():
        raise ValueError("evaluation artifact expired or missing finite expiry")


def prepare_review(snapshot: dict, question: dict, prompt_id: str, policy_specs: list[dict], seed: int = 0, *, fidelity: str = "exact") -> tuple[dict, dict]:
    _live(snapshot)
    if question["question"] != snapshot["primary_query"]:
        raise ValueError("snapshot primary question does not match evaluation question")
    for key in ("id", "topic_group", "category"):
        if not question.get(key):
            raise ValueError(f"question requires {key}")
    prompt = question["prompts"][prompt_id]
    if not prompt.get("reason"):
        raise ValueError("prompt requires a variant rationale")
    queries = build_query_plan(question["question"], prompt["variants"])
    if set(queries.variants) - set(snapshot["variants"]):
        raise ValueError("snapshot is missing prompt variants")
    omitted = set(snapshot["variants"]) - set(queries.variants)
    policies: dict[str, QueryFusionPolicy | None] = {"primary": None, "equal": None}
    for spec in policy_specs:
        if not spec.get("id") or spec["id"] in policies:
            raise ValueError("policy ids must be unique and not primary/equal")
        policies[spec["id"]] = QueryFusionPolicy(mode="weighted", **{key: value for key, value in spec.items() if key != "id"})
    ranked = {}
    ablations: dict[str, dict] = {}
    hits: dict[str, dict] = {}
    def run(name, extra=()):
        result = replay_snapshot(snapshot, mode=name if name in {"primary", "equal"} else "weighted",
                                 omit_variants=omitted | set(extra), limit=10, query_policy=policies[name], fidelity=fidelity)
        for hit in result["results"]:
            hits.setdefault(hit["canonical_url"], hit)
        return {"status": "ok", "urls": [hit["canonical_url"] for hit in result["results"]],
                "offline_replay_seconds": result["offline_replay_seconds"]}
    for name in policies:
        ranked[name] = run(name)
        if name != "primary":
            ablations[name] = {}
            for variant in queries.variants:
                try:
                    ablations[name][variant] = run(name, [variant])
                except ValueError as exc:
                    # A smaller query set may make the explicitly chosen weights invalid.
                    if "primary_weight must exceed" not in str(exc):
                        raise
                    ablations[name][variant] = {"status": "invalid_policy", "error": str(exc)}
    rng = random.Random(seed)
    urls = sorted(hits)
    rng.shuffle(urls)
    ids = {url: "c_" + fingerprint([question["id"], url])[:32] for url in urls}
    display_hits = {hit["canonical_url"]: hit for hit in replay_snapshot(snapshot, limit=sum(len(run["rows"]) for run in snapshot["query_runs"]), fidelity=fidelity)["results"]}
    candidates = [{"candidate_id": ids[url], "url": url, "title": display_hits[url]["title"],
                   "snippet": display_hits[url]["content"], "label": "pending", "rationale": "",
                   "checked_evidence": [], "original_material_id": None, "repost_of": None} for url in urls]
    common = {"schema_version": 1, "question_id": question["id"], "question": question["question"],
              "expires_at": snapshot["expires_at"], "data_origin": snapshot["data_origin"], "fidelity": fidelity}
    blind = {**common, "reviewer": "", "reviewer_kind": "", "reviewed_at": "", "candidates": candidates}
    for group in [ranked, *ablations.values()]:
        for result in group.values():
            if result["status"] == "ok":
                result["candidate_ids"] = [ids[url] for url in result.pop("urls")]
    primary_recalled = {
        canonicalize_url(row["url"])
        for run in snapshot["query_runs"] if run["query"] == snapshot["primary_query"]
        for row in run["rows"]
        if row.get("source") and row["source"] not in ANSWER_SOURCES and row.get("url")
        and not row.get("error") and not is_empty_result(row)
        and int(row.get("provider_rank", 0)) >= 1
    }
    private = {**common, "prompt_id": prompt_id, "prompt_hash": fingerprint(prompt),
               "primary_recalled_urls": sorted(primary_recalled),
               "question_hash": fingerprint(question), "snapshot_captured_at": snapshot["captured_at"],
               "retrieval_config": {key: snapshot["execution"][key] for key in ("route", "active_sources", "provider_counts", "timeout", "serpapi_engine", "count")},
               "topic_group": question["topic_group"], "category": question["category"],
               "queries": list(queries.queries), "limit": 10, "policy_specs": policy_specs,
               "rankings": ranked, "ablations": ablations, "candidate_urls": {ids[url]: url for url in urls},
               "candidate_display_hashes": {row["candidate_id"]: fingerprint([row["url"], row["title"], row["snippet"]]) for row in candidates},
               "collection": snapshot["collection"], "snapshot_hash": fingerprint(snapshot)}
    blind["packet_id"] = private["packet_id"] = fingerprint(private)
    return blind, private


def _review_kinds(review_policy: str) -> set[str]:
    if review_policy not in {"human_only", "allow_ai"}:
        raise ValueError("review_policy must be human_only or allow_ai")
    return {"human", "ai"} if review_policy == "allow_ai" else {"human"}


def summarize_review(private: dict, review: dict, *, review_policy: str = "human_only") -> dict:
    _live(private)
    _live(review)
    issues = []
    if review.get("schema_version") != 1 or review.get("question_id") != private["question_id"] or review.get("question") != private["question"]:
        raise ValueError("review schema/question identity does not match comparison")
    if review.get("packet_id") != private["packet_id"] and private["packet_id"] not in review.get("packet_ids", []):
        raise ValueError("review does not belong to this comparison")
    reviewer_kind = review.get("reviewer_kind")
    if reviewer_kind not in _review_kinds(review_policy) or not str(review.get("reviewer") or "").strip():
        issues.append(f"named reviewer with a kind allowed by {review_policy} is required")
    try:
        reviewed_at = datetime.fromisoformat(review.get("reviewed_at", ""))
        if reviewed_at.utcoffset() is None or reviewed_at.timestamp() > time.time() + 60:
            raise ValueError("review time requires a timezone and cannot be in the future")
    except (TypeError, ValueError):
        issues.append("valid reviewed_at with timezone is required")
    rows = review.get("candidates", [])
    labels = {row.get("candidate_id"): row for row in rows}
    if len(labels) != len(rows) or set(private["candidate_urls"]) - set(labels):
        raise ValueError("review candidate labels are missing, duplicated or unexpected")
    valid_labels = {"direct", "partial", "irrelevant", "constraint_violation", "pending"}
    for candidate_id, row in labels.items():
        if candidate_id != "c_" + fingerprint([private["question_id"], row.get("url")])[:32]:
            raise ValueError("review candidate identity is invalid")
        if candidate_id not in private["candidate_urls"]:
            continue
        if fingerprint([row.get("url"), row.get("title"), row.get("snippet")]) != private["candidate_display_hashes"][candidate_id]:
            raise ValueError("review changed original candidate display fields")
        if row.get("url") != private["candidate_urls"][candidate_id]:
            raise ValueError("review changed candidate URL identity")
        if row.get("label") not in valid_labels:
            raise ValueError("unknown relevance label")
        evidence = row.get("checked_evidence")
        if (row["label"] == "pending" or not str(row.get("rationale") or "").strip()
                or not isinstance(evidence, list) or not evidence
                or any(not isinstance(item, dict) or any(
                    not isinstance(item.get(key), str) or not item[key].strip()
                    for key in ("url", "note")) for item in evidence)):
            issues.append(f"{candidate_id}: pending judgment or missing checked evidence/rationale")
        if row.get("repost_of") and row["repost_of"] not in labels:
            raise ValueError("repost_of must reference another reviewed candidate_id")
        if row.get("repost_of") and (not row.get("original_material_id") or row["original_material_id"] != labels[row["repost_of"]].get("original_material_id")):
            issues.append(f"{candidate_id}: repost material identity must match its referenced candidate")
    primary = set(private["rankings"]["primary"]["candidate_ids"])
    def metrics(result):
        if result["status"] != "ok":
            return result
        ids = result["candidate_ids"]
        output = {f"at{k}": {label: sum(labels[item]["label"] == label for item in ids[:k]) for label in sorted(valid_labels)} for k in (5, 10)}
        useful = [item for item in ids if labels[item]["label"] == "direct"]
        materials = [labels[item].get("original_material_id") for item in useful if labels[item].get("original_material_id")]
        return {**output, "variant_only_valid": sum(private["candidate_urls"][item] not in private["primary_recalled_urls"] for item in useful),
                "new_in_top10": sum(item not in primary for item in useful),
                "direct_delta_at10": output["at10"]["direct"] - sum(labels[item]["label"] == "direct" for item in primary),
                "original_materials": len(set(materials)), "duplicate_evidence": len(materials) - len(set(materials)),
                "candidate_ids": ids, "failure_candidate_ids": [item for item in ids if labels[item]["label"] in {"irrelevant", "constraint_violation", "pending"}]}
    return {"schema_version": 1, "status": "not_passed" if issues else f"{reviewer_kind}_reviewed", "issues": issues,
            "review_policy": review_policy, "reviewer_kind": reviewer_kind,
            "fidelity": private.get("fidelity", "exact"),
            "recommendation": "do_not_switch_default", "expires_at": min(private["expires_at"], review["expires_at"]),
            "question_id": private["question_id"], "topic_group": private["topic_group"], "category": private["category"],
            "prompt_id": private["prompt_id"], "prompt_hash": private["prompt_hash"], "policy_specs": private["policy_specs"],
            "question_hash": private["question_hash"], "snapshot_captured_at": private["snapshot_captured_at"],
            "retrieval_config": private["retrieval_config"],
            "reviewer": review.get("reviewer"), "reviewed_at": review.get("reviewed_at"), "review_hash": fingerprint(review),
            "comparison_hash": fingerprint(private), "collection": private["collection"],
            "strategies": {name: metrics(result) for name, result in private["rankings"].items()},
            "ablations": {name: {variant: metrics(result) for variant, result in items.items()} for name, items in private["ablations"].items()}}


def _meets(metrics, thresholds):
    return (metrics["at5"]["direct"] >= thresholds["min_direct_at5"]
            and metrics["at10"]["constraint_violation"] <= thresholds["max_violations_at10"]
            and metrics["variant_only_valid"] >= thresholds["min_variant_only_valid"])


def _complete_review(report: dict, review_policy: str) -> bool:
    kind = report.get("reviewer_kind", "human")
    return (kind in _review_kinds(review_policy) and report.get("status") == f"{kind}_reviewed"
            and (kind != "ai" or report.get("review_policy") == "allow_ai"))


def freeze_development(reports: list[dict], selection: dict, versions: dict, thresholds: dict, question_set: dict, *, review_policy: str = "human_only") -> dict:
    _review_kinds(review_policy)
    if not reports or any(not _complete_review(report, review_policy) for report in reports):
        raise ValueError(f"complete reviews under {review_policy} are required before development selection")
    for report in reports:
        _live(report)
    if any(report["retrieval_config"] != reports[0]["retrieval_config"] for report in reports):
        raise ValueError("development retrieval configs differ; freeze requires one collection configuration")
    if not selection.get("selected_by") or not selection.get("selection_reason"):
        raise ValueError("reviewer selection requires selected_by and selection_reason")
    if selection.get("policy_id") == "primary":
        raise ValueError("primary is a comparison baseline, not a frozen expansion policy")
    if not all(isinstance(versions.get(key), str) and len(versions[key]) == 64 for key in ("skill_sha256", "variant_prompt_sha256")):
        raise ValueError("freeze requires Skill and variant prompt version hashes")
    if set(thresholds) != {"min_direct_at5", "max_violations_at10", "min_variant_only_valid"} or any(type(value) is not int or value < 0 for value in thresholds.values()):
        raise ValueError("explicit nonnegative integer pass thresholds are required")
    development, heldout = question_set["development"], question_set["heldout"]
    if not development or not heldout:
        raise ValueError("development and heldout question sets must both be nonempty")
    if {q["topic_group"] for q in development} & {q["topic_group"] for q in heldout}:
        raise ValueError("development and heldout topic groups overlap")
    all_ids = [q["id"] for q in development + heldout]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("development and heldout question ids must be unique")
    expected = {(q["id"], prompt) for q in development for prompt in q["prompts"]}
    actual = {(r["question_id"], r["prompt_id"]) for r in reports}
    if actual != expected or len(reports) != len(actual):
        raise ValueError("all development question/prompt comparisons must be reviewed once")
    questions = {q["id"]: q for q in development}
    if any(selection["prompt_id"] not in q["prompts"] for q in development + heldout):
        raise ValueError("selected prompt must exist in every development and heldout question")
    for report in reports:
        question = questions[report["question_id"]]
        if report["question_hash"] != fingerprint(question) or report["prompt_hash"] != fingerprint(question["prompts"][report["prompt_id"]]):
            raise ValueError("review prompt differs from frozen question set")
        if report["prompt_id"] == selection["prompt_id"]:
            policy_id = selection["policy_id"]
            spec = next((spec for spec in report["policy_specs"] if spec["id"] == policy_id), None)
            selected_policy = {"mode": "equal"} if policy_id == "equal" else {"mode": "weighted", **{key: value for key, value in (spec or {}).items() if key != "id"}}
            if spec is None and policy_id != "equal" or selected_policy != selection["query_fusion"]:
                raise ValueError("selection differs from the reviewed policy")
            if not _meets(report["strategies"][policy_id], thresholds):
                raise ValueError("selected development strategy fails explicit pass thresholds")
    if selection["prompt_id"] not in {report["prompt_id"] for report in reports}:
        raise ValueError("selected prompt has no reviewed evidence")
    kinds = sorted({report.get("reviewer_kind", "human") for report in reports})
    frozen = {"schema_version": 1, "artifact_type": "freeze", "status": "ai_selected" if "ai" in kinds else "human_selected", "selection": selection, "versions": versions,
              "review_policy": review_policy, "reviewer_kind": kinds[0] if len(kinds) == 1 else "mixed", "reviewer_kinds": kinds,
              "thresholds": thresholds, "limit": 10, "question_set_hash": fingerprint(question_set),
              "retrieval_config": reports[0]["retrieval_config"],
              "development_question_hashes": {q["id"]: fingerprint(q) for q in development},
              "heldout_question_hashes": {q["id"]: fingerprint(q) for q in heldout},
              "development_topic_groups": sorted({q["topic_group"] for q in development}),
              "heldout_topic_groups": sorted({q["topic_group"] for q in heldout}),
              "reviewers": sorted({report["reviewer"] for report in reports}),
              "report_hashes": [fingerprint(report) for report in reports], "frozen_at": time.time(),
              "recommendation": "do_not_switch_default", "heldout_status": "not_run"}
    return {**frozen, "freeze_id": fingerprint(frozen)}


def freeze_candidate(development_decision: dict, selection: dict, versions: dict, thresholds: dict,
                     question_set: dict, retrieval_config: dict, *, review_policy: str = "human_only") -> dict:
    """Fix an experiment after a negative development decision, without approving it."""
    _review_kinds(review_policy)
    decision = development_decision
    if (review_policy != "allow_ai" or decision.get("review_policy") != review_policy
            or decision.get("status") != "ai_review_completed_no_switch"
            or decision.get("quality_acceptance") != "not_passed"
            or decision.get("human_review") is not False or decision.get("default_changed") is not False
            or decision.get("freeze") != "not_selected"):
        raise ValueError("candidate freeze requires an explicit negative AI development decision")
    reviewed_at = datetime.fromisoformat(decision.get("completed_at", ""))
    if reviewed_at.utcoffset() is None or reviewed_at.timestamp() > time.time() + 60:
        raise ValueError("development decision time requires a timezone and cannot be in the future")
    development, heldout = question_set["development"], question_set["heldout"]
    if not development or not heldout:
        raise ValueError("development and heldout question sets must both be nonempty")
    if {q["topic_group"] for q in development} & {q["topic_group"] for q in heldout}:
        raise ValueError("development and heldout topic groups overlap")
    all_ids = [q["id"] for q in development + heldout]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("development and heldout question ids must be unique")
    review_hashes = decision.get("review_hashes", {})
    unavailable = decision.get("unavailable_questions", [])
    missing_ids = [item["question_id"] for item in unavailable]
    if (not review_hashes or decision.get("reviewed_questions") != len(review_hashes)
            or decision.get("expected_questions") != len(development)
            or len(missing_ids) != len(set(missing_ids)) or set(missing_ids) & set(review_hashes)
            or set(review_hashes) | set(missing_ids) != {q["id"] for q in development}
            or any(item.get("status") != "not_evaluable" or not item.get("reason") for item in unavailable)):
        raise ValueError("development decision coverage does not match the frozen development set")
    labels = decision.get("labels", {})
    if (set(labels) != {"direct", "partial", "irrelevant", "constraint_violation", "pending"}
            or any(type(value) is not int or value < 0 for value in labels.values())
            or not sum(labels.values()) or decision.get("reviewed_candidates") != sum(labels.values())):
        raise ValueError("development decision requires consistent reviewed candidate counts")
    hashes = [decision.get("protocol_hash"), *review_hashes.values(), *decision.get("report_hashes", []),
              versions.get("skill_sha256"), versions.get("variant_prompt_sha256")]
    if (not decision.get("report_hashes") or any(not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value) for value in hashes)):
        raise ValueError("candidate freeze requires decision evidence and Skill/prompt version hashes")
    if not selection.get("selected_by") or not selection.get("selection_reason"):
        raise ValueError("candidate selection requires selected_by and selection_reason")
    policy = QueryFusionPolicy.from_config({"query_fusion": selection["query_fusion"]})
    if (selection.get("policy_id") in {None, "", "primary"}
            or (selection["policy_id"] == "equal") != (policy.mode == "equal")):
        raise ValueError("candidate policy identity must match its explicit expansion policy")
    for question in development + heldout:
        if selection["prompt_id"] not in question["prompts"]:
            raise ValueError("selected prompt must exist in every development and heldout question")
        plan = build_query_plan(question["question"], question["prompts"][selection["prompt_id"]]["variants"])
        policy.weights(list(plan.queries), plan.primary_query)
    if set(thresholds) != {"min_direct_at5", "max_violations_at10", "min_variant_only_valid"} or any(type(value) is not int or value < 0 for value in thresholds.values()):
        raise ValueError("explicit nonnegative integer pass thresholds are required")
    if (set(retrieval_config) != {"route", "active_sources", "provider_counts", "timeout", "serpapi_engine", "count"}
            or retrieval_config["count"] != 10 or not retrieval_config["active_sources"]
            or not retrieval_config["provider_counts"]):
        raise ValueError("candidate freeze requires an explicit retrieval configuration and count 10")
    frozen = {
        "schema_version": 1, "artifact_type": "freeze", "status": "candidate_frozen",
        "release_eligible": False, "development_quality": "not_passed",
        "development_decision_sha256": fingerprint(decision),
        "development_decision_status": decision["status"], "development_labels": dict(labels),
        "unavailable_development_questions": missing_ids,
        "selection": selection, "versions": versions, "thresholds": thresholds, "limit": 10,
        "retrieval_config": retrieval_config, "review_policy": review_policy,
        "reviewer_kind": "ai", "reviewer_kinds": ["ai"],
        "report_hashes": list(decision["report_hashes"]), "question_set_hash": fingerprint(question_set),
        "development_question_hashes": {q["id"]: fingerprint(q) for q in development},
        "heldout_question_hashes": {q["id"]: fingerprint(q) for q in heldout},
        "development_topic_groups": sorted({q["topic_group"] for q in development}),
        "heldout_topic_groups": sorted({q["topic_group"] for q in heldout}),
        "frozen_at": time.time(), "recommendation": "do_not_switch_default", "heldout_status": "not_run",
    }
    return {**frozen, "freeze_id": fingerprint(frozen)}


def validate_freeze(freeze: dict, *, versions: dict, selection: dict | None = None, heldout_question: dict | None = None, review_policy: str = "human_only", allow_candidate: bool = False) -> None:
    allowed = _review_kinds(review_policy)
    if freeze.get("review_policy", "human_only") != review_policy:
        raise ValueError("frozen review policy mismatch")
    kinds = set(freeze.get("reviewer_kinds", ["human"]))
    candidate = freeze.get("status") == "candidate_frozen"
    if candidate:
        if not allow_candidate:
            raise ValueError("candidate freeze requires explicit allow_candidate")
        if (freeze.get("release_eligible") is not False or freeze.get("development_quality") != "not_passed"
                or freeze.get("development_decision_status") != "ai_review_completed_no_switch"
                or not freeze.get("development_decision_sha256") or kinds != {"ai"}):
            raise ValueError("candidate freeze must retain its negative development decision")
    expected_status = "candidate_frozen" if candidate else "ai_selected" if "ai" in kinds else "human_selected"
    if not kinds or not kinds <= allowed or freeze.get("status") != expected_status or (not candidate and not freeze.get("reviewers")) or not freeze.get("report_hashes"):
        raise ValueError(f"valid reviewed freeze under {review_policy} is required")
    expected_kind = next(iter(kinds)) if len(kinds) == 1 else "mixed"
    if freeze.get("reviewer_kind", "human") != expected_kind:
        raise ValueError("freeze reviewer kind contradicts its review provenance")
    if freeze.get("freeze_id") != fingerprint({key: value for key, value in freeze.items() if key != "freeze_id"}):
        raise ValueError("freeze record hash mismatch")
    if freeze["versions"] != versions:
        raise ValueError("frozen version mismatch; do not reuse heldout evidence")
    if selection is not None and freeze["selection"] != selection:
        raise ValueError("frozen selection/config mismatch")
    if heldout_question is not None and freeze["heldout_question_hashes"].get(heldout_question["id"]) != fingerprint(heldout_question):
        raise ValueError("question is not an unchanged member of the frozen heldout set")


def evaluate_heldout(freeze: dict, reports: list[dict], *, versions: dict, question_set: dict, review_policy: str = "human_only", allow_candidate: bool = False) -> dict:
    validate_freeze(freeze, versions=versions, review_policy=review_policy, allow_candidate=allow_candidate)
    if fingerprint(question_set) != freeze["question_set_hash"]:
        raise ValueError("frozen evaluation question set mismatch")
    expected = set(freeze["heldout_question_hashes"])
    if {r["question_id"] for r in reports} != expected or len(reports) != len(expected):
        raise ValueError("heldout reports must cover each frozen question exactly once")
    # Snapshots encode times at datetime's microsecond precision. Compare the
    # freeze at that same precision without changing its stored value or hash.
    frozen_at = datetime.fromtimestamp(freeze["frozen_at"], timezone.utc).timestamp()
    failures = []
    for report in reports:
        _live(report)
        if report["retrieval_config"] != freeze["retrieval_config"]:
            raise ValueError("heldout retrieval configuration differs from freeze")
        if report["prompt_id"] != freeze["selection"]["prompt_id"]:
            raise ValueError("heldout prompt differs from frozen selection")
        question = next(q for q in question_set["heldout"] if q["id"] == report["question_id"])
        if report["question_hash"] != fingerprint(question) or report["prompt_hash"] != fingerprint(question["prompts"][report["prompt_id"]]):
            raise ValueError("heldout question/prompt data differs from frozen input")
        if datetime.fromisoformat(report["snapshot_captured_at"]).timestamp() < frozen_at:
            raise ValueError("heldout capture predates freeze; independent evaluation unavailable")
        policy_id = freeze["selection"]["policy_id"]
        spec: dict = next((s for s in report["policy_specs"] if s["id"] == policy_id), {})
        actual_policy = {"mode": "equal"} if policy_id == "equal" else {"mode": "weighted", **{key: value for key, value in spec.items() if key != "id"}}
        if actual_policy != freeze["selection"]["query_fusion"]:
            raise ValueError("heldout policy differs from frozen selection")
        if not _complete_review(report, review_policy) or not _meets(report["strategies"][freeze["selection"]["policy_id"]], freeze["thresholds"]):
            failures.append(report["question_id"])
    kinds = sorted({str(report.get("reviewer_kind", "human")) for report in reports})
    candidate_fields = {"freeze_status": "candidate_frozen", "release_eligible": False,
                        "development_quality": freeze["development_quality"]} if freeze["status"] == "candidate_frozen" else {}
    return {"status": "not_passed" if failures else "heldout_thresholds_met", "failed_questions": failures, **candidate_fields,
            "review_policy": review_policy, "reviewer_kind": kinds[0] if len(kinds) == 1 else "mixed", "reviewer_kinds": kinds,
            "freeze_id": freeze["freeze_id"], "expires_at": min(r["expires_at"] for r in reports),
            "recommendation": "do_not_switch_default", "workflow_acceptance": "still_required",
            "report_hashes": [fingerprint(report) for report in reports]}


def load_artifact(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("artifact_type") == "freeze":
        validate_freeze(value, versions=value.get("versions", {}), review_policy=value.get("review_policy", "human_only"), allow_candidate=True)
    else:
        _live(value)
    return value


def write_artifact(value: dict, path: str | Path) -> None:
    if value.get("artifact_type") == "freeze":
        validate_freeze(value, versions=value.get("versions", {}), review_policy=value.get("review_policy", "human_only"), allow_candidate=True)
    else:
        _live(value)
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

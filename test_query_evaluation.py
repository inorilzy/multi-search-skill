import copy
import json
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.search.snapshots import capture_snapshot


def inputs():
    question = {"id": "q1", "question": "primary", "topic_group": "topic-a", "category": "technical",
                "prompts": {"p1": {"variants": ["a", "b"], "reason": "two distinct evidence angles"},
                            "p2": {"variants": ["c"], "reason": "other angle"}}}
    provider = ProviderSpec("brave", "brave", lambda query, *_: [
        {"source": "brave", "url": "https://example.test/" + query, "title": query},
        {"source": "brave", "url": "https://example.test/shared", "title": "shared"}])
    snapshot = capture_snapshot({"query": "primary", "sources": ["brave"]}, expand=["a", "b", "c"],
                                providers={"brave": provider}, keys={}, config={})
    return snapshot, question


def reviewed(snapshot, question, prompt, specs, label="direct", *, reviewer_kind="human", review_policy="human_only"):
    from multi_search_mcp.src.search.evaluation import prepare_review, summarize_review
    blind, private = prepare_review(snapshot, question, prompt, specs)
    blind.update(reviewer="SYNTHETIC TEST reviewer", reviewer_kind=reviewer_kind, reviewed_at=datetime.now(timezone.utc).isoformat())
    for row in blind["candidates"]:
        row.update(label=label, rationale="fixture scope checked", checked_evidence=[{"url": row["url"], "note": "fixture inspected"}])
    return summarize_review(private, blind, review_policy=review_policy)


class QueryEvaluationTests(unittest.TestCase):
    def test_primary_recall_includes_results_beyond_rank_fifteen(self):
        from multi_search_mcp.src.search.evaluation import prepare_review

        _, question = inputs()
        provider = ProviderSpec("brave", "brave", lambda query, *_: [
            {"source": "brave", "title": f"{query}-{rank}",
             "url": f"https://example.test/{query}-{rank}"} for rank in range(1, 17)
        ])
        snapshot = capture_snapshot({"query": "primary", "sources": ["brave"], "count": 16},
                                    expand=["a", "b"], providers={"brave": provider}, keys={}, config={})
        _, private = prepare_review(snapshot, question, "p1", [])
        self.assertEqual(len(private["primary_recalled_urls"]), 16)
        self.assertIn("https://example.test/primary-16", private["primary_recalled_urls"])

    def test_blank_or_nontext_checked_evidence_cannot_approve_a_review(self):
        from multi_search_mcp.src.search.evaluation import prepare_review, summarize_review

        snapshot, question = inputs()
        blind, private = prepare_review(snapshot, question, "p1", [])
        blind.update(reviewer="SYNTHETIC AI", reviewer_kind="ai",
                     reviewed_at=datetime.now(timezone.utc).isoformat())
        for row in blind["candidates"]:
            row.update(label="direct", rationale="synthetic evidence validation",
                       checked_evidence=[{"url": row["url"], "note": "fixture read"}])
        for field in ("url", "note"):
            for invalid in (" ", "\t\n", 123, ["not text"]):
                with self.subTest(field=field, invalid=invalid):
                    review = copy.deepcopy(blind)
                    review["candidates"][0]["checked_evidence"][0][field] = invalid
                    report = summarize_review(private, review, review_policy="allow_ai")
                    self.assertEqual(report["status"], "not_passed")
                    self.assertTrue(any("missing checked evidence" in issue for issue in report["issues"]))

    def test_sanitized_review_preparation_preserves_declared_fidelity_through_cli(self):
        from multi_search_mcp.src.search.evaluation import prepare_review, summarize_review

        _, question = inputs()
        provider = ProviderSpec("brave", "brave", lambda *_: [{"source": "brave", "url": "https://example.test/doc",
                                                                "title": "doc", "description": "MYSQL_ROOT_PASSWORD=public_example"}])
        snapshot = capture_snapshot({"query": "primary", "sources": ["brave"]}, expand=["a", "b", "c"],
                                    providers={"brave": provider}, keys={}, config={})
        with self.assertRaisesRegex(ValueError, "redaction"):
            prepare_review(snapshot, question, "p1", [])
        blind, private = prepare_review(snapshot, question, "p1", [], fidelity="sanitized_content")
        self.assertEqual(private["fidelity"], "sanitized_content")
        self.assertNotIn("public_example", json.dumps(blind))
        report = summarize_review(private, blind)
        self.assertEqual(report["fidelity"], "sanitized_content")
        self.assertEqual(report["status"], "not_passed")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("snapshot", snapshot), ("question", question), ("specs", [])):
                (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
            result = subprocess.run([sys.executable, "scripts/evaluate_query_fusion.py", "prepare", str(root / "snapshot.json"),
                                     "--question", str(root / "question.json"), "--prompt-id", "p1",
                                     "--policy-specs", str(root / "specs.json"), "--fidelity", "sanitized_content",
                                     "--blind", str(root / "blind.json"), "--private", str(root / "private.json")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root / "private.json").read_text(encoding="utf-8"))["fidelity"], "sanitized_content")

    def test_candidate_freeze_runs_heldout_without_approving_failed_development(self):
        from multi_search_mcp.src.search.evaluation import (
            evaluate_heldout, fingerprint, freeze_candidate, load_artifact, validate_freeze, write_artifact,
        )

        snapshot, question = inputs()
        heldout = dict(question, id="heldout", topic_group="heldout-topic")
        questions = {"development": [question], "heldout": [heldout]}
        decision = {"status": "ai_review_completed_no_switch", "quality_acceptance": "not_passed",
                    "review_policy": "allow_ai", "human_review": False, "default_changed": False,
                    "freeze": "not_selected", "completed_at": datetime.now(timezone.utc).isoformat(),
                    "reviewed_questions": 1, "expected_questions": 1, "reviewed_candidates": 4,
                    "labels": {"direct": 0, "partial": 0, "irrelevant": 0, "constraint_violation": 1, "pending": 3},
                    "unavailable_questions": [], "protocol_hash": "a" * 64,
                    "review_hashes": {"q1": "b" * 64}, "report_hashes": ["c" * 64]}
        selection = {"prompt_id": "p1", "policy_id": "equal", "query_fusion": {"mode": "equal"},
                     "selected_by": "SYNTHETIC AI", "selection_reason": "fixed experiment, not quality approval"}
        versions = {"skill_sha256": "a" * 64, "variant_prompt_sha256": "b" * 64}
        thresholds = {"min_direct_at5": 3, "max_violations_at10": 0, "min_variant_only_valid": 1}
        retrieval = {key: snapshot["execution"][key] for key in
                     ("route", "active_sources", "provider_counts", "timeout", "serpapi_engine", "count")}
        frozen = freeze_candidate(decision, selection, versions, thresholds, questions, retrieval,
                                  review_policy="allow_ai")
        self.assertEqual(frozen["status"], "candidate_frozen")
        self.assertFalse(frozen["release_eligible"])
        self.assertEqual(frozen["development_quality"], "not_passed")
        self.assertEqual(frozen["development_decision_sha256"], fingerprint(decision))
        self.assertEqual(frozen["thresholds"], thresholds)
        self.assertNotIn("candidates", frozen)
        for invalid in ({}, dict(decision, quality_acceptance="passed"), dict(decision, report_hashes=[]),
                        dict(decision, expected_questions=2), dict(decision, reviewed_candidates=99)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                freeze_candidate(invalid, selection, versions, thresholds, questions, retrieval, review_policy="allow_ai")
        with self.assertRaises(ValueError):
            freeze_candidate(decision, selection, versions, thresholds, questions, retrieval)
        with self.assertRaisesRegex(ValueError, "candidate"):
            validate_freeze(frozen, versions=versions, review_policy="allow_ai")
        validate_freeze(frozen, versions=versions, review_policy="allow_ai", allow_candidate=True)
        with self.assertRaisesRegex(ValueError, "version"):
            validate_freeze(frozen, versions=dict(versions, skill_sha256="c" * 64), review_policy="allow_ai", allow_candidate=True)
        contradictory = dict(frozen, release_eligible=True)
        contradictory["freeze_id"] = fingerprint({k: v for k, v in contradictory.items() if k != "freeze_id"})
        with self.assertRaisesRegex(ValueError, "negative development"):
            validate_freeze(contradictory, versions=versions, review_policy="allow_ai", allow_candidate=True)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            write_artifact(frozen, path)
            self.assertEqual(load_artifact(path), frozen)
            root = Path(directory)
            for name, value in (("decision", decision), ("selection", selection), ("versions", versions),
                                ("thresholds", thresholds), ("questions", questions), ("retrieval", retrieval)):
                (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
            result = subprocess.run([sys.executable, "scripts/evaluate_query_fusion.py", "freeze-candidate",
                                     "--development-decision", str(root / "decision.json"),
                                     "--selection", str(root / "selection.json"), "--versions", str(root / "versions.json"),
                                     "--thresholds", str(root / "thresholds.json"), "--question-set", str(root / "questions.json"),
                                     "--retrieval-config", str(root / "retrieval.json"), "--review-policy", "allow_ai",
                                     "--output", str(root / "cli-candidate.json")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            candidate = load_artifact(root / "cli-candidate.json")
            fresh, _ = inputs()
            report = reviewed(fresh, heldout, "p1", [], reviewer_kind="ai", review_policy="allow_ai")
            (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
            result = subprocess.run([sys.executable, "scripts/evaluate_query_fusion.py", "heldout",
                                     str(root / "cli-candidate.json"), "--report", str(root / "report.json"),
                                     "--versions", str(root / "versions.json"), "--question-set", str(root / "questions.json"),
                                     "--review-policy", "allow_ai", "--allow-candidate", "--output", str(root / "heldout.json")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = load_artifact(root / "heldout.json")
            self.assertEqual(result["freeze_id"], candidate["freeze_id"])
            self.assertFalse(result["release_eligible"])
        fresh, _ = inputs()
        for label, expected in (("direct", "heldout_thresholds_met"), ("pending", "not_passed")):
            reports = [reviewed(fresh, heldout, "p1", [], label, reviewer_kind="ai", review_policy="allow_ai")]
            with self.assertRaisesRegex(ValueError, "candidate"):
                evaluate_heldout(frozen, reports, versions=versions, question_set=questions, review_policy="allow_ai")
            result = evaluate_heldout(frozen, reports, versions=versions, question_set=questions,
                                      review_policy="allow_ai", allow_candidate=True)
            self.assertEqual(result["status"], expected)
            self.assertFalse(result["release_eligible"])
            self.assertEqual(result["freeze_status"], "candidate_frozen")
            self.assertEqual(result["development_quality"], "not_passed")
            self.assertEqual(result["recommendation"], "do_not_switch_default")
        for field, value in (("retrieval_config", dict(retrieval, timeout=retrieval["timeout"] + 1)),
                             ("snapshot_captured_at", "2000-01-01T00:00:00+00:00"),
                             ("question_hash", "d" * 64)):
            invalid = dict(reports[0], **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate_heldout(frozen, [invalid], versions=versions, question_set=questions,
                                  review_policy="allow_ai", allow_candidate=True)

    def test_blind_review_hides_strategy_and_reuses_requested_prompt_queries(self):
        from multi_search_mcp.src.search.evaluation import prepare_review

        snapshot, question = inputs()
        blind, private = prepare_review(snapshot, question, "p1", [{"id": "w09", "primary_weight": 1.0, "variant_budget": 0.9}])
        self.assertEqual(len(blind["candidates"]), 4)
        for forbidden in ("rrf_score", "provider_ranks", "w09", "query_ranks"):
            self.assertNotIn(forbidden, json.dumps(blind))
        self.assertEqual(private["queries"], ["primary", "a", "b"])
        self.assertEqual(set(private["rankings"]), {"primary", "equal", "w09"})
        self.assertEqual(set(private["ablations"]["equal"]), {"a", "b"})
        self.assertEqual(blind["expires_at"], snapshot["expires_at"])

    def test_only_complete_human_evidence_produces_reviewed_metrics(self):
        from multi_search_mcp.src.search.evaluation import prepare_review, summarize_review

        snapshot, question = inputs()
        blind, private = prepare_review(snapshot, question, "p1", [{"id": "w09", "primary_weight": 1.0, "variant_budget": 0.9}])
        self.assertEqual(summarize_review(private, blind)["status"], "not_passed")
        blind.update(reviewer="test reviewer", reviewer_kind="human", reviewed_at=datetime.now(timezone.utc).isoformat())
        for candidate in blind["candidates"]:
            candidate.update(label="direct", rationale="Checked the requested scope against the material",
                             checked_evidence=[{"url": candidate["url"], "note": "Inspected fixture passage"}],
                             original_material_id="one-material")
        summary = summarize_review(private, blind)
        self.assertEqual(summary["status"], "human_reviewed")
        self.assertEqual(summary["strategies"]["equal"]["at10"]["direct"], 4)
        self.assertEqual(summary["strategies"]["equal"]["variant_only_valid"], 2)
        self.assertEqual(summary["strategies"]["equal"]["original_materials"], 1)
        self.assertEqual(summary["strategies"]["equal"]["duplicate_evidence"], 3)
        self.assertEqual(summary["recommendation"], "do_not_switch_default")
        blind["reviewer_kind"] = "llm"
        self.assertEqual(summarize_review(private, blind)["status"], "not_passed")

    def test_freeze_requires_human_reviews_and_rejects_drift_and_topic_overlap(self):
        from multi_search_mcp.src.search.evaluation import prepare_review, summarize_review, freeze_development, validate_freeze

        snapshot, question = inputs()
        specs = [{"id": "w09", "primary_weight": 1.0, "variant_budget": 0.9}]
        blind, private = prepare_review(snapshot, question, "p1", specs)
        heldout = dict(question, id="q2", topic_group="topic-b")
        question_set = {"development": [question], "heldout": [heldout]}
        selection = {"prompt_id": "p1", "policy_id": "w09", "query_fusion": {"mode": "weighted", "primary_weight": 1.0, "variant_budget": 0.9},
                     "selected_by": "human selector", "selection_reason": "fixture-only structural test"}
        versions = {"skill_sha256": "a" * 64, "variant_prompt_sha256": "b" * 64}
        thresholds = {"min_direct_at5": 0, "max_violations_at10": 0, "min_variant_only_valid": 0}
        with self.assertRaisesRegex(ValueError, "human"):
            freeze_development([summarize_review(private, blind)], selection, versions, thresholds, question_set)
        reports = []
        for prompt_id in question["prompts"]:
            blind, private = prepare_review(snapshot, question, prompt_id, specs)
            blind.update(reviewer="test human", reviewer_kind="human", reviewed_at=datetime.now(timezone.utc).isoformat())
            for row in blind["candidates"]:
                row.update(label="direct", rationale="scope checked", checked_evidence=[{"url": row["url"], "note": "fixture inspected"}])
            reports.append(summarize_review(private, blind))
        frozen = freeze_development(reports, selection, versions, thresholds, question_set)
        self.assertEqual(frozen["status"], "human_selected")
        validate_freeze(frozen, versions=versions, selection=selection, heldout_question=heldout)
        with self.assertRaisesRegex(ValueError, "version"):
            validate_freeze(frozen, versions=dict(versions, skill_sha256="c" * 64))
        with self.assertRaisesRegex(ValueError, "topic"):
            freeze_development(reports, selection, versions, thresholds, {"development": [question], "heldout": [dict(heldout, topic_group="topic-a")]})
        with self.assertRaisesRegex(ValueError, "baseline"):
            freeze_development(reports, dict(selection, policy_id="primary"), versions, thresholds, question_set)
        drifted = copy.deepcopy(reports)
        drifted[0]["retrieval_config"]["timeout"] += 1
        with self.assertRaisesRegex(ValueError, "retrieval configs"):
            freeze_development(drifted, selection, versions, thresholds, question_set)

    def test_same_question_can_share_labels_across_prompt_packets(self):
        from multi_search_mcp.src.search.evaluation import prepare_review, summarize_review

        snapshot, question = inputs()
        first, private1 = prepare_review(snapshot, question, "p1", [])
        second, private2 = prepare_review(snapshot, question, "p2", [])
        first_ids = {row["url"]: row["candidate_id"] for row in first["candidates"]}
        second_ids = {row["url"]: row["candidate_id"] for row in second["candidates"]}
        self.assertEqual(first_ids["https://example.test/shared"], second_ids["https://example.test/shared"])
        merged = dict(first, packet_ids=[first["packet_id"], second["packet_id"]])
        merged["candidates"] = list({row["candidate_id"]: row for row in first["candidates"] + second["candidates"]}.values())
        self.assertEqual(summarize_review(private1, merged)["status"], "not_passed")
        self.assertEqual(summarize_review(private2, merged)["status"], "not_passed")
        merged["question_id"] = "wrong-question"
        with self.assertRaisesRegex(ValueError, "identity"):
            summarize_review(private1, merged)

    def test_expired_and_redacted_inputs_never_create_successful_review_artifacts(self):
        from multi_search_mcp.src.search.evaluation import load_artifact, prepare_review, write_artifact

        snapshot, question = inputs()
        snapshot["credentials_redacted"] = True
        with self.assertRaisesRegex(ValueError, "redaction"):
            prepare_review(snapshot, question, "p1", [])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "expired.json"
            expired = {"schema_version": 1, "expires_at": time.time() - 1, "status": "human_selected"}
            with self.assertRaisesRegex(ValueError, "expired"):
                write_artifact(expired, path)
            path.write_text(json.dumps(expired), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expired"):
                load_artifact(path)

    def test_heldout_cli_saves_and_loads_passing_and_failing_reports(self):
        from multi_search_mcp.src.search.evaluation import freeze_development, load_artifact

        snapshot, question = inputs()
        specs = [{"id": "w09", "primary_weight": 1.0, "variant_budget": 0.9}]
        dev = [reviewed(snapshot, question, prompt, specs) for prompt in question["prompts"]]
        heldout_question = dict(question, id="heldout", topic_group="heldout-topic")
        questions = {"development": [question], "heldout": [heldout_question]}
        versions = {"skill_sha256": "a" * 64, "variant_prompt_sha256": "b" * 64}
        selection = {"prompt_id": "p1", "policy_id": "w09", "query_fusion": {"mode": "weighted", "primary_weight": 1.0, "variant_budget": 0.9}, "selected_by": "SYNTHETIC", "selection_reason": "structural test only"}
        frozen = freeze_development(dev, selection, versions, {"min_direct_at5": 1, "max_violations_at10": 0, "min_variant_only_valid": 0}, questions)
        fresh, _ = inputs()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("freeze", frozen), ("versions", versions), ("questions", questions)):
                (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
            for label, status in (("direct", "heldout_thresholds_met"), ("constraint_violation", "not_passed")):
                report = reviewed(fresh, heldout_question, "p1", specs, label)
                (root / "review.json").write_text(json.dumps(report), encoding="utf-8")
                result = subprocess.run([sys.executable, "scripts/evaluate_query_fusion.py", "heldout", str(root / "freeze.json"), "--report", str(root / "review.json"), "--versions", str(root / "versions.json"), "--question-set", str(root / "questions.json"), "--output", str(root / f"{label}.json")], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(load_artifact(root / f"{label}.json")["status"], status)

    def test_review_cannot_change_the_question_or_original_displayed_candidate(self):
        from multi_search_mcp.src.search.evaluation import prepare_review, summarize_review

        snapshot, question = inputs()
        blind, private = prepare_review(snapshot, question, "p1", [])
        for mutate in (lambda packet: packet.update(question="different question"),
                       lambda packet: packet["candidates"][0].update(snippet="different evidence")):
            changed = copy.deepcopy(blind)
            mutate(changed)
            with self.assertRaisesRegex(ValueError, "question|display"):
                summarize_review(private, changed)

    def test_primary_rank_eleven_promotion_is_not_variant_only_recall(self):
        _, question = inputs()
        question["prompts"] = {"p1": question["prompts"]["p1"]}
        def row(name):
            return {"source": "brave", "title": name, "url": "https://example.test/" + name}
        data = {"primary": [row(f"p{rank:02d}") for rank in range(1, 13)],
                "a": [row("p11"), row("only-a")], "b": [row("p11"), row("only-b")]}
        snapshot = capture_snapshot({"query": "primary", "sources": ["brave"], "count": 15}, expand=["a", "b"],
                                    providers={"brave": ProviderSpec("brave", "brave", lambda query, *_: data[query])}, keys={}, config={})
        summary = reviewed(snapshot, question, "p1", [])
        self.assertEqual(summary["strategies"]["equal"]["variant_only_valid"], 2)
        self.assertEqual(summary["strategies"]["equal"]["new_in_top10"], 3)

    def test_ai_review_requires_explicit_policy_and_never_bypasses_pending_evidence(self):
        from multi_search_mcp.src.search.evaluation import prepare_review, summarize_review

        snapshot, question = inputs()
        review, private = prepare_review(snapshot, question, "p1", [])
        review.update(reviewer="SYNTHETIC TEST AI", reviewer_kind="ai", reviewed_at=datetime.now(timezone.utc).isoformat())
        for row in review["candidates"]:
            row.update(label="direct", rationale="fixture inspected", checked_evidence=[{"url": row["url"], "note": "checked scope"}])
        self.assertEqual(summarize_review(private, review)["status"], "not_passed")
        accepted = summarize_review(private, review, review_policy="allow_ai")
        self.assertEqual(accepted["status"], "ai_reviewed")
        self.assertEqual(accepted["reviewer_kind"], "ai")
        self.assertEqual(accepted["review_policy"], "allow_ai")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "private.json").write_text(json.dumps(private), encoding="utf-8")
            (root / "review.json").write_text(json.dumps(review), encoding="utf-8")
            for policy, status in (("human_only", "not_passed"), ("allow_ai", "ai_reviewed")):
                output = root / f"{policy}.json"
                command = [sys.executable, "scripts/evaluate_query_fusion.py", "summarize", str(root / "private.json"), str(root / "review.json"), "--review-policy", policy, "--output", str(output)]
                completed = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"], status)
        review["candidates"][0]["label"] = "pending"
        self.assertEqual(summarize_review(private, review, review_policy="allow_ai")["status"], "not_passed")
        review["candidates"][0].update(label="direct", checked_evidence=[])
        self.assertEqual(summarize_review(private, review, review_policy="allow_ai")["status"], "not_passed")

    def test_ai_freeze_and_heldout_require_matching_explicit_policy(self):
        from multi_search_mcp.src.search.evaluation import freeze_development, validate_freeze, evaluate_heldout, load_artifact, write_artifact

        snapshot, question = inputs()
        dev = [reviewed(snapshot, question, prompt, [], reviewer_kind="ai", review_policy="allow_ai") for prompt in question["prompts"]]
        heldout_question = dict(question, id="heldout", topic_group="heldout-topic")
        questions = {"development": [question], "heldout": [heldout_question]}
        versions = {"skill_sha256": "a" * 64, "variant_prompt_sha256": "b" * 64}
        selection = {"prompt_id": "p1", "policy_id": "equal", "query_fusion": {"mode": "equal"}, "selected_by": "SYNTHETIC AI", "selection_reason": "structural test only"}
        thresholds = {"min_direct_at5": 1, "max_violations_at10": 0, "min_variant_only_valid": 0}
        with self.assertRaisesRegex(ValueError, "human"):
            freeze_development(dev, selection, versions, thresholds, questions)
        frozen = freeze_development(dev, selection, versions, thresholds, questions, review_policy="allow_ai")
        self.assertEqual(frozen["status"], "ai_selected")
        self.assertEqual(frozen["reviewer_kind"], "ai")
        with self.assertRaisesRegex(ValueError, "policy"):
            validate_freeze(frozen, versions=versions)
        validate_freeze(frozen, versions=versions, review_policy="allow_ai")
        fresh, _ = inputs()
        reports = [reviewed(fresh, heldout_question, "p1", [], reviewer_kind="ai", review_policy="allow_ai")]
        result = evaluate_heldout(frozen, reports, versions=versions, question_set=questions, review_policy="allow_ai")
        self.assertEqual(result["status"], "heldout_thresholds_met")
        self.assertEqual(result["reviewer_kind"], "ai")
        self.assertEqual(result["review_policy"], "allow_ai")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ai-freeze.json"
            write_artifact(frozen, path)
            self.assertEqual(load_artifact(path), frozen)


if __name__ == "__main__":
    unittest.main()

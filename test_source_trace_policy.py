import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parent
DRIVER = ROOT / "scripts/source_trace_fixture.py"


class SourceTracePolicyTests(unittest.TestCase):
    def invoke(self, session, *, config=None, extra=(), expand=True, count=2, overrides=None):
        command = [sys.executable, str(DRIVER), "--scenario", "technical",
                   "--session", str(session), "--tool", "search_web", "--args", "-"]
        if config is not None:
            command.extend(["--config", str(config)])
        command.extend(extra)
        args = {"query": "primary", "count": count}
        if expand:
            args["expand"] = ["variant"]
        args.update(overrides or {})
        return subprocess.run(command, input=json.dumps(args), capture_output=True,
                              text=True, encoding="utf-8", cwd=ROOT)

    def test_explicit_config_changes_actual_core_fusion_and_marks_unfrozen_run(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(json.dumps({"query_fusion": {
                "mode": "weighted", "primary_weight": 1.0, "variant_budget": 0.9,
            }}), encoding="utf-8")
            weighted = self.invoke(root / "weighted", config=config)
            self.assertEqual(weighted.returncode, 0, weighted.stderr)
            result = json.loads(weighted.stdout)
            self.assertAlmostEqual(result["results"][0]["rrf_score"], 0.04634146341463415)
            self.assertEqual(result["diagnostics"]["query_fusion"]["weights"],
                             {"primary": 1.0, "variant": 0.9})
            metadata = json.loads((root / "weighted/metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["policy_status"], "experimental_unfrozen")
            self.assertEqual(metadata["query_fusion"]["mode"], "weighted")
            self.assertEqual(len(metadata["config_sha256"]), 64)

    def test_default_sessions_remain_compatible_and_single_query_scores_stay_unchanged(self):
        with TemporaryDirectory() as directory:
            session = Path(directory) / "default"
            first = self.invoke(session, expand=False)
            second = self.invoke(session, expand=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            metadata = json.loads((session / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(set(metadata), {"scenario", "skill_sha256", "fixtures_sha256", "prompt", "mode"})
            self.assertAlmostEqual(json.loads(second.stdout)["results"][0]["rrf_score"],
                                   0.04878048780487805)

    def test_nonsecret_config_defaults_reach_core_query_planning(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text('{"expand":["configured-angle"]}', encoding="utf-8")
            result = self.invoke(root / "session", config=config, expand=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["diagnostics"]["queries"],
                             ["primary", "configured-angle"])

    def test_a_config_change_cannot_mix_policies_in_the_same_session(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text('{}', encoding="utf-8")
            first = self.invoke(root / "session", config=config)
            self.assertEqual(first.returncode, 0, first.stderr)
            config.write_text('{"query_fusion":{"mode":"weighted","primary_weight":1,"variant_budget":0.9}}', encoding="utf-8")
            second = self.invoke(root / "session", config=config)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(len((root / "session/calls.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_an_experiment_is_rejected_as_a_human_review_freeze(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text('{}', encoding="utf-8")
            freeze = root / "freeze.json"
            freeze.write_text('{"status":"experimental_unfrozen"}', encoding="utf-8")
            result = self.invoke(root / "session", config=config, extra=(
                "--freeze", str(freeze), "--variant-prompt", str(ROOT / "skills/multi-search/SKILL.md"),
            ))
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("unrecognized arguments", result.stderr)
            self.assertNotIn("ImportError", result.stderr)
            self.assertFalse((root / "session/calls.jsonl").exists())

    def synthetic_freeze(self, root, sources=("brave", "exa"), capture_config=None, capture_count=10, review_kind="human"):
        """Temporary structural input only; these labels are not human evidence."""
        from multi_search_mcp.src.search.evaluation import (
            prepare_review, summarize_review, freeze_development,
        )
        from multi_search_mcp.src.search.search_runner import ProviderSpec
        from multi_search_mcp.src.search.snapshots import capture_snapshot

        question = {"id": "dev", "question": "primary", "topic_group": "dev-topic", "category": "test",
                    "prompts": {"p1": {"variants": ["variant"], "reason": "synthetic angle"}}}
        def provider(source):
            return ProviderSpec(source, source, lambda query, *_: [{
                "source": source, "url": "https://fixture.example/" + query, "title": query,
            }])
        snapshot = capture_snapshot({"query": "primary", "sources": list(sources), "count": capture_count}, expand=["variant"],
                                    providers={source: provider(source) for source in sources}, keys={}, config=capture_config or {})
        policy = {"mode": "weighted", "primary_weight": 1.0, "variant_budget": 0.9}
        blind, private = prepare_review(snapshot, question, "p1", [
            {"id": "w09", "primary_weight": 1.0, "variant_budget": 0.9},
        ])
        blind.update(reviewer="SYNTHETIC TEST DECLARATION", reviewer_kind=review_kind,
                     reviewed_at=datetime.now(timezone.utc).isoformat())
        for row in blind["candidates"]:
            row.update(label="direct", rationale="synthetic schema test",
                       checked_evidence=[{"url": row["url"], "note": "synthetic test only"}])
        prompt = root / "prompt.md"
        prompt.write_text("Synthetic variant instructions for CLI tests only.", encoding="utf-8")
        versions = {
            "skill_sha256": hashlib.sha256((ROOT / "skills/multi-search/SKILL.md").read_bytes()).hexdigest(),
            "variant_prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
        }
        review_policy = "allow_ai" if review_kind == "ai" else "human_only"
        frozen = freeze_development([summarize_review(private, blind, review_policy=review_policy)], {
            "prompt_id": "p1", "policy_id": "w09", "query_fusion": policy,
            "selected_by": "SYNTHETIC TEST DECLARATION", "selection_reason": "temporary CLI structure test",
        }, versions, {"min_direct_at5": 0, "max_violations_at10": 0, "min_variant_only_valid": 0}, {
            "development": [question], "heldout": [dict(question, id="heldout", topic_group="heldout-topic")],
        }, review_policy=review_policy)
        config = root / "config.json"
        config.write_text(json.dumps({"query_fusion": policy}), encoding="utf-8")
        freeze = root / "freeze.json"
        freeze.write_text(json.dumps(frozen), encoding="utf-8")
        return config, freeze, prompt

    def test_frozen_policy_runs_core_but_rejects_a_different_display_window(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, freeze, prompt = self.synthetic_freeze(root)
            extra = ("--freeze", str(freeze), "--variant-prompt", str(prompt))
            result = self.invoke(root / "frozen", config=config, extra=extra, count=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertAlmostEqual(json.loads(result.stdout)["results"][0]["rrf_score"],
                                   0.04634146341463415)
            metadata = json.loads((root / "frozen/metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["policy_status"], "human_selected_frozen")
            changed = self.invoke(root / "different-window", config=config, extra=extra, count=2)
            self.assertNotEqual(changed.returncode, 0)
            self.assertFalse((root / "different-window/calls.jsonl").exists())

    def test_ai_freeze_requires_explicit_ai_policy_and_keeps_ai_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, freeze, prompt = self.synthetic_freeze(root, review_kind="ai")
            extra = ("--freeze", str(freeze), "--variant-prompt", str(prompt))
            rejected = self.invoke(root / "rejected", config=config, extra=extra, count=10)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse((root / "rejected/calls.jsonl").exists())
            accepted = self.invoke(root / "accepted", config=config,
                                   extra=extra + ("--review-policy", "allow_ai"), count=10)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            metadata = json.loads((root / "accepted/metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["policy_status"], "ai_selected_frozen")

    def test_candidate_freeze_requires_explicit_opt_in_and_never_marks_release_approval(self):
        from multi_search_mcp.src.search.evaluation import fingerprint

        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, freeze, prompt = self.synthetic_freeze(root, review_kind="ai")
            record = json.loads(freeze.read_text(encoding="utf-8"))
            record.update(status="candidate_frozen", release_eligible=False,
                          development_quality="not_passed",
                          development_decision_status="ai_review_completed_no_switch",
                          development_decision_sha256="1" * 64)
            record["freeze_id"] = fingerprint({k: v for k, v in record.items() if k != "freeze_id"})
            freeze.write_text(json.dumps(record), encoding="utf-8")
            extra = ("--freeze", str(freeze), "--variant-prompt", str(prompt),
                     "--review-policy", "allow_ai")
            rejected = self.invoke(root / "rejected", config=config, extra=extra, count=10)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("allow_candidate", rejected.stderr)
            self.assertFalse((root / "rejected/calls.jsonl").exists())
            accepted = self.invoke(root / "accepted", config=config,
                                   extra=extra + ("--allow-candidate",), count=10)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            metadata = json.loads((root / "accepted/metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["policy_status"], "candidate_frozen")
            self.assertIs(metadata["release_eligible"], False)

    def test_frozen_policy_rejects_policy_skill_and_prompt_drift_before_search(self):
        from multi_search_mcp.src.search.evaluation import fingerprint

        for drift in ("policy", "skill", "prompt"):
            with self.subTest(drift=drift), TemporaryDirectory() as directory:
                root = Path(directory)
                config, freeze, prompt = self.synthetic_freeze(root)
                if drift == "policy":
                    config.write_text('{"query_fusion":{"mode":"weighted","primary_weight":1,"variant_budget":0.8}}', encoding="utf-8")
                elif drift == "prompt":
                    prompt.write_text("Changed variant instructions.", encoding="utf-8")
                else:
                    # Simulate an older Skill in the synthetic freeze without
                    # modifying the real Skill or any concurrent AI session.
                    frozen = json.loads(freeze.read_text(encoding="utf-8"))
                    frozen["versions"]["skill_sha256"] = "0" * 64
                    frozen["freeze_id"] = fingerprint({key: value for key, value in frozen.items() if key != "freeze_id"})
                    freeze.write_text(json.dumps(frozen), encoding="utf-8")
                result = self.invoke(root / "session", config=config, count=10, extra=(
                    "--freeze", str(freeze), "--variant-prompt", str(prompt),
                ))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mismatch", result.stderr)
                self.assertFalse((root / "session/calls.jsonl").exists())

    def test_brave_only_freeze_rejects_the_drivers_brave_and_exa_execution(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, freeze, prompt = self.synthetic_freeze(root, sources=("brave",))
            result = self.invoke(root / "drifted", config=config, count=10, extra=(
                "--freeze", str(freeze), "--variant-prompt", str(prompt),
            ))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("retrieval", result.stderr)
            self.assertFalse((root / "drifted/calls.jsonl").exists())
            matched = self.invoke(root / "matching", config=config, count=10, extra=(
                "--freeze", str(freeze), "--variant-prompt", str(prompt),
            ), overrides={"sources": ["brave"]})
            self.assertEqual(matched.returncode, 0, matched.stderr)
            self.assertEqual(json.loads(matched.stdout)["diagnostics"]["active_sources"], ["brave"])

    def test_frozen_retrieval_route_counts_timeout_and_engine_must_match_resolved_core_plan(self):
        for capture_config in ({"type": "fast"}, {"counts": {"brave": 3}},
                               {"timeout": 1}, {"serpapi_engine": "google"}):
            with self.subTest(capture_config=capture_config), TemporaryDirectory() as directory:
                root = Path(directory)
                config, freeze, prompt = self.synthetic_freeze(
                    root, capture_config=capture_config,
                    capture_count=None if "counts" in capture_config else 10,
                )
                result = self.invoke(root / "session", config=config, count=10, extra=(
                    "--freeze", str(freeze), "--variant-prompt", str(prompt),
                ))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("retrieval", result.stderr)
                self.assertFalse((root / "session/calls.jsonl").exists())


if __name__ == "__main__":
    unittest.main()

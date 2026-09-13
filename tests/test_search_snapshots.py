import copy
import io
import json
import socket
import time
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.service import _run_search_candidates


def fixed_providers():
    data = {
        "question": [
            {"source": "brave", "title": "Z first", "url": "https://example.test/z", "description": "first"},
            {"source": "brave", "title": "Shared", "url": "https://example.test/shared", "description": "excerpt", "scraped_content": "NEVER STORE BODY", "content_kind": "body"},
        ],
        "variant": [
            {"source": "brave", "title": "Added", "url": "https://example.test/added"},
            {"source": "brave", "title": "Shared", "url": "https://example.test/shared"},
        ],
    }
    return {"brave": ProviderSpec("brave", "brave", lambda query, *_: copy.deepcopy(data[query]))}


class SearchSnapshotTests(unittest.TestCase):
    def test_parallel_publication_date_survives_search_capture_and_replay(self):
        from multi_search_mcp.src.search.searchers import parallel
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        payload = {"results": [{
            "url": "https://example.test/release", "title": "Release",
            "publish_date": "2026-09-09", "excerpts": ["Release details"],
        }]}
        providers = {"parallel": ProviderSpec("parallel", "parallel", lambda query, cfg, ctx, key:
            parallel.search_parallel(query, key or "fixture-key", cfg.counts["parallel"], timeout=ctx.timeout))}
        request = {"query": "release", "sources": ["parallel"], "use_state": False}
        with mock.patch.object(parallel, "urlopen_retry", side_effect=lambda *_args, **_kwargs:
                               io.BytesIO(json.dumps(payload).encode())):
            actual = _run_search_candidates(request, providers=providers, keys={}, config={})
            snapshot = capture_snapshot(request, expand=[], providers=providers, keys={}, config={})
        self.assertEqual(actual["results"][0]["published_at"], "2026-09-09")
        self.assertEqual(snapshot["query_runs"][0]["rows"][0]["published_at"], "2026-09-09")
        self.assertEqual(replay_snapshot(snapshot)["results"][0]["published_at"], "2026-09-09")

    def test_windowed_legacy_or_mismatched_algorithm_cannot_be_replayed(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, load_snapshot, replay_snapshot

        snapshot = capture_snapshot({"query": "question", "sources": ["brave"]},
                                    expand=[], providers=fixed_providers(), keys={}, config={})
        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(snapshot["fusion"], {
            "algorithm": "two_level_rrf", "rank_constant": 40, "rank_window": None,
        })
        for change in (
            lambda value: value.update(schema_version=1),
            lambda value: value.pop("fusion"),
            lambda value: value["fusion"].update(rank_window=15),
            lambda value: value["fusion"].update(rank_constant=60),
        ):
            changed = copy.deepcopy(snapshot)
            change(changed)
            with self.assertRaisesRegex(ValueError, "unsupported snapshot"):
                replay_snapshot(changed)
            with TemporaryDirectory() as directory:
                path = Path(directory) / "incompatible.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "unsupported snapshot"):
                    load_snapshot(path)
                self.assertTrue(path.exists())

    def test_replay_keeps_recall_count_separate_from_final_limit(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        provider = ProviderSpec("brave", "brave", lambda *_: [
            {"source": "brave", "title": f"Result {rank}",
             "url": f"https://example.test/{rank}"} for rank in range(1, 31)
        ])
        snapshot = capture_snapshot({"query": "question", "sources": ["brave"], "count": 30},
                                    expand=[], providers={"brave": provider}, keys={}, config={})
        self.assertEqual(snapshot["execution"]["count"], 30)
        self.assertEqual(snapshot["execution"]["result_limit"], 15)
        self.assertEqual(len(snapshot["query_runs"][0]["rows"]), 30)
        self.assertEqual(len(replay_snapshot(snapshot)["results"]), 15)
        self.assertEqual(len(replay_snapshot(snapshot, limit=30)["results"]), 30)

    def test_public_credential_example_requires_explicit_sanitized_content_replay(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, compare_snapshot, replay_snapshot

        providers = {"brave": ProviderSpec("brave", "brave", lambda *_: [{
            "source": "brave", "url": "https://example.test/docker", "title": "Docker setup",
            "description": "Set MYSQL_ROOT_PASSWORD=public_example before startup.",
        }])}
        snapshot = capture_snapshot({"query": "Docker setup", "sources": ["brave"]},
                                    expand=[], providers=providers, keys={}, config={})
        self.assertNotIn("public_example", json.dumps(snapshot))
        with self.assertRaisesRegex(ValueError, "redaction"):
            replay_snapshot(snapshot)
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")):
            replay = replay_snapshot(snapshot, fidelity="sanitized_content")
            comparison = compare_snapshot(snapshot, fidelity="sanitized_content")
        self.assertEqual(replay["fidelity"], "sanitized_content")
        self.assertEqual(replay["results"][0]["canonical_url"], "https://example.test/docker")
        self.assertEqual(replay["results"][0]["provider_ranks"], [
            {"provider": "brave", "query": "Docker setup", "rank": 1},
        ])
        self.assertIn("<redacted>", replay["results"][0]["content"])
        self.assertEqual(comparison["candidate"]["fidelity"], "sanitized_content")

    def test_sanitized_content_refuses_identity_filter_and_title_redaction(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        for field in ("title", "url", "source", "error", "status"):
            with self.subTest(field=field):
                row = {"source": "brave", "url": "https://example.test/docs", "title": "Docs"}
                row[field] = "https://example.test/?password=example" if field == "url" else "password=example"
                providers = {"brave": ProviderSpec("brave", "brave", lambda *_, row=row: [row.copy()])}
                snapshot = capture_snapshot({"query": "question", "sources": ["brave"]},
                                            expand=[], providers=providers, keys={}, config={})
                with self.assertRaisesRegex(ValueError, "proof"):
                    replay_snapshot(snapshot, fidelity="sanitized_content")
        providers = {"brave": ProviderSpec("brave", "brave", lambda *_: [{
            "source": "brave", "url": "https://example.test/docs",
        }])}
        snapshot = capture_snapshot({"query": "password=example", "sources": ["brave"]},
                                    expand=[], providers=providers, keys={}, config={})
        with self.assertRaisesRegex(ValueError, "proof"):
            replay_snapshot(snapshot, fidelity="sanitized_content")

    def test_sanitized_content_proof_survives_json_but_not_legacy_or_changed_inputs(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        snapshot = capture_snapshot({"query": "question", "sources": ["brave"]},
                                    expand=["variant"], providers=fixed_providers(), keys={}, config={})
        serialized = json.loads(json.dumps(snapshot))
        self.assertEqual(replay_snapshot(serialized)["fidelity"], "exact")
        self.assertEqual(replay_snapshot(serialized, fidelity="sanitized_content")["results"],
                         replay_snapshot(snapshot)["results"])
        for change in (
            lambda value: value.pop("sanitized_content_proof"),
            lambda value: value["query_runs"][0]["rows"][0].update(provider_rank=9),
            lambda value: value["query_runs"][0]["rows"][0].update(status="changed"),
            lambda value: value["query_runs"][0]["rows"][0].update(content="changed excerpt"),
        ):
            changed = copy.deepcopy(serialized)
            change(changed)
            with self.assertRaisesRegex(ValueError, "proof"):
                replay_snapshot(changed, fidelity="sanitized_content")

    def test_sanitized_content_does_not_change_snippet_eligibility_or_retention(self):
        from multi_search_mcp.src.search.capabilities import PROVIDER_CAPABILITIES, RetentionPolicy
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        providers = {"brave": ProviderSpec("brave", "brave", lambda *_: [{
            "source": "brave", "url": "https://example.test/docs", "description": "    ",
            "content_kind": "body",
        }])}
        snapshot = capture_snapshot({"query": "question", "sources": ["brave"]},
                                    expand=[], providers=providers, keys={"example": "    "}, config={})
        with self.assertRaisesRegex(ValueError, "proof"):
            replay_snapshot(snapshot, fidelity="sanitized_content")
        restricted = replace(PROVIDER_CAPABILITIES["brave"], retention=RetentionPolicy(persist_content=False))
        with mock.patch.dict(PROVIDER_CAPABILITIES, {"brave": restricted}):
            snapshot = capture_snapshot({"query": "question", "sources": ["brave"]},
                                        expand=[], providers=fixed_providers(), keys={}, config={})
        with self.assertRaisesRegex(ValueError, "retention"):
            replay_snapshot(snapshot, fidelity="sanitized_content")

    def test_capture_replays_actual_core_candidates_without_network(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        request = {"query": "question", "sources": ["brave"], "count": 3, "use_state": False}
        snapshot = capture_snapshot(request, expand=["variant"], providers=fixed_providers(), keys={}, config={})
        actual = _run_search_candidates(dict(request, expand=["variant"]), providers=fixed_providers(), keys={}, config={})
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("offline replay accessed network")):
            first = replay_snapshot(snapshot)
            second = replay_snapshot(snapshot)
        def comparable(hits):
            return [{k: v for k, v in hit.items() if k not in {"source_id", "content_ref"}} for hit in hits]
        self.assertEqual(comparable(first["results"]), comparable(actual["results"]))
        self.assertEqual(first["results"], second["results"])
        self.assertEqual(first["results"][0]["canonical_url"], "https://example.test/shared")
        self.assertNotIn("NEVER STORE BODY", json.dumps(snapshot))
        self.assertEqual(snapshot["collection"]["provider_attempt_count"], 2)

    def test_explicit_expansion_and_ablation_preserve_primary_baseline(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, compare_snapshot, replay_snapshot

        config = {"expand": ["not explicitly provided"], "expand_queries": ["also excluded"]}
        request = {"query": "question", "sources": ["brave"], "count": 2}
        primary = capture_snapshot(request, expand=[], providers=fixed_providers(), keys={}, config=config)
        self.assertEqual(primary["variants"], [])
        self.assertEqual(primary["collection"]["provider_attempt_count"], 1)
        self.assertEqual(config["expand"], ["not explicitly provided"])
        expanded = capture_snapshot(request, expand=["variant"], providers=fixed_providers(), keys={}, config=config)
        ablated = replay_snapshot(expanded, omit_variants=["variant"])
        baseline = replay_snapshot(expanded, mode="primary")
        self.assertEqual(ablated["results"], baseline["results"])
        report = compare_snapshot(expanded, limit=2)
        self.assertEqual(report["difference"]["added"], ["https://example.test/added"])
        self.assertEqual(report["difference"]["lost"], ["https://example.test/z"])
        self.assertEqual(report["difference"]["rank_changes"], [{"canonical_url": "https://example.test/shared", "before": 2, "after": 1}])
        report = compare_snapshot(expanded, omit_variants=["variant"], limit=2)
        self.assertEqual(report["difference"]["added"], ["https://example.test/z"])
        self.assertEqual(report["difference"]["lost"], ["https://example.test/added"])

    def test_missing_rows_ranks_or_expired_data_cannot_be_replayed(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        snapshot = capture_snapshot({"query": "question", "sources": ["brave"]}, expand=["variant"], providers=fixed_providers(), keys={}, config={})
        for change in (
            lambda value: value["query_runs"].pop(),
            lambda value: value["query_runs"][0]["rows"].pop(),
            lambda value: value["query_runs"][0]["rows"][0].pop("provider_rank"),
            lambda value: value.update(expires_at=time.time() - 1),
        ):
            broken = copy.deepcopy(snapshot)
            change(broken)
            with self.assertRaises(ValueError):
                replay_snapshot(broken)

    def test_restricted_content_and_credentials_are_excluded_with_explicit_replay_failure(self):
        from multi_search_mcp.src.search.capabilities import PROVIDER_CAPABILITIES, RetentionPolicy
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        restricted = replace(PROVIDER_CAPABILITIES["brave"], retention=RetentionPolicy(persist_content=False, max_ttl_seconds=20))
        with mock.patch.dict(PROVIDER_CAPABILITIES, {"brave": restricted}):
            snapshot = capture_snapshot({"query": "question", "sources": ["brave"]}, expand=[], providers=fixed_providers(), keys={}, config={})
        self.assertNotIn("description", snapshot["query_runs"][0]["rows"][0])
        self.assertLess(snapshot["expires_at"], time.time() + 21)
        with self.assertRaisesRegex(ValueError, "retention"):
            replay_snapshot(snapshot)

        providers = {"brave": ProviderSpec("brave", "brave", lambda *_: [{
            "source": "brave", "title": "credential TEST_SECRET_123", "url": "https://person:password@example.test/?token=hidden", "raw": {"auth": "should never store"},
        }])}
        snapshot = capture_snapshot({"query": "question", "sources": ["brave"]}, expand=[], providers=providers, keys={"brave": "TEST_SECRET_123"}, config={"ignored_key": "should never store"})
        serialized = json.dumps(snapshot)
        for forbidden in ("TEST_SECRET_123", "person:password", "hidden", "should never store"):
            self.assertNotIn(forbidden, serialized)
        with self.assertRaisesRegex(ValueError, "redaction"):
            replay_snapshot(snapshot)

    def test_snapshot_file_expires_and_is_removed_on_read(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, load_snapshot, write_snapshot

        snapshot = capture_snapshot({"query": "question", "sources": ["brave"]}, expand=[], providers=fixed_providers(), keys={}, config={})
        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            write_snapshot(snapshot, path)
            self.assertEqual(load_snapshot(path), snapshot)
            snapshot["expires_at"] = time.time() - 1
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expired"):
                load_snapshot(path)
            self.assertFalse(path.exists())

    def test_missing_or_invalid_expiry_preserves_the_input_file(self):
        from multi_search_mcp.src.search.snapshots import FUSION_ALGORITHM, SCHEMA_VERSION, load_snapshot

        with TemporaryDirectory() as directory:
            path = Path(directory) / "incomplete.json"
            for expiry in (None, "yesterday", True, float("nan"), float("inf")):
                value = {"schema_version": SCHEMA_VERSION, "fusion": dict(FUSION_ALGORITHM), "important": "keep"}
                if expiry is not None:
                    value["expires_at"] = expiry
                original = json.dumps(value)
                path.write_text(original, encoding="utf-8")
                with self.subTest(expiry=expiry), self.assertRaises(ValueError):
                    load_snapshot(path)
                self.assertTrue(path.exists())
                self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_retention_forbidden_source_does_not_persist_error_text(self):
        from multi_search_mcp.src.search.capabilities import PROVIDER_CAPABILITIES, RetentionPolicy
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        restricted = replace(PROVIDER_CAPABILITIES["brave"], retention=RetentionPolicy(persist_search_result=False, persist_content=False))
        providers = {"brave": ProviderSpec("brave", "brave", lambda *_: [{"source": "brave", "error": "FORBIDDEN provider text"}])}
        with mock.patch.dict(PROVIDER_CAPABILITIES, {"brave": restricted}):
            snapshot = capture_snapshot({"query": "question", "sources": ["brave"]}, expand=[], providers=providers, keys={}, config={})
        self.assertNotIn("FORBIDDEN", json.dumps(snapshot))
        self.assertTrue(snapshot["query_runs"][0]["restrictions"])
        with self.assertRaisesRegex(ValueError, "retention"):
            replay_snapshot(snapshot)

    def test_unavailable_provider_is_not_an_empty_successful_capture(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        snapshot = capture_snapshot({"query": "question", "sources": ["brave", "exa"]}, expand=[], providers=fixed_providers(), keys={}, config={})
        with self.assertRaisesRegex(ValueError, "unavailable|missing"):
            replay_snapshot(snapshot)

    def test_collection_counts_key_retry_and_preserves_redacted_attempt_failure(self):
        from multi_search_mcp.src.search.snapshots import capture_snapshot, replay_snapshot

        def call(query, config, context, key):
            if key == "bad_key_123":
                return [{"source": "brave", "error": "HTTP 401 api_key=bad_key_123"}]
            return [{"source": "brave", "url": "https://example.test/success", "title": "Success"}]
        provider = ProviderSpec("brave", "brave", call, key_name="brave")
        snapshot = capture_snapshot({"query": "question", "sources": ["brave"]}, expand=[], providers={"brave": provider}, keys={"brave": ["bad_key_123", "good_key_123"]}, config={})
        self.assertEqual(snapshot["collection"]["provider_attempt_count"], 2)
        self.assertEqual([attempt["status"] for attempt in snapshot["collection"]["provider_attempts"]], ["error", "ok"])
        self.assertNotIn("bad_key_123", json.dumps(snapshot))
        self.assertEqual(replay_snapshot(snapshot)["results"][0]["url"], "https://example.test/success")

    def test_weighted_replay_matches_core_and_ablation_uses_the_same_query_set(self):
        from multi_search_mcp.src.search.query_policy import QueryFusionPolicy
        from multi_search_mcp.src.search.snapshots import capture_snapshot, compare_snapshot, replay_snapshot

        request = {"query": "question", "sources": ["brave"], "count": 2, "use_state": False}
        policy = QueryFusionPolicy(mode="weighted", primary_weight=1.0, variant_budget=0.9)
        config = {"query_fusion": policy.to_dict()}
        snapshot = capture_snapshot(request, expand=["variant"], providers=fixed_providers(), keys={}, config=config)
        actual = _run_search_candidates(dict(request, expand=["variant"]), providers=fixed_providers(), keys={}, config=config)
        weighted = replay_snapshot(snapshot, mode="weighted", query_policy=policy)
        self.assertEqual(
            replay_snapshot(snapshot, mode="weighted", query_policy=policy, fidelity="sanitized_content")["results"],
            weighted["results"],
        )
        def comparable(hits):
            return [{k: v for k, v in hit.items() if k not in {"source_id", "content_ref"}} for hit in hits]
        self.assertEqual(comparable(weighted["results"]), comparable(actual["results"]))
        self.assertEqual(snapshot["execution"]["query_fusion"], config["query_fusion"])
        self.assertEqual(replay_snapshot(snapshot)["queries"], weighted["queries"])
        ablation = compare_snapshot(snapshot, mode="weighted", omit_variants=["variant"], query_policy=policy)
        self.assertEqual(ablation["candidate"]["results"], replay_snapshot(snapshot, mode="primary")["results"])
        with self.assertRaisesRegex(ValueError, "explicit query_policy"):
            replay_snapshot(snapshot, mode="weighted", query_policy=QueryFusionPolicy())


if __name__ == "__main__":
    unittest.main()

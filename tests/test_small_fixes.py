"""Regression tests for the T06 small fixes.

Covers the compatibility Markdown rerank fallback label, single search-plan
resolution per request, key recovery clearing the quota deadline, and manual
key disabling being visible in status summaries and human output.
"""
from __future__ import annotations

import io
import tempfile
import unittest
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import multi_search_mcp.cli as cli
from multi_search_mcp.src.search.rerank import RerankError
from multi_search_mcp.src.service import MultiSearchRequest, run_multi_search
from multi_search_mcp.src.state import key_state
from multi_search_mcp.src.state.key_state import (
    ACTIVE,
    KeyOutcome,
    SQLiteKeyManager,
    summarize_status_rows,
)
from multi_search_mcp.src.state.state_store import StateStore


def _fake_ranked_fetch_stage(hits, **kwargs):
    """Return deterministic fetched bodies without running the network callback."""
    return {
        "results": [
            {"source_id": hit["source_id"], "url": hit["url"],
             "body": f"Fetched body for {hit['url']}", "backend": "fake"}
            for hit in hits
        ],
        "errors": [],
    }


class _FakeRunner:
    def __init__(self, config, providers, route_resolver=None, key_manager=None):
        pass

    def run(self, query, *, deadline=None):
        return [{
            "source": "brave", "title": "Doc",
            "url": "https://example.com/doc", "description": "excerpt",
        }]


class _FailingReranker:
    def score(self, query, candidates, *, deadline):
        raise RerankError("auth")


def _run_multi_search(config, request, *, reranker=None):
    with mock.patch(
        "multi_search_mcp.src.state.runtime.load_config_safe", return_value=config,
    ), mock.patch(
        "multi_search_mcp.src.state.runtime.load_keys", return_value={},
    ), mock.patch(
        "multi_search_mcp.src.search.candidates.SearchRunner", _FakeRunner,
    ), mock.patch(
        "multi_search_mcp.src.search.registry.build_provider_registry", return_value={},
    ), mock.patch(
        "multi_search_mcp.src.search_web.run_ranked_fetch_stage",
        side_effect=_fake_ranked_fetch_stage,
    ):
        return run_multi_search(request, reranker=reranker)


class MultiSearchPresentationTests(unittest.TestCase):
    def test_markdown_reports_model_fallback_to_rrf(self):
        response = _run_multi_search(
            {},
            MultiSearchRequest(
                query="q", output="markdown", use_state=False,
                ranking={"mode": "rrf_model", "base_url": "http://127.0.0.1:9", "model": "fixture"},
            ),
            reranker=_FailingReranker(),
        )
        self.assertEqual(
            (response["mode_requested"], response["mode_used"], response["fallback_reason"]),
            ("rrf_model", "rrf", "auth"),
        )
        self.assertIn("**排序：** 模型暂不可用，已使用 RRF", response["markdown"])

    def test_deprecated_config_warns_once_per_request(self):
        legacy = {"scrape_top": 0, "want_content": True}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _run_multi_search(legacy, MultiSearchRequest(query="q", use_state=False, output="json"))
        future = [item for item in caught if issubclass(item.category, FutureWarning)]
        self.assertEqual(len(future), 1, [str(item.message) for item in future])
        self.assertIn("scrape_top", str(future[0].message))


class KeyStateRecoveryTests(unittest.TestCase):
    def test_success_after_expired_quota_deadline_clears_exhausted_until(self):
        start = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            manager = SQLiteKeyManager(StateStore(Path(temp) / "state.sqlite"))
            candidate = manager.candidates("exa", "fixture-key")[0]
            with mock.patch.object(key_state, "_now", return_value=start):
                manager.record_result(
                    "exa", candidate,
                    KeyOutcome(False, True, "quota_exhausted", "quota exhausted"),
                )
            self.assertEqual(
                manager.status_rows("exa")[0]["exhausted_until"],
                (start + timedelta(hours=24)).isoformat(),
            )

            with mock.patch.object(key_state, "_now", return_value=start + timedelta(hours=25)):
                manager.record_result("exa", candidate, KeyOutcome(True, False))

            row = manager.status_rows("exa")[0]
            self.assertEqual(row["status"], ACTIVE)
            self.assertIsNone(row["exhausted_until"])
            self.assertIsNone(row["cooldown_until"])

    def test_status_summary_marks_manually_disabled_keys(self):
        rows = summarize_status_rows([{
            "provider": "exa", "key_id": "exa:fixture", "key_fingerprint": "sha256:fixture",
            "status": ACTIVE, "manually_disabled": 1,
        }])
        self.assertTrue(rows[0]["manually_disabled"])

    def test_keys_status_human_output_shows_manual_disable(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "key_status", return_value=[{
            "provider": "exa", "key_id": "exa:fixture", "status": ACTIVE,
            "manually_disabled": 1,
        }]):
            code = cli.main(["keys", "status", "--format", "human"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn("手动禁用", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()

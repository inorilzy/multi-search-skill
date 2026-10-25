"""Ported cache acquisition metadata and explicit CLI reset confirmation."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.read import run_read_source
from multi_search_mcp.src.scrape.fetch import run_fetch_source
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.search_web import run_search_web
from multi_search_mcp.src.state.content_store import (
    ContentStore, ContentTooLargeError, DEFAULT_MAX_OBJECT_BYTES,
)
from multi_search_mcp.src.state.key_state import KeyOutcome, SQLiteKeyManager
from multi_search_mcp.src.state.state_store import StateStore


class AcquisitionMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="port-core-cache-")
        self.addCleanup(temporary.cleanup)
        self.store = StateStore(Path(temporary.name) / "state.sqlite")
        self.cache = ContentStore(self.store)
        self.body = "正文 body acquired from a fixture"
        self.scraper = mock.Mock(return_value={"markdown": self.body, "via": "fixture"})

    def fetch(self, **request):
        if "source_id" not in request:
            request.setdefault("url", "https://example.com/article")
        request.setdefault("full_content", True)
        return run_fetch_source(
            request, state_store=self.store, keys={}, config={},
            scraper=self.scraper, url_resolver=lambda _: ["93.184.216.34"],
        )

    def test_existing_v2_acquisition_flag_reaches_fetch_and_read(self):
        first = self.fetch()
        source_id = first["source_id"]
        self.store.execute("UPDATE content_sources SET truncated=1 WHERE source_id=?", (source_id,))
        self.assertTrue(self.cache.get(source_id)["truncated"])
        cached = self.fetch(source_id=source_id)
        self.assertTrue(cached["cache_hit"])
        self.assertTrue(cached["truncated"])
        self.assertEqual(cached["body"], self.body)
        read = run_read_source({"source_id": source_id}, state_store=self.store)
        self.assertTrue(read["truncated"])
        self.assertFalse(read["has_more"], "end of cached pages is not proof of remote completeness")
        self.assertEqual(read["content"], self.body)
        reused = self.fetch()
        self.assertTrue(reused["cache_hit"])
        self.assertTrue(reused["truncated"])
        self.assertTrue(self.cache.get(reused["source_id"])["truncated"])
        self.assertTrue(run_read_source({"source_id": reused["source_id"]}, state_store=self.store)["truncated"])
        self.scraper.assert_called_once()

    def test_acquisition_flag_survives_fresh_fetch_and_url_reuse(self):
        self.scraper.return_value["truncated"] = True
        first = self.fetch()
        self.assertTrue(first["truncated"])
        self.assertTrue(first["persisted"])
        self.assertTrue(self.cache.get(first["source_id"])["truncated"])
        reused = self.fetch()
        self.assertNotEqual(first["source_id"], reused["source_id"])
        self.assertTrue(reused["cache_hit"])
        self.assertTrue(reused["truncated"])
        self.assertTrue(self.cache.get(reused["source_id"])["truncated"])
        self.scraper.assert_called_once()

    def test_same_body_bindings_are_independent_and_complete_update_clears_flag(self):
        partial = self.cache.put("partial", self.body, truncated=True,
                                 canonical_url="https://example.com/a", cache_scope="scope")
        complete = self.cache.put("complete", self.body)
        self.assertEqual(partial["content_hash"], complete["content_hash"])
        self.assertTrue(self.cache.get("partial")["truncated"])
        self.assertFalse(self.cache.get("complete")["truncated"])
        reused = self.cache.reuse_for_url("reused", canonical_url="https://example.com/a", cache_scope="scope")
        self.assertTrue(reused["truncated"])
        self.cache.put("partial", self.body)
        self.assertFalse(self.cache.get("partial")["truncated"])
        self.assertTrue(self.cache.get("reused")["truncated"])
        self.assertEqual(len(self.store.rows("SELECT * FROM content_objects")), 1)

    def test_preview_and_read_paging_do_not_mark_complete_acquisition(self):
        preview = self.fetch(full_content=False, max_chars=2)
        self.assertTrue(preview["truncated"])
        self.assertEqual(preview["body"], self.body[:2])
        source_id = preview["source_id"]
        self.assertFalse(self.cache.get(source_id)["truncated"])
        complete = self.fetch(source_id=source_id)
        self.assertFalse(complete["truncated"])
        self.assertEqual(complete["body"], self.body)
        page = run_read_source({"source_id": source_id, "limit": 2}, state_store=self.store)
        self.assertTrue(page["has_more"])
        self.assertFalse(page["truncated"])

    def test_acquisition_length_metadata_is_preserved_without_preview_pollution(self):
        self.scraper.return_value["length"] = len(self.body) + 10
        acquired = self.fetch()
        self.assertTrue(acquired["truncated"])
        self.assertEqual(acquired["body"], self.body)
        self.assertTrue(self.cache.get(acquired["source_id"])["truncated"])

    def test_search_projection_keeps_acquisition_flag_without_new_pipeline_logic(self):
        self.scraper.return_value["truncated"] = True
        rows = [{"source": "brave", "title": "Article", "url": "https://example.com/article",
                 "description": "summary", "content_kind": "excerpt"}]
        provider = ProviderSpec(name="brave", public_name="brave", call=lambda *_args: rows)
        response = run_search_web(
            {"query": "article", "sources": ["brave"]},
            providers={"brave": provider}, state_store=self.store, keys={}, config={},
            scraper=self.scraper, url_resolver=lambda _: ["93.184.216.34"],
        )
        self.assertEqual(response["errors"], [])
        page, hit = response["scrapes"][0], response["results"][0]
        self.assertEqual(page["markdown"], self.body)
        self.assertTrue(page["truncated"])
        self.assertTrue(hit["body_truncated"])
        self.assertTrue(self.cache.get(hit["source_id"])["truncated"])

    def test_use_state_false_preserves_acquisition_flag_without_database_access(self):
        self.scraper.return_value["truncated"] = True
        with mock.patch("multi_search_mcp.src.scrape.fetch.StateStore", side_effect=AssertionError("no DB")):
            result = self.fetch(use_state=False)
        self.assertTrue(result["truncated"])
        self.assertFalse(result["persisted"])
        self.assertEqual(result["body"], self.body)
        self.assertEqual(self.store.rows("SELECT * FROM content_sources"), [])

    def test_large_body_returns_unchanged_and_never_gets_cropped_into_cache(self):
        for body in ("中" * (DEFAULT_MAX_OBJECT_BYTES // 3 + 1), "x" * (DEFAULT_MAX_OBJECT_BYTES + 1)):
            for truncated in (False, True):
                with self.subTest(chars=len(body), truncated=truncated):
                    self.scraper.return_value = {"markdown": body, "via": "fixture", "truncated": truncated}
                    response = self.fetch()
                    self.assertEqual(response["body"], body)
                    self.assertEqual(response["content_length"], len(body))
                    self.assertFalse(response["persisted"])
                    self.assertEqual(response["truncated"], truncated)
                    self.assertEqual(response["persist_error"]["reason"], "content_too_large")
                    self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])
                    self.assertEqual(self.store.rows("SELECT * FROM content_sources"), [])
                    with self.assertRaises(ContentTooLargeError):
                        self.cache.put("over-limit", body, truncated=truncated)


class ExplicitResetTests(unittest.TestCase):
    @staticmethod
    def run_cli(*args):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.main(["keys", "reset", *args], stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_unconfirmed_or_conflicting_reset_never_opens_database(self):
        cases = [
            ([], "requires --all"),
            (["--all", "--provider", "exa"], "cannot be combined"),
            (["--all", "--key-id", "exa:id"], "cannot be combined"),
            (["--all", "--provider", "exa", "--key-id", "exa:id"], "cannot be combined"),
        ]
        for arguments, reason in cases:
            with self.subTest(arguments=arguments), mock.patch(
                "multi_search_mcp.src.state.operations.StateStore", side_effect=AssertionError("no database access")
            ) as open_store:
                code, stdout, stderr = self.run_cli(*arguments)
                self.assertEqual(code, 2, stderr)
                self.assertEqual(stdout, "")
                self.assertIn(reason, stderr)
                self.assertNotIn("unrecognized arguments", stderr)
                open_store.assert_not_called()

    def test_confirmed_all_and_scoped_resets_keep_manual_disable(self):
        with tempfile.TemporaryDirectory(prefix="port-core-reset-") as temporary:
            store = StateStore(Path(temporary) / "state.sqlite")
            manager = SQLiteKeyManager(store)
            exa = manager.candidates("exa", "synthetic-exa")[0]
            tavily = manager.candidates("tavily", "synthetic-tavily")[0]
            failure = KeyOutcome(False, True, "rate_limit", "HTTP 429")
            with mock.patch("multi_search_mcp.src.state.operations.StateStore", return_value=store):
                for arguments, expected in ((["--provider", "exa"], 1), (["--key-id", tavily.key_id], 1),
                                            (["--all"], 2)):
                    manager.record_result("exa", exa, failure)
                    manager.record_result("tavily", tavily, failure)
                    store.execute("UPDATE key_state SET manually_disabled=1 WHERE provider='exa'")
                    code, stdout, stderr = self.run_cli(*arguments)
                    self.assertEqual(code, 0, stderr)
                    self.assertEqual(json.loads(stdout)["updated"], expected)
                    rows = {row["provider"]: row for row in manager.status_rows()}
                    selected = {"exa", "tavily"} if "--all" in arguments else ({"exa"} if "--provider" in arguments else {"tavily"})
                    for provider, row in rows.items():
                        self.assertEqual(row["status"], "active" if provider in selected else "cooldown")
                    self.assertEqual(rows["exa"]["manually_disabled"], 1)
                    self.assertEqual(manager.candidates("exa", "synthetic-exa"), [])


if __name__ == "__main__":
    unittest.main()

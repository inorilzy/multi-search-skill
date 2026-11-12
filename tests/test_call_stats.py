"""T03 call statistics through fake searchers and scrape backends, with real SQLite."""
import io
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.plugins import usage_store
from multi_search_mcp.src.scrape import scrape
from multi_search_mcp.src.scrape.fetch import run_fetch_source
from multi_search_mcp.src.scrape.service import run_scrape_raw
from multi_search_mcp.src.search import registry
from multi_search_mcp.src.search.search_runner import ProviderSpec, SearchRunner, SearchRunnerConfig
from multi_search_mcp.src.state import runtime
from multi_search_mcp.src.state.key_state import SQLiteKeyManager
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support.requests import FetchSourceRequest, ScrapeRequest


URL = "https://example.com/article"


class CallStatsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="call-stats-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        environment = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        self.path = self.home / ".multi-search" / "usage.sqlite"
        self.store = StateStore(self.home / "state.sqlite")
        cooldown = mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False)
        cooldown.start()
        self.addCleanup(cooldown.stop)

    def assert_daily(self, provider, purpose, calls, failures=0):
        snapshot = usage_store.read_usage()
        self.assertIsNone(snapshot.usage_error)
        self.assertEqual(snapshot.daily, [{
            "day": datetime.now().astimezone().date().isoformat(),
            "provider": provider, "purpose": purpose, "calls": calls, "failures": failures,
        }])

    def run_sources(self, providers, *, keys=None, state=True):
        config = SearchRunnerConfig(
            route="default", counts={}, timeout=5, serpapi_engine="google", keys=keys or {},
        )
        return SearchRunner(
            config, providers, route_resolver=lambda _route: list(providers),
            key_manager=SQLiteKeyManager(self.store) if state else None,
        ).run("fixture query")

    def run_scrape(self, *, keys=None, use_state=True, backends=None):
        return run_scrape_raw(
            ScrapeRequest(url=URL, use_state=use_state), state_store=self.store,
            keys=keys or {}, config={"scrape_backends": backends or ["jina_key", "jina_anon"]},
        )[0]

    def cli_search(self, rows, *, no_state=False):
        provider = ProviderSpec("brave", "brave", lambda *_args: rows, key_required=False)
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(registry, "build_provider_registry", return_value={"brave": provider}),
            mock.patch.object(runtime, "load_config_safe", return_value={}),
            mock.patch.object(runtime, "load_runtime_key_context", return_value=SimpleNamespace(keys={}, errors={})),
        ):
            code = cli.main(
                ["search", "--source", "brave", "--no-fetch", *(["--no-state"] if no_state else []), "--", "fixture"],
                stdout=stdout, stderr=stderr,
            )
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_successful_search_counts_one_call(self):
        rows = [{"source": "brave", "url": URL, "title": "Evidence"}]
        result = self.run_sources({"brave": ProviderSpec("brave", "brave", lambda *_: rows)})
        self.assertEqual(result[0]["url"], URL)
        self.assert_daily("brave", "search", 1)

    def test_search_error_counts_one_failure(self):
        rows = [{"source": "brave", "error": "fixture failure", "error_type": "network"}]
        self.assertEqual(self.run_sources({"brave": ProviderSpec("brave", "brave", lambda *_: rows)}), rows)
        self.assert_daily("brave", "search", 1, 1)

    def test_search_exception_counts_one_failure(self):
        def broken(*_args):
            raise RuntimeError("fixture failure")

        result = self.run_sources({"brave": ProviderSpec("brave", "brave", broken)})
        self.assertEqual(result, [{"source": "brave", "error": "fixture failure"}])
        self.assert_daily("brave", "search", 1, 1)

    def test_missing_search_key_does_not_create_usage_database(self):
        call = mock.Mock(side_effect=AssertionError("must not run"))
        result = self.run_sources({"brave": ProviderSpec("brave", "brave", call, key_name="brave")})
        self.assertEqual(result[0]["error_type"], "missing_key")
        self.assertFalse(self.path.exists())

    def test_unusable_search_keys_do_not_count_an_unissued_request(self):
        manager = SQLiteKeyManager(self.store)
        candidate = manager.candidates("brave", "fixture-key")[0]
        with self.store.connect() as conn:
            conn.execute("UPDATE key_state SET manually_disabled = 1 WHERE key_id = ?", (candidate.key_id,))
        call = mock.Mock(side_effect=AssertionError("must not run"))
        self.run_sources({"brave": ProviderSpec("brave", "brave", call, key_name="brave")}, keys={"brave": "fixture-key"})
        self.assertFalse(self.path.exists())

    def test_github_search_sources_accumulate_under_one_plugin(self):
        # Separate completions avoid the store's intentionally best-effort first-write race.
        for source, public in (("github_repos", "github-repos"), ("github_code", "github-code")):
            self.run_sources({source: ProviderSpec(source, public, lambda *_: [])})
        self.assert_daily("github", "search", 2)

    def test_search_key_fallback_counts_once_for_the_completed_source(self):
        call = mock.Mock(side_effect=[
            [{"source": "brave", "error": "HTTP 401", "error_type": "invalid"}],
            [{"source": "brave", "url": URL}],
        ])
        result = self.run_sources(
            {"brave": ProviderSpec("brave", "brave", call, key_name="brave")},
            keys={"brave": ["fixture-first", "fixture-second"]},
        )
        self.assertEqual(result[0]["url"], URL)
        self.assert_daily("brave", "search", 1)

    def test_search_partial_success_does_not_count_a_failure(self):
        rows = [{"source": "brave", "url": URL}, {"source": "brave", "error": "one page failed"}]
        self.run_sources({"brave": ProviderSpec("brave", "brave", lambda *_: rows)})
        self.assert_daily("brave", "search", 1)

    def test_cli_no_state_search_does_not_create_usage_database(self):
        code, payload, _stderr = self.cli_search([{"source": "brave", "url": URL}], no_state=True)
        self.assertEqual(code, 0)
        self.assertEqual(payload["results"][0]["url"], URL)
        self.assertFalse(self.path.exists())

    def test_jina_key_and_anonymous_attempts_accumulate_under_jina(self):
        def fake_jina(url, key="", **_kwargs):
            return {"url": url, "error": "Jina: HTTP 402", "kind": "quota_exhausted"} if key else {"markdown": "body"}

        with mock.patch.object(scrape, "scrape_url_jina", side_effect=fake_jina):
            result = self.run_scrape(keys={"jina": "fixture-key"})
        self.assertEqual(result["markdown"], "body")
        self.assert_daily("jina", "scrape", 2, 1)

    def test_missing_scrape_key_is_skipped_without_counting(self):
        with mock.patch.object(scrape, "scrape_url_jina", return_value={"markdown": "body"}):
            self.run_scrape()
        self.assert_daily("jina", "scrape", 1)

    def test_all_scrape_backends_skipped_do_not_create_usage_database(self):
        result = self.run_scrape(backends=["jina_key", "tavily", "exa"])
        self.assertEqual(result["error"], "no scrape backend available")
        self.assertFalse(self.path.exists())

    def test_blocked_scrape_content_counts_a_failure(self):
        with mock.patch.object(scrape, "scrape_url_jina", return_value={"markdown": "blocked"}), mock.patch.object(
            scrape, "_resolve_scrape_policy", return_value={
                "name": "fixture", "backends": ["jina_anon"], "jina": {}, "tavily": {},
                "blocked": lambda _body: True,
            },
        ):
            result = self.run_scrape()
        self.assertIn("blocked content fetch", result["error"])
        self.assert_daily("jina", "scrape", 1, 1)

    def test_twitter_platform_scrape_counts_under_twitter(self):
        with mock.patch.object(scrape, "scrape_url_twitter", return_value={"markdown": "tweet body"}):
            result, _updates, _chars = run_scrape_raw(
                ScrapeRequest(url="https://x.com/user/status/123"), state_store=self.store, keys={}, config={},
            )
        self.assertEqual(result["markdown"], "tweet body")
        self.assert_daily("twitter", "scrape", 1)

    def test_scrape_no_state_does_not_create_usage_database(self):
        with mock.patch.object(scrape, "scrape_url_jina", return_value={"markdown": "body"}):
            self.assertEqual(self.run_scrape(use_state=False)["markdown"], "body")
        self.assertFalse(self.path.exists())

    def test_local_body_cache_hit_does_not_increment_scrape_calls(self):
        with mock.patch.object(scrape, "scrape_url_jina", return_value={"markdown": "complete body"}):
            first = run_fetch_source(
                FetchSourceRequest(url=URL), state_store=self.store,
                keys={}, config={"scrape_backends": ["jina_anon"]},
            )
        with mock.patch.object(scrape, "scrape_url_jina", side_effect=AssertionError("cache must be used")):
            second = run_fetch_source(
                FetchSourceRequest(source_id=first["source_id"]), state_store=self.store,
                keys={}, config={"scrape_backends": ["jina_anon"]},
            )
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(second["body"], first["body"])
        self.assert_daily("jina", "scrape", 1)

    def test_usage_write_failure_preserves_successful_search_results_and_exit_code(self):
        rows = [{"source": "brave", "url": URL, "title": "Evidence"}]
        before_code, before, _stderr = self.cli_search(rows)
        self.assert_daily("brave", "search", 1)
        self.path.write_bytes(b"corrupt usage fixture")
        after_code, after, _stderr = self.cli_search(rows)
        self.assertEqual((before_code, after_code), (0, 0))
        self.assertEqual(after["outcome"], before["outcome"])
        self.assertEqual(after["provider_status"], before["provider_status"])
        self.assertEqual(after["errors"], before["errors"])
        self.assertEqual(
            [(row["url"], row["title"]) for row in after["results"]],
            [(row["url"], row["title"]) for row in before["results"]],
        )
        self.assertEqual(self.path.read_bytes(), b"corrupt usage fixture")

    def test_usage_write_failure_preserves_search_error_classification_and_exit_code(self):
        rows = [{"source": "brave", "error": "fixture failure", "error_type": "network"}]
        before_code, before, _stderr = self.cli_search(rows)
        self.assert_daily("brave", "search", 1, 1)
        self.path.write_bytes(b"corrupt usage fixture")
        after_code, after, _stderr = self.cli_search(rows)
        self.assertEqual((before_code, after_code), (1, 1))
        self.assertEqual(after["outcome"], before["outcome"])
        self.assertEqual(after["errors"], before["errors"])
        self.assertEqual(after["provider_status"], before["provider_status"])
        self.assertEqual(after["results"], before["results"])
        self.assertEqual(self.path.read_bytes(), b"corrupt usage fixture")

    def test_usage_write_failure_preserves_scrape_result(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"corrupt usage fixture")
        with mock.patch.object(scrape, "scrape_url_jina", return_value={"markdown": "body"}):
            result = self.run_scrape()
        self.assertEqual(result["markdown"], "body")
        self.assertNotIn("error", result)
        self.assertEqual(self.path.read_bytes(), b"corrupt usage fixture")


if __name__ == "__main__":
    unittest.main()

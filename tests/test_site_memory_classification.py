"""Site memory must only blame the target site, not the provider or the batch budget."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.state.operations import (
    reset_site_scraper_stats,
    set_site_scraper_preference,
    site_scraper_stats,
)
from multi_search_mcp.src.state.site_memory import ScrapeAttempt, SiteScraperMemory
from multi_search_mcp.src.state.state_store import StateStore


URL = "https://example.com/article"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class SiteMemoryClassificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = StateStore(Path(temporary.name) / "state.sqlite")
        self.memory = SiteScraperMemory(self.store)
        patcher = mock.patch(
            "multi_search_mcp.src.state.site_memory._now", side_effect=lambda: NOW,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _stats_row(self, scraper="jina"):
        return next(
            (row for row in self.memory.stats("example.com") if row["scraper"] == scraper),
            None,
        )

    def test_batch_deadline_exceeded_does_not_cool_down_the_backend(self):
        self.memory.record_attempt(ScrapeAttempt(
            URL, "jina", success=False, error_message="scrape deadline exceeded",
        ))

        row = self._stats_row()
        self.assertEqual(row["timeout_count"], 1)
        self.assertIsNone(row["cooldown_until"])
        self.assertEqual(self.memory.reorder_backends(URL, ["jina", "exa"]), ["jina", "exa"])

    def test_provider_login_401_does_not_cool_down_the_backend(self):
        self.memory.record_attempt(ScrapeAttempt(
            URL, "jina", success=False,
            error_message="Jina: HTTP 401: Login required",
        ))

        row = self._stats_row()
        self.assertEqual(row["failure_count"], 1)
        self.assertIsNone(row["cooldown_until"])
        self.assertEqual(self.memory.reorder_backends(URL, ["jina", "exa"]), ["jina", "exa"])

    def test_provider_origin_failure_through_scrape_chain_does_not_cool_down(self):
        def fake_firecrawl(url, key="", **kwargs):
            return {
                "url": url,
                "error": "Firecrawl: HTTP 401: Login required",
                "kind": "invalid",
                "error_type": "invalid",
                "origin": "provider",
                "error_origin": "provider",
            }

        with mock.patch(
            "multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl",
            side_effect=fake_firecrawl,
        ):
            result = scrape_url_smart(
                URL, backends=("firecrawl",), site_memory=self.memory,
            )

        self.assertIn("error", result)
        row = self._stats_row("firecrawl")
        self.assertIsNone(row["cooldown_until"])
        self.assertEqual(
            self.memory.reorder_backends(URL, ["firecrawl", "jina"]),
            ["firecrawl", "jina"],
        )

    def test_batch_deadline_result_through_scrape_chain_does_not_cool_down(self):
        with mock.patch(
            "multi_search_mcp.src.scrape.scrape.scrape_url_jina",
            side_effect=AssertionError("deadline must prevent the call"),
        ):
            result = scrape_url_smart(
                URL, backends=("jina",), jina_keys=[], backend_timeout=0,
                site_memory=self.memory,
            )

        self.assertEqual(result.get("error"), "scrape deadline exceeded")
        row = self._stats_row()
        self.assertIsNone(row["cooldown_until"])

    def test_target_timeout_still_cools_down_the_backend(self):
        self.memory.record_attempt(ScrapeAttempt(
            URL, "jina", success=False, error_type="timeout", error_origin="target",
        ))

        row = self._stats_row()
        self.assertEqual(row["timeout_count"], 1)
        self.assertIsNotNone(row["cooldown_until"])

    def test_target_http_error_still_cools_down_the_backend(self):
        self.memory.record_attempt(ScrapeAttempt(
            URL, "jina", success=False, error_type="error", error_origin="target",
        ))

        row = self._stats_row()
        self.assertEqual(row["failure_count"], 1)
        self.assertIsNotNone(row["cooldown_until"])

    def test_short_success_does_not_increment_failure_count(self):
        self.memory.record_attempt(ScrapeAttempt(
            URL, "jina", success=True, content_length=20,
        ))

        row = self._stats_row()
        self.assertEqual(row["failure_count"], 0)
        self.assertEqual(row["success_count"], 1)
        self.assertEqual(
            self.store.rows("SELECT success, content_length FROM scrape_attempts"),
            [{"success": 1, "content_length": 20}],
        )

    def test_attempt_and_statistics_are_committed_in_one_transaction(self):
        with self.store.connect() as conn:
            conn.execute(
                "CREATE TRIGGER reject_site_stat_update "
                "BEFORE UPDATE ON site_scraper_stats "
                "BEGIN SELECT RAISE(ABORT, 'boom'); END"
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.memory.record_attempt(ScrapeAttempt(
                URL, "jina", success=True, content_length=1000,
            ))

        self.assertEqual(self.store.rows("SELECT * FROM scrape_attempts"), [])
        self.assertEqual(self.store.rows("SELECT * FROM site_scraper_stats"), [])


class SiteCommandUrlNormalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = StateStore(Path(temporary.name) / "state.sqlite")

    def test_set_preference_accepts_a_url_for_the_site(self):
        result = set_site_scraper_preference(
            "https://example.com/a", "exa", priority=1, store=self.store,
        )

        self.assertEqual(result["site"], "example.com")
        rows = site_scraper_stats("example.com", store=self.store)
        self.assertEqual(
            [(row["site"], row["scraper"], row["manually_pinned"]) for row in rows],
            [("example.com", "exa", 1)],
        )
        self.assertEqual(
            SiteScraperMemory(self.store).reorder_backends(
                "https://example.com/b", ["jina", "exa"],
            ),
            ["exa", "jina"],
        )

    def test_stats_accepts_a_url_for_the_site(self):
        SiteScraperMemory(self.store).record_attempt(ScrapeAttempt(
            URL, "jina", success=True, content_length=1000,
        ))

        rows = site_scraper_stats("https://www.example.com/a", store=self.store)

        self.assertEqual([row["scraper"] for row in rows], ["jina"])

    def test_reset_accepts_a_url_for_the_site(self):
        SiteScraperMemory(self.store).record_attempt(ScrapeAttempt(
            URL, "jina", success=True, content_length=1000,
        ))

        deleted = reset_site_scraper_stats("https://www.example.com/a", store=self.store)

        self.assertEqual(deleted, 1)
        self.assertEqual(site_scraper_stats("example.com", store=self.store), [])


class ZhihuPolicyTests(unittest.TestCase):
    def test_zhihu_url_with_port_uses_zhihu_policy(self):
        captured = {}

        def fake_jina(url, key="", **kwargs):
            captured.update(kwargs)
            return {
                "url": url, "title": "zhihu",
                "markdown": "知乎正文" * 200, "via": "jina",
            }

        with mock.patch(
            "multi_search_mcp.src.scrape.scrape._jina_anonymous_cooling_down",
            return_value=False,
        ), mock.patch(
            "multi_search_mcp.src.scrape.scrape.scrape_url_jina",
            side_effect=fake_jina,
        ):
            result = scrape_url_smart(
                "https://www.zhihu.com:443/question/123",
                backends=("jina",), jina_keys=[],
            )

        self.assertEqual(result["via"], "jina")
        self.assertEqual(captured.get("respond_with"), "text")


if __name__ == "__main__":
    unittest.main()

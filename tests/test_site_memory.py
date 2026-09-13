import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.state.site_memory import ScrapeAttempt, SiteScraperMemory, site_key
from multi_search_mcp.src.state.state_store import StateStore


class SiteKeyTests(unittest.TestCase):
    def test_uses_standard_url_hostname_semantics(self):
        self.assertEqual(
            site_key("HTTPS://User:Pass@[2001:DB8::1]:8443/article"),
            "2001:db8::1",
        )
        self.assertEqual(site_key("https://User:Pass@EXAMPLE.COM:443/article"), "example.com")
        self.assertNotEqual(
            site_key("https://[2001:db8::1]/article"),
            site_key("https://[2001:db8::2]/article"),
        )

    def test_zhihu_grouping_requires_a_domain_boundary(self):
        self.assertEqual(site_key("https://zhihu.com/question/1"), "zhihu.com")
        self.assertEqual(site_key("https://www.zhihu.com/question/1"), "zhihu.com")
        self.assertEqual(site_key("https://api.zhihu.com/question/1"), "zhihu.com")
        self.assertEqual(site_key("https://evilzhihu.com/question/1"), "evilzhihu.com")

    def test_existing_www_reddit_and_github_grouping_remains_unchanged(self):
        self.assertEqual(site_key("https://www.example.com/article"), "example.com")
        self.assertEqual(site_key("https://www.reddit.com/r/python"), "reddit.com")
        self.assertEqual(site_key("https://old.reddit.com/r/python"), "old.reddit.com")
        self.assertEqual(site_key("https://api.reddit.com/r/python"), "api.reddit.com")
        self.assertEqual(site_key("https://github.com/owner/repo"), "github.com/repo")
        self.assertEqual(site_key("https://github.com/owner/repo/issues/1"), "github.com/issues")
        self.assertEqual(site_key("https://github.com/owner/repo/pull/1"), "github.com/pull")
        self.assertEqual(
            site_key("https://github.com/owner/repo/discussions/1"),
            "github.com/discussions",
        )


class SiteMemoryOrderingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.memory = SiteScraperMemory(StateStore(Path(temporary.name) / "state.sqlite"))
        self.url = "https://example.com/article"
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        patcher = mock.patch("multi_search_mcp.src.state.site_memory._now", side_effect=lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cold_site_preserves_original_order(self):
        self.assertEqual(self.memory.reorder_backends(self.url, ["tavily", "jina", "exa"]), ["tavily", "jina", "exa"])

    def test_cooling_failed_backend_follows_successful_and_untried_backends(self):
        self.memory.record_attempt(ScrapeAttempt(self.url, "jina", False, error_type="timeout"))
        self.memory.record_attempt(ScrapeAttempt(self.url, "tavily", True, content_length=1000))

        self.assertEqual(self.memory.reorder_backends(self.url, ["jina", "exa", "tavily"]), ["tavily", "exa", "jina"])

    def test_expired_cooldown_allows_backend_to_be_tried_again(self):
        self.memory.record_attempt(ScrapeAttempt(self.url, "jina", False, error_type="blocked"))
        self.assertEqual(self.memory.reorder_backends(self.url, ["jina", "exa"]), ["exa", "jina"])

        self.now += timedelta(hours=1, seconds=1)

        self.assertEqual(self.memory.reorder_backends(self.url, ["jina", "exa"]), ["jina", "exa"])

    def test_manual_pins_keep_priority_even_during_cooldown(self):
        self.memory.set_preference("example.com", "jina", priority=1)
        self.memory.set_preference("example.com", "tavily", priority=2)
        self.memory.record_attempt(ScrapeAttempt(self.url, "jina", False, error_type="timeout"))

        self.assertEqual(self.memory.reorder_backends(self.url, ["exa", "tavily", "jina"]), ["jina", "tavily", "exa"])

    def test_independent_hosts_do_not_share_cooldown_or_failure_state(self):
        for first_url, second_url in (
            ("https://[2001:db8::1]/article", "https://[2001:db8::2]/article"),
            ("https://evilzhihu.com/article", "https://www.zhihu.com/question/1"),
        ):
            with self.subTest(first_url=first_url, second_url=second_url):
                self.memory.record_attempt(ScrapeAttempt(first_url, "jina", False, error_type="timeout"))

                self.assertEqual(
                    self.memory.reorder_backends(second_url, ["jina", "exa"]),
                    ["jina", "exa"],
                )
                self.assertEqual(
                    self.memory.reorder_backends(first_url, ["jina", "exa"]),
                    ["exa", "jina"],
                )

    def test_preference_and_reset_are_scoped_to_canonical_site_key(self):
        preferred_url = "https://api.zhihu.com/question/1"
        independent_url = "https://evilzhihu.com/question/1"
        preferred_site = site_key(preferred_url)

        self.memory.set_preference(preferred_site, "exa", priority=1)

        self.assertEqual(
            self.memory.reorder_backends(preferred_url, ["jina", "exa"]),
            ["exa", "jina"],
        )
        self.assertEqual(
            self.memory.reorder_backends(independent_url, ["jina", "exa"]),
            ["jina", "exa"],
        )

        self.memory.record_attempt(ScrapeAttempt(independent_url, "jina", False, error_type="timeout"))
        self.assertEqual(self.memory.reset(preferred_site), 1)
        self.assertEqual(self.memory.stats(preferred_site), [])
        self.assertEqual(len(self.memory.stats(site_key(independent_url))), 1)
        self.assertEqual(
            self.memory.reorder_backends(independent_url, ["jina", "exa"]),
            ["exa", "jina"],
        )


if __name__ == "__main__":
    unittest.main()

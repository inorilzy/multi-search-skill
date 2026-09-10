import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.state.site_memory import ScrapeAttempt, SiteScraperMemory
from multi_search_mcp.src.state.state_store import StateStore


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


if __name__ == "__main__":
    unittest.main()

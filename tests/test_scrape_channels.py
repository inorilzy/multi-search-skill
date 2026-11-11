"""Scrape chain channels: keyed and anonymous Jina / Firecrawl are separate entries."""
import unittest
from unittest import mock

from multi_search_mcp.src.scrape import scrape
from multi_search_mcp.src.scrape.service import configured_scrape_backends, run_scrape_raw
from multi_search_mcp.src.support.backends import expand_backends
from multi_search_mcp.src.support.requests import ScrapeRequest

URL = "https://example.com/article"


class ScrapeChannelTests(unittest.TestCase):
    def _run(self, keys, *, config=None, jina=None, firecrawl=None):
        calls = []

        def fake_jina(url, key="", **kwargs):
            calls.append(("jina", key))
            return (jina or (lambda k: {"url": url, "markdown": f"jina {k or 'anon'}"}))(key)

        def fake_firecrawl(url, key="", **kwargs):
            calls.append(("firecrawl", key))
            return (firecrawl or (lambda k: {"url": url, "markdown": f"fc {k or 'anon'}"}))(key)

        with (
            mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False),
            mock.patch.object(scrape, "scrape_url_jina", side_effect=fake_jina),
            mock.patch.object(scrape, "scrape_url_firecrawl", side_effect=fake_firecrawl),
            mock.patch.object(scrape, "scrape_url_exa", side_effect=AssertionError("exa")),
            mock.patch.object(scrape, "scrape_url_tavily", side_effect=AssertionError("tavily")),
        ):
            result, _updates, _chars = run_scrape_raw(
                ScrapeRequest(url=URL, use_state=False), keys=keys, config=config or {},
            )
        return result, calls

    def test_factory_chain_uses_the_jina_key_first(self):
        result, calls = self._run({"jina": "jk-1"})
        self.assertEqual(calls, [("jina", "jk-1")])
        self.assertEqual(result["markdown"], "jina jk-1")
        self.assertEqual(result["via"], "jina")

    def test_without_a_jina_key_the_anonymous_channel_runs_next(self):
        result, calls = self._run({})
        self.assertEqual(calls, [("jina", "")])
        self.assertEqual(result["markdown"], "jina anon")

    def test_a_failing_jina_key_falls_through_to_anonymous_jina(self):
        def jina(key):
            return {"url": URL, "error": "Jina: HTTP 402: quota"} if key else {"url": URL, "markdown": "free"}

        result, calls = self._run({"jina": "jk-1"}, jina=jina)
        self.assertEqual(calls, [("jina", "jk-1"), ("jina", "")])
        self.assertEqual(result["markdown"], "free")

    def test_anonymous_firecrawl_is_a_separate_last_channel(self):
        failing = lambda key: {"url": URL, "error": "Jina: HTTP 403: blocked"}  # noqa: E731
        result, calls = self._run({"firecrawl": "fk-1"}, jina=failing,
                                  firecrawl=lambda k: {"url": URL, "error": "Firecrawl: HTTP 402"}
                                  if k else {"url": URL, "markdown": "fc anon"})
        self.assertEqual(calls, [("jina", ""), ("firecrawl", "fk-1"), ("firecrawl", "")])
        self.assertEqual(result["markdown"], "fc anon")

    def test_a_disabled_anonymous_channel_is_never_called(self):
        result, calls = self._run({}, config={"scrape_backends": ["jina_key", "firecrawl_key"]})
        self.assertEqual(calls, [])
        self.assertIn("error", result)

    def test_saved_historical_names_keep_their_original_behavior(self):
        self.assertEqual(configured_scrape_backends({"scrape_backends": ["jina", "firecrawl"]}),
                         ("jina", "firecrawl"))
        result, calls = self._run({"jina": "jk-1"}, config={"scrape_backends": ["jina"]})
        # Historical ``jina`` stays anonymous-first.
        self.assertEqual(calls, [("jina", "")])
        self.assertEqual(result["markdown"], "jina anon")

    def test_expanding_historical_names_keeps_their_former_order(self):
        self.assertEqual(expand_backends(["jina", "exa", "firecrawl"]),
                         ("jina_anon", "jina_key", "exa", "firecrawl_key", "firecrawl_anon"))
        self.assertEqual(expand_backends(["jina_key", "jina"]), ("jina_key", "jina_anon"))
        with self.assertRaises(ValueError):
            expand_backends(["bing"])

    def test_forcing_the_keyed_channel_without_a_key_fails_eagerly(self):
        result = scrape.scrape_url_smart(URL, backends=["jina_key"])
        self.assertEqual(result["error"], "missing key for backend: jina_key")


class SiteMemoryChannelTests(unittest.TestCase):
    def test_a_provider_pin_recorded_before_the_split_still_applies(self):
        from multi_search_mcp.src.state.site_memory import SiteScraperMemory

        memory = SiteScraperMemory.__new__(SiteScraperMemory)
        memory.store = mock.Mock()
        memory.store.rows.return_value = [{"scraper": "firecrawl", "manually_pinned": 1, "manual_priority": 0}]
        order = memory.reorder_backends(URL, ["jina_key", "jina_anon", "firecrawl_key", "firecrawl_anon"])
        self.assertEqual(order[:2], ["firecrawl_key", "firecrawl_anon"])


if __name__ == "__main__":
    unittest.main()

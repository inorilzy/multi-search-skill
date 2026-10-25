import unittest
from unittest import mock

from multi_search_mcp.src.support.requests import MultiSearchRequest, ScrapeRequest
from multi_search_mcp.src.scrape.service import run_scrape_raw
from multi_search_mcp.src.scrape import scrape
from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.scrape.service import configured_scrape_backends
from multi_search_mcp.src.scrape.scrape import KNOWN_BACKENDS as DEFAULT_SCRAPE_BACKENDS


def resolve_scrape_backends(config):
    return list(configured_scrape_backends(config))


from multi_search_mcp.src.support.config import ConfigError

URL = "https://example.com/article"


def _resolver(_host):
    return ["93.184.216.34"]


class ResolveScrapeBackendsTests(unittest.TestCase):
    def test_missing_or_null_uses_the_legacy_default_order(self):
        self.assertEqual(resolve_scrape_backends({}), list(DEFAULT_SCRAPE_BACKENDS))
        self.assertEqual(
            resolve_scrape_backends({"scrape_backends": None}),
            ["jina", "exa", "tavily", "firecrawl"],
        )

    def test_configured_order_is_preserved_and_duplicates_are_dropped_in_place(self):
        self.assertEqual(
            resolve_scrape_backends({"scrape_backends": ["firecrawl", "jina", "tavily"]}),
            ["firecrawl", "jina", "tavily"],
        )
        self.assertEqual(
            resolve_scrape_backends({"scrape_backends": ["jina", "exa", "jina", "firecrawl", "exa"]}),
            ["jina", "exa", "firecrawl"],
        )

    def test_empty_list_is_a_configuration_error(self):
        with self.assertRaisesRegex(ConfigError, "scrape_backends requires at least one backend"):
            resolve_scrape_backends({"scrape_backends": []})

    def test_unknown_backends_fail_with_the_valid_names(self):
        with self.assertRaisesRegex(
            ConfigError,
            r"unknown scrape backend; valid backends: jina, exa, tavily, firecrawl",
        ):
            resolve_scrape_backends({"scrape_backends": ["jinaa", "bing"]})

    def test_non_string_elements_fail(self):
        with self.assertRaisesRegex(ConfigError, "scrape_backends requires a list of strings"):
            resolve_scrape_backends({"scrape_backends": ["jina", 3]})
        with self.assertRaisesRegex(ConfigError, "scrape_backends requires a list of strings"):
            resolve_scrape_backends({"scrape_backends": "jina"})



class ScrapeChainExecutionTests(unittest.TestCase):
    def _run(self, config, request, *, calls):
        def firecrawl(url, key="", timeout=0, deadline=None):
            calls.append("firecrawl")
            return {"url": url, "error": "fixture firecrawl unavailable"}

        def jina(url, key="", **kwargs):
            calls.append("jina")
            return {"url": url, "title": "j", "markdown": "jina body", "via": "jina"}

        def exa(url, key, **kwargs):
            calls.append("exa")
            return {"url": url, "markdown": "exa body", "via": "exa"}

        def tavily(url, key, **kwargs):
            calls.append("tavily")
            return {"url": url, "markdown": "tavily body", "via": "tavily"}

        with (
            mock.patch.object(scrape, "jina_anonymous_cooling_down", return_value=False),
            mock.patch.object(scrape, "scrape_url_jina", side_effect=jina),
            mock.patch.object(scrape, "scrape_url_firecrawl", side_effect=firecrawl),
            mock.patch.object(scrape, "scrape_url_exa", side_effect=exa),
            mock.patch.object(scrape, "scrape_url_tavily", side_effect=tavily),
        ):
            return run_scrape_raw(
                request, scraper=scrape_url_smart, keys={}, config=config,
                url_resolver=_resolver,
            )[0]

    def test_configured_chain_controls_fallback_order(self):
        calls = []
        result = self._run(
            {"scrape_backends": ["firecrawl", "jina"]},
            ScrapeRequest(url=URL, use_state=False, output="json"),
            calls=calls,
        )
        self.assertEqual(calls, ["firecrawl", "jina"])
        self.assertEqual(result["via"], "jina")
        self.assertNotIn("error", result)

    def test_keyless_configured_backends_are_skipped_instead_of_failing(self):
        # exa requires a key, but a configured chain is not a strict request:
        # the dispatcher skips it and continues to jina.
        calls = []
        result = self._run(
            {"scrape_backends": ["exa", "jina"]},
            ScrapeRequest(url=URL, use_state=False, output="json"),
            calls=calls,
        )
        self.assertEqual(calls, ["jina"])
        self.assertEqual(result["via"], "jina")

    def test_keyless_default_chain_still_tries_anonymous_jina_first(self):
        calls = []
        result = self._run({}, ScrapeRequest(url=URL, use_state=False, output="json"), calls=calls)
        self.assertEqual(calls, ["jina"])
        self.assertEqual(result["via"], "jina")

    def test_explicit_backend_without_key_is_still_a_strict_error(self):
        calls = []
        result = self._run(
            {},
            ScrapeRequest(url=URL, backends=["exa"], use_state=False, output="json"),
            calls=calls,
        )
        self.assertEqual(result["error"], "missing key for backend: exa")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

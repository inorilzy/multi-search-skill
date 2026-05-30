import unittest

from scripts.dedup import _norm_url, deduplicate
from scripts.main import available_routes, normalize_route, resolve_route
from scripts import scrape


class RouteTests(unittest.TestCase):
    def test_aliases_resolve_to_expected_profiles(self):
        self.assertEqual(normalize_route("all"), "default")
        self.assertEqual(normalize_route("balanced"), "lite")
        self.assertEqual(normalize_route("social+community"), "discussion")
        self.assertEqual(resolve_route("github"), {"github_repos"})
        self.assertEqual(resolve_route("google"), {"serpapi"})
        self.assertEqual(resolve_route("x"), {"twitter"})
        self.assertEqual(resolve_route("balanced"), {"tavily", "exa", "firecrawl"})
        self.assertEqual(resolve_route("social+community"), {"twitter", "hackernews", "stackoverflow"})

    def test_unknown_route_resolves_empty_for_validation(self):
        self.assertEqual(resolve_route("not-a-route"), set())
        self.assertIn("default", available_routes())
        self.assertIn("lite", available_routes())
        self.assertIn("discussion", available_routes())


class DedupTests(unittest.TestCase):
    def test_tracking_params_are_removed_for_consensus(self):
        self.assertEqual(
            _norm_url("http://Example.com/path/?utm_source=x&keep=1#frag"),
            "https://example.com/path?keep=1",
        )

    def test_duplicate_urls_merge_sources_and_richer_fields(self):
        results = [
            {"source": "brave", "title": "A", "url": "https://example.com/a", "description": "short"},
            {
                "source": "tavily",
                "title": "Longer title",
                "url": "https://example.com/a?utm_campaign=x",
                "description": "a longer description",
                "scraped_content": "full text",
            },
        ]
        deduped, raw_counts = deduplicate(results)
        self.assertEqual(raw_counts, {"brave": 1, "tavily": 1})
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["also_from"], ["tavily"])
        self.assertEqual(deduped[0]["title"], "Longer title")
        self.assertEqual(deduped[0]["scraped_content"], "full text")


class ScrapeRoutingTests(unittest.TestCase):
    def test_jina_is_last_fallback_by_default(self):
        calls = []
        originals = (
            scrape.scrape_url_tavily,
            scrape.scrape_url_exa,
            scrape.scrape_url_firecrawl,
            scrape.scrape_url_jina,
        )

        def fail(name):
            def _inner(*args, **kwargs):
                calls.append(name)
                return {"url": "https://example.com", "error": f"{name} failed"}
            return _inner

        def succeed_jina(*args, **kwargs):
            calls.append("jina")
            return {"url": "https://example.com", "markdown": "ok", "via": "jina"}

        try:
            scrape.scrape_url_tavily = fail("tavily")
            scrape.scrape_url_exa = fail("exa")
            scrape.scrape_url_firecrawl = fail("firecrawl")
            scrape.scrape_url_jina = succeed_jina
            result = scrape.scrape_url_smart(
                "https://example.com",
                "firecrawl-key",
                exa_key="exa-key",
                tavily_key="tavily-key",
                primary="tavily",
            )
        finally:
            (
                scrape.scrape_url_tavily,
                scrape.scrape_url_exa,
                scrape.scrape_url_firecrawl,
                scrape.scrape_url_jina,
            ) = originals

        self.assertEqual(calls, ["tavily", "exa", "firecrawl", "jina"])
        self.assertEqual(result["via"], "jina")


if __name__ == "__main__":
    unittest.main()

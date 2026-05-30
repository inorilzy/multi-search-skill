import unittest

from scripts.dedup import _norm_url, deduplicate
from scripts.main import available_routes, normalize_route, resolve_route


class RouteTests(unittest.TestCase):
    def test_aliases_resolve_to_expected_profiles(self):
        self.assertEqual(normalize_route("github"), "repos")
        self.assertEqual(resolve_route("github"), {"github_repos"})
        self.assertEqual(resolve_route("google"), {"serpapi"})
        self.assertEqual(resolve_route("x"), {"twitter"})

    def test_unknown_route_resolves_empty_for_validation(self):
        self.assertEqual(resolve_route("not-a-route"), set())
        self.assertIn("balanced", available_routes())
        self.assertIn("all", available_routes())


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


if __name__ == "__main__":
    unittest.main()

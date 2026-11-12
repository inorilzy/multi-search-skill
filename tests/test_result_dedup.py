"""Near-duplicate URLs must not crowd the final 15 results (observed with one provider
returning ten variants of the same documentation page)."""
import unittest

from multi_search_mcp.src.search.candidate import (
    MAX_RESULTS_PER_SITE,
    SEARCH_RESULT_LIMIT,
    canonicalize_url,
    diversify_by_site,
    fuse_search_results,
)

DOC = "https://docs.python.org/3/library/asyncio.html"


def _row(source, url, rank):
    return {"source": source, "title": url, "url": url, "provider_rank": rank}


class CanonicalVariantTests(unittest.TestCase):
    def test_repeated_path_slashes_are_one_page(self):
        for variant in (
            "https://docs.python.org/3/library//asyncio.html",
            "https://docs.python.org/3//library/asyncio.html",
            "https://docs.python.org//3/library/asyncio.html",
        ):
            self.assertEqual(canonicalize_url(variant), DOC, variant)
        self.assertEqual(canonicalize_url("https://example.com//"), "https://example.com/")

    def test_a_trailing_slash_does_not_split_one_page(self):
        page = "https://www.geeksforgeeks.org/python/asyncio-in-python"
        self.assertEqual(canonicalize_url(page + "/"), canonicalize_url(page))
        self.assertEqual(canonicalize_url(page + "//?id=1"), canonicalize_url(page + "?id=1"))
        # The site root keeps its single slash.
        self.assertEqual(canonicalize_url("https://example.com"), "https://example.com/")
        self.assertEqual(canonicalize_url("https://example.com/"), "https://example.com/")

    def test_display_and_tracking_parameters_are_dropped(self):
        self.assertEqual(canonicalize_url(DOC + "?highlight=asyncio"), DOC)
        self.assertEqual(canonicalize_url(DOC + "?abrmid=0901b02"), DOC)
        self.assertEqual(canonicalize_url(DOC + "?featured_on=pythonbytes"), DOC)
        # Unknown business parameters still keep URLs distinct.
        self.assertEqual(canonicalize_url(DOC + "?id=2&highlight=x"), DOC + "?id=2")

    def test_variants_fuse_into_one_hit(self):
        rows = [
            _row("parallel", DOC, 1),
            _row("parallel", DOC.replace("/library/", "/library//"), 2),
            _row("parallel", DOC + "?highlight=asyncio", 3),
            _row("brave", DOC, 1),
        ]
        hits = fuse_search_results([("q", rows)], response_id="dedup")
        self.assertEqual([hit["canonical_url"] for hit in hits], [DOC])
        self.assertEqual(hits[0]["providers"], ["brave", "parallel"])


class SiteDiversityTests(unittest.TestCase):
    def _hits(self, urls):
        rows = [_row("parallel", url, rank) for rank, url in enumerate(urls, start=1)]
        return fuse_search_results([("q", rows)], response_id="sites", limit=100)

    def test_one_site_cannot_take_more_than_its_share_while_others_wait(self):
        docs = [f"https://docs.python.org/3.{minor}/library/asyncio.html" for minor in range(8, 14)]
        others = [f"https://site{index}.example/page" for index in range(12)]
        hits = diversify_by_site(self._hits(docs + others), SEARCH_RESULT_LIMIT)
        self.assertEqual(len(hits), SEARCH_RESULT_LIMIT)
        hosts = [hit["url"].split("/")[2] for hit in hits]
        self.assertEqual(hosts.count("docs.python.org"), MAX_RESULTS_PER_SITE)
        # Kept entries stay in fused order; the best-ranked pages of the site win.
        self.assertEqual([hit["url"] for hit in hits[:MAX_RESULTS_PER_SITE]], docs[:MAX_RESULTS_PER_SITE])

    def test_deferred_pages_fill_the_list_when_other_sites_run_out(self):
        docs = [f"https://docs.python.org/3.{minor}/library/asyncio.html" for minor in range(8, 14)]
        hits = diversify_by_site(self._hits(docs + ["https://other.example/a"]), SEARCH_RESULT_LIMIT)
        self.assertEqual(len(hits), len(docs) + 1)
        urls = [hit["url"] for hit in hits]
        self.assertEqual(urls[:MAX_RESULTS_PER_SITE], docs[:MAX_RESULTS_PER_SITE])
        self.assertEqual(urls[MAX_RESULTS_PER_SITE], "https://other.example/a")
        self.assertEqual(urls[MAX_RESULTS_PER_SITE + 1:], docs[MAX_RESULTS_PER_SITE:])

    def test_www_prefix_counts_as_the_same_site(self):
        urls = [f"https://www.example.com/{i}" for i in range(2)] + [f"https://example.com/{i}" for i in range(2, 6)]
        urls += [f"https://other{i}.example/" for i in range(3)]
        hits = diversify_by_site(self._hits(urls), 6)
        self.assertEqual(sum("example.com" in hit["url"] for hit in hits), MAX_RESULTS_PER_SITE)


class ConfigurablePerSiteCapTests(unittest.TestCase):
    def _docs_and_others(self):
        docs = [f"https://docs.python.org/3.{minor}/library/asyncio.html" for minor in range(4, 14)]
        # Enough other sites that deferred docs pages never back-fill the 15 slots.
        others = [f"https://site{index}.example/page" for index in range(20)]
        rows = [_row("parallel", url, rank) for rank, url in enumerate(docs + others, start=1)]
        return fuse_search_results([("q", rows)], response_id="cap", limit=100)

    def test_the_default_cap_is_three_and_config_can_raise_or_remove_it(self):
        from multi_search_mcp.src.support.config import (
            MAX_RESULTS_PER_SITE_DEFAULT, resolve_max_results_per_site,
        )

        self.assertEqual(MAX_RESULTS_PER_SITE_DEFAULT, MAX_RESULTS_PER_SITE)
        self.assertEqual(resolve_max_results_per_site({}), 3)
        self.assertEqual(resolve_max_results_per_site({"max_results_per_site": None}), 3)
        for cap in (1, 6, 15):
            with self.subTest(cap=cap):
                self.assertEqual(resolve_max_results_per_site({"max_results_per_site": cap}), cap)
                hits = diversify_by_site(self._docs_and_others(), SEARCH_RESULT_LIMIT, cap)
                hosts = [hit["url"].split("/")[2] for hit in hits]
                self.assertEqual(hosts.count("docs.python.org"), min(cap, 10))

    def test_invalid_caps_are_config_errors(self):
        from multi_search_mcp.src.support.config import ConfigError, resolve_max_results_per_site

        for bad in (0, 16, -1, 2.5, "3", True):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                resolve_max_results_per_site({"max_results_per_site": bad})

    def test_the_search_plan_carries_the_configured_cap(self):
        from multi_search_mcp.src.search.resolve import SearchPlanRequest, resolve_search_plan
        from multi_search_mcp.src.support.config import ConfigError

        self.assertEqual(resolve_search_plan(SearchPlanRequest(), {}).max_results_per_site, 3)
        plan = resolve_search_plan(SearchPlanRequest(), {"max_results_per_site": 5})
        self.assertEqual(plan.max_results_per_site, 5)
        with self.assertRaises(ConfigError):
            resolve_search_plan(SearchPlanRequest(), {"max_results_per_site": 0})

    def test_finalize_uses_the_given_cap_for_scored_and_unscored_hits(self):
        from multi_search_mcp.src.search.notices import finalize_results

        hits = self._docs_and_others()
        # Every hit scored, as after a full rerank: one pass, one cap.
        for hit in hits:
            hit["relevance_score"] = 0.9
        final = finalize_results(hits, SEARCH_RESULT_LIMIT, 5)
        self.assertEqual(sum("docs.python.org" in hit["url"] for hit in final), 5)
        self.assertEqual(
            sum("docs.python.org" in hit["url"] for hit in finalize_results(hits, SEARCH_RESULT_LIMIT, 2)), 2,
        )


if __name__ == "__main__":
    unittest.main()

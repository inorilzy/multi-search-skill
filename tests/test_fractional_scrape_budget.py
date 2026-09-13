import unittest
from contextlib import ExitStack
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.scrape import scrape
from multi_search_mcp.src.search.search_runner import ProviderSpec


URL = "https://example.com/fixture"
BODY = "# Fixture\n\ninstant body"


def _resolver(_host):
    return ["93.184.216.34"]


def _provider():
    return ProviderSpec(
        name="hackernews",
        public_name="hackernews",
        call=lambda *_args: [{
            "source": "hackernews",
            "title": "Fixture",
            "url": URL,
            "description": "fixture excerpt",
        }],
    )


class FractionalScrapeBudgetTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch(
            "socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")
        ))
        self.stack.enter_context(mock.patch(
            "socket.socket.connect", side_effect=AssertionError("unexpected connection")
        ))

    def _instant_jina(self, calls):
        def jina(url, *args, **kwargs):
            calls.append(kwargs["timeout"])
            return {"url": url, "markdown": BODY, "via": "jina"}

        return jina

    def test_search_fetch_with_one_second_budget_reaches_instant_backend(self):
        calls = []
        with (
            mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False),
            mock.patch.object(scrape, "scrape_url_jina", side_effect=self._instant_jina(calls)),
        ):
            response = service.run_search_web(
                service.SearchWebRequest(
                    query="fixture", sources=["hackernews"], use_state=False,
                ),
                providers={"hackernews": _provider()},
                keys={},
                config={"scrape_timeout": 1},
                scraper=scrape.scrape_url_smart,
                url_resolver=_resolver,
            )

        self.assertEqual(len(calls), 1)
        self.assertGreater(calls[0], 0)
        self.assertLessEqual(calls[0], 1)
        self.assertEqual(response["diagnostics"]["body_success_count"], 1)
        self.assertEqual(response["scrapes"][0]["source_id"], response["results"][0]["source_id"])
        self.assertEqual(response["scrapes"][0]["markdown"], BODY)

    def test_runtime_fractional_timeout_is_not_reparsed_as_integer(self):
        observed = {}

        def instant_scraper(url, **kwargs):
            observed.update(kwargs)
            return {"url": url, "markdown": BODY, "via": "fixture"}

        result = service.run_fetch_source(
            service.FetchSourceRequest(url=URL, use_state=False),
            scraper=instant_scraper,
            keys={},
            config={},
            url_resolver=_resolver,
            deadline=service.time.monotonic() + 0.25,
            runtime_timeout=0.25,
        )

        self.assertEqual(result["body"], BODY)
        self.assertGreater(observed["timeout"], 0)
        self.assertLess(observed["timeout"], 1)

    def test_direct_scrape_keeps_integer_timeout_and_reaches_backend(self):
        calls = []
        with (
            mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False),
            mock.patch.object(scrape, "scrape_url_jina", side_effect=self._instant_jina(calls)),
        ):
            result = service.run_scrape(
                service.ScrapeRequest(
                    url=URL, backends=["jina"], timeout=1,
                    output="json", use_state=False,
                ),
                scraper=scrape.scrape_url_smart,
                keys={},
                config={},
                url_resolver=_resolver,
            )

        self.assertEqual(result["result"]["markdown"], BODY)
        self.assertEqual(len(calls), 1)
        self.assertGreater(calls[0], 0)
        self.assertLessEqual(calls[0], 1)

    def test_public_zero_or_negative_timeout_never_starts_backend(self):
        for timeout in (0, -1):
            with self.subTest(timeout=timeout), \
                 mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False), \
                 mock.patch.object(scrape, "scrape_url_jina") as backend:
                result = service.run_scrape(
                    service.ScrapeRequest(
                        url=URL, backends=["jina"], timeout=timeout,
                        output="json", use_state=False,
                    ),
                    scraper=scrape.scrape_url_smart,
                    keys={},
                    config={},
                    url_resolver=_resolver,
                )

            backend.assert_not_called()
            self.assertTrue(result["result"].get("error"))

    def test_search_fetch_reuses_one_absolute_batch_deadline(self):
        captured = {}

        def instant_scraper(url, **kwargs):
            captured["scraper_deadline"] = kwargs["deadline"]
            captured["scraper_timeout"] = kwargs["timeout"]
            return {"url": url, "markdown": BODY, "via": "fixture"}

        def fetch_stage(hits, **kwargs):
            captured["stage_deadline"] = kwargs["deadline"]
            return {"results": [kwargs["fetch"](hits[0], 0.25)], "errors": []}

        with mock.patch.object(service, "run_ranked_fetch_stage", side_effect=fetch_stage):
            response = service.run_search_web(
                service.SearchWebRequest(
                    query="fixture", sources=["hackernews"], use_state=False,
                ),
                providers={"hackernews": _provider()},
                keys={},
                config={"scrape_timeout": 1},
                scraper=instant_scraper,
                url_resolver=_resolver,
            )

        self.assertEqual(response["diagnostics"]["body_success_count"], 1)
        self.assertIs(captured["scraper_deadline"], captured["stage_deadline"])
        self.assertGreater(captured["scraper_timeout"], 0)
        self.assertLess(captured["scraper_timeout"], 1)

    def test_positive_subsecond_deadline_is_not_rounded_up(self):
        calls = []
        with (
            mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False),
            mock.patch.object(scrape, "scrape_url_jina", side_effect=self._instant_jina(calls)),
            mock.patch.object(scrape.time, "monotonic", return_value=100.0),
        ):
            result = scrape.scrape_url_smart(
                URL,
                backends=["jina"],
                timeout=1,
                deadline=100.05,
                url_resolver=_resolver,
            )

        self.assertNotIn("error", result)
        self.assertEqual(len(calls), 1)
        self.assertGreater(calls[0], 0)
        self.assertLessEqual(calls[0], 0.05)

    def test_expired_runtime_budget_does_not_start_backend(self):
        with (
            mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False),
            mock.patch.object(scrape, "scrape_url_jina") as backend,
            mock.patch.object(scrape.time, "monotonic", return_value=100.0),
        ):
            result = scrape.scrape_url_smart(
                URL,
                backends=["jina"],
                timeout=1,
                deadline=100.0,
                url_resolver=_resolver,
            )

        backend.assert_not_called()
        self.assertTrue(result.get("error"))


if __name__ == "__main__":
    unittest.main()

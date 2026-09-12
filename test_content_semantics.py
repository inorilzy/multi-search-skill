import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.search.searchers.baidu import _rows_from_response
from multi_search_mcp.src.search.searchers.brave import search_brave
from multi_search_mcp.src.search.searchers.exa import search_exa
from multi_search_mcp.src.search.searchers.github import search_github_repos
from multi_search_mcp.src.search.searchers.hackernews import search_hackernews
from multi_search_mcp.src.search.searchers.parallel import search_parallel
from multi_search_mcp.src.search.searchers.serpapi import search_serpapi
from multi_search_mcp.src.search.searchers.stackoverflow import search_stackoverflow
from multi_search_mcp.src.search.searchers.tavily import search_tavily
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support.models import SearchResult


class _FakeResponse:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        if isinstance(self._payload, bytes):
            return self._payload
        if isinstance(self._payload, str):
            return self._payload.encode("utf-8")
        return json.dumps(self._payload).encode("utf-8")


class SearchResultContractTests(unittest.TestCase):
    def test_search_result_round_trip_preserves_content_kind(self):
        row = SearchResult(
            source="exa",
            title="Example",
            url="https://example.com",
            description="snippet",
            scraped_content="body",
            content_kind="body",
        ).to_dict()

        restored = SearchResult.from_dict(row)

        self.assertEqual(restored.content_kind, "body")
        self.assertEqual(restored.to_dict()["content_kind"], "body")


class ProviderContentKindTests(unittest.TestCase):
    def test_brave_rows_mark_descriptions_as_excerpt(self):
        payload = {
            "web": {
                "results": [{
                    "title": "Example",
                    "url": "https://example.com",
                    "description": "summary",
                    "extra_snippets": ["detail"],
                }]
            }
        }

        with mock.patch(
            "multi_search_mcp.src.search.searchers.brave.urlopen_retry",
            return_value=_FakeResponse(payload),
        ):
            rows = search_brave("q", "bk")

        self.assertEqual(rows[0]["content_kind"], "excerpt")
        self.assertEqual(rows[0]["description"], "summary · detail")

    def test_exa_highlights_are_excerpt_not_body(self):
        payload = {
            "results": [{
                "title": "Example",
                "url": "https://example.com",
                "highlights": ["alpha", "beta"],
            }]
        }

        with mock.patch(
            "multi_search_mcp.src.search.searchers.exa.urlopen_retry",
            return_value=_FakeResponse(payload),
        ):
            rows = search_exa("q", "ek", want_content=False)

        self.assertEqual(rows[0]["content_kind"], "excerpt")
        self.assertEqual(rows[0]["description"], "alpha\n\nbeta")
        self.assertEqual(rows[0]["scraped_content"], "alpha\n\nbeta")

    def test_exa_full_text_is_body(self):
        payload = {
            "results": [{
                "title": "Example",
                "url": "https://example.com",
                "text": "full page body",
            }]
        }

        with mock.patch(
            "multi_search_mcp.src.search.searchers.exa.urlopen_retry",
            return_value=_FakeResponse(payload),
        ):
            rows = search_exa("q", "ek", want_content=True)

        self.assertEqual(rows[0]["content_kind"], "body")
        self.assertEqual(rows[0]["scraped_content"], "full page body")

    def test_tavily_raw_content_is_body(self):
        payload = {
            "results": [{
                "title": "Example",
                "url": "https://example.com",
                "content": "summary",
                "raw_content": "markdown body",
            }]
        }

        with mock.patch(
            "multi_search_mcp.src.search.searchers.tavily.urlopen_retry",
            return_value=_FakeResponse(payload),
        ):
            rows = search_tavily("q", "tk", want_content=True)

        self.assertEqual(rows[0]["content_kind"], "body")
        self.assertEqual(rows[0]["scraped_content"], "markdown body")

    def test_baidu_rows_mark_answer_and_summary(self):
        rows = _rows_from_response(
            {
                "choices": [{"message": {"content": "answer text"}}],
                "references": [{
                    "title": "Reference",
                    "url": "https://example.com",
                    "content": "page summary",
                }],
            },
            endpoint="/v2/ai_search/web_summary",
            max_references=5,
        )

        self.assertEqual(rows[0]["content_kind"], "answer")
        self.assertEqual(rows[1]["content_kind"], "excerpt")
        self.assertEqual(rows[1]["description"], "page summary")
        self.assertNotIn("scraped_content", rows[1])

    def test_github_repo_description_is_excerpt(self):
        payload = {
            "items": [{
                "full_name": "octo/repo",
                "html_url": "https://github.com/octo/repo",
                "description": "repo summary",
                "stargazers_count": 7,
            }]
        }

        with mock.patch(
            "multi_search_mcp.src.search.searchers.github._github_api",
            return_value=(0, json.dumps(payload), ""),
        ):
            rows = search_github_repos("q")

        self.assertEqual(rows[0]["content_kind"], "excerpt")

    def test_hackernews_story_cards_without_story_text_are_metadata(self):
        payload = {
            "hits": [{
                "objectID": "42",
                "title": "Launch",
                "url": "https://example.com/story",
                "points": 10,
                "num_comments": 3,
                "author": "alice",
                "created_at": "2026-08-27T00:00:00Z",
            }]
        }

        with mock.patch(
            "multi_search_mcp.src.search.searchers.hackernews.urlopen_retry",
            return_value=_FakeResponse(payload),
        ):
            rows = search_hackernews("q")

        self.assertEqual(rows[0]["content_kind"], "metadata")

    def test_parallel_excerpts_are_excerpt(self):
        payload = {
            "results": [{
                "title": "Example",
                "url": "https://example.com",
                "excerpts": ["alpha", "beta"],
            }]
        }

        with mock.patch(
            "multi_search_mcp.src.search.searchers.parallel.urlopen_retry",
            return_value=_FakeResponse(payload),
        ):
            rows = search_parallel("q", "pk")

        self.assertEqual(rows[0]["content_kind"], "excerpt")
        self.assertEqual(rows[0]["description"], "alpha\n\nbeta")

    def test_serpapi_answers_and_organic_snippets_are_explicit(self):
        payload = {
            "answer_box": {"title": "Fact", "answer": "42"},
            "organic_results": [{
                "title": "Example",
                "link": "https://example.com",
                "snippet": "result summary",
            }],
        }

        with mock.patch(
            "multi_search_mcp.src.search.searchers.serpapi.urlopen_retry",
            return_value=_FakeResponse(payload),
        ):
            rows = search_serpapi("q", "sk")

        self.assertEqual(rows[0]["content_kind"], "answer")
        self.assertEqual(rows[1]["content_kind"], "excerpt")

    def test_stackoverflow_question_cards_are_metadata(self):
        payload = {
            "items": [{
                "title": "How to test this?",
                "link": "https://stackoverflow.com/questions/1",
                "score": 5,
                "answer_count": 2,
                "view_count": 99,
                "is_answered": True,
                "tags": ["python", "testing"],
            }]
        }

        with mock.patch(
            "multi_search_mcp.src.search.searchers.stackoverflow.urlopen_retry",
            return_value=_FakeResponse(payload),
        ):
            rows = search_stackoverflow("q")

        self.assertEqual(rows[0]["content_kind"], "metadata")


class SearchWebContentKindTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="search-content-semantics-")
        self.addCleanup(temp.cleanup)
        self.store = StateStore(Path(temp.name) / "state.sqlite")

    def _search(self, rows, scraper, *, use_state=True):
        providers = {
            source: ProviderSpec(
                name=source,
                public_name=source,
                call=lambda _query, _config, _context, _key, source=source: [
                    dict(row) for row in rows if row["source"] == source
                ],
            )
            for source in {row["source"] for row in rows}
        }
        with (
            mock.patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")),
            mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected connection")),
        ):
            return service.run_search_web(
                service.SearchWebRequest(query="query", sources=list(providers), use_state=use_state),
                providers=providers, keys={}, config={}, state_store=self.store,
                scraper=scraper, url_resolver=lambda _host: ["93.184.216.34"],
            )

    def test_excerpt_does_not_block_scrape_even_when_long(self):
        scraper = mock.Mock(return_value={"markdown": "fetched body", "via": "fake"})
        response = self._search(
            [{
                "source": "exa",
                "title": "Example",
                "url": "https://example.com/excerpt",
                "description": "x" * 1200,
                "scraped_content": "x" * 1200,
                "content_kind": "excerpt",
            }],
            scraper,
        )

        self.assertEqual(response["errors"], [])
        scraper.assert_called_once()
        self.assertEqual(scraper.call_args.args[0], "https://example.com/excerpt")
        self.assertEqual(response["results"][0]["content"], "x" * 1200)
        self.assertEqual(response["results"][0]["content_kind"], "excerpt")
        self.assertEqual(response["scrapes"][0]["markdown"], "fetched body")

    def test_short_body_skips_scrape_without_length_threshold(self):
        for use_state in (True, False):
            with self.subTest(use_state=use_state):
                scraper = mock.Mock(side_effect=AssertionError("body must skip fetch"))
                response = self._search(
                    [{
                        "source": "baidu",
                        "title": "Example",
                        "url": "https://example.com/body",
                        "scraped_content": "short body",
                        "content_kind": "body",
                    }],
                    scraper, use_state=use_state,
                )

                self.assertEqual(response["errors"], [])
                scraper.assert_not_called()
                self.assertTrue(response["results"][0]["body_available"])
                self.assertEqual(response["scrapes"][0]["markdown"], "short body")

    def test_prefetched_body_skips_duplicate_excerpt_scrape(self):
        rows = [
            {
                "source": "baidu",
                "title": "Body",
                "url": "https://example.com/shared",
                "scraped_content": "body",
                "content_kind": "body",
            },
            {
                "source": "exa",
                "title": "Excerpt",
                "url": "https://example.com/shared",
                "description": "summary",
                "content_kind": "excerpt",
            },
        ]
        for use_state in (True, False):
            with self.subTest(use_state=use_state):
                scraper = mock.Mock(side_effect=AssertionError("duplicate body must be reused"))
                response = self._search(rows, scraper, use_state=use_state)

                self.assertEqual(response["errors"], [])
                scraper.assert_not_called()
                self.assertEqual(len(response["results"]), 1)
                self.assertEqual(response["results"][0]["providers"], ["baidu", "exa"])
                self.assertEqual(response["results"][0]["content"], "summary")
                self.assertEqual(response["scrapes"][0]["markdown"], "body")

    def test_fetched_body_keeps_public_snippet_separate(self):
        rows = [{
            "source": "brave", "url": "https://example.com",
            "description": "snippet", "content_kind": "excerpt",
        }]
        response = self._search(
            rows,
            mock.Mock(return_value={"markdown": "body", "via": "fake"}),
        )

        self.assertEqual(response["errors"], [])
        hit = response["results"][0]
        self.assertEqual(hit["content"], "snippet")
        self.assertEqual(hit["content_kind"], "excerpt")
        self.assertTrue(hit["body_available"])
        self.assertNotIn("body", hit)
        self.assertNotIn("scraped_content", hit)
        self.assertEqual(response["scrapes"][0]["markdown"], "body")
        cached = service.run_read_source(
            service.ReadSourceRequest(source_id=hit["source_id"]), state_store=self.store,
        )
        self.assertEqual(cached["content"], "body")


if __name__ == "__main__":
    unittest.main()

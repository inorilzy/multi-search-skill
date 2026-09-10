import json
import unittest
from unittest import mock

from multi_search_mcp.src.scrape.scrape_planner import plan_scrapes
from multi_search_mcp.src.search.searchers.baidu import _rows_from_response
from multi_search_mcp.src.search.searchers.brave import search_brave
from multi_search_mcp.src.search.searchers.exa import search_exa
from multi_search_mcp.src.search.searchers.github import search_github_repos
from multi_search_mcp.src.search.searchers.hackernews import search_hackernews
from multi_search_mcp.src.search.searchers.linuxdo import search_linuxdo_api
from multi_search_mcp.src.search.searchers.parallel import search_parallel
from multi_search_mcp.src.search.searchers.serpapi import search_serpapi
from multi_search_mcp.src.search.searchers.stackoverflow import search_stackoverflow
from multi_search_mcp.src.search.searchers.tavily import search_tavily
from multi_search_mcp.src.support.dedup import _norm_url, apply_scraped_content
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

    def test_linuxdo_blurb_rows_are_excerpt(self):
        payload = {
            "posts": [{
                "topic_id": 123,
                "blurb": "forum excerpt",
                "username": "alice",
                "like_count": 5,
            }]
        }

        with mock.patch(
            "multi_search_mcp.src.search.searchers.linuxdo.urllib.request.urlopen",
            return_value=_FakeResponse(payload),
        ):
            rows = search_linuxdo_api("q", cookie="cookie")

        self.assertEqual(rows[0]["content_kind"], "excerpt")
        self.assertEqual(rows[0]["content"], "forum excerpt")

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


class ScrapePlannerContentKindTests(unittest.TestCase):
    def test_excerpt_does_not_block_scrape_even_when_long(self):
        plan = plan_scrapes(
            [{
                "source": "exa",
                "title": "Example",
                "url": "https://example.com/excerpt",
                "description": "x" * 1200,
                "scraped_content": "x" * 1200,
                "content_kind": "excerpt",
            }],
            keys={},
            scrape_top=5,
            scrape_per_source=5,
        )

        self.assertEqual(plan.with_content, [])
        self.assertEqual([item["url"] for item in plan.items_to_scrape], ["https://example.com/excerpt"])

    def test_short_body_skips_scrape_without_length_threshold(self):
        plan = plan_scrapes(
            [{
                "source": "baidu",
                "title": "Example",
                "url": "https://example.com/body",
                "scraped_content": "short body",
                "content_kind": "body",
            }],
            keys={},
            scrape_top=5,
            scrape_per_source=5,
        )

        self.assertEqual(plan.items_to_scrape, [])
        self.assertEqual([item["url"] for item in plan.with_content], ["https://example.com/body"])

    def test_prefetched_body_skips_duplicate_excerpt_scrape(self):
        plan = plan_scrapes(
            [
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
            ],
            keys={},
            scrape_top=5,
            scrape_per_source=5,
        )

        self.assertEqual(plan.items_to_scrape, [])
        self.assertEqual(set(plan.content_pool), {_norm_url("https://example.com/shared")})


class ScrapeWritebackTests(unittest.TestCase):
    def test_apply_scraped_content_marks_rows_as_body(self):
        rows = [{"source": "brave", "url": "https://example.com", "description": "snippet"}]
        apply_scraped_content(
            rows,
            {_norm_url("https://example.com"): {"markdown": "body", "via": "jina"}},
        )

        self.assertEqual(rows[0]["scraped_content"], "body")
        self.assertEqual(rows[0]["content_kind"], "body")


if __name__ == "__main__":
    unittest.main()

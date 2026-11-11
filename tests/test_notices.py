"""Ticket 12: truncation notices and upstream warnings are not errors.

A successful provider response can still be capped or carry a warning.  Those
rows belong in ``notices``; ``outcome``, ``provider_status`` errors, and key
health must only count real failures.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.searchers import github, parallel
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.content_store import ContentStore
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support.query_limits import limit_query


def _response(payload):
    result = mock.MagicMock()
    result.__enter__.return_value = result
    result.read.return_value = json.dumps(payload).encode()
    return result


def _row(source, rank, *, site="example.com", body=None):
    row = {
        "source": source,
        "title": f"{source}-{rank}",
        "url": f"https://{site}/{source}-{rank}",
        "description": f"result {rank}",
        "content_kind": "excerpt",
    }
    if body is not None:
        row["scraped_content"] = body
        row["content_kind"] = "body"
    return row


def _providers(rows):
    return {
        "brave": ProviderSpec(
            name="brave",
            public_name="brave",
            call=lambda _query, _config, _context, _key: [dict(row) for row in rows],
        )
    }


class QueryTruncationNoticeTests(unittest.TestCase):
    def test_successful_truncated_query_is_success_and_reports_notice(self):
        query = " ".join(["word"] * 20)

        def brave(provider_query, _config, _context, _key):
            _limited, notes = limit_query("brave", provider_query, max_chars=20)
            return notes + [_row("brave", 1)]

        response = service.run_search_candidates(
            service.SearchWebRequest(
                query=query, sources=["brave"], count=1, use_state=False,
            ),
            providers={
                "brave": ProviderSpec("brave", "brave", brave),
            },
            keys={},
            config={},
        )

        self.assertEqual(response["outcome"], "success")
        self.assertEqual(response["errors"], [])
        self.assertEqual(response["provider_status"][0]["status"], "ok")
        self.assertEqual(response["provider_status"][0]["errors"], [])
        self.assertEqual(response["notices"], [{
            "source": "brave",
            "query": query,
            "notice": "query truncated to the provider limit (20 characters)",
        }])

    def test_limit_query_returns_a_notice_row_without_an_error(self):
        text, notes = limit_query(
            "brave", " ".join(["word"] * 100), max_chars=600, max_words=75,
        )

        self.assertEqual(len(text.split()), 75)
        self.assertEqual(notes, [{
            "source": "brave",
            "notice": "query truncated to the provider limit (600 characters / 75 words)",
        }])


class UpstreamWarningTests(unittest.TestCase):
    def test_parallel_warning_is_a_notice_row_without_an_error(self):
        payload = {
            "results": [{
                "url": "https://example.com/a", "title": "A", "excerpts": ["excerpt"],
            }],
            "warnings": [{"message": "max_results was clamped"}],
        }
        with mock.patch.object(parallel, "urlopen_retry", return_value=_response(payload)):
            rows = parallel.search_parallel("query", "key")

        self.assertEqual(rows[-1], {
            "source": "parallel",
            "notice": "Parallel warning: max_results was clamped",
        })
        self.assertNotIn("error", rows[-1])


class GitHubQueryTruncationTests(unittest.TestCase):
    def test_truncated_query_never_ends_with_a_boolean_operator(self):
        limited, truncated = github.limit_github_query(
            "a" * 250 + " bbbbbbbbbb OR c AND d",
        )

        self.assertTrue(truncated)
        self.assertNotIn(limited.split()[-1], {"AND", "OR", "NOT"})
        self.assertLessEqual(len(limited), 256)

    def test_urls_and_error_code_tokens_count_toward_the_text_limit(self):
        for query in (
            "http://example.com/" + "x" * 300,
            "error:E0308 " + "word " * 60,
        ):
            with self.subTest(query=query[:20]):
                limited, truncated = github.limit_github_query(query)
                self.assertTrue(truncated)
                self.assertLessEqual(len(limited), 256)

    def test_github_truncation_and_incomplete_results_are_notices(self):
        payload = {
            "incomplete_results": True,
            "items": [{
                "full_name": "a/b",
                "html_url": "https://github.com/a/b",
                "description": "repository",
            }],
        }
        with mock.patch.object(github, "urlopen_retry", return_value=_response(payload)):
            rows = github.search_github_repos(
                " ".join(["word"] * 80), token="fixture-token", timeout=1,
            )

        notices = [row["notice"] for row in rows if "notice" in row]
        self.assertIn(
            "query truncated to GitHub's 256-character / 5-operator limit", notices,
        )
        self.assertIn("GitHub search timed out; results may be incomplete", notices)
        self.assertFalse(any("error" in row for row in rows))


class OversizedBodyPersistenceTests(unittest.TestCase):
    def test_oversized_body_reports_one_persistence_error_per_call(self):
        with TemporaryDirectory() as temporary:
            store = StateStore(Path(temporary) / "state.sqlite")
            rows = [_row("exa", 1, site="evidence.example", body="证据" * 4)]

            def cache(inner_store, **options):
                return ContentStore(inner_store, max_object_bytes=10, **options)

            with mock.patch(
                "multi_search_mcp.src.search.candidates.ContentStore", side_effect=cache,
            ), mock.patch(
                "multi_search_mcp.src.scrape.fetch.ContentStore", side_effect=cache,
            ), mock.patch(
                "socket.getaddrinfo", side_effect=AssertionError("unexpected DNS"),
            ), mock.patch(
                "socket.socket.connect", side_effect=AssertionError("unexpected connection"),
            ):
                response = service.run_search_web(
                    service.SearchWebRequest(query="query", sources=["exa"], count=1),
                    providers={
                        "exa": ProviderSpec(
                            "exa", "exa",
                            lambda _query, _config, _context, _key: [dict(row) for row in rows],
                        ),
                    },
                    keys={},
                    config={},
                    state_store=store,
                    scraper=mock.Mock(side_effect=AssertionError("unexpected scrape")),
                )

        persistence_errors = (
            response["diagnostics"]["content_store_errors"]
            + response["diagnostics"]["body_persist_failures"]
        )
        self.assertEqual(len(persistence_errors), 1)
        self.assertEqual(response["diagnostics"]["body_persist_failures"][0]["reason"], "content_too_large")
        self.assertIn("not cached", response["scrapes"][0]["persist_error"])
        self.assertFalse(response["scrapes"][0]["persisted"])


class _FixedReranker:
    def score(self, query, candidates, *, deadline):
        return {
            str(candidate["source_id"]): (
                0.99 if candidate["url"].startswith("https://a.example/") else 0.1
            )
            for candidate in candidates
        }


class RerankedResultOrderingTests(unittest.TestCase):
    @staticmethod
    def _search(rows, candidate_limit):
        config = {
            "ranking": {
                "mode": "rrf_model",
                "base_url": "http://gateway.test/v1",
                "model": "fixture-model",
                "candidate_limit": candidate_limit,
            },
        }
        return service.run_search_candidates(
            service.SearchWebRequest(
                query="query", sources=["brave"], count=10, use_state=False,
            ),
            providers=_providers(rows),
            keys={},
            config=config,
            reranker=_FixedReranker(),
        )

    def test_reranked_hits_stay_before_unscored_results_when_candidate_limit_is_10_to_14(self):
        rows = (
            [_row("brave", rank, site="a.example") for rank in range(1, 7)]
            + [_row("brave", rank, site=f"b{rank}.example") for rank in range(7, 16)]
        )
        for candidate_limit in (10, 14):
            with self.subTest(candidate_limit=candidate_limit):
                response = self._search(rows, candidate_limit)
                scores = [hit["relevance_score"] for hit in response["results"]]

                self.assertEqual(len(scores), 15)
                self.assertEqual(sum(score is not None for score in scores), candidate_limit)
                self.assertTrue(all(score is not None for score in scores[:candidate_limit]))
                self.assertTrue(all(score is None for score in scores[candidate_limit:]))

    def test_rerank_diversity_pool_is_not_smaller_than_pure_rrf(self):
        rows = (
            [_row("brave", rank, site="a.example") for rank in range(1, 16)]
            + [_row("brave", rank, site=f"b{rank}.example") for rank in range(16, 26)]
        )
        response = self._search(rows, 10)

        self.assertEqual(len(response["results"]), 15)
        self.assertGreater(len({hit["canonical_url"].split("/")[2] for hit in response["results"]}), 1)


if __name__ == "__main__":
    unittest.main()

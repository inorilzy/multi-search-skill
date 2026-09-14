import asyncio
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from multi_search_mcp.src.search.searchers.twitter import search_twitter


def tweet(tweet_id, full_text=None):
    return SimpleNamespace(
        id=tweet_id, text="Legacy truncated text",
        full_text=full_text or f"Acquired tweet {tweet_id}",
        user=SimpleNamespace(screen_name="fixture"),
        reply_count=3, favorite_count=7, retweet_count=2,
    )


class ClientFixture:
    def __init__(self):
        self.http = SimpleNamespace(aclose=mock.AsyncMock())
        self.set_cookies = mock.Mock()
        self.search_tweet = mock.AsyncMock(return_value=[tweet("1"), tweet("2")])
        self.get_tweet_by_id = mock.AsyncMock(side_effect=AssertionError("search must not fetch details"))


def client_module(client):
    return mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=mock.Mock(return_value=client)), "twikit": None})


class TwitterPartialResultsTests(unittest.TestCase):
    def test_search_returns_candidates_without_details_or_body(self):
        client = ClientFixture()
        cookies = {"auth_token": "fixture-token", "ct0": "fixture-csrf"}
        with client_module(client):
            rows = search_twitter("query", count=1, cookies=cookies, timeout=1)
        client.search_tweet.assert_awaited_once_with("query", "Top", count=1)
        client.get_tweet_by_id.assert_not_called()
        client.set_cookies.assert_called_once_with(cookies)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://x.com/fixture/status/1")
        self.assertEqual(rows[0]["description"], "💬3 ♥7 🔁2\nAcquired tweet 1")
        self.assertEqual(rows[0]["scraped_content"], "")
        self.assertEqual(rows[0]["content_kind"], "excerpt")
        self.assertEqual(rows[0]["author"], "fixture")
        self.assertEqual(rows[0]["tweet_id"], "1")
        self.assertEqual(rows[0]["favorite_count"], 7)
        self.assertEqual(rows[0]["retweet_count"], 2)
        self.assertEqual(rows[0]["reply_count"], 3)
        client.http.aclose.assert_awaited_once()

    def test_long_tweet_snippet_uses_full_text_without_claiming_full_body(self):
        client = ClientFixture()
        full_text = "Long tweet title\n" + "Full text " * 80
        client.search_tweet.return_value = [tweet("1", full_text)]
        with client_module(client):
            rows = search_twitter("query", cookies={}, timeout=1)
        self.assertEqual(rows[0]["title"], "@fixture: Long tweet title")
        self.assertEqual(rows[0]["description"], "💬3 ♥7 🔁2\n" + full_text[:500])
        self.assertEqual(len(rows[0]["description"].split("\n", 1)[1]), 500)
        self.assertNotIn("Legacy truncated", str(rows))
        self.assertEqual(rows[0]["scraped_content"], "")
        self.assertEqual(rows[0]["content_kind"], "excerpt")
        client.get_tweet_by_id.assert_not_called()

    def test_missing_author_retains_canonical_tweet_url(self):
        client = ClientFixture()
        row_tweet = tweet("1")
        row_tweet.user = None
        client.search_tweet.return_value = [row_tweet]
        with client_module(client):
            rows = search_twitter("query", cookies={}, timeout=1)
        self.assertEqual(rows[0]["url"], "https://x.com/i/web/status/1")
        self.assertEqual(rows[0]["title"], "Acquired tweet 1")
        self.assertEqual(rows[0]["author"], "")

    def test_candidates_are_published_before_session_closes(self):
        client = ClientFixture()
        published = []

        async def close():
            self.assertEqual(len(published), 1)
            self.assertEqual(len(published[0]), 2)

        client.http.aclose.side_effect = close
        with client_module(client):
            rows = search_twitter("query", cookies={}, publish_partial=published.append, timeout=1)
        self.assertEqual(published, [rows])
        self.assertIsNot(published[0][0], rows[0])

    def test_runner_deadline_preserves_published_candidates_and_provider_rank(self):
        from multi_search_mcp.src.search import search_runner
        from multi_search_mcp.src.search.registry import build_provider_registry

        client = ClientFixture()
        closing = threading.Event()
        pool = search_runner.BoundedDaemonExecutor(
            max_workers=1, thread_name_prefix="test-twitter-candidate-partial",
        )

        async def close():
            closing.set()
            await asyncio.sleep(0.3)

        client.http.aclose.side_effect = close
        runner = search_runner.SearchRunner(
            search_runner.SearchRunnerConfig("social", {"twitter": 2}, 0.15, "google", {
                "twitter": {"auth_token": "fixture-token", "ct0": "fixture-csrf"},
            }), build_provider_registry(),
        )
        with client_module(client), mock.patch.object(search_runner, "_SEARCH_POOL", pool):
            try:
                rows = runner.run("query")
            finally:
                pool.shutdown(wait=True)
        self.assertTrue(closing.is_set())
        candidates = [row for row in rows if row.get("url") and not row.get("error")]
        self.assertEqual([row["url"] for row in candidates], [
            "https://x.com/fixture/status/1", "https://x.com/fixture/status/2",
        ])
        self.assertEqual([row["provider_rank"] for row in candidates], [1, 2])
        self.assertTrue(all(row["content_kind"] == "excerpt" and not row["scraped_content"] for row in candidates))
        self.assertTrue(any("timeout after" in row.get("error", "") for row in rows))
        client.get_tweet_by_id.assert_not_called()

    def test_search_timeout_is_explicit_and_closes_session(self):
        client = ClientFixture()

        async def slow_search(*_args, **_kwargs):
            await asyncio.sleep(1)

        client.search_tweet.side_effect = slow_search
        with client_module(client):
            rows = search_twitter("query", cookies={}, timeout=0.03)
        self.assertEqual(len(rows), 1)
        self.assertIn("TimeoutError", rows[0]["error"])
        client.http.aclose.assert_awaited_once()
        client.get_tweet_by_id.assert_not_called()

    def test_expired_deadline_does_not_start_search(self):
        client = ClientFixture()
        with client_module(client):
            rows = search_twitter("query", cookies={}, deadline=time.monotonic() - 1)
        self.assertIn("deadline exhausted", rows[0]["error"])
        client.search_tweet.assert_not_called()
        client.http.aclose.assert_awaited_once()

    def test_xkit_uses_remaining_request_budget(self):
        client = ClientFixture()
        factory = mock.Mock(return_value=client)
        with mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=factory), "twikit": None}):
            rows = search_twitter("query", count=1, cookies={}, timeout=20, deadline=time.monotonic() + 12)
        self.assertEqual(len(rows), 1)
        request_timeout = factory.call_args.kwargs["timeout"]
        self.assertGreater(request_timeout, 11)
        self.assertLessEqual(request_timeout, 12)
        client.http.aclose.assert_awaited_once()

    def test_initial_search_failure_closes_session_and_redacts_credentials(self):
        client = ClientFixture()
        cookies = {"auth_token": "fixture-secret", "ct0": "raw-csrf-secret"}
        client.search_tweet.side_effect = RuntimeError("request failed auth_token=fixture-secret, csrf raw-csrf-secret")
        with client_module(client):
            rows = search_twitter("query", cookies=cookies, timeout=1)
        self.assertEqual(len(rows), 1)
        self.assertIn("request failed", rows[0]["error"])
        self.assertNotIn("fixture-secret", str(rows))
        self.assertNotIn("raw-csrf-secret", str(rows))
        client.http.aclose.assert_awaited_once()
        client.search_tweet.assert_awaited_once()

    def test_session_close_failure_keeps_candidates_and_explicit_error(self):
        client = ClientFixture()
        client.http.aclose.side_effect = RuntimeError("close failed ct0=fixture-secret")
        with client_module(client):
            rows = search_twitter("query", cookies={}, timeout=1)
        self.assertEqual(len([row for row in rows if not row.get("error")]), 2)
        self.assertIn("close failed", rows[-1]["error"])
        self.assertNotIn("fixture-secret", str(rows))

    def test_json_cookie_path_is_supported(self):
        client = ClientFixture()
        cookies = {"auth_token": "fixture-token", "ct0": "fixture-csrf"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.json"
            path.write_text(json.dumps(cookies), encoding="utf-8")
            with client_module(client):
                rows = search_twitter("query", cookies=str(path), timeout=1)
        self.assertEqual(len(rows), 2)
        client.set_cookies.assert_called_once_with(cookies)

    def test_missing_cookie_path_fails_before_network(self):
        client = ClientFixture()
        with tempfile.TemporaryDirectory() as directory, client_module(client):
            rows = search_twitter("query", cookies=str(Path(directory) / "missing.json"), timeout=1)
        self.assertIn("cookies file not found", rows[0]["error"])
        client.search_tweet.assert_not_called()

    def test_existing_rate_limit_retry_keeps_top_search_contract(self):
        client = ClientFixture()
        client.search_tweet.side_effect = [RuntimeError("429 rate limited"), [tweet("1")]]
        with client_module(client), mock.patch("asyncio.sleep", new_callable=mock.AsyncMock) as sleep:
            rows = search_twitter("query", count=1, cookies={}, timeout=1)
        self.assertEqual(len(rows), 1)
        sleep.assert_awaited_once_with(5)
        self.assertEqual(client.search_tweet.await_args_list, [
            mock.call("query", "Top", count=1), mock.call("query", "Top", count=1),
        ])
        client.get_tweet_by_id.assert_not_called()


if __name__ == "__main__":
    unittest.main()

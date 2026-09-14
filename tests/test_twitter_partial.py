import asyncio
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from multi_search_mcp.src.search.searchers.twitter import search_twitter


def tweet(tweet_id, text=None):
    return SimpleNamespace(
        id=tweet_id, text=text or f"Acquired tweet {tweet_id}",
        user=SimpleNamespace(screen_name="fixture"),
    )


class ClientFixture:
    def __init__(self, *_args, **_kwargs):
        self.http = SimpleNamespace(aclose=mock.AsyncMock())

    def set_cookies(self, _cookies):
        pass

    async def search_tweet(self, *_args, **_kwargs):
        return [tweet("1"), tweet("2")]

    async def get_tweet_by_id(self, _tweet_id):
        return SimpleNamespace(replies=None)


class TwitterPartialResultsTests(unittest.TestCase):
    def test_fast_details_do_not_lose_tweets_to_fixed_waits(self):
        with mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=ClientFixture), "twikit": None}):
            rows = search_twitter("query", count=2, cookies={}, timeout=0.05)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not row.get("error") for row in rows))
        self.assertTrue(all("Replies incomplete" not in row["scraped_content"] for row in rows))

    def test_reply_timeout_keeps_all_acquired_tweets(self):
        class Client(ClientFixture):
            async def get_tweet_by_id(self, _tweet_id):
                await asyncio.sleep(1)

        with mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=Client), "twikit": None}):
            rows = search_twitter("query", count=2, cookies={}, timeout=0.05)
        candidates = [row for row in rows if not row.get("error")]
        self.assertEqual([row["url"] for row in candidates], [
            "https://x.com/fixture/status/1", "https://x.com/fixture/status/2",
        ])
        self.assertIn("Acquired tweet 1", candidates[0]["scraped_content"])
        self.assertIn("Acquired tweet 2", candidates[1]["scraped_content"])
        errors = [row for row in rows if row.get("error")]
        self.assertEqual({row["url"] for row in errors}, {row["url"] for row in candidates})
        self.assertTrue(all("replies" in row["error"] for row in errors))

    def test_runner_deadline_preserves_published_tweets_before_reply_cancellation_finishes(self):
        from multi_search_mcp.src.search.registry import build_provider_registry
        from multi_search_mcp.src.search.search_runner import SearchRunner, SearchRunnerConfig

        finished = threading.Event()

        class Client(ClientFixture):
            async def get_tweet_by_id(self, _tweet_id):
                try:
                    await asyncio.sleep(2)
                except asyncio.CancelledError:
                    await asyncio.sleep(0.05)
                    raise
                finally:
                    finished.set()

        runner = SearchRunner(
            SearchRunnerConfig("social", {"twitter": 2}, 0.05, "google", {
                "twitter": {"auth_token": "fixture-token", "ct0": "fixture-csrf"},
            }), build_provider_registry(),
        )
        try:
            with mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=Client), "twikit": None}):
                rows = runner.run("query")
            candidates = [row for row in rows if row.get("url") and not row.get("error")]
            self.assertEqual(len(candidates), 2)
            self.assertEqual([row["provider_rank"] for row in candidates], [1, 2])
            for row in candidates:
                self.assertIn("Acquired tweet", row["scraped_content"])
                self.assertTrue(any(error.get("url") == row["url"] and "replies" in error.get("error", "")
                                    for error in rows))
        finally:
            self.assertTrue(finished.wait(timeout=1))

    def test_runner_deadline_keeps_updated_body_and_removes_resolved_reply_errors(self):
        from multi_search_mcp.src.search import search_runner
        from multi_search_mcp.src.search.registry import build_provider_registry

        full_text = "Complete acquired tweet text with its original tail"
        reply_text = "Already acquired reply"
        second_started = threading.Event()
        pool = search_runner.BoundedDaemonExecutor(
            max_workers=1, thread_name_prefix="test-twitter-updated-partial",
        )

        class Client(ClientFixture):
            async def get_tweet_by_id(self, tweet_id):
                if tweet_id == "1":
                    return SimpleNamespace(
                        text=full_text, replies=[tweet("reply", reply_text)], reply_count=1,
                    )
                second_started.set()
                try:
                    await asyncio.sleep(2)
                except asyncio.CancelledError:
                    # Keep the provider pending while the runner returns its snapshot.
                    await asyncio.sleep(0.1)
                    raise

        runner = search_runner.SearchRunner(
            search_runner.SearchRunnerConfig("social", {"twitter": 2}, 0.2, "google", {
                "twitter": {"auth_token": "fixture-token", "ct0": "fixture-csrf"},
            }), build_provider_registry(),
        )
        with mock.patch.dict(sys.modules, {
            "xkit": SimpleNamespace(Client=Client), "twikit": SimpleNamespace(Client=Client),
        }), \
                mock.patch.object(search_runner, "_SEARCH_POOL", pool):
            try:
                rows = runner.run("query")
            finally:
                pool.shutdown(wait=True)

        self.assertTrue(second_started.is_set())
        candidates = [row for row in rows if row.get("url") and not row.get("error")]
        self.assertEqual([row["url"] for row in candidates], [
            "https://x.com/fixture/status/1", "https://x.com/fixture/status/2",
        ])
        self.assertEqual([row["provider_rank"] for row in candidates], [1, 2])
        self.assertIn(full_text, candidates[0]["scraped_content"])
        self.assertIn(reply_text, candidates[0]["scraped_content"])
        self.assertNotIn("Replies incomplete", candidates[0]["scraped_content"])
        reply_errors = [row for row in rows if row.get("url") and row.get("error")]
        self.assertEqual(len(reply_errors), 1)
        self.assertEqual(reply_errors[0]["url"], candidates[1]["url"])
        self.assertTrue(any("timeout after" in row.get("error", "") for row in rows))

    def test_failed_reply_page_keeps_full_text_and_identifies_only_affected_tweet(self):
        reply_text = "Reply " * 60 + "\nUncut reply tail"
        full_text = "Longer acquired tweet text\nOriginal tweet tail"

        class Page(list):
            next_cursor = "next-page"

            async def next(self):
                raise RuntimeError("page failed auth_token=fixture-secret")

        class Client(ClientFixture):
            async def get_tweet_by_id(self, tweet_id):
                if tweet_id == "1":
                    return SimpleNamespace(text=full_text, replies=Page([tweet("reply", reply_text)]))
                return SimpleNamespace(replies=None)

        with mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=Client), "twikit": None}):
            rows = search_twitter("query", count=2, cookies={}, timeout=1)
        candidates = [row for row in rows if not row.get("error")]
        self.assertEqual(len(candidates), 2)
        self.assertIn(full_text, candidates[0]["scraped_content"])
        self.assertIn(reply_text, candidates[0]["scraped_content"])
        errors = [row for row in rows if row.get("error")]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["url"], "https://x.com/fixture/status/1")
        self.assertIn("page failed", errors[0]["error"])
        self.assertNotIn("fixture-secret", str(rows))
        self.assertNotIn("Replies incomplete", candidates[1]["scraped_content"])

    def test_reply_limit_marks_only_known_omissions(self):
        for reply_count in (20, 21):
            with self.subTest(reply_count=reply_count):
                class Client(ClientFixture):
                    async def search_tweet(self, *_args, **_kwargs):
                        return [tweet("1")]

                    async def get_tweet_by_id(self, _tweet_id):
                        return SimpleNamespace(replies=[tweet(str(index)) for index in range(reply_count)])

                with mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=Client), "twikit": None}):
                    rows = search_twitter("query", count=1, cookies={}, timeout=1)
                self.assertEqual(rows[0]["scraped_content"].count("  - @fixture"), 20)
                errors = [row for row in rows if row.get("error")]
                self.assertEqual(len(errors), int(reply_count > 20))
                self.assertEqual("Replies incomplete" in rows[0]["scraped_content"], reply_count > 20)

    def test_xkit_uses_request_budget_and_closes_http_session(self):
        clients = []

        class Client(ClientFixture):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.options = kwargs
                clients.append(self)

        with mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=Client), "twikit": None}):
            rows = search_twitter("query", count=1, cookies={}, timeout=12)
        self.assertEqual(len(rows), 1)
        self.assertGreater(clients[0].options["timeout"], 11)
        self.assertLessEqual(clients[0].options["timeout"], 12)
        clients[0].http.aclose.assert_awaited_once()

    def test_xkit_initial_search_failure_closes_session_and_redacts_cookie(self):
        client = ClientFixture()
        client.search_tweet = mock.AsyncMock(side_effect=RuntimeError("auth_token=fixture-secret"))
        with mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=lambda *a, **kw: client), "twikit": None}):
            rows = search_twitter("query", cookies={"auth_token": "fixture-secret"}, timeout=1)
        self.assertEqual(len(rows), 1)
        self.assertIn("error", rows[0])
        self.assertNotIn("fixture-secret", str(rows))
        client.http.aclose.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

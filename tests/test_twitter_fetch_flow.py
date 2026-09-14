"""X search/fetch integration through the real service and domain dispatcher."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.service import run_fetch_source, run_read_source, run_search_web
from multi_search_mcp.src.state.content_store import ContentStore
from multi_search_mcp.src.state.source_registry import SourceRegistry
from multi_search_mcp.src.state.state_store import StateStore


def public_resolver(_hostname):
    return ["93.184.216.34"]


def tweet(tweet_id, full_text, *, replies=None):
    return SimpleNamespace(
        id=tweet_id, text="Legacy shortened body", full_text=full_text,
        user=SimpleNamespace(screen_name="fixture"),
        favorite_count=7, retweet_count=2,
        reply_count=len(replies or []), replies=replies,
    )


class XKitFixture:
    def __init__(self, count=1):
        self.events = []
        self.clients = []
        self.cookies = []
        self.detail_delay = 0
        self.candidates = [tweet(str(index), f"Candidate excerpt {index}") for index in range(1, count + 1)]
        self.details = {
            str(index): tweet(str(index), f"Fetched full body {index}")
            for index in range(1, count + 1)
        }

    def client(self, *_args, **_kwargs):
        fixture = self

        class Client:
            def __init__(self):
                self.http = SimpleNamespace(aclose=mock.AsyncMock())

            def set_cookies(self, cookies):
                fixture.cookies.append(cookies)

            async def search_tweet(self, query, product, count):
                fixture.events.append(("search", query, product, count))
                return fixture.candidates[:count]

            async def get_tweet_by_id(self, tweet_id):
                fixture.events.append(("detail", tweet_id))
                if fixture.detail_delay:
                    await asyncio.sleep(fixture.detail_delay)
                result = fixture.details[tweet_id]
                if isinstance(result, Exception):
                    raise result
                return result

        client = Client()
        self.clients.append(client)
        return client

    def patched(self):
        return mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=self.client)})

    def detail_ids(self):
        return [event[1] for event in self.events if event[0] == "detail"]


class TwitterFetchFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = StateStore(Path(self.directory.name) / "state.sqlite")
        self.cookies = {"auth_token": "fixture-auth-token", "ct0": "fixture-csrf-token"}
        self.options = {
            "state_store": self.store, "keys": {"twitter": self.cookies},
            "config": {}, "url_resolver": public_resolver,
        }

    def test_only_final_fifteen_candidates_fetch_after_search_and_cache_full_text(self):
        api = XKitFixture(count=20)
        full_body = "Full post paragraph. " * 180 + "POST_LONG_TAIL"
        full_reply = "Full reply paragraph. " * 100 + "REPLY_LONG_TAIL"
        api.details["1"] = tweet("1", full_body, replies=[tweet("reply", full_reply)])

        def search_completed(query_runs):
            self.assertEqual(len(query_runs[0][1]), 20)
            self.assertEqual(api.detail_ids(), [])
            api.events.append(("search-completed",))

        with api.patched():
            result = run_search_web(
                {"query": "OpenAI", "sources": ["twitter"], "count": 20},
                **self.options, scrape_chars=80, scrape_concurrency=3,
                query_runs_observer=search_completed,
            )
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["diagnostics"]["raw_result_count"], 20)
            self.assertEqual(len(result["results"]), 15)
            self.assertEqual(len(result["scrapes"]), 15)
            self.assertEqual([row["url"].rsplit("/", 1)[1] for row in result["results"]],
                             [str(index) for index in range(1, 16)])
            self.assertCountEqual(api.detail_ids(), [str(index) for index in range(1, 16)])
            self.assertEqual(api.events[0], ("search", "OpenAI", "Top", 20))
            self.assertEqual(api.events[1], ("search-completed",))
            self.assertTrue(all(event[0] == "detail" for event in api.events[2:]))
            self.assertTrue(all(row["content_kind"] == "excerpt" for row in result["results"]))
            self.assertEqual(result["results"][0]["content"], "💬0 ♥7 🔁2 Candidate excerpt 1")
            self.assertTrue(all(row["body_available"] for row in result["results"]))
            self.assertTrue(all(row["via"] == "twitter" for row in result["scrapes"]))
            first_page = result["scrapes"][0]
            self.assertLessEqual(len(first_page["markdown"]), 80)
            self.assertTrue(first_page["truncated"])
            self.assertNotIn("POST_LONG_TAIL", first_page["markdown"])
            source_id = result["results"][0]["source_id"]
            fetched = run_fetch_source({"source_id": source_id, "full_content": True}, **self.options)
            self.assertTrue(fetched["cache_hit"])
            self.assertFalse(fetched["truncated"])
            self.assertEqual(fetched["backend"], "content-store")
            self.assertIn(full_body, fetched["body"])
            self.assertIn(full_reply, fetched["body"])
            self.assertNotIn("Legacy shortened body", fetched["body"])
            read = run_read_source(
                {"source_id": source_id, "keyword": "REPLY_LONG_TAIL", "limit": 100},
                state_store=self.store,
            )
            self.assertIn("REPLY_LONG_TAIL", read["content"])
            self.assertEqual(read["content_length"], fetched["content_length"])
            self.assertEqual(len(api.detail_ids()), 15)
        self.assertEqual(len(api.cookies), 16)
        self.assertTrue(all(cookies == self.cookies for cookies in api.cookies))
        for client in api.clients:
            client.http.aclose.assert_awaited_once()

    def test_slow_reply_page_preserves_current_fetch_and_complete_acquired_cache(self):
        api = XKitFixture()
        full_body = "Acquired full post. " * 30 + "POST_ACQUIRED_TAIL"
        full_reply = "Acquired full reply. " * 20 + "REPLY_ACQUIRED_TAIL"

        class Page(list):
            next_cursor = "next-page"

            async def next(self):
                api.events.append(("reply-next",))
                await asyncio.sleep(2)
                return []

        api.details["1"] = tweet("1", full_body, replies=Page([tweet("reply", full_reply)]))
        with api.patched():
            result = run_search_web(
                {"query": "OpenAI", "sources": ["twitter"], "count": 1},
                **self.options, scrape_chars=20_000, scrape_timeout=1,
            )
            self.assertEqual(result["errors"], [])
            self.assertTrue(result["results"][0]["body_available"])
            page = result["scrapes"][0]
            self.assertNotIn("error", page)
            self.assertFalse(page["truncated"])
            self.assertIn(full_body, page["markdown"])
            self.assertIn(full_reply, page["markdown"])
            self.assertIn("Replies incomplete", page["markdown"])
            self.assertIn(("reply-next",), api.events)
            source_id = result["results"][0]["source_id"]
            fetched = run_fetch_source(
                {"source_id": source_id, "full_content": True}, **self.options,
            )
            self.assertTrue(fetched["cache_hit"])
            self.assertEqual(fetched["body"], page["markdown"])
            read = run_read_source(
                {"source_id": source_id, "limit": 8_000}, state_store=self.store,
            )
            self.assertEqual(read["content"], page["markdown"])
            self.assertEqual(api.detail_ids(), ["1"])

    def test_initial_detail_timeout_still_reports_fetch_error(self):
        api = XKitFixture()
        api.detail_delay = 2
        with api.patched():
            result = run_search_web(
                {"query": "OpenAI", "sources": ["twitter"], "count": 1},
                **self.options, scrape_timeout=1,
            )
        self.assertEqual(len(result["results"]), 1)
        self.assertFalse(result["results"][0]["body_available"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["stage"], "fetch")
        self.assertRegex(result["errors"][0]["error"], "timeout|timed out|deadline")
        self.assertIn("error", result["scrapes"][0])
        self.assertEqual(api.detail_ids(), ["1"])

    def test_cookie_file_reaches_search_and_fetch_clients(self):
        api = XKitFixture()
        cookie_path = Path(self.directory.name) / "x-cookies.json"
        cookie_path.write_text(json.dumps(self.cookies), encoding="utf-8")
        options = {**self.options, "keys": {"twitter_cookies": str(cookie_path)}}
        with api.patched():
            result = run_search_web(
                {"query": "OpenAI", "sources": ["twitter"], "count": 1}, **options,
            )
        self.assertEqual(result["errors"], [])
        self.assertEqual(api.detail_ids(), ["1"])
        self.assertEqual(api.cookies, [self.cookies, self.cookies])

    def test_direct_x_url_forces_twitter_scraper_even_with_exa_selected(self):
        api = XKitFixture()
        api.details["1"] = tweet("1", "Direct full body " * 50 + "DIRECT_LONG_TAIL")
        with api.patched():
            result = run_fetch_source(
                {"url": "https://mobile.twitter.com/fixture/status/1", "backends": ["exa"], "max_chars": 40},
                **self.options,
            )
            self.assertEqual(result["backend"], "twitter")
            self.assertTrue(result["truncated"])
            self.assertEqual(len(result["body"]), 40)
            cached = run_fetch_source(
                {"source_id": result["source_id"], "full_content": True}, **self.options,
            )
            self.assertTrue(cached["cache_hit"])
            self.assertIn("DIRECT_LONG_TAIL", cached["body"])
        self.assertEqual(api.events, [("detail", "1")])
        self.assertEqual(api.cookies, [self.cookies])

    def test_detail_failure_keeps_candidate_and_exposes_redacted_fetch_error(self):
        api = XKitFixture(count=2)
        api.details["1"] = RuntimeError(
            "detail failed auth_token=fixture-auth-token csrf fixture-csrf-token"
        )
        with api.patched():
            result = run_search_web(
                {"query": "OpenAI", "sources": ["twitter"], "count": 2}, **self.options,
            )
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0]["content"], "💬0 ♥7 🔁2 Candidate excerpt 1")
        self.assertFalse(result["results"][0]["body_available"])
        self.assertTrue(result["results"][1]["body_available"])
        self.assertEqual(len(result["errors"]), 1)
        error = result["errors"][0]
        self.assertEqual(error["stage"], "fetch")
        self.assertEqual(error["url"], "https://x.com/fixture/status/1")
        self.assertIn("detail failed", error["error"])
        self.assertNotIn("fixture-auth-token", str(result))
        self.assertNotIn("fixture-csrf-token", str(result))
        self.assertCountEqual(api.detail_ids(), ["1", "2"])
        for client in api.clients:
            client.http.aclose.assert_awaited_once()

    def test_failed_direct_x_detail_does_not_fall_back_to_selected_exa(self):
        api = XKitFixture()
        api.details["1"] = RuntimeError("detail failed auth_token=fixture-auth-token")
        with api.patched(), self.assertRaisesRegex(ValueError, "detail failed") as raised:
            run_fetch_source(
                {"url": "https://x.com/fixture/status/1", "backends": ["exa"]}, **self.options,
            )
        self.assertNotIn("missing key", str(raised.exception))
        self.assertNotIn("fixture-auth-token", str(raised.exception))
        self.assertEqual(api.events, [("detail", "1")])

    def test_generic_provider_prefetch_cannot_bypass_authenticated_x_scraper(self):
        api = XKitFixture()
        provider = ProviderSpec(
            name="exa", public_name="exa", key_required=False,
            call=lambda _query, _config, _context, _key: [{
                "source": "exa", "url": "https://x.com/fixture/status/1",
                "title": "X post from generic search", "description": "Generic search excerpt",
                "scraped_content": "Generic incomplete provider body", "content_kind": "body",
            }],
        )
        with api.patched():
            result = run_search_web(
                {"query": "OpenAI", "sources": ["exa"], "count": 1},
                providers={"exa": provider}, **self.options,
            )
            self.assertEqual(result["errors"], [])
            page = result["scrapes"][0]
            self.assertEqual(page["via"], "twitter")
            self.assertIn("Fetched full body 1", page["markdown"])
            self.assertNotIn("Generic incomplete provider body", page["markdown"])
            cached = run_fetch_source(
                {"source_id": result["results"][0]["source_id"], "full_content": True}, **self.options,
            )
            self.assertIn("Fetched full body 1", cached["body"])
            self.assertNotIn("Generic incomplete provider body", cached["body"])
        self.assertEqual(api.events, [("detail", "1")])

    def test_old_x_search_and_generic_caches_are_refetched_once(self):
        for index, old_scope in enumerate(("", "a" * 64), start=1):
            with self.subTest(old_scope=old_scope):
                api = XKitFixture(count=2)
                source_id = f"src_old_{index}"
                url = f"https://x.com/fixture/status/{index}"
                SourceRegistry(self.store).register("resp_old", [{
                    "source_id": source_id, "url": url, "canonical_url": url,
                    "title": "Old X post", "content": "Old short preview",
                    "content_kind": "body", "providers": ["twitter"],
                    "body_available": True,
                }])
                cache = ContentStore(self.store)
                cache.put(
                    source_id, "Old short preview",
                    canonical_url=url if old_scope else "", cache_scope=old_scope,
                )
                with api.patched():
                    fetched = run_fetch_source(
                        {"source_id": source_id, "full_content": True}, **self.options,
                    )
                    self.assertFalse(fetched["cache_hit"])
                    self.assertEqual(fetched["backend"], "twitter")
                    self.assertIn(f"Fetched full body {index}", fetched["body"])
                    self.assertNotIn("Old short preview", fetched["body"])
                    second = run_fetch_source(
                        {"source_id": source_id, "full_content": True}, **self.options,
                    )
                    self.assertTrue(second["cache_hit"])
                    self.assertEqual(second["body"], fetched["body"])
                self.assertEqual(api.events, [("detail", str(index))])
                self.assertTrue(cache.get(source_id)["cache_scope"].startswith("twitter-detail-v1:"))

    def test_x_fixed_endpoint_fetch_bypasses_tun_dns_but_generic_urls_stay_guarded(self):
        api = XKitFixture()
        forbidden_resolver = mock.Mock(side_effect=AssertionError("X URL must not resolve through generic DNS validation"))
        with api.patched():
            fetched = run_fetch_source(
                {"url": "https://x.com/fixture/status/1", "backends": ["exa"]},
                **{**self.options, "url_resolver": forbidden_resolver},
            )
            self.assertEqual(fetched["backend"], "twitter")
            self.assertIn("Fetched full body 1", fetched["body"])
            forbidden_resolver.assert_not_called()
            self.assertEqual(api.events, [("detail", "1")])
            self.assertEqual(len(api.clients), 1)

            private_resolver = mock.Mock(return_value=["198.18.0.123"])
            with self.assertRaisesRegex(ValueError, "private"):
                run_fetch_source(
                    {"url": "https://evidence.example/article", "backends": ["exa"]},
                    **{**self.options, "url_resolver": private_resolver},
                )
            private_resolver.assert_called_once_with("evidence.example")
            self.assertEqual(api.events, [("detail", "1")])
            self.assertEqual(len(api.clients), 1)

    def test_ordinary_url_uses_generic_backend_without_twitter_credentials(self):
        api = XKitFixture()
        observed = []

        def record_actual_scraper(url, **kwargs):
            observed.append(kwargs)
            return scrape_url_smart(url, **kwargs)

        with api.patched(), self.assertRaisesRegex(ValueError, "missing key for backend: exa"):
            run_fetch_source(
                {"url": "https://evidence.example/article", "backends": ["exa"]},
                scraper=record_actual_scraper, **self.options,
            )
        self.assertEqual(len(observed), 1)
        self.assertNotIn("twitter_cookies", observed[0])
        self.assertEqual(api.clients, [])
        self.assertEqual(api.events, [])


if __name__ == "__main__":
    unittest.main()

"""X detail fetching: real XKit text fields, partial replies, and URL safety."""
import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from twikit.tweet import Tweet

from multi_search_mcp.src.scrape.scrapers import twitter


URL = "https://x.com/fixture/status/12345"
PUBLIC = lambda _host: ["104.244.42.1"]
COOKIES = {"auth_token": "fixture-token", "ct0": "fixture-csrf"}


def tweet(text="Ordinary post", *, note=None, replies=None, reply_count=0):
    # Use the installed library's properties: legacy text and note text really
    # differ here, so reading Tweet.text would fail the long-post regression.
    data = {"rest_id": "12345", "legacy": {
        "full_text": text, "reply_count": reply_count, "favorite_count": 7, "retweet_count": 3,
    }}
    if note is not None:
        data["note_tweet"] = {"note_tweet_results": {"result": {"text": note}}}
    result = Tweet(None, data, SimpleNamespace(screen_name="fixture"))
    result.replies = replies
    return result


class Page(list):
    def __init__(self, rows, next_page=None, *, error=None, delay=0, cursor=None):
        super().__init__(rows)
        self.next_cursor = cursor or ("next" if next_page is not None or error or delay else None)
        self.next_calls = 0
        self.next_page, self.error, self.delay = next_page, error, delay

    async def next(self):
        self.next_calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.next_page


def client_fixture(full=None):
    return SimpleNamespace(
        get_tweet_by_id=mock.AsyncMock(return_value=full or tweet()),
        set_cookies=mock.Mock(), http=SimpleNamespace(aclose=mock.AsyncMock()),
    )


class TwitterScraperTests(unittest.TestCase):
    def fetch(self, full=None, *, client=None, **kwargs):
        client = client or client_fixture(full)
        factory = mock.Mock(return_value=client)
        kwargs.setdefault("cookies", COOKIES)
        kwargs.setdefault("url_resolver", PUBLIC)
        with mock.patch.dict(sys.modules, {"xkit": SimpleNamespace(Client=factory)}):
            result = twitter.scrape_url_twitter(kwargs.pop("url", URL), **kwargs)
        return result, client, factory

    def test_long_post_and_reply_use_real_xkit_full_text_without_cropping(self):
        body = "Long post\n" + "正文 " * 1000 + "\nOriginal post tail"
        reply_body = "Long reply\n" + "comment " * 600 + "\nOriginal reply tail"
        reply = tweet("Reply preview…", note=reply_body)
        full = tweet("Post preview…", note=body, replies=[reply], reply_count=1)
        self.assertNotEqual(full.text, full.full_text)
        self.assertNotEqual(reply.text, reply.full_text)
        result, client, _factory = self.fetch(full)
        self.assertNotIn("error", result)
        self.assertIn(body, result["markdown"])
        self.assertIn(reply_body, result["markdown"])
        self.assertNotIn("preview…", result["markdown"])
        self.assertNotIn("Replies incomplete", result["markdown"])
        self.assertEqual(result["length"], len(result["markdown"]))
        self.assertEqual(result["via"], "twitter")
        self.assertFalse(result["truncated"])
        client.get_tweet_by_id.assert_awaited_once_with("12345")
        client.http.aclose.assert_awaited_once()

    def test_ordinary_post_without_note_retains_body(self):
        result, _client, _factory = self.fetch(tweet("Ordinary body\nSecond line"))
        self.assertIn("Ordinary body\nSecond line", result["markdown"])
        self.assertIn(f"[Original post]({URL}) · @fixture · ♥7 · 🔁3 · 💬0", result["markdown"])
        self.assertEqual(result["title"], "@fixture: Ordinary body")
        self.assertFalse(result["truncated"])

    def test_comments_follow_next_cursor_until_terminal_page(self):
        last = Page([tweet("Second reply")])
        first = Page([tweet("First reply")], next_page=last)
        result, _client, _factory = self.fetch(tweet(replies=first, reply_count=2))
        self.assertIn("First reply", result["markdown"])
        self.assertIn("Second reply", result["markdown"])
        self.assertNotIn("Replies incomplete", result["markdown"])
        self.assertEqual(first.next_calls, 1)
        self.assertEqual(last.next_calls, 0)

    def test_reply_limit_marks_known_omissions_but_not_exact_terminal_twenty(self):
        for count, cursor in ((20, None), (21, None), (20, "more")):
            with self.subTest(count=count, cursor=cursor):
                page = Page([tweet(f"Reply number {index}") for index in range(count)], cursor=cursor)
                result, _client, _factory = self.fetch(tweet(replies=page, reply_count=count))
                self.assertEqual(result["markdown"].count("  - @fixture"), 20)
                self.assertEqual("Replies incomplete" in result["markdown"], bool(count > 20 or cursor))
                self.assertEqual(page.next_calls, 0)
                self.assertFalse(result["truncated"])

    def test_limit_applies_across_pages(self):
        second = Page([tweet(f"Later reply {index}") for index in range(10)])
        first = Page([tweet(f"Early reply {index}") for index in range(15)], next_page=second)
        result, _client, _factory = self.fetch(tweet(replies=first, reply_count=25))
        self.assertEqual(result["markdown"].count("  - @fixture"), 20)
        self.assertIn("Later reply 4", result["markdown"])
        self.assertNotIn("Later reply 5", result["markdown"])
        self.assertIn("replies limit 20 reached", result["markdown"])

    def test_failed_page_retains_acquired_text_and_scrubs_cookie_values(self):
        page = Page([tweet("Acquired reply")], error=RuntimeError(
            "failed auth_token=fixture-token; csrf fixture-csrf"))
        result, client, _factory = self.fetch(tweet("Acquired body", replies=page))
        self.assertNotIn("error", result)
        self.assertIn("Acquired body", result["markdown"])
        self.assertIn("Acquired reply", result["markdown"])
        self.assertIn("Replies incomplete", result["markdown"])
        self.assertNotIn("fixture-token", str(result))
        self.assertNotIn("fixture-csrf", str(result))
        self.assertFalse(result["truncated"])
        client.http.aclose.assert_awaited_once()

    def test_page_timeout_preserves_acquired_content_and_closes_session(self):
        page = Page([tweet("Reply before timeout")], delay=1)
        result, client, _factory = self.fetch(tweet("Body before timeout", replies=page), timeout=0.3)
        self.assertIn("Body before timeout", result["markdown"])
        self.assertIn("Reply before timeout", result["markdown"])
        self.assertIn("Replies incomplete", result["markdown"])
        self.assertIn("timed out", result["markdown"])
        self.assertIn("comment budget exhausted", result["markdown"])
        self.assertFalse(result["truncated"])
        client.http.aclose.assert_awaited_once()

    def test_comment_timeout_reserves_cleanup_time_after_detail(self):
        real_wait_for = asyncio.wait_for
        for timeout, detail_time, expected in ((1, 0, 0.9), (10, 0, 9.75), (1, 0.8, 0.18)):
            with self.subTest(timeout=timeout, detail_time=detail_time):
                clock = [100.0]
                timeouts = []
                page = Page([tweet("First reply")], next_page=Page([]))
                full = tweet("Acquired body", replies=page)
                client = client_fixture(full)

                async def detail(_id):
                    clock[0] += detail_time
                    return full

                async def capture_wait_for(awaitable, timeout):
                    timeouts.append(timeout)
                    return await real_wait_for(awaitable, timeout)

                client.get_tweet_by_id.side_effect = detail
                with mock.patch.object(twitter, "time", SimpleNamespace(monotonic=lambda: clock[0])), \
                     mock.patch.object(twitter.asyncio, "wait_for", side_effect=capture_wait_for):
                    result, _client, _factory = self.fetch(client=client, timeout=timeout)
                self.assertNotIn("error", result)
                self.assertEqual(len(timeouts), 2)
                self.assertAlmostEqual(timeouts[0], timeout)
                self.assertAlmostEqual(timeouts[1], expected)
                client.http.aclose.assert_awaited_once()

    def test_reported_reply_count_and_missing_next_page_are_marked(self):
        for page, reported in ((None, 3), (Page([tweet("One reply")]), 2),
                               (Page([tweet("One reply")], cursor="more"), 1)):
            with self.subTest(reported=reported, has_page=page is not None):
                result, _client, _factory = self.fetch(tweet(replies=page, reply_count=reported))
                self.assertIn("Replies incomplete", result["markdown"])

    def test_pagination_shares_one_overall_timeout(self):
        last = Page([tweet("Reply beyond the deadline")])
        second = Page([tweet("Reply inside the deadline")], next_page=last, delay=0.06)
        first = Page([tweet("First reply")], next_page=second, delay=0.06)
        result, client, _factory = self.fetch(tweet(replies=first), timeout=0.1)
        self.assertIn("Reply inside the deadline", result["markdown"])
        self.assertNotIn("Reply beyond the deadline", result["markdown"])
        self.assertIn("timed out", result["markdown"])
        client.http.aclose.assert_awaited_once()

    def test_initial_detail_failure_is_error_and_closes_session(self):
        client = client_fixture()
        client.get_tweet_by_id.side_effect = RuntimeError("auth_token=fixture-token fixture-csrf")
        result, _client, _factory = self.fetch(client=client)
        self.assertIn("error", result)
        self.assertNotIn("markdown", result)
        self.assertNotIn("fixture-token", str(result))
        self.assertNotIn("fixture-csrf", str(result))
        client.http.aclose.assert_awaited_once()

    def test_initial_detail_timeout_is_error(self):
        async def delayed(_id):
            await asyncio.sleep(1)
        client = client_fixture()
        client.get_tweet_by_id.side_effect = delayed
        result, _client, _factory = self.fetch(client=client, timeout=0.05)
        self.assertIn("timed out", result["error"])
        self.assertNotIn("markdown", result)
        client.http.aclose.assert_awaited_once()

    def test_empty_body_is_error_even_when_replies_exist(self):
        for text in ("", " \n\t", None):
            with self.subTest(text=text):
                result, client, _factory = self.fetch(tweet(text, replies=[tweet("A reply")]))
                self.assertIn("empty", result["error"])
                self.assertNotIn("markdown", result)
                client.http.aclose.assert_awaited_once()

    def test_empty_reply_marks_incomplete_without_losing_post(self):
        result, _client, _factory = self.fetch(tweet("Main body", replies=[tweet("")]))
        self.assertIn("Main body", result["markdown"])
        self.assertIn("Replies incomplete", result["markdown"])

    def test_request_timeout_uses_smaller_deadline(self):
        result, client, factory = self.fetch(timeout=60, deadline=time.monotonic()+10)
        self.assertNotIn("error", result)
        self.assertGreater(factory.call_args.kwargs["timeout"], 9)
        self.assertLessEqual(factory.call_args.kwargs["timeout"], 10)
        client.http.aclose.assert_awaited_once()

    def test_expired_deadline_prevents_cookie_loading_and_client_creation(self):
        with mock.patch.object(twitter, "load_twitter_cookies") as load:
            result, _client, factory = self.fetch(deadline=time.monotonic()-1)
        self.assertIn("deadline", result["error"])
        factory.assert_not_called()
        load.assert_not_called()

    def test_cookies_support_dict_explicit_path_and_default_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.json"
            path.write_text(json.dumps(COOKIES), encoding="utf-8")
            for cookies in (COOKIES, str(path), ""):
                with self.subTest(cookie_type=type(cookies).__name__), \
                     mock.patch("multi_search_mcp.src.support.xkit.os.path.expanduser", return_value=str(path)):
                    result, client, _factory = self.fetch(cookies=cookies)
                    self.assertNotIn("error", result)
                    client.set_cookies.assert_called_once_with(COOKIES)

    def test_invalid_cookie_file_does_not_create_client(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.json"
            for content in ("[]", "invalid JSON"):
                path.write_text(content, encoding="utf-8")
                result, _client, factory = self.fetch(cookies=str(path))
                self.assertIn("error", result)
                factory.assert_not_called()

    def test_missing_xkit_is_explicit_installation_error(self):
        with mock.patch.dict(sys.modules, {"xkit": None}):
            result = twitter.scrape_url_twitter(URL, cookies=COOKIES, url_resolver=PUBLIC)
        self.assertIn("XKit-py unavailable", result["error"])
        self.assertNotIn("markdown", result)

    def test_cookie_setup_failure_still_closes_session(self):
        client = client_fixture()
        client.set_cookies.side_effect = ValueError("cookie fixture-token invalid")
        result, _client, _factory = self.fetch(client=client)
        self.assertIn("error", result)
        self.assertNotIn("fixture-token", str(result))
        client.get_tweet_by_id.assert_not_called()
        client.http.aclose.assert_awaited_once()

    def test_recognizes_only_explicit_x_and_twitter_domains(self):
        for host in ("x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
            self.assertTrue(twitter.is_twitter_url(f"https://{host}/fixture/status/12345"), host)
        for url in ("https://x.com.example.org/a/status/12345", "https://notx.com/a/status/12345",
                    "https://api.x.com/a/status/12345", "https://t.co/id", "ftp://x.com/a/status/12345",
                    "https://[invalid", "https://x.com@evil.example/a/status/12345"):
            self.assertFalse(twitter.is_twitter_url(url), url)

    def test_supported_post_url_variants(self):
        for url in ("https://x.com/fixture/status/12345?lang=en", "https://twitter.com/i/web/status/12345",
                    "https://mobile.twitter.com/i/status/12345", "https://www.x.com/a/status/12345/",
                    "https://x.com/a/status/12345/photo/1", "https://x.com/a/status/12345/video/2?s=20"):
            with self.subTest(url=url):
                result, client, _factory = self.fetch(url=url)
                self.assertNotIn("error", result)
                self.assertEqual(result["url"], url)
                client.get_tweet_by_id.assert_awaited_once_with("12345")

    def test_tun_fake_ip_resolver_is_unused_for_fixed_xkit_endpoints(self):
        resolver = mock.Mock(return_value=["198.18.0.11"])
        result, client, _factory = self.fetch(url_resolver=resolver)
        self.assertNotIn("error", result)
        resolver.assert_not_called()
        client.get_tweet_by_id.assert_awaited_once_with("12345")
        client.set_cookies.assert_called_once_with(COOKIES)

    def test_validator_strips_outer_whitespace_without_rewriting_post_url(self):
        url = "https://www.twitter.com:443/fixture/status/12345/photo/1?lang=en"
        self.assertEqual(twitter.validate_twitter_url(f" \n{url}\t "), url)

    def test_unsafe_or_nonpost_urls_never_load_cookies_or_create_client(self):
        cases = ["https://user:password@x.com/a/status/12345",
                 "https://@x.com/a/status/12345",
                 "https://x.com:444/a/status/12345",
                 "https://x.com:bad/a/status/12345",
                 "https://x.com:99999/a/status/12345",
                 "https://x.com/fixture",
                 "https://x.com/search?q=test",
                 "https://x.com/a/status/not-a-number",
                 "https://x.com/a/status/12345/anything",
                 "https://x.com.example.org/a/status/12345",
                 "https://x.com./a/status/12345",
                 "https://127.0.0.1/a/status/12345",
                 "https://x.com/a/status/12\t345",
                 "ftp://x.com/a/status/12345",
                 "https://[invalid/a/status/12345"]
        for url in cases:
            with self.subTest(url=url), mock.patch.object(twitter, "load_twitter_cookies") as load:
                result, _client, factory = self.fetch(url=url)
                self.assertIn("error", result)
                factory.assert_not_called()
                load.assert_not_called()
                with self.assertRaises(twitter.UrlSecurityError):
                    twitter.validate_twitter_url(url)


if __name__ == "__main__":
    unittest.main()

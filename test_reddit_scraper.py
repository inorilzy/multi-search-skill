"""Reddit domain routing, content fidelity, and anonymous-session boundaries."""
import copy
from concurrent.futures import ThreadPoolExecutor
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.scrape.scrapers import _eddrit, reddit
from multi_search_mcp.src.service import FetchSourceRequest, run_fetch_source
from multi_search_mcp.src.state.state_store import StateStore


URL = "https://www.reddit.com/r/python/comments/abc123/example/"
PUBLIC = lambda host: ["151.101.1.140"]


def response_data():
    return [
        {"data": {"children": [{"kind": "t3", "data": {
            "id": "abc123", "title": "A real post", "selftext": "Full body `&amp;` " + "正文 " * 80,
            "is_self": True, "url": URL,
        }}]}},
        {"data": {"children": [
            {"kind": "t1", "data": {"author": "alice", "body": "Parent comment", "replies": {
                "data": {"children": [{"kind": "t1", "data": {
                    "author": "bob", "body": "Nested comment", "replies": "",
                }}]}}}},
            {"kind": "more", "data": {"count": 25}},
        ]}},
    ]


def token_response(token="test-token", ttl=3600):
    return mock.Mock(status_code=200,
                     headers={"content-type": "application/json", "x-reddit-loid": "loid", "x-reddit-session": "session"},
                     json=mock.Mock(return_value={"access_token": token, "expires_in": ttl}))


class RedditRoutingTests(unittest.TestCase):
    def test_unknown_backend_is_still_rejected_for_reddit(self):
        with mock.patch.object(reddit, "get_post_json") as fetch:
            result = scrape_url_smart(URL, backends=("typo",), url_resolver=PUBLIC)
        self.assertEqual(result["error"], "unknown scrape backend: typo")
        fetch.assert_not_called()

    def test_reddit_overrides_generic_planner_backends_without_api_keys(self):
        with mock.patch.object(reddit, "get_post_json", return_value=response_data()), \
             mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_jina") as jina, \
             mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_exa") as exa:
            result = scrape_url_smart(URL, backends=("exa", "jina"), url_resolver=PUBLIC)
        self.assertEqual(result["via"], "reddit")
        self.assertIn("Nested comment", result["markdown"])
        jina.assert_not_called()
        exa.assert_not_called()

    def test_non_reddit_keeps_existing_backend_selection(self):
        for host in ("example.com", "reddit.com.example.org", "notreddit.com", "i.redd.it"):
            with self.subTest(host=host), \
                 mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_reddit") as dedicated, \
                 mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_jina", return_value={"markdown": "ordinary page"}) as generic:
                result = scrape_url_smart(f"https://{host}/", backends=("jina",), url_resolver=PUBLIC)
                self.assertEqual(result["markdown"], "ordinary page")
                dedicated.assert_not_called()
                generic.assert_called_once()

    def test_reddit_failure_is_not_hidden_by_generic_backend(self):
        with mock.patch.object(reddit, "get_post_json", side_effect=_eddrit.EddritError("Reddit returned HTTP 403")), \
             mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_jina") as generic:
            result = scrape_url_smart(URL, url_resolver=PUBLIC)
        self.assertIn("403", result["error"])
        self.assertNotIn("markdown", result)
        generic.assert_not_called()

    def test_private_resolution_and_credentials_are_rejected_before_auth(self):
        for url, resolver in ((URL, lambda host: ["127.0.0.1"]),
                              (URL.replace("https://", "https://user:password@"), PUBLIC)):
            with self.subTest(url=url), mock.patch.object(reddit, "get_post_json") as fetch:
                self.assertIn("error", scrape_url_smart(url, url_resolver=resolver))
                fetch.assert_not_called()

    def test_supported_permalink_variants_and_comment_focus(self):
        urls = [URL, URL.replace("www.", "old."), URL.replace("www.", "new."),
                "https://reddit.com/comments/abc123", "https://redd.it/abc123",
                "https://reddit.com/r/python/comments/abc123/.json"]
        for url in urls:
            with self.subTest(url=url):
                post_id, _ = reddit._post_target(url)
                self.assertEqual(post_id, "abc123")
        post_id, params = reddit._post_target(URL + "def456/?sort=new&redirect=https://example.org")
        self.assertEqual((post_id, params["comment"], params["sort"]), ("abc123", "def456", "new"))
        self.assertNotIn("redirect", params)

    def test_unsupported_urls_do_not_send_auth(self):
        for path in ("/r/python/", "/r/python/s/sharetoken", "/wiki/api", "/login", "/comments/../"):
            with self.subTest(path=path), mock.patch.object(reddit, "get_post_json") as fetch:
                result = scrape_url_smart("https://www.reddit.com" + path, url_resolver=PUBLIC)
                self.assertIn("Unsupported Reddit URL", result["error"])
                fetch.assert_not_called()

    def test_expired_deadline_never_fetches(self):
        with mock.patch.object(reddit, "get_post_json") as fetch:
            result = scrape_url_smart(URL, deadline=time.monotonic()-1, url_resolver=PUBLIC)
        self.assertIn("deadline", result["error"])
        fetch.assert_not_called()

    def test_transport_error_never_exposes_credentials(self):
        with mock.patch.object(reddit, "get_post_json", side_effect=RuntimeError("secret-proxy-password")):
            result = scrape_url_smart(URL, url_resolver=PUBLIC)
        self.assertIn("RuntimeError", result["error"])
        self.assertNotIn("secret-proxy-password", result["error"])


class RedditContentTests(unittest.TestCase):
    def test_body_nested_comments_and_partial_marker_preserve_markdown(self):
        title, text = reddit._render(response_data(), "abc123")
        self.assertEqual(title, "A real post")
        self.assertIn("Full body `&amp;`", text)
        self.assertIn("- u/alice:", text)
        self.assertIn("  - u/bob:", text)
        self.assertIn("not the complete discussion", text)

    def test_media_urls_are_links_and_are_not_fetched(self):
        data = response_data()
        post = data[0]["data"]["children"][0]["data"]
        post.update(is_self=False, selftext="", url="https://example.org/article",
                    media_metadata={"img": {"s": {"u": "https://i.redd.it/image.png"}}})
        _, text = reddit._render(data, "abc123")
        self.assertIn("https://example.org/article", text)
        self.assertIn("https://i.redd.it/image.png", text)

    def test_block_page_or_wrong_post_cannot_be_success(self):
        for data in ({"content": "You've been blocked by network security"}, [], response_data()):
            with self.subTest(data_type=type(data).__name__):
                with self.assertRaises(_eddrit.EddritError):
                    reddit._render(data, "differentid")

    def test_comment_count_is_bounded_and_marked(self):
        data = response_data()
        item = {"kind": "t1", "data": {"author": "test", "body": "one comment", "replies": ""}}
        data[1]["data"]["children"] = [copy.deepcopy(item) for _ in range(105)]
        _, text = reddit._render(data, "abc123")
        self.assertEqual(text.count("one comment"), 100)
        self.assertIn("not the complete discussion", text)

    def test_fetch_source_caches_complete_body_even_for_short_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StateStore(Path(temp)/"state.sqlite")
            with mock.patch.object(reddit, "get_post_json", return_value=response_data()) as fetch:
                short = run_fetch_source(FetchSourceRequest(url=URL, max_chars=30),
                                         state_store=store, keys={}, config={}, url_resolver=PUBLIC)
                full = run_fetch_source(FetchSourceRequest(source_id=short["source_id"], max_chars=2000),
                                        state_store=store, keys={}, config={}, url_resolver=PUBLIC)
            self.assertEqual(short["backend"], "reddit")
            self.assertEqual(len(short["body"]), 30)
            self.assertTrue(short["truncated"])
            self.assertIn("Nested comment", full["body"])
            self.assertTrue(full["cache_hit"])
            fetch.assert_called_once()


class AnonymousAuthTests(unittest.TestCase):
    def test_concurrent_requests_share_one_token_exchange(self):
        auth = _eddrit.AnonymousAuth()
        def exchange(*args, **kwargs):
            time.sleep(0.03)
            return token_response()
        session = mock.Mock(post=mock.Mock(side_effect=exchange))
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: auth.headers(session, time.monotonic()+2, None), range(4)))
        self.assertTrue(all(value == values[0] for value in values))
        session.post.assert_called_once()

    def test_token_cache_reuses_identity_and_renews_after_expiry(self):
        auth = _eddrit.AnonymousAuth()
        session = mock.Mock()
        session.post.return_value = token_response()
        end = time.monotonic()+10
        one = auth.headers(session, end, None)
        two = auth.headers(session, end, None)
        self.assertEqual(one, two)
        session.post.assert_called_once()
        one["Authorization"] = "changed caller copy"
        self.assertNotEqual(auth.headers(session, end, None)["Authorization"], one["Authorization"])
        auth._expires_at = 0
        session.post.return_value = token_response("fresh-token")
        self.assertEqual(auth.headers(session, end, None)["Authorization"], "Bearer fresh-token")
        self.assertEqual(session.post.call_count, 2)

    def test_proxy_change_and_401_invalidation_discard_old_credentials(self):
        auth = _eddrit.AnonymousAuth()
        session = mock.Mock()
        session.post.return_value = token_response()
        end = time.monotonic()+10
        auth.headers(session, end, None)
        headers = auth.headers(session, end, "http://proxy.example")
        self.assertEqual(session.post.call_count, 2)
        auth.invalidate(headers, end)
        auth.headers(session, end, "http://proxy.example")
        self.assertEqual(session.post.call_count, 3)

    def test_non_json_and_auth_error_never_cache_credentials(self):
        for response in (mock.Mock(status_code=403, headers={}),
                         mock.Mock(status_code=200, headers={"content-type": "text/html"}),
                         token_response(ttl=-1)):
            with self.subTest(status=response.status_code):
                auth = _eddrit.AnonymousAuth()
                session = mock.Mock(post=mock.Mock(return_value=response))
                with self.assertRaises(_eddrit.EddritError):
                    auth.headers(session, time.monotonic()+10, None)
                self.assertFalse(auth._headers)

    def test_deadline_includes_lock_wait(self):
        auth = _eddrit.AnonymousAuth()
        auth._lock.acquire()
        session = mock.Mock()
        try:
            with self.assertRaises(TimeoutError):
                auth.headers(session, time.monotonic()+0.02, None)
        finally:
            auth._lock.release()
        session.post.assert_not_called()

    def test_transport_validates_destination_and_does_not_follow_redirects(self):
        from curl_cffi.requests import Session
        with mock.patch("curl_cffi.requests.Session", autospec=Session) as factory, \
             mock.patch.object(_eddrit, "_auth", _eddrit.AnonymousAuth()):
            session = factory.return_value.__enter__.return_value
            session.post.return_value = token_response()
            session.get.return_value = mock.Mock(status_code=302, headers={"location": "https://attacker.invalid"})
            with self.assertRaisesRegex(_eddrit.EddritError, "302"):
                _eddrit.get_post_json("abc123", {}, time.monotonic()+10, resolver=PUBLIC)
            self.assertFalse(factory.call_args.kwargs["allow_redirects"])
            self.assertEqual(session.get.call_args.args[0], "https://oauth.reddit.com/comments/abc123.json")
            self.assertEqual(session.get.call_args.kwargs["headers"]["Cookie"], "")
            session.get.assert_called_once()

    def test_401_invalidates_token_without_retrying_the_failed_request(self):
        with mock.patch("curl_cffi.requests.Session") as factory, \
             mock.patch.object(_eddrit, "_auth", _eddrit.AnonymousAuth()):
            session = factory.return_value.__enter__.return_value
            session.post.return_value = token_response()
            session.get.side_effect = [mock.Mock(status_code=401, headers={}),
                                      mock.Mock(status_code=200, headers={"content-type": "application/json"},
                                                json=mock.Mock(return_value=response_data()))]
            with self.assertRaisesRegex(_eddrit.EddritError, "401"):
                _eddrit.get_post_json("abc123", {}, time.monotonic()+10, resolver=PUBLIC)
            session.get.assert_called_once()
            data = _eddrit.get_post_json("abc123", {}, time.monotonic()+10, resolver=PUBLIC)
            self.assertEqual(data[0]["data"]["children"][0]["data"]["id"], "abc123")
            self.assertEqual(session.post.call_count, 2)


if __name__ == "__main__":
    unittest.main()

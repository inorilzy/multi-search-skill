"""Reddit domain routing, content fidelity, and anonymous-session boundaries."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.scrape.scrapers import _reddit_transport, reddit
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
        with mock.patch.object(reddit, "get_post_json", side_effect=_reddit_transport.RedditError("Reddit returned HTTP 403")), \
             mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_jina") as generic:
            result = scrape_url_smart(URL, url_resolver=PUBLIC)
        self.assertIn("403", result["error"])
        self.assertEqual(result["markdown"], "")
        self.assertEqual(result["via"], "reddit")
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
                with self.assertRaises(_reddit_transport.RedditError):
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


class FakeResponse:
    def __init__(self, body, content_type="application/json"):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = {"Content-Type": content_type}
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return self.body if size < 0 else self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RedditTransportTests(unittest.TestCase):
    def _get(self, response=None, side_effect=None):
        with mock.patch.object(_reddit_transport, "urlopen_retry",
                               return_value=response, side_effect=side_effect) as opened:
            try:
                data = _reddit_transport.get_post_json(
                    "abc123", {"raw_json": 1, "limit": 100}, time.monotonic() + 10, resolver=PUBLIC,
                )
            except Exception as exc:  # returned for assertions below
                data = exc
        return data, opened

    def test_request_is_anonymous_and_identifies_this_tool(self):
        data, opened = self._get(FakeResponse(response_data()))
        self.assertEqual(data[0]["data"]["children"][0]["data"]["id"], "abc123")
        opened.assert_called_once()
        request = opened.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://www.reddit.com/comments/abc123.json?raw_json=1&limit=100",
        )
        headers = {name.lower(): value for name, value in request.header_items()}
        self.assertTrue(headers["user-agent"].startswith("multi-search/"))
        for forbidden in ("authorization", "cookie", "x-reddit-loid", "x-reddit-session",
                          "x-reddit-device-id", "client-vendor-id"):
            self.assertNotIn(forbidden, headers)
        self.assertNotIn("android", headers["user-agent"].lower())

    def test_no_token_exchange_scope_or_official_client_identity_remains(self):
        source = Path(_reddit_transport.__file__).read_text(encoding="utf-8")
        for forbidden in ("pii", "scopes", "access-token", "ANDROID_CLIENT_ID", "ohXpoqrZYub1kg",
                          "curl_cffi", 'environ.get("PROXY")'):
            self.assertNotIn(forbidden, source)

    def test_uses_the_shared_transport_deadline_and_redirect_validation(self):
        end = time.monotonic() + 10
        with mock.patch.object(_reddit_transport, "urlopen_retry",
                               return_value=FakeResponse(response_data())) as opened:
            _reddit_transport.get_post_json("abc123", {}, end, resolver=PUBLIC)
        kwargs = opened.call_args.kwargs
        self.assertEqual(kwargs["deadline"], end)
        # Redirects use the shared no-DNS host rules; no resolver is injected.
        self.assertNotIn("redirect_resolver", kwargs)
        # Proxy choice is the shared urllib opener's: HTTP(S)_PROXY / ALL_PROXY / NO_PROXY.
        self.assertNotIn("extra_handlers", kwargs)

    def test_http_errors_block_pages_and_bad_json_are_errors(self):
        import email.message
        import io
        import urllib.error

        http_error = urllib.error.HTTPError(
            "https://www.reddit.com/comments/abc123.json", 429, "Too Many Requests",
            email.message.Message(), io.BytesIO(b"secret body"),
        )
        cases = (
            ({"side_effect": http_error}, "HTTP 429"),
            ({"response": FakeResponse(b"<html>blocked</html>", "text/html")}, "non-JSON"),
            ({"response": FakeResponse(b"{not json")}, "invalid JSON"),
        )
        for kwargs, message in cases:
            with self.subTest(message=message):
                error, _ = self._get(**kwargs)
                self.assertIsInstance(error, _reddit_transport.RedditError)
                self.assertIn(message, str(error))
                self.assertNotIn("secret body", str(error))

    def test_response_size_is_bounded(self):
        response = FakeResponse(b"[" + b" " * _reddit_transport.MAX_RESPONSE_BYTES + b"]")
        error, _ = self._get(response)
        self.assertIsInstance(error, _reddit_transport.RedditError)
        self.assertEqual(response.read_sizes, [_reddit_transport.MAX_RESPONSE_BYTES + 1])

    def test_private_destination_is_rejected_before_any_request(self):
        with mock.patch.object(_reddit_transport, "urlopen_retry") as opened:
            with self.assertRaises(Exception):
                _reddit_transport.get_post_json(
                    "abc123", {}, time.monotonic() + 10, resolver=lambda host: ["127.0.0.1"],
                )
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()

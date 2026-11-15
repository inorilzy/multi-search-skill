"""SerpApi can pass Google's own redirect links through as ``link``; they must become destinations."""
import io
import json
import unittest
import urllib.error
from unittest import mock

from multi_search_mcp.src.search import search_runner
from multi_search_mcp.src.search.candidates import query_provider_status
from multi_search_mcp.src.search.searchers import serpapi

OPAQUE = "https://www.google.com/url?opi=89978449&q=CAESaQHEIkXX&sa=U&ved=x&usg=y"
GOTO = "https://www.google.com/goto?url=CAESbgHEIkXX"


def api_response(links):
    result = mock.MagicMock()
    result.__enter__.return_value = result
    result.read.return_value = json.dumps({"organic_results": [
        {"title": str(index), "link": link} for index, link in enumerate(links)
    ]}).encode()
    return result


def redirect_response(location):
    result = mock.MagicMock()
    result.__enter__.return_value = result
    result.headers = {"Location": location}
    return result


def bad_request(url):
    return urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(b""))


def refresh_page(target):
    # Google's 200 "loading" page: no Location, a meta refresh to a second /goto hop.
    result = mock.MagicMock()
    result.__enter__.return_value = result
    result.headers = {}
    result.read.return_value = (
        f'<!doctype html><html><head><title>Google</title>'
        f'<meta content="5;url={target}" http-equiv="refresh"></head><body></body></html>'
    ).encode()
    return result


class SerpApiRedirectTests(unittest.TestCase):
    def run_search(self, links, redirects):
        resolved = []
        # A list answers successive requests for the same URL in order.
        pending = {url: list(target) if isinstance(target, list) else [target] for url, target in redirects.items()}

        def http(request, timeout, **options):
            url = getattr(request, "full_url", request)
            if url.startswith("https://serpapi.com/"):
                return api_response(links)
            resolved.append(url)
            answers = pending[url]
            target = answers.pop(0) if len(answers) > 1 else answers[0]
            if isinstance(target, Exception):
                raise target
            if isinstance(target, mock.MagicMock):
                return target
            return redirect_response(target)

        with mock.patch.object(serpapi, "urlopen_retry", side_effect=http), \
                mock.patch.object(serpapi.time, "sleep") as sleep:
            rows = serpapi.search_serpapi("python asyncio", "fixture-key")
        self.sleeps = [call.args[0] for call in sleep.call_args_list]
        return [row["url"] for row in rows], resolved

    def test_opaque_google_redirects_resolve_to_their_location(self):
        urls, resolved = self.run_search(
            [OPAQUE, GOTO, "https://example.com/direct"],
            {OPAQUE: "https://iproyal.com/blog/python-asyncio-tutorial/", GOTO: "https://docs.python.org/3/"},
        )
        self.assertEqual(urls, [
            "https://iproyal.com/blog/python-asyncio-tutorial/",
            "https://docs.python.org/3/",
            "https://example.com/direct",
        ])
        self.assertEqual(sorted(resolved), sorted([OPAQUE, GOTO]), "direct links are not requested")

    def test_a_loading_page_is_followed_to_its_goto_hop_after_a_wait(self):
        # Measured: a fresh /goto hop answers 400 at once and 302 two seconds later.
        hop = "https://www.google.com/goto?url=CAEScgHEIkXX"
        urls, resolved = self.run_search(
            [OPAQUE],
            {OPAQUE: refresh_page("/goto?url=CAEScgHEIkXX"),
             hop: "https://www.pickl.ai/blog/asyncio-in-python/"},
        )
        self.assertEqual(urls, ["https://www.pickl.ai/blog/asyncio-in-python/"])
        self.assertEqual(resolved, [OPAQUE, hop])
        self.assertEqual(self.sleeps, [2.0], "the hop is asked once, after the first wait")

    def test_a_plain_destination_in_the_query_needs_no_request(self):
        link = "https://www.google.com/url?q=https://example.org/page%3Fa%3D1&sa=U"
        urls, resolved = self.run_search([link], {})
        self.assertEqual(urls, ["https://example.org/page?a=1"])
        self.assertEqual(resolved, [])

    def test_an_unresolvable_redirect_keeps_the_original_link(self):
        urls, _ = self.run_search(
            [OPAQUE, GOTO],
            {OPAQUE: OSError("network down"), GOTO: "https://www.google.com/url?q=CAESagain"},
        )
        self.assertEqual(urls, [OPAQUE, GOTO])

    def test_a_goto_hop_that_never_answers_keeps_the_original_link(self):
        hop = "https://www.google.com/goto?url=CAEScgHEIkXX"
        urls, resolved = self.run_search(
            [OPAQUE], {OPAQUE: refresh_page("/goto?url=CAEScgHEIkXX"), hop: bad_request(hop)},
        )
        self.assertEqual(urls, [OPAQUE])
        # The slow ones only accept after 8-23 s: one wait, then the search moves on.
        self.assertEqual(resolved, [OPAQUE, hop])
        self.assertEqual(self.sleeps, [2.0])


ANSWER_ROWS = [
    {"source": "tavily_answer", "answer": "text", "content_kind": "answer"},
    {"source": "tavily", "url": "https://example.com/a", "title": "a"},
    {"source": "baidu_answer", "answer": "text", "content_kind": "answer"},
    {"source": "baidu", "url": "https://example.com/b", "title": "b"},
]


class AnswerRowsTests(unittest.TestCase):
    """``*_answer`` rows ride on their provider's request; they are not providers of their own."""

    def test_the_progress_stream_reports_answer_rows_under_their_provider(self):
        # The desktop search flow draws one searcher row per provider_result event.
        with mock.patch.object(search_runner.debug_log, "event") as event:
            search_runner._log_provider_results("query", ANSWER_ROWS, {"tavily": 900, "baidu": 7400}, 7400)
        results = {call.kwargs["source"]: call.kwargs for call in event.call_args_list
                   if call.args == ("provider_result",)}
        self.assertEqual(sorted(results), ["baidu", "tavily"])
        self.assertEqual(results["tavily"]["status"], "ok")
        self.assertEqual(results["tavily"]["hit_count"], 1)

    def test_answer_rows_are_not_listed_as_their_own_providers(self):
        status = query_provider_status([("query", ANSWER_ROWS)])
        self.assertEqual([row["source"] for row in status], ["baidu", "tavily"])
        self.assertTrue(all(row["raw_hits"] == 1 for row in status))


if __name__ == "__main__":
    unittest.main()

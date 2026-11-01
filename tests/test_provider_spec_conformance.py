"""Requests and response handling follow each provider's documented API.

Specs are saved under docs/<provider>/ with their source URLs.
"""
import json
import unittest
from unittest import mock

from multi_search_mcp.src.search.searchers import baidu, firecrawl, serpapi


def response(payload):
    result = mock.MagicMock()
    result.__enter__.return_value = result
    result.read.return_value = json.dumps(payload).encode()
    return result


class BaiduAuthHeaderTests(unittest.TestCase):
    # docs/baidu/common-headers.md: Authorization: Bearer <API Key>
    def test_web_summary_uses_the_documented_authorization_header(self):
        sent = []

        def capture(req, **_kwargs):
            sent.append(req)
            return response({"choices": [], "references": []})

        with mock.patch.object(baidu, "urlopen_retry", side_effect=capture):
            baidu.search_baidu("python asyncio", "fixture-key", count=3)
        headers = {name.lower(): value for name, value in sent[0].header_items()}
        self.assertEqual(headers["authorization"], "Bearer fixture-key")
        self.assertNotIn("x-appbuilder-authorization", headers)


class SerpApiEmptyResultsTests(unittest.TestCase):
    # docs/serpapi/api-status-and-error-codes.md: empty results are still Success.
    EMPTY = {
        "search_metadata": {"status": "Success"},
        "error": "Google Light hasn't returned any results for this query.",
    }

    def test_no_results_is_zero_hits_not_an_error(self):
        with mock.patch.object(serpapi, "urlopen_retry", return_value=response(self.EMPTY)):
            rows = serpapi.search_serpapi("no such term", "fixture-key", count=10)
        self.assertEqual(rows, [])

    def test_empty_later_page_keeps_earlier_hits_without_an_error_row(self):
        first = {"search_metadata": {"status": "Success"}, "organic_results": [
            {"title": str(i), "link": f"https://example.com/{i}"} for i in range(10)
        ]}
        with mock.patch.object(serpapi, "urlopen_retry",
                               side_effect=[response(first), response(self.EMPTY)]):
            rows = serpapi.search_serpapi("rare term", "fixture-key", count=20)
        self.assertEqual(len(rows), 10)
        self.assertFalse(any("error" in row for row in rows))

    def test_a_real_error_status_is_still_reported(self):
        failed = {"search_metadata": {"status": "Error"}, "error": "Invalid API key."}
        with mock.patch.object(serpapi, "urlopen_retry", return_value=response(failed)):
            rows = serpapi.search_serpapi("q", "fixture-key", count=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["error"], "Invalid API key.")
        self.assertEqual(rows[0]["kind"], "invalid")


class FirecrawlHighlightsTests(unittest.TestCase):
    # docs/firecrawl/search-highlights.md: highlights default to true.
    def test_search_requests_the_plain_snippet(self):
        sent = []

        def capture(req, **_kwargs):
            sent.append(json.loads(req.data))
            return response({"success": True, "data": {"web": []}})

        with mock.patch.object(firecrawl, "urlopen_retry", side_effect=capture):
            firecrawl.search_firecrawl("python asyncio", "fixture-key", count=3)
        self.assertIs(sent[0]["highlights"], False)


if __name__ == "__main__":
    unittest.main()

import io
import json
import unittest
import urllib.error
import urllib.parse
from unittest import mock

from multi_search_mcp.src.search.searchers.v2ex import search_v2ex
from multi_search_mcp.src.support.models import search_content


def _hit(**overrides):
    hit = {
        "_id": "123",
        "_score": None,
        "_source": {
            "id": 123,
            "title": "Python example",
            "content": "# Example\n\nUse `python` with <em>literal markup</em>.\n" + "body " * 100,
            "created": "2026-09-01T01:02:03.000Z",
            "member": "example",
            "replies": 2,
        },
        "highlight": {"content": ["Use <em>python</em> &amp; asyncio."]},
    }
    hit.update(overrides)
    return hit


class V2exApiTests(unittest.TestCase):
    def _search(self, payload, **kwargs):
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        with mock.patch(
            "multi_search_mcp.src.search.searchers.v2ex.urlopen_retry",
            return_value=response,
        ) as request:
            rows = search_v2ex("Python 中文 & async", **kwargs)
        return rows, request

    def test_anonymous_request_encodes_query_and_uses_relevance_without_date_filters(self):
        rows, request = self._search({"hits": []}, count=10, timeout=3.5)

        self.assertEqual(rows, [])
        req = request.call_args.args[0]
        self.assertEqual(req.get_method(), "GET")
        url = urllib.parse.urlsplit(req.full_url)
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "www.sov2ex.com", "/api/search"))
        self.assertEqual(urllib.parse.parse_qs(url.query), {
            "q": ["Python 中文 & async"], "from": ["0"], "size": ["10"], "sort": ["sumup"],
        })
        self.assertEqual(request.call_args.kwargs, {"timeout": 3.5})
        self.assertEqual({name.lower() for name, _ in req.header_items()}, {"user-agent", "accept"})

    def test_count_is_clamped_to_api_range(self):
        for count, expected in ((-1, "1"), (0, "1"), (50, "50"), (90, "50")):
            with self.subTest(count=count):
                _, request = self._search({"hits": []}, count=count)
                params = urllib.parse.parse_qs(urllib.parse.urlsplit(request.call_args.args[0].full_url).query)
                self.assertEqual(params["size"], [expected])

    def test_normalization_discards_indexed_body_and_cleans_highlights(self):
        hit = _hit()
        rows, _ = self._search({"hits": [hit], "timed_out": False})

        row = rows[0]
        self.assertEqual(row["source"], "v2ex")
        self.assertEqual(row["url"], "https://www.v2ex.com/t/123")
        self.assertEqual(row["title"], hit["_source"]["title"])
        self.assertEqual(row["description"], "Use python & asyncio.")
        self.assertNotIn("scraped_content", row)
        self.assertNotIn("body", row)
        self.assertEqual(row["content_kind"], "excerpt")
        self.assertEqual(row["published_at"], hit["_source"]["created"])
        self.assertEqual(row["author"], "example")
        self.assertEqual(row["reply_count"], 2)
        self.assertNotIn("score", row)
        content = search_content(row)
        self.assertEqual(content.body, "")
        self.assertEqual(content.snippet, "Use python & asyncio.")
        self.assertEqual(content.snippet_kind, "excerpt")

    def test_native_score_only_keeps_finite_numbers(self):
        for score, retained in ((None, False), (3.5, True), (0, True), (True, False), ("3", False), (float("nan"), False), (float("inf"), False)):
            with self.subTest(score=score):
                rows, _ = self._search({"hits": [_hit(_score=score)]})
                self.assertEqual("score" in rows[0], retained)

    def test_no_highlights_never_use_indexed_body_as_excerpt(self):
        hit = _hit(highlight={})
        rows, _ = self._search({"hits": [hit]})
        self.assertEqual(rows[0]["description"], "")
        self.assertEqual(rows[0]["content_kind"], "metadata")
        self.assertNotIn("scraped_content", rows[0])
        self.assertEqual(search_content(rows[0]).body, "")

    def test_indexed_body_is_ignored_regardless_of_value_or_shape(self):
        for body in (None, "INDEXED BODY MUST NOT BE USED", [], {}, False, 42):
            with self.subTest(body=body):
                hit = _hit()
                hit["_source"]["content"] = body
                rows, _ = self._search({"hits": [hit]})
                self.assertNotIn("error", rows[0])
                self.assertNotIn("scraped_content", rows[0])
                self.assertEqual(rows[0]["description"], "Use python & asyncio.")
                self.assertEqual(search_content(rows[0]).body, "")

    def test_highlight_excerpt_is_bounded_to_300_characters(self):
        rows, _ = self._search({"hits": [_hit(highlight={"content": ["<em>python</em> " * 100]})]})
        self.assertEqual(rows[0]["description"], ("python " * 100).strip()[:300])
        self.assertEqual(rows[0]["content_kind"], "excerpt")
        self.assertNotIn("scraped_content", rows[0])

    def test_reply_and_postscript_highlights_are_labeled_excerpts_not_body(self):
        for field, expected in (("reply_list.content", "Reply: python reply"), ("postscript_list.content", "Postscript: python reply")):
            with self.subTest(field=field):
                hit = _hit(highlight={field: ["<em>python</em> reply"]})
                hit["_source"]["content"] = ""
                rows, _ = self._search({"hits": [hit]})
                self.assertEqual(rows[0]["description"], expected)
                self.assertEqual(rows[0]["content_kind"], "excerpt")
                self.assertEqual(search_content(rows[0]).body, "")

    def test_no_body_or_highlights_is_metadata_candidate(self):
        hit = _hit(highlight={})
        del hit["_source"]["content"]
        rows, _ = self._search({"hits": [hit]})
        self.assertEqual(rows[0]["content_kind"], "metadata")
        self.assertEqual(rows[0]["url"], "https://www.v2ex.com/t/123")

    def test_document_id_is_used_when_source_id_is_absent(self):
        hit = _hit()
        del hit["_source"]["id"]
        rows, _ = self._search({"hits": [hit]})
        self.assertEqual(rows[0]["url"], "https://www.v2ex.com/t/123")

    def test_invalid_topic_ids_are_explicit_errors(self):
        for topic_id in (None, "", "abc", "12/34", "../x", 0, -1, True, 1.5):
            with self.subTest(topic_id=topic_id):
                hit = _hit()
                hit["_source"]["id"] = topic_id
                rows, _ = self._search({"hits": [hit]})
                self.assertIn("valid numeric topic id", rows[0]["error"])

    def test_partial_timeout_preserves_hits_and_reports_error(self):
        rows, _ = self._search({"hits": [_hit()], "timed_out": True})
        self.assertEqual(rows[0]["url"], "https://www.v2ex.com/t/123")
        self.assertIn("timed out", rows[1]["error"])

    def test_empty_timeout_is_error_not_success(self):
        rows, _ = self._search({"hits": [], "timed_out": True})
        self.assertIn("timed out", rows[0]["error"])

    def test_malformed_response_and_provider_errors_are_explicit(self):
        for payload in ([], None, {}, {"hits": None}, {"hits": {}}, {"error": "unavailable"}):
            with self.subTest(payload=payload):
                rows, _ = self._search(payload)
                self.assertIn("error", rows[0])

    def test_bad_hit_does_not_hide_valid_hit_or_fail_silently(self):
        for bad_hit in (None, {}, {"_source": []}, {"_source": {"id": 4, "title": False}}, _hit(highlight=[]), _hit(highlight={"content": "bad"})):
            with self.subTest(bad_hit=bad_hit):
                rows, _ = self._search({"hits": [bad_hit, _hit()]})
                self.assertIn("error", rows[0])
                self.assertEqual(rows[1]["url"], "https://www.v2ex.com/t/123")

    def test_transport_and_json_errors_are_reported(self):
        for error in (
            urllib.error.HTTPError("https://www.sov2ex.com/api/search", 429, "Too Many Requests", {}, None),
            TimeoutError("request timed out"),
        ):
            with self.subTest(error=error), mock.patch(
                "multi_search_mcp.src.search.searchers.v2ex.urlopen_retry", side_effect=error,
            ):
                self.assertIn("error", search_v2ex("python")[0])
        with mock.patch(
            "multi_search_mcp.src.search.searchers.v2ex.urlopen_retry", return_value=io.BytesIO(b"not JSON"),
        ):
            self.assertIn("error", search_v2ex("python")[0])


if __name__ == "__main__":
    unittest.main()

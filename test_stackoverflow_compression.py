import gzip
import json
import unittest
import zlib
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.searchers import stackoverflow


class _FakeResponse:
    def __init__(self, body, headers=None):
        self._body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


class StackOverflowCompressionTests(unittest.TestCase):
    @staticmethod
    def _stackoverflow_json_body(items=None):
        if items is None:
            items = [{
                "title": "Fixture question",
                "link": "https://stackoverflow.com/questions/1",
                "score": 5,
                "answer_count": 2,
                "view_count": 99,
                "is_answered": True,
                "tags": ["python"],
            }]
        return json.dumps({"items": items}).encode("utf-8")

    def test_compressed_responses_preserve_plain_response_rows(self):
        body = self._stackoverflow_json_body([
            {
                "title": "How &amp; why?",
                "link": "https://stackoverflow.com/questions/1",
                "score": 5,
                "answer_count": 2,
                "view_count": 99,
                "is_answered": True,
                "tags": ["python", "testing"],
            },
            {
                "title": "Second result",
                "link": "https://stackoverflow.com/questions/2",
                "score": 1,
                "answer_count": 0,
                "view_count": 10,
                "tags": [],
            },
        ])
        responses = (
            ("plain", body, {}),
            ("gzip", gzip.compress(body), {"Content-Encoding": "gzip"}),
            ("deflate", zlib.compress(body), {"Content-Encoding": "deflate"}),
        )
        expected = [
            (
                "How & why?",
                "https://stackoverflow.com/questions/1",
                "score 5 · 2 answers · 99 views · answered · tags: python, testing",
                "metadata",
            ),
            (
                "Second result",
                "https://stackoverflow.com/questions/2",
                "score 1 · 0 answers · 10 views",
                "metadata",
            ),
        ]

        for name, encoded, headers in responses:
            with self.subTest(encoding=name), mock.patch.object(
                stackoverflow,
                "urlopen_retry",
                return_value=_FakeResponse(encoded, headers),
            ):
                rows = stackoverflow.search_stackoverflow("fixture", count=2)

            actual = [
                (row.get("title"), row.get("url"), row.get("description"), row.get("content_kind"))
                for row in rows
            ]
            self.assertEqual(actual, expected)

    def test_missing_content_encoding_assumes_gzip_and_requests_compression(self):
        body = self._stackoverflow_json_body()
        captured = []

        def open_url(request, **_kwargs):
            captured.append(request)
            return _FakeResponse(gzip.compress(body))

        with mock.patch.object(stackoverflow, "urlopen_retry", side_effect=open_url):
            rows = stackoverflow.search_stackoverflow("fixture", count=1)

        self.assertEqual(rows[0]["url"], "https://stackoverflow.com/questions/1")
        self.assertEqual(
            dict(captured[0].header_items())["Accept-encoding"], "gzip, deflate"
        )

    def test_proxy_decompressed_json_survives_gzip_content_encoding(self):
        with mock.patch.object(
            stackoverflow,
            "urlopen_retry",
            return_value=_FakeResponse(
                self._stackoverflow_json_body(), {"Content-Encoding": "gzip"}
            ),
        ):
            rows = stackoverflow.search_stackoverflow("fixture", count=1)

        self.assertEqual(rows[0]["url"], "https://stackoverflow.com/questions/1")

    def test_malformed_compression_invalid_json_and_api_errors_are_explicit(self):
        cases = (
            (b"\x1f\x8b\x08broken", {"Content-Encoding": "gzip"}),
            (b"not-deflate", {"Content-Encoding": "deflate"}),
            (b"{not-json", {"Content-Encoding": "identity"}),
            (json.dumps({"error_message": "bad request"}).encode("utf-8"), {}),
        )

        for body, headers in cases:
            with self.subTest(headers=headers), mock.patch.object(
                stackoverflow,
                "urlopen_retry",
                return_value=_FakeResponse(body, headers),
            ):
                rows = stackoverflow.search_stackoverflow("fixture")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source"], "stackoverflow")
            self.assertTrue(rows[0].get("error"))

    def test_registry_and_search_runner_retain_stackoverflow_for_selected_and_named_routes(self):
        body = gzip.compress(self._stackoverflow_json_body())
        provider = build_provider_registry()["stackoverflow"]

        for request_kwargs in (
            {"sources": ["stackoverflow"]},
            {"route": "dev"},
            {"route": "all"},
        ):
            with self.subTest(request_kwargs=request_kwargs), mock.patch.object(
                stackoverflow,
                "urlopen_retry",
                return_value=_FakeResponse(body, {"Content-Encoding": "gzip"}),
            ):
                response = service.run_search_web(
                    service.SearchWebRequest(
                        query="fixture",
                        count=1,
                        timeout=5,
                        use_state=False,
                        **request_kwargs,
                    ),
                    providers={"stackoverflow": provider},
                    keys={},
                    config={},
                    scraper=lambda _url, **_kwargs: {
                        "markdown": "fixture body",
                        "via": "fixture",
                    },
                )

            self.assertIn("stackoverflow", response["diagnostics"]["route_sources"])
            self.assertEqual(
                [row["url"] for row in response["results"]],
                ["https://stackoverflow.com/questions/1"],
            )


if __name__ == "__main__":
    unittest.main()

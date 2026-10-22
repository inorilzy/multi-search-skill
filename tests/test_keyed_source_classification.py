"""Key-pool terminal rows keep the chosen provider's controlled classification."""
import io
import unittest
import urllib.error
from unittest import mock

from multi_search_mcp.src.search import search_runner
from multi_search_mcp.src.search.searchers import tavily
from multi_search_mcp.src.search.search_runner import run_keyed_source
from multi_search_mcp.src.state.key_state import BasicKeyManager, classify_error


KEYS = ["synthetic-classify-key-1", "synthetic-classify-key-2"]


def _http_error(code, body=b""):
    return urllib.error.HTTPError(
        "https://api.tavily.com/search", code, "fixture", {}, io.BytesIO(body)
    )


def _tavily_rows(code, body=b""):
    def call(api_key):
        with mock.patch.object(tavily, "urlopen_retry", side_effect=_http_error(code, body)):
            return tavily.search_tavily("fixture", api_key)
    return call


def _run(call):
    return run_keyed_source(
        "tavily", list(KEYS), call, key_manager=BasicKeyManager(), provider="tavily",
    )


class KeyedSourceClassificationTests(unittest.TestCase):
    def test_quota_432_terminal_row_keeps_quota_exhausted(self):
        rows = _run(_tavily_rows(432, b'{"detail":{"error":"Plan usage limit exceeded"}}'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "quota_exhausted")
        self.assertEqual(rows[0]["origin"], "provider")
        self.assertIn("key pool exhausted after 2 key(s)", rows[0]["error"])
        self.assertEqual(classify_error(rows[0]["error"], kind=rows[0]["kind"]), "quota_exhausted")

    def test_quota_433_terminal_row_keeps_quota_exhausted(self):
        rows = _run(_tavily_rows(433, b'{"detail":{"error":"quota"}}'))
        self.assertEqual(rows[0]["kind"], "quota_exhausted")

    def test_rate_limit_429_terminal_row_keeps_rate_limit(self):
        rows = _run(_tavily_rows(429, b'{"detail":{"error":"slow down"}}'))
        self.assertEqual(rows[0]["kind"], "rate_limit")
        self.assertEqual(rows[0]["origin"], "provider")

    def test_auth_401_terminal_row_keeps_invalid(self):
        rows = _run(_tavily_rows(401, b'{"detail":{"error":"bad key"}}'))
        self.assertEqual(rows[0]["kind"], "invalid")
        self.assertEqual(rows[0]["origin"], "provider")

    def test_unstructured_error_has_no_classification_fields(self):
        def call(api_key):
            return [{"source": "tavily", "error": f"plain failure for {api_key}"}]
        rows = _run(call)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("kind", rows[0])
        self.assertNotIn("origin", rows[0])

    def test_secret_is_scrubbed_and_other_provider_fields_are_not_copied(self):
        secret = KEYS[0]

        def call(api_key):
            return [{
                "source": "tavily",
                "error": f"HTTP Error 429: rejected {api_key}",
                "origin": "provider",
                "kind": "rate_limit",
                "raw_key": api_key,
                "debug": {"token": api_key},
            }]

        rows = _run(call)
        self.assertEqual(set(rows[0]), {"source", "error", "origin", "kind"})
        self.assertNotIn(secret, repr(rows))
        self.assertNotIn(KEYS[1], repr(rows))

    def test_target_origin_row_is_not_chosen_over_provider_row(self):
        def call(api_key):
            return [
                {"source": "tavily", "error": "target page blocked", "origin": "target", "kind": "target"},
                {"source": "tavily", "error": "HTTP Error 432: quota", "origin": "provider", "kind": "quota_exhausted"},
            ]
        rows = _run(call)
        self.assertEqual(rows[0]["kind"], "quota_exhausted")
        self.assertIn("HTTP Error 432", rows[0]["error"])

    def test_partial_hit_then_quota_keeps_hit_and_classification(self):
        calls = []
        hit = {"source": "tavily", "title": "ok", "url": "https://93.184.216.34/a", "description": "d"}

        def call(api_key):
            calls.append(api_key)
            if api_key == KEYS[0]:
                # Mixed retryable row: a usable hit plus a quota error from the same key.
                return [dict(hit), {"source": "tavily", "error": "HTTP Error 432: quota", "origin": "provider", "kind": "quota_exhausted"}]
            return [{"source": "tavily", "error": "HTTP Error 432: quota", "origin": "provider", "kind": "quota_exhausted"}]

        rows = _run(call)
        self.assertEqual(calls, KEYS)
        self.assertEqual([row["url"] for row in rows if row.get("url")], [hit["url"]])
        terminal = [row for row in rows if row.get("error")]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(terminal[0]["kind"], "quota_exhausted")


if __name__ == "__main__":
    unittest.main()

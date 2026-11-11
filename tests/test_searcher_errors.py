"""Stack Overflow, Baidu and Twitter searcher error-contract regressions.

These cover the review findings around provider-specific failure handling:
Stack Exchange quota exhaustion must not resend a query that already produced
results, Baidu HTTP 200 error bodies must be classified and redacted, and
Twitter must report missing cookies and short rate-limit budgets explicitly.
"""
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from multi_search_mcp.src.search.searchers import baidu, stackoverflow
from multi_search_mcp.src.search.searchers.twitter import search_twitter
from multi_search_mcp.src.search.search_runner import run_keyed_source
from multi_search_mcp.src.state.key_state import (
    QUOTA_EXHAUSTED,
    BasicKeyManager,
    SQLiteKeyManager,
    key_id_for,
)
from multi_search_mcp.src.state.state_store import StateStore


KEYS = ["synthetic-searcher-key-01", "synthetic-searcher-key-02"]
SO_ITEM = {
    "title": "Fixture question",
    "link": "https://stackoverflow.com/questions/1",
    "score": 5,
    "answer_count": 2,
    "view_count": 99,
    "is_answered": True,
    "tags": ["python"],
    "creation_date": 1700000000,
}
BAIDU_ENDPOINT = "/v2/ai_search/web_summary"


def response(payload):
    result = mock.MagicMock()
    result.__enter__.return_value = result
    result.read.return_value = json.dumps(payload).encode()
    result.headers = Message()
    return result


def baidu_rows(payload, api_key=""):
    return baidu._rows_from_response(
        payload, endpoint=BAIDU_ENDPOINT, max_references=1, api_key=api_key,
    )


class StackOverflowQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="searcher-errors-")
        self.addCleanup(self.temp.cleanup)
        self.manager = SQLiteKeyManager(StateStore(Path(self.temp.name) / "state.sqlite"))

    def test_quota_zero_with_results_requests_once_and_records_quota(self):
        calls = []

        def call(api_key):
            calls.append(api_key)
            with mock.patch.object(
                stackoverflow, "urlopen_retry",
                return_value=response({"items": [SO_ITEM], "quota_remaining": 0}),
            ):
                return stackoverflow.search_stackoverflow("fixture", api_key=api_key)

        rows = run_keyed_source(
            "stackoverflow", list(KEYS), call,
            key_manager=self.manager, provider="stackexchange",
        )

        self.assertEqual(calls, [KEYS[0]])
        self.assertEqual(
            [row["url"] for row in rows if row.get("url")], [SO_ITEM["link"]],
        )
        state = {row["key_id"]: row for row in self.manager.status_rows("stackexchange")}
        self.assertEqual(
            state[key_id_for("stackexchange", KEYS[0])]["status"], QUOTA_EXHAUSTED,
        )


class StackOverflowPublishedAtTests(unittest.TestCase):
    def test_question_rows_map_creation_date_to_published_at(self):
        with mock.patch.object(
            stackoverflow, "urlopen_retry",
            return_value=response({"items": [SO_ITEM]}),
        ):
            rows = stackoverflow.search_stackoverflow("fixture")

        self.assertEqual(
            rows[0]["published_at"],
            datetime.fromtimestamp(SO_ITEM["creation_date"], timezone.utc).isoformat(),
        )


class BaiduHttp200ErrorTests(unittest.TestCase):
    def test_http_200_error_body_redacts_the_api_key(self):
        secret = "synthetic-baidu-key-012345"
        payload = {
            "error": {
                "code": "invalid_iam_token",
                "message": f"IAM Certification failed for {secret}",
                "type": "invalid_request_error",
            },
            "id": "req-1",
        }

        row = baidu_rows(payload, api_key=secret)[0]

        self.assertNotIn(secret, row["error"])
        self.assertEqual(row["error_type"], "invalid")

    def test_http_200_chinese_auth_rate_limit_and_quota_errors_are_classified(self):
        cases = (
            ({"error": {"code": "AUTH", "message": "鉴权失败：密钥无效"}}, "invalid"),
            ({"error": {"code": "RATE", "message": "请求频率过高，已被限流"}}, "rate_limit"),
            ({"error": {"code": "QUOTA", "message": "调用额度已用尽"}}, "quota_exhausted"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected):
                row = baidu_rows(payload)[0]
                self.assertEqual(row["error_type"], expected)
                self.assertEqual(row["error_origin"], "provider")

    def test_baidu_auth_and_quota_errors_rotate_keys(self):
        cases = (
            (
                {"error": {
                    "code": "invalid_iam_token",
                    "message": "IAM Certification failed",
                    "type": "invalid_request_error",
                }},
                "invalid",
            ),
            (
                {"error": {
                    "code": "coding_plan_hour_quota_exceeded",
                    "message": "Coding Plan hour quota has been exceeded",
                    "type": "quota_exceeded",
                }},
                "quota_exhausted",
            ),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected):
                calls = []

                def call(api_key):
                    calls.append(api_key)
                    with mock.patch.object(
                        baidu, "urlopen_retry", return_value=response(payload),
                    ):
                        return baidu.search_baidu("fixture", api_key)

                rows = run_keyed_source(
                    "baidu", list(KEYS), call,
                    key_manager=BasicKeyManager(), provider="baidu",
                )

                self.assertEqual(calls, KEYS)
                self.assertEqual(rows[0]["error_type"], expected)


class TwitterCredentialAndRateLimitTests(unittest.TestCase):
    def test_missing_cookie_is_missing_key_without_full_home_path(self):
        with TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}):
            rows = search_twitter("fixture")

        self.assertEqual(rows[0]["error_type"], "missing_key")
        self.assertIn("~/.mcp-twikit/cookies.json", rows[0]["error"])
        self.assertNotIn(home, rows[0]["error"])

    def test_429_with_insufficient_budget_is_rate_limit_not_timeout(self):
        client = SimpleNamespace(
            search_tweet=mock.AsyncMock(side_effect=RuntimeError("429 Too Many Requests")),
            set_cookies=mock.Mock(),
            http=SimpleNamespace(aclose=mock.AsyncMock()),
        )
        with mock.patch.dict(
            sys.modules,
            {"xkit": SimpleNamespace(Client=mock.Mock(return_value=client))},
        ):
            rows = search_twitter("fixture", cookies={}, timeout=0.05)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("error_type"), "rate_limit")
        self.assertIn("429", rows[0]["error"])
        self.assertNotIn("timeout", rows[0]["error"].lower())


if __name__ == "__main__":
    unittest.main()

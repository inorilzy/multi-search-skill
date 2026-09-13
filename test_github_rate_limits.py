import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from multi_search_mcp.src.search.search_runner import run_keyed_source
from multi_search_mcp.src.search.searchers import github
from multi_search_mcp.src.state.key_state import COOLDOWN, SQLiteKeyManager
from multi_search_mcp.src.state.state_store import StateStore


KEY = "fixture-github-rate-limit-token"
PAYLOAD = {
    "items": [{
        "full_name": "fixture/repository",
        "html_url": "https://github.com/fixture/repository",
        "description": "Repository excerpt",
        "stargazers_count": 12,
    }],
}


class TrackingBody(io.BytesIO):
    def __init__(self, value):
        super().__init__(value)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class AdvancingBody(TrackingBody):
    def __init__(self, value, clock):
        super().__init__(value)
        self.clock = clock

    def read(self, size=-1):
        self.read_sizes.append(size)
        self.clock[0] = 101
        return self.getvalue()[:size]


class FailingBody:
    def __init__(self):
        self.read_sizes = []
        self.closed = False

    def read(self, size=-1):
        self.read_sizes.append(size)
        raise OSError("fixture body read failed")

    def close(self):
        self.closed = True


def response(payload=PAYLOAD):
    return io.BytesIO(json.dumps(payload).encode())


def http_error(status, reason, body, headers=None):
    return HTTPError(
        "https://api.github.com/search/repositories",
        status,
        reason,
        headers or {},
        body,
    )


class GitHubRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.network_guard = mock.patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("unexpected real HTTP request"),
        )
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)
        self.dns_guard = mock.patch(
            "socket.getaddrinfo",
            side_effect=AssertionError("unexpected real DNS lookup"),
        )
        self.dns_guard.start()
        self.addCleanup(self.dns_guard.stop)

    def call_adapter(self, error, *, token=KEY, deadline=None):
        with mock.patch.object(github, "urlopen_retry", side_effect=error):
            return github.search_github_repos("fixture", token=token, timeout=1, deadline=deadline)[0]

    def test_primary_403_uses_headers_and_structured_rate_limit_contract(self):
        body = TrackingBody(b'{"message":"API rate limit exceeded"}')
        result = self.call_adapter(
            http_error(
                403,
                "Forbidden",
                body,
                {
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-reset": "1893456000",
                },
            )
        )

        self.assertEqual(result["error_type"], "rate_limit")
        self.assertTrue(result["rate_limited"])
        self.assertEqual(result["error_origin"], "provider")
        self.assertIn("API rate limit exceeded", result["error"])
        self.assertNotIn(KEY, json.dumps(result))
        self.assertEqual(body.read_sizes[0], 4096)
        self.assertTrue(body.closed)

    def test_secondary_403_uses_explicit_body_signal(self):
        result = self.call_adapter(
            http_error(
                403,
                "Forbidden",
                io.BytesIO(b'{"message":"You have exceeded a secondary rate limit."}'),
                {"retry-after": "60"},
            )
        )

        self.assertEqual(result["error_type"], "rate_limit")
        self.assertTrue(result["rate_limited"])
        self.assertIn("secondary rate limit", result["error"])

    def test_429_is_rate_limit_without_relying_on_error_text(self):
        result = self.call_adapter(http_error(429, "Too Many Requests", None))

        self.assertEqual(result["error_type"], "rate_limit")
        self.assertTrue(result["rate_limited"])

    def test_auth_and_permission_403_are_not_rate_limits(self):
        for status, reason, message in (
            (401, "Unauthorized", "Bad credentials"),
            (403, "Forbidden", "Resource not accessible by integration"),
        ):
            with self.subTest(status=status):
                result = self.call_adapter(
                    http_error(status, reason, io.BytesIO(json.dumps({"message": message}).encode()))
                )
                self.assertEqual(result["error_type"], "invalid")
                self.assertNotIn("rate_limited", result)

    def test_ambiguous_or_malformed_errors_are_not_rate_limits(self):
        cases = (
            (403, "Forbidden", b"please try again later", "invalid"),
            (500, "Internal Server Error", b'{"message":"rate limit exceeded"}', "error"),
            (500, "Internal Server Error", b"not-json", "error"),
        )
        for status, reason, body, expected_type in cases:
            with self.subTest(status=status, body=body):
                result = self.call_adapter(http_error(status, reason, io.BytesIO(body)))
                self.assertEqual(result["error_type"], expected_type)
                self.assertNotIn("rate_limited", result)

    def test_error_body_read_is_bounded_and_failures_are_explicit(self):
        body = TrackingBody(b'{"message":"' + b"x" * 20_000 + b'"}')
        result = self.call_adapter(
            http_error(
                403,
                "Forbidden",
                body,
                {"x-ratelimit-remaining": "0"},
            )
        )
        self.assertLessEqual(body.read_sizes[0], 4096)
        self.assertEqual(result["error_type"], "rate_limit")

        failing_body = FailingBody()
        result = self.call_adapter(
            http_error(
                403,
                "Forbidden",
                failing_body,
                {"x-ratelimit-remaining": "0"},
            )
        )
        self.assertLessEqual(failing_body.read_sizes[0], 4096)
        self.assertIn("error body unavailable", result["error"])
        self.assertEqual(result["error_type"], "rate_limit")
        self.assertTrue(failing_body.closed)

        unknown_body = FailingBody()
        result = self.call_adapter(http_error(403, "Forbidden", unknown_body))
        self.assertEqual(result["error_type"], "error")
        self.assertNotIn("rate_limited", result)

    def test_expired_deadline_skips_error_body_read(self):
        body = TrackingBody(b'{"message":"API rate limit exceeded"}')
        clock = iter((99, 101))
        with mock.patch.object(github.time, "monotonic", side_effect=lambda: next(clock)):
            result = self.call_adapter(
                http_error(
                    403,
                    "Forbidden",
                    body,
                    {"x-ratelimit-remaining": "0"},
                ),
                deadline=100,
            )

        self.assertEqual(body.read_sizes, [])
        self.assertEqual(result["error_type"], "rate_limit")
        self.assertIn("error body unavailable", result["error"])

    def test_error_body_read_drops_body_when_deadline_expires_during_read(self):
        clock = [99]
        body = AdvancingBody(b'{"message":"secondary rate limit"}', clock)
        with mock.patch.object(github.time, "monotonic", side_effect=lambda: clock[0]):
            result = self.call_adapter(
                http_error(403, "Forbidden", body, {"retry-after": "60"}),
                deadline=100,
            )

        self.assertEqual(body.read_sizes, [4096])
        self.assertIn("error body unavailable (deadline exceeded)", result["error"])
        self.assertEqual(result["error_type"], "rate_limit")

    def test_keyed_runner_redacts_error_body_in_result_and_state(self):
        with tempfile.TemporaryDirectory(prefix="github-rate-limit-redaction-") as temp:
            store = StateStore(Path(temp) / "state.sqlite")
            manager = SQLiteKeyManager(store)
            body = io.BytesIO(json.dumps({
                "message": f"API rate limit exceeded for {KEY}",
            }).encode())
            with mock.patch.object(
                github,
                "urlopen_retry",
                side_effect=http_error(
                    403,
                    "Forbidden",
                    body,
                    {"x-ratelimit-remaining": "0"},
                ),
            ):
                result = run_keyed_source(
                    "github-repos",
                    [KEY],
                    lambda token: github.search_github_repos("fixture", token=token),
                    provider="github",
                    key_manager=manager,
                )

            visible = json.dumps(result) + json.dumps(manager.status_rows("github"))
            self.assertNotIn(KEY, visible)
            self.assertEqual(manager.status_rows("github")[0]["last_error_type"], "rate_limit")

    def test_gh_error_keeps_explicit_rate_limit_classification(self):
        with mock.patch.object(
            github,
            "_run_gh",
            return_value=(1, "", "HTTP 403: You have exceeded a secondary rate limit."),
        ):
            result = github.search_github_repos("fixture", token="", timeout=1)[0]

        self.assertEqual(result["error_type"], "rate_limit")
        self.assertTrue(result["rate_limited"])

    def test_three_rate_limits_cool_then_success_without_invalidating_token(self):
        with tempfile.TemporaryDirectory(prefix="github-rate-limit-tests-") as temp:
            store = StateStore(Path(temp) / "state.sqlite")
            manager = SQLiteKeyManager(store)
            failures = [
                http_error(
                    403,
                    "Forbidden",
                    io.BytesIO(b'{"message":"API rate limit exceeded"}'),
                    {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1893456000"},
                ),
                http_error(
                    403,
                    "Forbidden",
                    io.BytesIO(b'{"message":"You have exceeded a secondary rate limit."}'),
                    {"retry-after": "60"},
                ),
                http_error(429, "Too Many Requests", None),
            ]
            for failure in failures:
                with mock.patch.object(github, "urlopen_retry", side_effect=failure):
                    result = run_keyed_source(
                        "github-repos",
                        [KEY],
                        lambda token: github.search_github_repos("fixture", token=token),
                        provider="github",
                        key_manager=manager,
                    )
                self.assertIn("key pool exhausted", result[0]["error"])
                row = manager.status_rows("github")[0]
                self.assertEqual(row["status"], COOLDOWN)
                self.assertEqual(row["invalid_strikes"], 0)
                self.assertEqual(row["last_error_type"], "rate_limit")
                store.execute(
                    "UPDATE key_state SET cooldown_until = '2000-01-01T00:00:00+00:00'"
                )

            with mock.patch.object(github, "urlopen_retry", return_value=response()):
                result = run_keyed_source(
                    "github-repos",
                    [KEY],
                    lambda token: github.search_github_repos("fixture", token=token),
                    provider="github",
                    key_manager=manager,
                )

            self.assertEqual(result[0]["url"], PAYLOAD["items"][0]["html_url"])
            row = manager.status_rows("github")[0]
            self.assertEqual(row["status"], "active")
            self.assertEqual(row["invalid_strikes"], 0)
            self.assertEqual(row["rate_limit_count"], 3)
            self.assertEqual(row["use_count"], 4)
            self.assertEqual(row["success_count"], 1)


if __name__ == "__main__":
    unittest.main()

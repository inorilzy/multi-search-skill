"""Key-error classification: status codes need token boundaries, not substrings.

Regression coverage for the review finding that ordinary provider text such as
"content size 4032 exceeds ..." or "offset 4291" was read as a 403/429 and put a
healthy key into cooldown. A missing key is also classified explicitly instead
of surfacing as a generic ``error``.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import (
    ProviderSpec,
    SearchRunner,
    SearchRunnerConfig,
    missing,
    run_keyed_source,
)
from multi_search_mcp.src.state.key_state import (
    ACTIVE,
    COOLDOWN,
    SQLiteKeyManager,
    classify_error,
)
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support.auth import is_key_retryable_error


KEYS = ["synthetic-classify-key-01", "synthetic-classify-key-02"]


def _request(**overrides):
    fields = {"query": "fixture", "sources": ["brave"], "use_state": False}
    fields.update(overrides)
    return service.SearchWebRequest(**fields)


class StatusCodeTokenTests(unittest.TestCase):
    def test_numbers_inside_ordinary_text_are_not_status_codes(self):
        for message in (
            "content size 4032 exceeds max object bytes 262144",
            "json decode error at offset 4291",
            "response body 4291 bytes truncated",
            "wrote 1401 rows before failing",
            "processed 4030 entries",
        ):
            with self.subTest(message=message):
                self.assertEqual(classify_error(message), "error")
                self.assertFalse(is_key_retryable_error({"error": message}))

    def test_real_status_codes_still_classify(self):
        for message, expected in (
            ("HTTP Error 401: Unauthorized", "invalid"),
            ("HTTP 403: Forbidden", "invalid"),
            ("status code 403", "invalid"),
            ("HTTP Error 429: Too Many Requests", "rate_limit"),
            ("429", "rate_limit"),
            ("invalid key", "invalid"),
            ("quota exceeded", "quota_exhausted"),
        ):
            with self.subTest(message=message):
                self.assertEqual(classify_error(message), expected)
                self.assertTrue(is_key_retryable_error({"error": message}))

    def test_adapter_error_type_wins_over_misleading_text(self):
        self.assertEqual(
            classify_error("response body 4291 bytes truncated", error_type="invalid"),
            "invalid",
        )
        self.assertFalse(is_key_retryable_error({
            "error": "response body 4291 bytes truncated",
            "error_type": "error",
        }))


class MissingKeyTests(unittest.TestCase):
    def test_skipped_provider_row_carries_missing_key(self):
        self.assertEqual(
            missing("brave", "missing BRAVE_SEARCH_API_KEY"),
            [{
                "source": "brave",
                "error": "skipped: missing BRAVE_SEARCH_API_KEY",
                "error_type": "missing_key",
            }],
        )

    def test_missing_key_text_is_classified_without_an_adapter_type(self):
        for message in (
            "skipped: missing TAVILY_API_KEY",
            "missing API key",
            "No API key configured",
            "api key not set",
        ):
            with self.subTest(message=message):
                self.assertEqual(classify_error(message), "missing_key")
                self.assertFalse(is_key_retryable_error({"error": message}))

    def test_runner_classifies_provider_without_a_key(self):
        spec = ProviderSpec(
            name="brave",
            public_name="brave",
            call=lambda *_: [],
            key_name="brave",
            missing_message="missing BRAVE_SEARCH_API_KEY",
        )
        runner = SearchRunner(
            SearchRunnerConfig("default", {"brave": 1}, 10, "google", {}),
            {"brave": spec},
            route_resolver=lambda _route: {"brave"},
        )
        rows = runner.run("fixture")
        self.assertEqual(rows[0]["error_type"], "missing_key")
        self.assertIn("missing BRAVE_SEARCH_API_KEY", rows[0]["error"])

    def test_provider_status_exposes_missing_key_for_the_desktop(self):
        # The desktop consumes ``provider_status[].errors[].error_type`` and maps
        # ``missing_key`` to "save a key"; the CLI must emit that classification.
        provider = ProviderSpec(
            name="brave",
            public_name="brave",
            call=lambda *_: [],
            key_name="brave",
            missing_message="missing BRAVE_SEARCH_API_KEY",
        )
        response = service.run_search_web(
            _request(), providers={"brave": provider}, keys={}, config={},
        )
        status = response["provider_status"][0]
        self.assertEqual(status["source"], "brave")
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["errors"][0]["error_type"], "missing_key")


class KeyHealthRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="key-classification-")
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / "state.sqlite")
        self.manager = SQLiteKeyManager(self.store)

    def _rows(self):
        return {row["key_id"]: row for row in self.manager.status_rows("tavily")}

    def test_ordinary_error_text_does_not_cool_the_key(self):
        def call(_api_key):
            return [{"source": "tavily", "error": "response body 4291 bytes truncated"}]

        rows = run_keyed_source(
            "tavily", list(KEYS), call, key_manager=self.manager, provider="tavily",
        )
        self.assertEqual(len(rows), 1)
        self.assertNotIn("error_type", rows[0])
        # Rows are ordered by fingerprint (a key digest), so select the key that was
        # actually tried instead of relying on row order.
        used = [row for row in self._rows().values() if row["last_used_at"]]
        self.assertEqual(len(used), 1)
        state = used[0]
        self.assertEqual(state["status"], ACTIVE)
        self.assertIsNone(state["cooldown_until"])
        self.assertEqual(state["last_error_type"], "error")
        # The key stays selectable, so the provider is not silently unavailable.
        usable = [candidate.key for candidate in self.manager.candidates("tavily", KEYS)]
        self.assertEqual(sorted(usable), sorted(KEYS))

    def test_real_rate_limit_still_cools_the_key(self):
        def call(_api_key):
            return [{"source": "tavily", "error": "HTTP Error 429: Too Many Requests"}]

        run_keyed_source(
            "tavily", [KEYS[0]], call, key_manager=self.manager, provider="tavily",
        )
        state = list(self._rows().values())[0]
        self.assertEqual(state["status"], COOLDOWN)
        self.assertIsNotNone(state["cooldown_until"])
        self.assertEqual(self.manager.candidates("tavily", [KEYS[0]]), [])


if __name__ == "__main__":
    unittest.main()

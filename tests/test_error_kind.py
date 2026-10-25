"""Lock the structured-error contract: ``kind`` + ``origin`` fields.

Covers:
- ``classify_error`` keeps keyword-substring fallback for ``kind``-less rows.
- ``is_key_retryable_error`` reads ``kind``/``origin`` first, then falls back to
  legacy ``error_type``/``error_origin``/``rate_limited``/``key_exhausted``.
- ``normalize_error_kind`` rejects unknown values.
"""
import unittest

from multi_search_mcp.src.state.key_state import classify_error
from multi_search_mcp.src.support.auth import is_key_retryable_error
from multi_search_mcp.src.support.models import (
    ERROR_KIND_ERROR,
    ERROR_KIND_INVALID,
    ERROR_KIND_QUOTA_EXHAUSTED,
    ERROR_KIND_RATE_LIMIT,
    ERROR_KIND_TARGET,
    ERROR_KIND_TIMEOUT,
    ERROR_KIND_NETWORK,
    ERROR_KINDS,
    error_row,
    normalize_error_kind,
)


class ClassifyErrorFallbackTests(unittest.TestCase):
    """The substring matcher is the downgrade path when ``kind`` is absent."""

    def test_explicit_kind_wins_over_message_text(self):
        # Message contents that would otherwise pattern-match a different kind.
        self.assertEqual(
            classify_error("HTTP 401 unauthorized", kind=ERROR_KIND_RATE_LIMIT),
            ERROR_KIND_RATE_LIMIT,
        )
        # Legacy keyword alias still resolves for transitional callers.
        self.assertEqual(
            classify_error("any", error_type="quota_exhausted"),
            ERROR_KIND_QUOTA_EXHAUSTED,
        )

    def test_message_substring_fallback_when_kind_missing(self):
        cases = (
            ("HTTP 401 Unauthorized", ERROR_KIND_INVALID),
            ("forbidden by token", ERROR_KIND_INVALID),
            ("quota exhausted", ERROR_KIND_QUOTA_EXHAUSTED),
            ("insufficient balance", ERROR_KIND_QUOTA_EXHAUSTED),
            ("HTTP 429 too many requests", ERROR_KIND_RATE_LIMIT),
            ("rate limit exceeded", ERROR_KIND_RATE_LIMIT),
            ("connection timeout", ERROR_KIND_TIMEOUT),
            ("timed out", ERROR_KIND_TIMEOUT),
            ("network unreachable", ERROR_KIND_NETWORK),
            ("SSL handshake failed", ERROR_KIND_NETWORK),
            ("weird upstream blip", ERROR_KIND_ERROR),
            ("", ERROR_KIND_ERROR),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(classify_error(message), expected)


class NormalizeKindTests(unittest.TestCase):
    def test_known_values_pass_through(self):
        for kind in ERROR_KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(normalize_error_kind(kind), kind)

    def test_unknown_values_fall_back(self):
        self.assertEqual(normalize_error_kind("not-a-kind"), ERROR_KIND_ERROR)
        self.assertEqual(normalize_error_kind(""), ERROR_KIND_ERROR)
        self.assertEqual(normalize_error_kind(None), ERROR_KIND_ERROR)
        self.assertEqual(normalize_error_kind(42), ERROR_KIND_ERROR)
        self.assertEqual(normalize_error_kind("INVALID"), ERROR_KIND_INVALID)


class ErrorRowTests(unittest.TestCase):
    def test_minimal_row(self):
        self.assertEqual(
            error_row("exa", "nope"),
            {"source": "exa", "error": "nope"},
        )

    def test_full_row(self):
        self.assertEqual(
            error_row(
                "tavily",
                "denied",
                kind=ERROR_KIND_QUOTA_EXHAUSTED,
                origin="provider",
                extra="kept",
            ),
            {
                "source": "tavily",
                "error": "denied",
                "kind": ERROR_KIND_QUOTA_EXHAUSTED,
                "origin": "provider",
                "extra": "kept",
            },
        )


class RetryableDetectionTests(unittest.TestCase):
    """``is_key_retryable_error`` must see the new kind contract first."""

    def test_structured_kind_drives_retry(self):
        self.assertTrue(is_key_retryable_error(
            {"error": "anything", "kind": ERROR_KIND_INVALID}
        ))
        self.assertTrue(is_key_retryable_error(
            {"error": "anything", "kind": ERROR_KIND_QUOTA_EXHAUSTED}
        ))
        self.assertTrue(is_key_retryable_error(
            {"error": "anything", "kind": ERROR_KIND_RATE_LIMIT}
        ))
        # Non-keyed kinds do not rotate.
        for kind in (ERROR_KIND_TARGET, ERROR_KIND_TIMEOUT, ERROR_KIND_NETWORK, ERROR_KIND_ERROR):
            with self.subTest(kind=kind):
                self.assertFalse(is_key_retryable_error({"error": "anything", "kind": kind}))

    def test_target_origin_skips_credential_evidence(self):
        self.assertFalse(is_key_retryable_error(
            {"error": "401 unauthorized", "origin": "target", "kind": ERROR_KIND_TARGET}
        ))

    def test_legacy_fields_still_recognized_as_fallback(self):
        # Pre-kind emitters may still populate these; rotation must still work.
        self.assertTrue(is_key_retryable_error(
            {"error": "denied", "error_type": "invalid"}
        ))
        self.assertTrue(is_key_retryable_error(
            {"error": "denied", "rate_limited": True}
        ))
        self.assertTrue(is_key_retryable_error(
            {"error": "denied", "key_exhausted": True}
        ))
        # Target rows under the old contract still do not rotate.
        self.assertFalse(is_key_retryable_error(
            {"error": "denied", "error_origin": "target", "error_type": "invalid"}
        ))


if __name__ == "__main__":
    unittest.main()

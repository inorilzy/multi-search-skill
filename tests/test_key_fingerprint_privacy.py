"""Key fingerprints are irreversible short hashes and never contain key characters.

Regression coverage for the review finding that ``key_fingerprint`` returned the
first and last four characters of every key (an 8-character key was exposed in
full) and that value reached ``keys status`` / ``doctor`` output. Existing SQLite
rows written by older versions are rewritten in place on open.
"""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from multi_search_mcp.src import service
from multi_search_mcp.src.state.key_state import (
    ACTIVE,
    SQLiteKeyManager,
    key_fingerprint,
    key_id_for,
)
from multi_search_mcp.src.state.state_store import SCHEMA, StateStore


KEYS = ("WXYZ1234", "tvly-QWERTYUIOPASDFGHJKLZXCVB", "fc-MNOPQRSTUVWX", "k")


def _legacy_fingerprint(key: str) -> str:
    """The pre-fix format, reproduced only to seed an old database."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    if len(key) >= 8:
        return f"{key[:4]}...{key[-4:]} ({digest})"
    return f"sha256:{digest}"


class FingerprintFormatTests(unittest.TestCase):
    def test_fingerprint_is_short_hash_without_plaintext(self):
        for key in KEYS:
            with self.subTest(length=len(key)):
                fingerprint = key_fingerprint(key)
                self.assertRegex(fingerprint, r"^sha256:[0-9a-f]{8}$")
                self.assertNotIn(key[:4], fingerprint)
                self.assertNotIn(key[-4:], fingerprint)

    def test_eight_character_key_is_not_exposed(self):
        # The old format returned "WXYZ...1234", i.e. the whole key.
        self.assertNotIn("WXYZ", key_fingerprint("WXYZ1234"))
        self.assertNotIn("1234", key_fingerprint("WXYZ1234"))

    def test_fingerprint_is_derivable_from_key_id(self):
        for key in KEYS:
            with self.subTest(length=len(key)):
                key_id = key_id_for("exa", key)
                self.assertEqual(key_fingerprint(key), "sha256:" + key_id[-16:-8])


class FingerprintStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fingerprint-privacy-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite"

    def _seed_legacy_rows(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(SCHEMA[0])
            for key in KEYS:
                conn.execute(
                    """INSERT INTO key_state
                    (provider, key_id, key_fingerprint, status, success_count,
                     created_at, updated_at) VALUES (?, ?, ?, ?, 3, 'legacy', 'legacy')""",
                    ("exa", key_id_for("exa", key), _legacy_fingerprint(key), ACTIVE),
                )

    def test_open_rewrites_legacy_plaintext_fingerprints(self):
        self._seed_legacy_rows()
        rows = SQLiteKeyManager(StateStore(self.path)).status_rows("exa")
        self.assertEqual(len(rows), len(KEYS))
        by_id = {row["key_id"]: row for row in rows}
        serialized = json.dumps(rows)
        for key in KEYS:
            with self.subTest(length=len(key)):
                row = by_id[key_id_for("exa", key)]
                self.assertEqual(row["key_fingerprint"], key_fingerprint(key))
                # Other columns survive the rewrite untouched.
                self.assertEqual(row["success_count"], 3)
                self.assertEqual(row["created_at"], "legacy")
        for leaked in ("WXYZ", "1234", "tvly", "ZXCVB", "MNOP"):
            self.assertNotIn(leaked, serialized)

    def test_rewrite_is_idempotent_and_keeps_key_health(self):
        self._seed_legacy_rows()
        StateStore(self.path)
        first = SQLiteKeyManager(StateStore(self.path)).status_rows("exa")
        second = SQLiteKeyManager(StateStore(self.path)).status_rows("exa")
        self.assertEqual(first, second)
        # The key_id is unchanged, so the existing row (and its health) is reused.
        manager = SQLiteKeyManager(StateStore(self.path))
        self.assertEqual([c.key for c in manager.candidates("exa", [KEYS[0]])], [KEYS[0]])
        self.assertEqual(len(manager.status_rows("exa")), len(KEYS))

    def test_new_rows_and_status_outputs_carry_no_plaintext(self):
        store = StateStore(self.path)
        manager = SQLiteKeyManager(store)
        for candidate in manager.candidates("exa", list(KEYS)):
            manager.record_use("exa", candidate)
        rows = manager.status_rows("exa")
        summary = service.summarize_key_status(rows)
        for payload in (rows, summary):
            serialized = json.dumps(payload)
            for key in KEYS:
                if len(key) >= 4:
                    self.assertNotIn(key[:4], serialized)
                    self.assertNotIn(key[-4:], serialized)
        for row in summary:
            self.assertRegex(row["fingerprint"], r"^sha256:[0-9a-f]{8}$")


if __name__ == "__main__":
    unittest.main()

"""Desktop-owned SQLite/DPAPI additions, alongside legacy source priority tests."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from tests.desktop_schema import create_config_db as desktop_create_config_db
from multi_search_mcp.src.support.credential_store import CredentialStore, CredentialStoreError
from multi_search_mcp.src.state.keys import load_keys
SYNTHETIC_KEY = "synthetic-tavily-key-0001"


class SQLiteDPAPIStoreTests(unittest.TestCase):
    """Real DPAPI with synthetic values; all SQLite paths are disposable."""

    def setUp(self):
        from multi_search_mcp.src.support.credential_store import SQLiteCredentialBackend, ConfigDatabase
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.sqlite"
        self.backend = SQLiteCredentialBackend(self.path)
        self.store = CredentialStore(self.backend)
        self.db = ConfigDatabase(self.path)
        desktop_create_config_db(self.path)

    def test_explicit_database_selector_is_literal_and_home_priority_matches_desktop(self):
        from multi_search_mcp.src.support.credential_store import config_db_path
        for selected in ("~/config.sqlite", "%USERPROFILE%/config.sqlite", "relative/config.sqlite"):
            self.assertEqual(config_db_path({"MULTI_SEARCH_CONFIG_DB": selected}), Path(selected))
        self.assertEqual(config_db_path({"USERPROFILE": self.tmp.name, "HOME": "ignored"}),
                         Path(self.tmp.name) / ".multi-search" / "config.sqlite")
        self.assertEqual(config_db_path({"USERPROFILE": "", "HOME": self.tmp.name}),
                         Path(self.tmp.name) / ".multi-search" / "config.sqlite")

    def test_missing_database_read_does_not_create_or_touch_legacy_store(self):
        self.path.unlink()
        self.assertIsNone(self.store.get("tavily"))
        self.assertEqual(self.db.read_settings(), {})
        self.assertFalse(self.path.exists())
        # Writes must fail loudly rather than letting the CLI become a second
        # schema owner by creating the database itself.
        with self.assertRaisesRegex(CredentialStoreError, "desktop application"):
            self.db.write_settings({})
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(__import__("sys").platform == "win32", "native DPAPI requires Windows")
    def test_native_encrypted_roundtrip_restart_lists_jina_and_settings(self):
        import sqlite3
        from multi_search_mcp.src.support.credential_store import SQLiteCredentialBackend, WindowsDPAPI
        values = {"tavily": [SYNTHETIC_KEY, "synthetic-second-0011"],
                  "jina": [{"key": "synthetic-jina-0012", "exhausted": True, "metadata": "preserved"}]}
        for provider, value in values.items():
            self.store.set(provider, value, saved_at=1700000001.5)
        self.db.write_settings({"type": "fast", "timeout": 9, "disabled_sources": ["brave"]})
        restarted = CredentialStore(SQLiteCredentialBackend(self.path))
        for provider, value in values.items():
            self.assertEqual(restarted.get(provider), value)
        self.assertEqual(self.db.read_settings()["type"], "fast")
        from contextlib import closing
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            encrypted, stamp = conn.execute("SELECT encrypted_value,saved_at FROM credentials WHERE provider='tavily'").fetchone()
        self.assertEqual(json.loads(WindowsDPAPI().decrypt(encrypted))["saved_at"], stamp)
        for file in self.path.parent.iterdir():
            if file.is_file():
                raw = file.read_bytes()
                for secret in (SYNTHETIC_KEY, "synthetic-second-0011", "synthetic-jina-0012"):
                    self.assertNotIn(secret.encode(), raw)
        self.assertTrue(restarted.delete("tavily"))
        self.assertIsNone(restarted.get("tavily"))

    def test_future_schema_corruption_and_unreadable_settings_fail_explicitly(self):
        import sqlite3
        self.path.write_bytes(b"not sqlite " + SYNTHETIC_KEY.encode())
        with self.assertRaises(CredentialStoreError) as error:
            self.store.get("tavily")
        self.assertNotIn(SYNTHETIC_KEY, str(error.exception))
        self.path.unlink()
        from contextlib import closing
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("PRAGMA user_version=2")
        with self.assertRaisesRegex(CredentialStoreError, "schema version"):
            self.db.read_settings()
        self.path.unlink()
        desktop_create_config_db(self.path)
        self.db.write_settings({})
        from contextlib import closing
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE settings SET data=?", (SYNTHETIC_KEY,))
            conn.commit()
        with self.assertRaisesRegex(CredentialStoreError, "settings are unreadable"):
            self.db.read_settings()

    def test_failed_encrypt_and_transaction_never_write_plaintext_or_partial_changes(self):
        self.backend.protector = mock.Mock()
        self.backend.protector.encrypt.side_effect = CredentialStoreError("DPAPI encryption failed")
        with self.assertRaises(CredentialStoreError):
            self.store.set("tavily", SYNTHETIC_KEY)
        # Encryption fails before any SQL runs: the credentials table stays empty.
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM credentials").fetchone()[0], 0)
        self.db.write_settings({"timeout": 8})
        with self.assertRaises(RuntimeError):
            with self.db.connect() as conn:
                conn.execute("UPDATE settings SET data='{}'")
                raise RuntimeError("synthetic failure")
        self.assertEqual(self.db.read_settings(), {"timeout": 8})

    @unittest.skipUnless(__import__("sys").platform == "win32", "native DPAPI requires Windows")
    def test_default_database_preserves_explicit_env_precedence_and_no_implicit_legacy_store_reads(self):
        from multi_search_mcp.src.support.credential_store import default_store
        from multi_search_mcp.src.support.config import load_config
        old_keys = Path(self.tmp.name) / ".search-keys.json"
        old_keys.write_text(json.dumps({"tavily": "synthetic-old-file-0012"}), encoding="utf-8")
        old_config = Path(self.tmp.name) / "old-config.json"
        old_config.write_text(json.dumps({"timeout": 55}), encoding="utf-8")
        env = {"MULTI_SEARCH_CONFIG_DB": str(self.path), "MULTI_SEARCH_CONFIG": str(old_config),
               "USERPROFILE": self.tmp.name, "HOME": self.tmp.name, "TAVILY_API_KEY": "synthetic-env-0013"}
        with mock.patch.dict("os.environ", env):
            store = default_store()
            store.set("tavily", SYNTHETIC_KEY)
            self.db.write_settings({"timeout": 7})
            self.assertEqual(load_keys()["tavily"], "synthetic-env-0013")
            self.assertEqual(load_config()["timeout"], 55)
            store.delete("tavily")
            with mock.patch("multi_search_mcp.src.support.credential_store.WindowsCredentialBackend", side_effect=AssertionError("no legacy reads")):
                self.assertEqual(load_keys()["tavily"], "synthetic-env-0013")
            self.assertEqual(old_keys.read_text(encoding="utf-8"), json.dumps({"tavily": "synthetic-old-file-0012"}))

    def test_cli_never_creates_or_migrates_schema(self):
        """Ticket 05: the CLI must not perform schema creation or migration SQL."""
        import sqlite3 as _sqlite3
        from contextlib import closing
        # Missing database: read is empty, write refuses and no file appears.
        self.path.unlink()
        self.assertEqual(self.db.read_settings(), {})
        with self.assertRaisesRegex(CredentialStoreError, "desktop application"):
            self.db.write_settings({"timeout": 5})
        self.assertFalse(self.path.exists())
        # Version 0 database: untouched byte-for-byte and reported as unsupported.
        with closing(_sqlite3.connect(self.path)) as conn:
            conn.execute("CREATE TABLE unrelated(value TEXT)")
            conn.commit()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(CredentialStoreError, "desktop application"):
            self.db.read_settings()
        with self.assertRaisesRegex(CredentialStoreError, "desktop application"):
            self.db.write_settings({})
        self.assertEqual(self.path.read_bytes(), before)
        with closing(_sqlite3.connect(self.path)) as conn:
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                0,
                "the CLI must not bump user_version",
            )
        # Version 1 database: writes are allowed but the version is unchanged.
        self.path.unlink()
        desktop_create_config_db(self.path)
        self.db.write_settings({"timeout": 5})
        with closing(_sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_version_zero_nonempty_and_version_one_missing_or_wrong_columns_rejected(self):
        from contextlib import closing
        # v0 (even with plausible-looking tables) is never adopted: the CLI does
        # not migrate or create schema.
        for statements, pattern in (
            (("CREATE TABLE unrelated(value TEXT)",), "desktop application"),
            (("PRAGMA user_version=1",), "schema is invalid"),
            (("CREATE TABLE settings(id INTEGER PRIMARY KEY,data BLOB)", "PRAGMA user_version=1"), "schema is invalid"),
        ):
            if self.path.exists():
                self.path.unlink()
            with closing(sqlite3.connect(self.path)) as conn:
                for sql in statements:
                    conn.execute(sql)
                conn.commit()
            before = self.path.read_bytes()
            with self.assertRaisesRegex(CredentialStoreError, pattern):
                self.db.read_settings()
            self.assertEqual(self.path.read_bytes(), before)

    @unittest.skipUnless(__import__("sys").platform == "win32", "native DPAPI requires Windows")
    def test_corrupt_ciphertext_is_explicit_without_plaintext_fallback(self):
        self.store.set("tavily", SYNTHETIC_KEY)
        with self.db.connect() as conn:
            conn.execute("UPDATE credentials SET encrypted_value=? WHERE provider='tavily'", (b"synthetic-invalid-ciphertext",))
        with self.assertRaisesRegex(CredentialStoreError, "DPAPI decryption failed"):
            self.store.get("tavily")

    def test_hash_fingerprint_contains_no_key_prefix_or_suffix(self):
        from multi_search_mcp.src.state.key_state import key_fingerprint
        value = key_fingerprint(SYNTHETIC_KEY)
        self.assertTrue(value.startswith("sha256:"))
        self.assertNotIn(SYNTHETIC_KEY[:4], value)
        self.assertNotIn(SYNTHETIC_KEY[-4:], value)

    def test_legacy_state_display_masks_are_replaced_with_hashes(self):
        from multi_search_mcp.src.state.state_store import StateStore
        from multi_search_mcp.src.state.key_state import SQLiteKeyManager, key_id_for
        state_path = Path(self.tmp.name) / "state.sqlite"
        # Write the legacy row into a v0 state database so the one-shot
        # migration (guarded by PRAGMA user_version) performs the rewrite when
        # the store is opened. Constructing the manager afterwards must not
        # rewrite anything.
        import sqlite3 as _sqlite3
        from contextlib import closing
        with closing(_sqlite3.connect(state_path)) as conn:
            conn.executescript(
                "CREATE TABLE key_state (provider TEXT NOT NULL, key_id TEXT NOT NULL, key_fingerprint TEXT NOT NULL, "
                "status TEXT NOT NULL, success_count INTEGER NOT NULL DEFAULT 0, failure_count INTEGER NOT NULL DEFAULT 0, "
                "rate_limit_count INTEGER NOT NULL DEFAULT 0, quota_error_count INTEGER NOT NULL DEFAULT 0, "
                "use_count INTEGER NOT NULL DEFAULT 0, invalid_strikes INTEGER NOT NULL DEFAULT 0, last_used_at TEXT, "
                "last_success_at TEXT, last_failure_at TEXT, last_error_type TEXT, last_error_message TEXT, "
                "cooldown_until TEXT, exhausted_until TEXT, manually_disabled INTEGER NOT NULL DEFAULT 0, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (provider, key_id));"
            )
            conn.execute("INSERT INTO key_state(provider,key_id,key_fingerprint,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                         ("tavily", key_id_for("tavily", SYNTHETIC_KEY), "synt...0001 (old)", "active", "now", "now"))
            conn.commit()
        state = StateStore(state_path)
        manager = SQLiteKeyManager(state)
        fingerprint = manager.status_rows()[0]["key_fingerprint"]
        self.assertTrue(fingerprint.startswith("sha256:"))
        self.assertNotIn("synt", fingerprint)
        self.assertNotIn("0001", fingerprint)
        # The migration is one-shot: a legacy-format row written after the
        # version bump is not silently rewritten on every manager construction.
        state.execute("INSERT INTO key_state(provider,key_id,key_fingerprint,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                      ("brave", key_id_for("brave", "synthetic-brave-0002"), "brv...0002 (old)", "active", "now", "now"))
        SQLiteKeyManager(state)
        fingerprints = {row["provider"]: row["key_fingerprint"] for row in SQLiteKeyManager(state).status_rows()}
        self.assertTrue(fingerprints["tavily"].startswith("sha256:"))
        self.assertEqual(fingerprints["brave"], "brv...0002 (old)")

    def test_invalid_nested_pools_and_unknown_provider_are_rejected(self):
        for value in ([[SYNTHETIC_KEY]], [], [None], {"key": SYNTHETIC_KEY}):
            with self.assertRaises(ValueError):
                self.store.set("tavily", value)
        with self.assertRaises(ValueError):
            self.store.set("not-a-provider", SYNTHETIC_KEY)

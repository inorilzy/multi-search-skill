"""Core storage protocol the desktop relies on.

The desktop runs ``multi-search doctor --no-keys --format json`` and checks the
``config_storage`` handshake ``{"backend": "sqlite-dpapi", "schema_version": 1}``
(``credential_commands::supports_storage``). The identifier is kept stable;
``config.sqlite`` now holds only the ``settings`` record and API keys live in
``~/.multi-search/keys.json``. These tests lock that contract, settings from
``config.sqlite``, file-only X cookies, and key-state reservation.
"""
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src import diagnostics, service
from multi_search_mcp.src.state import runtime
from multi_search_mcp.src.state.key_state import KeyOutcome, SQLiteKeyManager, TRANSIENT_INVALID
from multi_search_mcp.src.state.keys import CREDENTIAL_STORE_PROVIDERS
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support import config


def create_config_db(path: Path, settings: dict | None = None) -> None:
    """The desktop-owned schema v1 (``config_db.rs`` MIGRATIONS[0])."""
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TABLE credentials(provider TEXT PRIMARY KEY, "
            "encrypted_value BLOB NOT NULL, saved_at REAL NOT NULL)"
        )
        conn.execute("CREATE TABLE settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
        conn.execute("PRAGMA user_version=1")
        if settings is not None:
            conn.execute("INSERT INTO settings(id,data) VALUES(1,?)", (json.dumps(settings),))


class StorageFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="config-storage-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "config.sqlite"
        for patcher in (
            mock.patch("multi_search_mcp.src.diagnostics.StateStore",
                       return_value=StateStore(self.root / "state.sqlite")),
            mock.patch("multi_search_mcp.src.state.runtime.load_keys", return_value={}),
            mock.patch.object(config, "USER_CONFIG_PATH", self.root / "missing-user.json"),
            mock.patch.object(config, "IS_SOURCE_CHECKOUT", False),
            mock.patch.dict(os.environ, {config.CONFIG_ENV_VAR: "", config.CONFIG_DB_ENV: str(self.db)}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class DoctorStorageContractTests(StorageFixture):
    def test_doctor_no_keys_reports_sqlite_dpapi_protocol(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.main(["doctor", "--no-keys", "--format", "json"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["config_storage"], {"backend": "sqlite-dpapi", "schema_version": 1})
        self.assertEqual(payload["key_sources"]["file"], "~/.multi-search/keys.json")
        for removed in ("storage", "database", "legacy_sources"):
            self.assertNotIn(removed, payload["key_sources"])
        self.assertEqual(payload["twitter_cookie_storage"]["mode"], "file")
        self.assertNotIn("config_error", payload)
        self.assertNotIn("keys_error", payload)

    def test_service_facade_exposes_the_same_protocol(self):
        self.assertEqual(service.config_storage(), diagnostics.config_storage())
        self.assertEqual(service.doctor_data(include_keys=False)["config_storage"]["backend"], "sqlite-dpapi")

    def test_legacy_managed_cookie_mode_is_reported_as_file(self):
        create_config_db(self.db, {"twitter_cookies_mode": "managed"})
        data = service.doctor_data(include_keys=False)
        self.assertEqual(data["twitter_cookie_storage"]["mode"], "file")
        self.assertNotIn("DPAPI", data["twitter_cookie_storage"]["boundary"])
        self.assertEqual(data["config_path_source"], "sqlite")
        self.assertNotIn("keys_error", data)


class SqliteSettingsTests(StorageFixture):
    def test_saved_desktop_settings_are_authoritative(self):
        create_config_db(self.db, {"timeout": 7})
        self.assertEqual(config.resolve_config_path_source(), (self.db, "sqlite"))
        self.assertEqual(config.load_config(), {"timeout": 7})

    def test_database_without_settings_falls_back_to_defaults(self):
        create_config_db(self.db)
        self.assertEqual(config.resolve_config_path_source()[1], "defaults")
        self.assertEqual(config.load_config(), {})

    def test_explicit_json_still_wins(self):
        create_config_db(self.db, {"timeout": 7})
        explicit = self.root / "explicit.json"
        explicit.write_text('{"timeout": 9}', encoding="utf-8")
        with mock.patch.dict(os.environ, {config.CONFIG_ENV_VAR: str(explicit)}):
            self.assertEqual(config.load_config(), {"timeout": 9})

    def test_unsupported_schema_fails_closed(self):
        create_config_db(self.db, {"timeout": 7})
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("PRAGMA user_version=2")
        self.assertEqual(config.resolve_config_path_source()[1], "sqlite")
        with self.assertRaises(config.ConfigError):
            config.load_config()


class LegacyCookieModeTests(unittest.TestCase):
    """``twitter_cookies_mode`` is a removed setting: any value means file mode."""

    def test_managed_mode_is_ignored_and_the_file_reference_is_used(self):
        with mock.patch.object(runtime, "load_keys", return_value={"twitter": "/tmp/legacy.json"}) as load:
            keys = runtime.load_runtime_keys(
                {"twitter_cookies_mode": "managed", "twitter_cookies_path": "/tmp/configured.json"}
            )
        load.assert_called_once_with(twitter_cookies_path="/tmp/configured.json")
        self.assertEqual(keys, {"twitter": "/tmp/legacy.json"})
        self.assertNotIn("twitter_cookies", keys)

    def test_any_legacy_mode_value_is_accepted_without_error(self):
        for mode in ("managed", "file", "other", 1, None, ["managed"]):
            with self.subTest(mode=mode), \
                 mock.patch.object(runtime, "load_keys", return_value={}) as load:
                self.assertEqual(runtime.load_runtime_keys({"twitter_cookies_mode": mode}), {})
            load.assert_called_once_with()

    def test_cookie_reference_is_not_a_keyed_provider(self):
        self.assertNotIn("twitter_cookies", CREDENTIAL_STORE_PROVIDERS)
        self.assertIn("jina", CREDENTIAL_STORE_PROVIDERS)


class KeyReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="key-reserve-")
        self.addCleanup(self.temp.cleanup)
        self.manager = SQLiteKeyManager(StateStore(Path(self.temp.name) / "state.sqlite"))

    def test_reserve_rotates_least_recently_used_and_skips_cooling_keys(self):
        candidates = self.manager.candidates("exa", ["one", "two"])
        first = self.manager.reserve("exa", candidates)
        second = self.manager.reserve("exa", candidates)
        self.assertEqual({first.key, second.key}, {"one", "two"})
        self.assertEqual(sorted(row["use_count"] for row in self.manager.status_rows("exa")), [1, 1])
        self.manager.record_result("exa", first, KeyOutcome(False, True, "rate_limit", "429"))
        self.assertEqual(self.manager.reserve("exa", candidates), second)

    def test_late_success_does_not_clear_a_newer_failure(self):
        candidate = self.manager.candidates("exa", "one")[0]
        started = datetime.now(timezone.utc) - timedelta(seconds=5)
        self.manager.record_result("exa", candidate, KeyOutcome(False, True, "invalid", "401"))
        self.manager.record_result("exa", candidate, KeyOutcome(True, False), started_at=started)
        row = self.manager.status_rows("exa")[0]
        self.assertEqual((row["status"], row["invalid_strikes"], row["success_count"]),
                         (TRANSIENT_INVALID, 1, 1))


if __name__ == "__main__":
    unittest.main()

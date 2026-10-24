"""Reliable state writes: WAL + single-transaction key updates and atomic keys files.

Regression coverage for the review findings that every SQLite call opened its own
connection (so a read-modify-write spanned several transactions) and that
``mark_exhausted`` rewrote ``~/.search-keys.json`` in place, which could truncate
the only copy of every key on a crash.
"""
import json
import os
import stat
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.state.key_state import (
    ACTIVE,
    INVALID,
    SQLiteKeyManager,
)
from multi_search_mcp.src.state.keys import (
    KEYS_FILE_MODE,
    keys_file_permission_warning,
    write_keys_file_atomic,
)
from multi_search_mcp.src.state.mark_exhausted import _mark_config_exhausted
from multi_search_mcp.src.state.state_store import StateStore


class StateStoreWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="state-writes-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite"

    def test_wal_mode_is_enabled(self):
        store = StateStore(self.path)
        row = store.rows("PRAGMA journal_mode")[0]
        self.assertEqual(row["journal_mode"], "wal")

    def test_one_transaction_reuses_one_connection(self):
        store = StateStore(self.path)
        with mock.patch.object(store, "_open", wraps=store._open) as opened:
            with store.transaction():
                store.execute("INSERT OR IGNORE INTO key_state "
                              "(provider, key_id, key_fingerprint, status, created_at, updated_at) "
                              "VALUES ('exa', 'exa:1', 'sha256:1', 'active', 't', 't')")
                store.execute("UPDATE key_state SET success_count = success_count + 1")
                store.rows("SELECT * FROM key_state")
            self.assertEqual(opened.call_count, 1)
        self.assertEqual(store.rows("SELECT success_count FROM key_state")[0]["success_count"], 1)

    def test_transaction_rolls_back_as_a_unit_and_releases_the_connection(self):
        store = StateStore(self.path)
        with self.assertRaises(RuntimeError):
            with store.transaction():
                store.execute("INSERT INTO key_state "
                              "(provider, key_id, key_fingerprint, status, created_at, updated_at) "
                              "VALUES ('exa', 'exa:rollback', 'sha256:1', 'active', 't', 't')")
                self.assertEqual(len(store.rows("SELECT * FROM key_state")), 1)
                raise RuntimeError("boom")
        self.assertEqual(store.rows("SELECT * FROM key_state"), [])
        self.assertIsNone(getattr(store._local, "conn", None))
        self.assertEqual(getattr(store._local, "depth", 0), 0)

    def test_reader_sees_the_previous_snapshot_while_a_writer_holds_the_lock(self):
        writer = StateStore(self.path)
        reader = StateStore(self.path)
        with writer.transaction():
            writer.execute("INSERT INTO key_state "
                           "(provider, key_id, key_fingerprint, status, created_at, updated_at) "
                           "VALUES ('exa', 'exa:pending', 'sha256:1', 'active', 't', 't')")
            # WAL: a reader does not block on the uncommitted writer.
            started = threading.Event()
            seen = []

            def read():
                seen.append(reader.rows("SELECT * FROM key_state"))
                started.set()

            thread = threading.Thread(target=read)
            thread.start()
            self.assertTrue(started.wait(5))
            thread.join(5)
            self.assertEqual(seen, [[]])
        self.assertEqual(len(writer.rows("SELECT * FROM key_state")), 1)


class ConcurrentKeyStateTests(unittest.TestCase):
    """Concurrent writers must not lose increments or split a key-health update."""

    WORKERS = 6

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="state-concurrent-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite"
        self.manager = SQLiteKeyManager(StateStore(self.path))

    def test_concurrent_record_use_counts_every_write(self):
        for sharing in ("manager", "store", "database"):
            with self.subTest(sharing=sharing), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "state.sqlite"
                manager = SQLiteKeyManager(StateStore(path))
                candidate = manager.candidates("exa", "fixture-key")[0]
                managers = (
                    [manager] * self.WORKERS if sharing == "manager"
                    else [SQLiteKeyManager(manager.store) for _ in range(self.WORKERS)] if sharing == "store"
                    else [SQLiteKeyManager(StateStore(path)) for _ in range(self.WORKERS)]
                )
                start = threading.Barrier(self.WORKERS, timeout=10)

                def use(worker):
                    start.wait()
                    worker.record_use("exa", candidate)

                with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
                    for future in [pool.submit(use, worker) for worker in managers]:
                        future.result(timeout=30)
                row = manager.status_rows("exa")[0]
                self.assertEqual(row["use_count"], self.WORKERS)

    def test_concurrent_auth_failures_never_lose_an_update(self):
        candidate = self.manager.candidates("exa", "fixture-key")[0]
        outcome = self.manager.classify_result("exa", {"error": "HTTP 401 unauthorized"})
        for sharing in ("manager", "store", "database"):
            with self.subTest(sharing=sharing), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "state.sqlite"
                manager = SQLiteKeyManager(StateStore(path))
                candidate = manager.candidates("exa", "fixture-key")[0]
                managers = (
                    [manager] * self.WORKERS if sharing == "manager"
                    else [SQLiteKeyManager(manager.store) for _ in range(self.WORKERS)] if sharing == "store"
                    else [SQLiteKeyManager(StateStore(path)) for _ in range(self.WORKERS)]
                )
                start = threading.Barrier(self.WORKERS, timeout=10)

                def record(worker):
                    start.wait()
                    worker.record_result("exa", candidate, outcome)

                with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
                    for future in [pool.submit(record, worker) for worker in managers]:
                        future.result(timeout=30)
                row = manager.status_rows("exa")[0]
                self.assertEqual(row["failure_count"], self.WORKERS)
                self.assertEqual(row["invalid_strikes"], self.WORKERS)
                self.assertEqual(row["status"], INVALID)
                self.assertIsNone(row["cooldown_until"])

    def test_concurrent_use_and_result_keep_one_row_per_key(self):
        candidate = self.manager.candidates("exa", "fixture-key")[0]
        start = threading.Barrier(2, timeout=10)

        def use(_index):
            start.wait()
            self.manager.record_use("exa", candidate)

        def result(_index):
            start.wait()
            self.manager.record_result(
                "exa", candidate, self.manager.classify_result("exa", {"error": "timeout"}),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(use, 0), pool.submit(result, 1)]
            for future in futures:
                future.result(timeout=30)
        rows = self.manager.status_rows("exa")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["use_count"], rows[0]["failure_count"]), (1, 1))
        self.assertEqual(rows[0]["status"], ACTIVE)


class KeysFileWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keys-file-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "search-keys.json"

    def test_atomic_write_replaces_content_without_leaving_temporaries(self):
        self.path.write_text('{"tavily": "old"}', encoding="utf-8")
        write_keys_file_atomic(self.path, {"tavily": "new", "jina": [{"key": "j", "exhausted": True}]})
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            {"tavily": "new", "jina": [{"key": "j", "exhausted": True}]},
        )
        self.assertEqual([item.name for item in Path(self.temp.name).iterdir()], ["search-keys.json"])

    @unittest.skipUnless(os.name == "posix", "POSIX file modes only")
    def test_atomic_write_creates_an_owner_only_file(self):
        self.path.write_text('{"tavily": "old"}', encoding="utf-8")
        os.chmod(self.path, 0o644)
        write_keys_file_atomic(self.path, {"tavily": "new"})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), KEYS_FILE_MODE)
        self.assertEqual(KEYS_FILE_MODE, 0o600)

    def test_failed_replace_keeps_the_original_file(self):
        self.path.write_text('{"tavily": "old"}', encoding="utf-8")
        with mock.patch("multi_search_mcp.src.state.keys.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_keys_file_atomic(self.path, {"tavily": "new"})
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"tavily": "old"}')
        self.assertEqual([item.name for item in Path(self.temp.name).iterdir()], ["search-keys.json"])

    def test_mark_exhausted_uses_the_atomic_path(self):
        # `mark_exhausted` owns the default location, not an injected path.
        home = Path(self.temp.name) / "home"
        home.mkdir()
        keys_file = home / ".search-keys.json"
        keys_file.write_text(json.dumps({"jina": [{"key": "j1"}, {"key": "j2"}]}), encoding="utf-8")
        with mock.patch("pathlib.Path.home", return_value=home):
            self.assertTrue(_mark_config_exhausted("j2"))
        self.assertEqual(
            json.loads(keys_file.read_text(encoding="utf-8")),
            {"jina": [{"key": "j1"}, {"key": "j2", "exhausted": True}]},
        )
        self.assertEqual([item.name for item in home.iterdir()], [".search-keys.json"])

    def test_failed_mark_keeps_the_original_file_and_reports_false(self):
        home = Path(self.temp.name) / "home"
        home.mkdir()
        keys_file = home / ".search-keys.json"
        original = json.dumps({"jina": [{"key": "j1"}]})
        keys_file.write_text(original, encoding="utf-8")
        with mock.patch("pathlib.Path.home", return_value=home), mock.patch(
            "multi_search_mcp.src.state.keys.os.replace", side_effect=OSError("read-only")
        ):
            self.assertFalse(_mark_config_exhausted("j1"))
        self.assertEqual(keys_file.read_text(encoding="utf-8"), original)
        self.assertEqual([item.name for item in home.iterdir()], [".search-keys.json"])


class KeysFilePermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keys-permission-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.path = self.home / ".search-keys.json"

    @unittest.skipUnless(os.name == "posix", "POSIX file modes only")
    def test_world_readable_file_is_reported(self):
        self.path.write_text('{"tavily": "k"}', encoding="utf-8")
        os.chmod(self.path, 0o644)
        warning = keys_file_permission_warning(self.path)
        self.assertIn("readable by other users", warning)
        self.assertIn("chmod 600", warning)

    @unittest.skipUnless(os.name == "posix", "POSIX file modes only")
    def test_owner_only_and_missing_files_are_not_reported(self):
        self.path.write_text('{"tavily": "k"}', encoding="utf-8")
        os.chmod(self.path, 0o600)
        self.assertIsNone(keys_file_permission_warning(self.path))
        self.assertIsNone(keys_file_permission_warning(self.home / "missing.json"))

    @unittest.skipUnless(os.name == "posix", "POSIX file modes only")
    def test_doctor_reports_the_keys_file_permission_warning(self):
        self.path.write_text('{"tavily": "k"}', encoding="utf-8")
        os.chmod(self.path, 0o644)
        store = StateStore(self.home / "state.sqlite")
        with mock.patch("pathlib.Path.home", return_value=self.home), mock.patch.object(
            service, "StateStore", return_value=store
        ), mock.patch.object(service, "load_keys", return_value={"tavily": "k"}):
            data = service.doctor_data(include_keys=False)
        self.assertEqual(len(data["keys_file_warnings"]), 1)
        self.assertIn("readable by other users", data["keys_file_warnings"][0])


if __name__ == "__main__":
    unittest.main()

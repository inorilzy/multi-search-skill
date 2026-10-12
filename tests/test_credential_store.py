import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.state import keys as keys_module
from multi_search_mcp.src.state.keys import KeysError, key_sources, load_keys
from multi_search_mcp.src.support.credential_store import (
    CredentialStore,
    CredentialStoreError,
    credential_namespace,
    validate_key,
)


class MemoryBackend:
    """In-memory stand-in for Windows Credential Manager; never touches the real store."""

    def __init__(self):
        self.entries: dict[str, bytes] = {}
        self.fail: Exception | None = None

    def read(self, target):
        if self.fail:
            raise self.fail
        return self.entries.get(target)

    def write(self, target, blob):
        if self.fail:
            raise self.fail
        self.entries[target] = blob

    def delete(self, target):
        if self.fail:
            raise self.fail
        return self.entries.pop(target, None) is not None


SYNTHETIC_KEY = "synthetic-tavily-key-0001"


class CredentialStoreRoundTripTests(unittest.TestCase):
    def test_set_get_delete_uses_namespaced_target_and_versioned_blob(self):
        backend = MemoryBackend()
        store = CredentialStore(backend, namespace="ns-test")
        store.set("tavily", f"  {SYNTHETIC_KEY}  ", saved_at=1700000000)

        self.assertEqual(list(backend.entries), ["ns-test/tavily"])
        blob = json.loads(backend.entries["ns-test/tavily"].decode("utf-8"))
        self.assertEqual(blob, {"v": 1, "key": SYNTHETIC_KEY, "saved_at": 1700000000.0})
        self.assertEqual(store.get("tavily"), SYNTHETIC_KEY)
        self.assertTrue(store.delete("tavily"))
        self.assertIsNone(store.get("tavily"))
        self.assertFalse(store.delete("tavily"))

    def test_invalid_keys_are_rejected_without_echoing_value(self):
        for bad in ("", "   ", "line\nbreak", "x" * 1025, None, 12):
            with self.subTest(bad=bad if isinstance(bad, (type(None), int)) else "str"):
                with self.assertRaises(ValueError) as ctx:
                    validate_key(bad)
                self.assertNotIn(SYNTHETIC_KEY, str(ctx.exception))

    def test_unreadable_entry_raises_without_leaking_contents(self):
        backend = MemoryBackend()
        backend.entries["multi-search/tavily"] = b"{not json " + SYNTHETIC_KEY.encode()
        with self.assertRaises(CredentialStoreError) as ctx:
            CredentialStore(backend).get("tavily")
        self.assertNotIn(SYNTHETIC_KEY, str(ctx.exception))

    def test_store_failure_is_explicit(self):
        backend = MemoryBackend()
        backend.fail = CredentialStoreError("credential store access denied")
        with self.assertRaises(CredentialStoreError):
            CredentialStore(backend).set("tavily", SYNTHETIC_KEY)

    def test_namespace_defaults_and_env_override(self):
        self.assertEqual(credential_namespace({}), "multi-search")
        self.assertEqual(credential_namespace({"MULTI_SEARCH_CREDENTIAL_NAMESPACE": "disposable"}), "disposable")


class LoadKeysPriorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.keys_file = Path(self.tmp.name) / "keys.json"
        self.file_key = "file-tavily-key-0002"

    def write_file(self, data):
        self.keys_file.write_text(json.dumps(data), encoding="utf-8")

    def store_with(self, value):
        backend = MemoryBackend()
        store = CredentialStore(backend, namespace="ns-test")
        if value is not None:
            store.set("tavily", value)
        return store

    def test_store_beats_file(self):
        self.write_file({"tavily": self.file_key})
        keys = load_keys(self.keys_file, environ={}, credential_store=self.store_with(SYNTHETIC_KEY))
        self.assertEqual(keys["tavily"], SYNTHETIC_KEY)

    def test_env_beats_store_and_file(self):
        self.write_file({"tavily": self.file_key})
        keys = load_keys(
            self.keys_file,
            environ={"TAVILY_API_KEY": "env-tavily-key-0003"},
            credential_store=self.store_with(SYNTHETIC_KEY),
        )
        self.assertEqual(keys["tavily"], "env-tavily-key-0003")

    def test_file_used_when_store_empty(self):
        self.write_file({"tavily": self.file_key})
        keys = load_keys(self.keys_file, environ={}, credential_store=self.store_with(None))
        self.assertEqual(keys["tavily"], self.file_key)

    def test_store_unavailable_never_falls_back_to_file(self):
        self.write_file({"tavily": self.file_key})
        backend = MemoryBackend()
        backend.fail = CredentialStoreError("credential store access denied")
        with self.assertRaises(KeysError) as ctx:
            load_keys(self.keys_file, environ={}, credential_store=CredentialStore(backend))
        self.assertNotIn(self.file_key, str(ctx.exception))
        self.assertNotIn(SYNTHETIC_KEY, str(ctx.exception))

    def test_process_store_is_not_consulted_under_test_isolation(self):
        env = {"MULTI_SEARCH_TEST_ISOLATION": "1"}
        with mock.patch.object(keys_module.sys, "platform", "win32"), \
                mock.patch("multi_search_mcp.src.support.credential_store.default_store") as default:
            load_keys(self.keys_file, environ=env)
        default.assert_not_called()

    def test_process_store_disabled_off_windows(self):
        with mock.patch.object(keys_module.sys, "platform", "linux"), \
                mock.patch("multi_search_mcp.src.support.credential_store.default_store") as default:
            load_keys(self.keys_file, environ={})
        default.assert_not_called()


class KeySourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.keys_file = Path(self.tmp.name) / "keys.json"

    def test_reports_effective_source_without_values(self):
        self.keys_file.write_text(json.dumps({"tavily": "file-tavily-key-0002"}), encoding="utf-8")
        store = CredentialStore(MemoryBackend(), namespace="ns-test")
        store.set("tavily", SYNTHETIC_KEY)
        report = key_sources(self.keys_file, environ={"TAVILY_API_KEY": "env-tavily-key-0003"}, credential_store=store)
        row = report["tavily"]
        self.assertEqual(row["effective_source"], "env")
        self.assertEqual(row["env_vars_set"], ["TAVILY_API_KEY"])
        self.assertTrue(row["env_overrides_store"])
        self.assertEqual(row["credential_store"], "present")
        self.assertTrue(row["file_present"])
        serialized = json.dumps(report)
        for secret in (SYNTHETIC_KEY, "file-tavily-key-0002", "env-tavily-key-0003"):
            self.assertNotIn(secret, serialized)

    def test_store_unavailable_is_reported_not_raised(self):
        backend = MemoryBackend()
        backend.fail = CredentialStoreError("credential store access denied")
        report = key_sources(self.keys_file, environ={}, credential_store=CredentialStore(backend))
        self.assertEqual(report["tavily"]["credential_store"], "unavailable")
        self.assertEqual(report["tavily"]["effective_source"], "none")


if __name__ == "__main__":
    unittest.main()

"""Explicit migration of legacy ~/.search-keys.json entries into the credential store.

Synthetic keys and a memory backend only. The real keys file, real Credential Manager, and real
user config are never touched; every path comes from a temp directory.
"""
import json
import tempfile
import unittest
from pathlib import Path

from multi_search_mcp.src.support.credential_store import CredentialStore
from multi_search_mcp.src.support import legacy_migration as lm


class MemoryBackend:
    def __init__(self):
        self.entries: dict[str, bytes] = {}
        self.writes: list[str] = []
        self.fail_write: Exception | None = None

    def read(self, target):
        return self.entries.get(target)

    def write(self, target, blob):
        if self.fail_write is not None:
            raise self.fail_write
        self.writes.append(target)
        self.entries[target] = blob

    def delete(self, target):
        return self.entries.pop(target, None) is not None


SYN_TAVILY = "synthetic-tavily-0001"
SYN_BRAVE = "synthetic-brave-0002"
SYN_OTHER = "synthetic-other-0003"


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.keys_file = self.dir / "search-keys.json"
        self.backend = MemoryBackend()
        self.store = CredentialStore(self.backend, namespace="migration-test")

    def write_keys(self, data):
        self.keys_file.write_text(json.dumps(data), encoding="utf-8")

    def plan(self):
        return lm.plan_migration(self.keys_file, self.store)

    def item(self, plan, provider):
        return next(i for i in plan["items"] if i["provider"] == provider)

    # --- detection and masking -------------------------------------------------

    def test_supported_single_keys_are_planned_with_masked_preview_only(self):
        self.write_keys({"tavily": SYN_TAVILY, "brave": SYN_BRAVE})
        plan = self.plan()
        tavily = self.item(plan, "tavily")
        self.assertEqual(tavily["action"], "migrate")
        self.assertNotIn(SYN_TAVILY, json.dumps(plan))
        self.assertNotIn(SYN_BRAVE, json.dumps(plan))
        self.assertTrue(tavily["preview"].startswith("synth"))
        self.assertTrue(tavily["preview"].endswith("0001"))

    def test_single_element_list_is_accepted_as_one_key(self):
        self.write_keys({"exa": [SYN_OTHER]})
        self.assertEqual(self.item(self.plan(), "exa")["action"], "migrate")

    def test_multi_key_lists_and_jina_migrate_without_collapsing(self):
        values = {"tavily": [SYN_TAVILY, SYN_OTHER], "jina": [{"key": SYN_BRAVE, "exhausted": False}]}
        self.write_keys(values)
        plan = self.plan()
        for provider in values:
            self.assertEqual(self.item(plan, provider)["action"], "migrate")
        lm.apply_migration(self.keys_file, self.store, plan, approved=list(values), choices={})
        for provider, value in values.items():
            self.assertEqual(self.store.get(provider), value)

    def test_unknown_provider_names_are_unsupported_not_guessed(self):
        self.write_keys({"mystery": SYN_TAVILY})
        self.assertEqual(self.item(self.plan(), "mystery")["action"], "unsupported")

    def test_twitter_missing_path_reference_is_unsupported_and_not_reported_usable(self):
        self.write_keys({"twitter": str(self.dir / "absent-cookies.json")})
        item = self.item(self.plan(), "settings")
        self.assertEqual(item["action"], "migrate")
        self.assertNotIn("path_exists", item)

    def test_twitter_existing_path_reference_is_already_current_without_reading_cookies(self):
        cookies = self.dir / "synthetic-cookies.json"
        cookies.write_text(json.dumps({"auth_token": SYN_OTHER, "ct0": SYN_BRAVE}), encoding="utf-8")
        self.write_keys({"twitter": str(cookies)})
        item = self.item(self.plan(), "settings")
        self.assertEqual(item["action"], "migrate")
        self.assertNotIn(SYN_OTHER, json.dumps(self.plan()))
        self.assertNotIn("twitter", self.plan()["migratable"])

    def test_twitter_cookie_object_is_unsupported_and_source_is_untouched(self):
        self.write_keys({"twitter": {"auth_token": SYN_OTHER, "ct0": SYN_BRAVE}})
        before = self.keys_file.read_bytes()
        plan = self.plan()
        self.assertEqual(self.item(plan, "twitter")["action"], "unsupported")
        lm.apply_migration(self.keys_file, self.store, plan, approved=[], choices={})
        self.assertEqual(self.keys_file.read_bytes(), before)
        self.assertNotIn(SYN_OTHER, json.dumps(plan))

    def test_unsupported_skips_are_listed_so_they_are_never_reported_as_full_success(self):
        self.write_keys({"tavily": SYN_TAVILY, "unsupported-provider": SYN_BRAVE})
        plan = self.plan()
        self.assertEqual(plan["skipped"], ["unsupported-provider"])
        self.assertEqual(plan["migratable"], ["tavily"])

    def test_non_object_or_invalid_file_is_an_explicit_error(self):
        self.keys_file.write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(lm.MigrationError):
            self.plan()
        self.keys_file.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(lm.MigrationError) as ctx:
            self.plan()
        self.assertNotIn("not json", str(ctx.exception))

    # --- conflicts and idempotence ---------------------------------------------

    def test_existing_identical_store_value_is_already_current_not_rewritten(self):
        self.write_keys({"tavily": SYN_TAVILY})
        self.store.set("tavily", SYN_TAVILY)
        plan = self.plan()
        self.assertEqual(self.item(plan, "tavily")["action"], "already_current")
        result = lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily"], choices={})
        self.assertEqual(self.backend.writes, ["migration-test/tavily"], "only the initial store write")
        self.assertEqual(result["written"], [])

    def test_different_store_value_is_a_conflict_that_needs_an_explicit_choice(self):
        self.write_keys({"tavily": SYN_TAVILY})
        self.store.set("tavily", SYN_OTHER)
        plan = self.plan()
        self.assertEqual(self.item(plan, "tavily")["action"], "conflict")
        with self.assertRaises(lm.MigrationError):
            lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily"], choices={})
        self.assertEqual(self.store.get("tavily"), SYN_OTHER, "conflict without a choice never overwrites")

    def test_conflict_choice_keep_existing_leaves_store_untouched(self):
        self.write_keys({"tavily": SYN_TAVILY})
        self.store.set("tavily", SYN_OTHER)
        plan = self.plan()
        result = lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily"], choices={"tavily": "keep"})
        self.assertEqual(self.store.get("tavily"), SYN_OTHER)
        self.assertEqual(result["kept"], ["tavily"])

    def test_conflict_choice_replace_writes_the_file_value(self):
        self.write_keys({"tavily": SYN_TAVILY})
        self.store.set("tavily", SYN_OTHER)
        plan = self.plan()
        result = lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily"], choices={"tavily": "replace"})
        self.assertEqual(self.store.get("tavily"), SYN_TAVILY)
        self.assertEqual(result["written"], ["tavily"])

    def test_repeating_a_completed_migration_creates_no_new_writes(self):
        self.write_keys({"tavily": SYN_TAVILY, "brave": SYN_BRAVE})
        first = lm.apply_migration(self.keys_file, self.store, self.plan(), approved=["tavily", "brave"], choices={})
        self.assertEqual(sorted(first["written"]), ["brave", "tavily"])
        writes_after_first = len(self.backend.writes)
        second_plan = self.plan()
        self.assertEqual(self.item(second_plan, "tavily")["action"], "already_current")
        second = lm.apply_migration(self.keys_file, self.store, second_plan, approved=["tavily", "brave"], choices={})
        self.assertEqual(second["written"], [])
        self.assertEqual(len(self.backend.writes), writes_after_first)

    # --- apply safety ----------------------------------------------------------

    def test_apply_refuses_when_the_file_changed_after_preview(self):
        self.write_keys({"tavily": SYN_TAVILY})
        plan = self.plan()
        self.write_keys({"tavily": SYN_OTHER})
        with self.assertRaises(lm.MigrationError):
            lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily"], choices={})
        self.assertNotIn("tavily", self.backend.entries)

    def test_apply_refuses_when_the_store_changed_after_preview(self):
        self.write_keys({"tavily": SYN_TAVILY})
        plan = self.plan()
        self.store.set("tavily", SYN_OTHER)
        with self.assertRaises(lm.MigrationError):
            lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily"], choices={"tavily": "replace"})
        self.assertEqual(self.store.get("tavily"), SYN_OTHER)

    def test_only_approved_items_are_written(self):
        self.write_keys({"tavily": SYN_TAVILY, "brave": SYN_BRAVE})
        result = lm.apply_migration(self.keys_file, self.store, self.plan(), approved=["brave"], choices={})
        self.assertEqual(result["written"], ["brave"])
        self.assertNotIn("tavily", self.backend.entries)

    def test_store_failure_is_reported_as_partial_and_never_as_complete(self):
        from multi_search_mcp.src.support.credential_store import CredentialStoreError
        self.write_keys({"tavily": SYN_TAVILY, "brave": SYN_BRAVE})
        plan = self.plan()
        self.backend.fail_write = CredentialStoreError("credential store access denied")
        result = lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily", "brave"], choices={})
        self.assertEqual(result["written"], [])
        self.assertEqual(sorted(result["failed"]), ["brave", "tavily"])
        self.assertFalse(result["complete"])
        self.assertNotIn(SYN_TAVILY, json.dumps(result))

    def test_source_file_is_never_modified_or_deleted(self):
        self.write_keys({"tavily": SYN_TAVILY, "jina": SYN_BRAVE})
        before = self.keys_file.read_bytes()
        lm.apply_migration(self.keys_file, self.store, self.plan(), approved=["tavily"], choices={})
        self.assertEqual(self.keys_file.read_bytes(), before)
        self.assertTrue(self.keys_file.exists())


class LegacyMigrationCliTests(unittest.TestCase):
    """Independent CLI path: plan, then apply with a token. Store is an injected memory backend."""

    def setUp(self):
        from unittest import mock
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.keys_file = self.dir / "search-keys.json"
        self.keys_file.write_text(json.dumps({"tavily": SYN_TAVILY, "jina": SYN_BRAVE}), encoding="utf-8")
        self.backend = MemoryBackend()
        store = CredentialStore(self.backend, namespace="migration-cli")
        patcher = mock.patch("multi_search_mcp.cli._migration_store", lambda: store)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = store

    def run_cli(self, *argv):
        import io
        from multi_search_mcp import cli
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def test_plan_then_apply_writes_approved_key_and_never_prints_it(self):
        code, out, _ = self.run_cli("migrate-legacy", "plan", "--keys-file", str(self.keys_file), "--format", "json")
        self.assertEqual(code, 0)
        self.assertNotIn(SYN_TAVILY, out)
        self.assertNotIn(SYN_BRAVE, out)
        plan = json.loads(out)
        request = self.dir / "request.json"
        request.write_text(json.dumps({"plan_token": plan["plan_token"], "approved": ["tavily"], "choices": {}}), encoding="utf-8")
        code, out, _ = self.run_cli("migrate-legacy", "apply", "--keys-file", str(self.keys_file), "--request", str(request), "--format", "json")
        self.assertEqual(code, 0)
        self.assertNotIn(SYN_TAVILY, out)
        self.assertEqual(json.loads(out)["written"], ["tavily"])
        self.assertEqual(self.store.get("tavily"), SYN_TAVILY)
        self.assertIn("jina", plan["migratable"], "Jina migration is supported without data loss")

    def test_stale_plan_token_is_refused_before_any_write(self):
        code, out, _ = self.run_cli("migrate-legacy", "plan", "--keys-file", str(self.keys_file), "--format", "json")
        token = json.loads(out)["plan_token"]
        self.keys_file.write_text(json.dumps({"tavily": SYN_OTHER}), encoding="utf-8")
        request = self.dir / "request.json"
        request.write_text(json.dumps({"plan_token": token, "approved": ["tavily"], "choices": {}}), encoding="utf-8")
        code, _, err = self.run_cli("migrate-legacy", "apply", "--keys-file", str(self.keys_file), "--request", str(request), "--format", "json")
        self.assertNotEqual(code, 0)
        self.assertNotIn(SYN_OTHER, err)
        self.assertIsNone(self.store.get("tavily"))


class MultiSourceSQLiteMigrationTests(unittest.TestCase):
    def setUp(self):
        from multi_search_mcp.src.support.credential_store import SQLiteCredentialBackend, ConfigDatabase
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "config.sqlite"
        self.backend = SQLiteCredentialBackend(self.path)
        self.store = CredentialStore(self.backend)
        self.db = ConfigDatabase(self.path)
        self.keys_file = self.root / "keys.json"
        self.settings_file = self.root / "settings.json"
        self.keys_file.write_text(json.dumps({"tavily": [SYN_TAVILY, SYN_OTHER], "jina": [{"key": SYN_BRAVE, "exhausted": True}]}), encoding="utf-8")
        self.settings_file.write_text(json.dumps({"type": "fast", "timeout": 8, "disabled_sources": ["brave"]}), encoding="utf-8")
        self.old_backend = MemoryBackend()
        self.old_store = CredentialStore(self.old_backend)
        self.old_store.set("tavily", "synthetic-legacy-manager-0011")
        self.env = {"TAVILY_API_KEY": "synthetic-environment-0012", "JINA_API_KEY": "synthetic-jina-env-0013"}
        self.options = dict(settings_file=self.settings_file, include_credentials=True,
                            include_environment=True, legacy_store=self.old_store, environ=self.env,
                            database=self.db)

    @unittest.skipUnless(__import__("sys").platform == "win32", "native DPAPI requires Windows")
    def test_all_explicit_sources_require_choice_and_preserve_sources(self):
        before = (self.keys_file.read_bytes(), self.settings_file.read_bytes(), dict(self.old_backend.entries), dict(self.env))
        plan = lm.plan_migration(self.keys_file, self.store, **self.options)
        tavily = next(i for i in plan["items"] if i["provider"] == "tavily")
        self.assertTrue(tavily["source_conflict"])
        self.assertFalse(tavily["target_conflict"])
        self.assertEqual({s["source"] for s in tavily["sources"]}, {"file", "credentials", "environment:TAVILY_API_KEY"})
        self.assertNotIn(SYN_TAVILY, json.dumps(plan))
        with self.assertRaises(lm.MigrationError):
            lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily"], choices={}, **self.options)
        result = lm.apply_migration(self.keys_file, self.store, plan,
                                   approved=["tavily", "jina", "settings"], choices={},
                                   sources={"tavily": "file", "jina": "file"}, **self.options)
        self.assertTrue(result["complete"])
        self.assertEqual(self.store.get("tavily"), [SYN_TAVILY, SYN_OTHER])
        self.assertEqual(self.store.get("jina"), [{"key": SYN_BRAVE, "exhausted": True}])
        self.assertEqual(self.db.read_settings()["type"], "fast")
        self.assertEqual(before, (self.keys_file.read_bytes(), self.settings_file.read_bytes(), self.old_backend.entries, self.env))

    def test_environment_manager_and_settings_changes_invalidate_preview(self):
        for source in ("environment", "credentials", "settings"):
            plan = lm.plan_migration(self.keys_file, self.store, **self.options)
            if source == "environment":
                self.env["TAVILY_API_KEY"] += "changed"
            elif source == "credentials":
                self.old_store.set("tavily", SYN_OTHER)
            else:
                self.settings_file.write_text('{"timeout": 10}', encoding="utf-8")
            with self.assertRaises(lm.MigrationError):
                lm.apply_migration(self.keys_file, self.store, plan, approved=[], choices={}, **self.options)
            self.assertFalse(self.path.exists())

    def test_entire_import_rolls_back_on_second_encryption_failure(self):
        from multi_search_mcp.src.support.credential_store import CredentialStoreError
        self.db.write_settings({"timeout": 3, "unrelated": True})
        original = self.db.read_settings()
        self.backend.protector = __import__("unittest").mock.Mock()
        self.backend.protector.encrypt.side_effect = [b"synthetic-ciphertext", CredentialStoreError("DPAPI encryption failed")]
        plan = lm.plan_migration(self.keys_file, self.store, settings_file=self.settings_file, database=self.db)
        result = lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily", "jina", "settings"],
                                   choices={"settings": "replace"}, settings_file=self.settings_file, database=self.db)
        self.assertEqual(result["written"], [])
        self.assertEqual(set(result["failed"]), {"tavily", "jina", "settings"})
        self.assertEqual(self.db.read_settings(), original)
        self.assertIsNone(self.store.get("tavily"))
        self.assertIsNone(self.store.get("jina"))

    @unittest.skipUnless(__import__("sys").platform == "win32", "native DPAPI requires Windows")
    def test_apply_rechecks_destination_under_transaction_lock(self):
        self.db.write_settings({"timeout": 3})
        plan = lm.plan_migration(self.keys_file, self.store, database=self.db)
        original_import = self.backend.import_batch
        def changed(values, settings, check):
            self.store.set("brave", SYN_OTHER)
            return original_import(values, settings, check)
        self.backend.import_batch = changed
        with self.assertRaises(lm.MigrationError):
            lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily"], choices={}, database=self.db)
        self.assertIsNone(self.store.get("tavily"))


if __name__ == "__main__":
    unittest.main()

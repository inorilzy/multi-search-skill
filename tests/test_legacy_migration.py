"""Explicit migration of legacy ~/.search-keys.json entries into the credential store.

Synthetic keys and a memory backend only. The real keys file, real Credential Manager, and real
user config are never touched; every path comes from a temp directory.
"""
import json
import os
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
        # The preview is an irreversible short hash: no prefix or suffix of the key.
        self.assertRegex(tavily["preview"], r"^sha256:[0-9a-f]{8}$")
        self.assertNotIn("synth", tavily["preview"])
        self.assertNotIn("0001", tavily["preview"])
        self.assertNotEqual(tavily["preview"], self.item(plan, "brave")["preview"])

    def test_mask_reveals_no_plaintext_for_any_key_length(self):
        from multi_search_mcp.src.state.key_state import key_fingerprint

        for key in ("abcdefgh", "abcdefghijkl", "tvly-" + "x" * 32, "k"):
            with self.subTest(length=len(key)):
                preview = lm.mask(key)
                self.assertRegex(preview, r"^sha256:[0-9a-f]{8}$")
                self.assertNotIn(key[:4], preview)
                self.assertNotIn(key[-4:], preview)
                # Same identifier as `keys status`, so a migrated key can be matched.
                self.assertEqual(preview, key_fingerprint(key))

    def test_single_element_list_is_accepted_as_one_key(self):
        self.write_keys({"exa": [SYN_OTHER]})
        self.assertEqual(self.item(self.plan(), "exa")["action"], "migrate")

    def test_multi_key_lists_and_jina_are_reported_unsupported_and_never_collapsed(self):
        self.write_keys({"tavily": [SYN_TAVILY, SYN_OTHER], "jina": [{"key": SYN_BRAVE, "exhausted": False}]})
        plan = self.plan()
        for provider in ("tavily", "jina"):
            item = self.item(plan, provider)
            self.assertEqual(item["action"], "unsupported", provider)
            self.assertIn("reason", item)
        self.assertNotIn("tavily", self.backend.entries)

    def test_unknown_provider_names_are_unsupported_not_guessed(self):
        self.write_keys({"mystery": SYN_TAVILY})
        self.assertEqual(self.item(self.plan(), "mystery")["action"], "unsupported")

    def test_twitter_missing_path_reference_is_unsupported_and_not_reported_usable(self):
        self.write_keys({"twitter": str(self.dir / "absent-cookies.json")})
        item = self.item(self.plan(), "twitter")
        self.assertEqual(item["action"], "unsupported")
        self.assertFalse(item["path_exists"])

    def test_twitter_existing_path_reference_is_already_current_without_reading_cookies(self):
        cookies = self.dir / "synthetic-cookies.json"
        cookies.write_text(json.dumps({"auth_token": SYN_OTHER, "ct0": SYN_BRAVE}), encoding="utf-8")
        self.write_keys({"twitter": str(cookies)})
        item = self.item(self.plan(), "twitter")
        self.assertEqual(item["action"], "already_current")
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
        self.write_keys({"tavily": SYN_TAVILY, "jina": SYN_BRAVE})
        plan = self.plan()
        self.assertEqual(plan["skipped"], ["jina"])
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

    def test_apply_reports_the_plaintext_file_it_never_deletes(self):
        self.write_keys({"tavily": SYN_TAVILY})
        os.chmod(self.keys_file, 0o600)
        plan = self.plan()
        result = lm.apply_migration(self.keys_file, self.store, plan, approved=["tavily"], choices={})
        self.assertEqual(result["written"], ["tavily"])
        self.assertEqual(result["legacy_file"], str(self.keys_file))
        self.assertTrue(result["legacy_file_has_plaintext"])
        self.assertEqual(result["warnings"], [])
        # The source is intentionally left untouched for the operator to remove.
        self.assertEqual(json.loads(self.keys_file.read_text(encoding="utf-8")), {"tavily": SYN_TAVILY})

    def test_empty_file_has_no_plaintext_reminder(self):
        self.write_keys({})
        plan = self.plan()
        result = lm.apply_migration(self.keys_file, self.store, plan, approved=[], choices={})
        self.assertFalse(result["legacy_file_has_plaintext"])

    @unittest.skipUnless(os.name == "posix", "POSIX file modes only")
    def test_permissive_keys_file_is_reported_in_plan_and_apply(self):
        self.write_keys({"tavily": SYN_TAVILY})
        os.chmod(self.keys_file, 0o644)
        try:
            plan = self.plan()
            self.assertEqual(len(plan["warnings"]), 1)
            self.assertIn("readable by other users", plan["warnings"][0])
            self.assertIn(str(self.keys_file), plan["warnings"][0])
            result = lm.apply_migration(
                self.keys_file, self.store, plan, approved=["tavily"], choices={},
            )
            self.assertEqual(result["warnings"], plan["warnings"])
            self.assertNotIn(SYN_TAVILY, json.dumps(result))

            os.chmod(self.keys_file, 0o600)
            self.assertEqual(self.plan()["warnings"], [])
        finally:
            os.chmod(self.keys_file, 0o600)

class MigrationPlanTokenTests(unittest.TestCase):
    """The token contract belongs to Core, not the CLI layer (issue 24 / L-03)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.keys_file = self.dir / "search-keys.json"
        self.keys_file.write_text(json.dumps({"tavily": SYN_TAVILY}), encoding="utf-8")
        self.store = CredentialStore(MemoryBackend(), namespace="token-test")
        self.plan = lm.plan_migration(self.keys_file, self.store)

    def test_token_is_stable_opaque_and_tracks_both_digests(self):
        token = lm.plan_token(self.plan)
        self.assertRegex(token, r"^[0-9a-f]{64}$")
        self.assertEqual(token, lm.plan_token(dict(self.plan)))
        self.assertNotIn(self.plan["source_digest"], token)
        self.assertNotIn(self.plan["store_digest"], token)

        source_changed = {**self.plan, "source_digest": "0" * 64}
        store_changed = {**self.plan, "store_digest": "0" * 64}
        self.assertNotEqual(token, lm.plan_token(source_changed))
        self.assertNotEqual(token, lm.plan_token(store_changed))
        self.assertNotEqual(
            lm.plan_token(source_changed), lm.plan_token(store_changed),
        )


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
        self.assertIn("jina", plan["skipped"], "jina skip is reported")

    def test_plan_token_is_the_core_token(self):
        code, out, _ = self.run_cli("migrate-legacy", "plan", "--keys-file", str(self.keys_file), "--format", "json")
        self.assertEqual(code, 0)
        token = json.loads(out)["plan_token"]
        core_plan = lm.plan_migration(self.keys_file, self.store)
        self.assertEqual(token, lm.plan_token(core_plan))

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

if __name__ == "__main__":
    unittest.main()

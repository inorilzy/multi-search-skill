"""T01 account storage contract: public functions and on-disk behavior only."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.plugins import accounts, oauth_store, registry
from multi_search_mcp.src.state.key_state import key_fingerprint
from multi_search_mcp.src.state.keys import KeysError, load_keys



def parallel_login_ref():
    """The balance-credential fingerprint of a Parallel login saved before login_id existed."""
    return key_fingerprint(oauth_store.balance_credential_ref("parallel_account", {}))

class AccountsStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="accounts-store-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.path = self.home / ".multi-search" / "keys.json"
        self.oauth_path = self.path.with_name("oauth.json")
        patcher = mock.patch("pathlib.Path.home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_keys(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def read_keys(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def rows(self, provider="tavily"):
        return accounts.list_accounts(provider)[provider]

    def test_missing_file_has_virtual_defaults_without_creating_storage(self):
        groups = accounts.list_accounts()
        self.assertEqual(list(groups), [plugin.id for plugin in registry.builtin_plugins()])
        for rows in groups.values():
            self.assertEqual(rows, [{"id": "default", "name": "默认账号", "source": "manual",
                                     "keys": [], "balance_credentials": {}}])
        self.assertFalse(self.path.exists())

    def test_legacy_formats_and_environment_overrides_need_no_migration(self):
        original = {
            "tavily": "synthetic-tavily-key",
            "brave": ["synthetic-brave-one", "synthetic-brave-two"],
            "jina": [{"key": "synthetic-jina-one", "exhausted": True, "note": "keep"},
                     {"key": "synthetic-jina-two", "exhausted": False}],
            "future_config": {"nested": [1, 2, 3]},
        }
        self.write_keys(original)
        before = self.path.read_bytes()
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "synthetic-env-only-key"}):
            groups = accounts.list_accounts()
        self.assertEqual(groups["tavily"][0]["keys"], [key_fingerprint(original["tavily"])])
        self.assertEqual(groups["brave"][0]["keys"], list(map(key_fingerprint, original["brave"])))
        self.assertEqual(groups["jina"][0]["keys"], [key_fingerprint(item["key"]) for item in original["jina"]])
        self.assertEqual(self.path.read_bytes(), before)
        row = accounts.create_account("jina", "  个人  ")
        self.assertRegex(row["id"], r"^acc_[A-Za-z0-9]+$")
        self.assertEqual(row, {"id": row["id"], "name": "个人", "source": "manual",
                               "keys": [], "balance_credentials": {}})
        self.assertEqual(self.read_keys(), {**original, "accounts": {"jina": [row]}})
        self.assertEqual(load_keys(environ={})["jina"], original["jina"])
        for secret in [original["tavily"], *original["brave"], *(item["key"] for item in original["jina"])]:
            self.assertNotIn(secret, json.dumps(groups))
            self.assertNotIn(secret, json.dumps(self.read_keys()["accounts"]))

    def test_explicit_paths_use_the_sibling_oauth_file(self):
        path = self.home / "custom" / "keys.json"
        path.parent.mkdir()
        oauth_path = path.with_name("oauth.json")
        token = "synthetic-custom-account-token"
        oauth_path.write_text(json.dumps({"parallel_account": {"access_token": token}}), encoding="utf-8")
        row = accounts.upsert_oauth_account(
            "parallel", "user@example.test", balance_credentials={"parallel_account": parallel_login_ref()},
            keys_file=path,
        )
        listed = accounts.list_accounts("parallel", keys_file=path)["parallel"]
        self.assertEqual(listed[1], row)
        self.assertFalse(self.path.exists())
        self.assertNotIn(token, path.read_text(encoding="utf-8"))

    def test_create_move_rename_and_old_writer_keys_preserve_unrelated_content(self):
        keys = ["synthetic-search-one", "synthetic-search-two", "synthetic-search-three"]
        self.write_keys({"tavily": keys[:2], "custom": {"keep": True}, "brave": "synthetic-brave"})
        other = accounts.create_account("brave", "Other")
        first = accounts.create_account("tavily", "First", keys=[key_fingerprint(keys[0])])
        second = accounts.create_account("tavily", "Second")
        self.assertNotEqual(first["id"], second["id"])
        moved = accounts.move_key("tavily", key_fingerprint(keys[0]), second["id"])
        self.assertEqual(moved["keys"], [key_fingerprint(keys[0])])
        self.assertEqual(self.rows()[1]["keys"], [])
        self.assertEqual(self.rows()[0]["keys"], [key_fingerprint(keys[1])])
        renamed = accounts.rename_account("tavily", second["id"], "公司 <literal>")
        self.assertEqual(renamed["name"], "公司 <literal>")
        self.assertEqual(renamed["id"], second["id"])
        self.assertEqual(renamed["source"], "manual")
        default = accounts.move_key("tavily", key_fingerprint(keys[0]), "default")
        self.assertEqual(default["keys"], list(map(key_fingerprint, keys[:2])))
        saved = self.read_keys()
        saved["tavily"].append(keys[2])  # Old writers know nothing about accounts.
        self.write_keys(saved)
        self.assertEqual(self.rows()[0]["keys"], list(map(key_fingerprint, keys)))
        accounts.rename_account("tavily", first["id"], "个人")
        final = self.read_keys()
        self.assertEqual(final["tavily"], keys)
        self.assertEqual(final["custom"], {"keep": True})
        self.assertEqual(final["accounts"]["brave"], [other])
        self.assertNotIn("default", [row["id"] for row in final["accounts"]["tavily"]])

    def test_default_cannot_be_renamed_or_deleted_and_invalid_requests_do_not_write(self):
        self.write_keys({"tavily": "synthetic-tavily"})
        row = accounts.create_account("tavily", "Personal")
        before = self.path.read_bytes()
        calls = [
            lambda: accounts.rename_account("tavily", "default", "New"),
            lambda: accounts.delete_account("tavily", "default"),
            lambda: accounts.delete_account("tavily", "default", keep_keys=False),
            lambda: accounts.rename_account("tavily", row["id"], "  "),
            lambda: accounts.create_account("tavily", "  "),
            lambda: accounts.create_account("unknown", "New"),
            lambda: accounts.list_accounts("unknown"),
            lambda: accounts.delete_account("tavily", "acc_missing"),
            lambda: accounts.delete_account("tavily", row["id"], keep_keys="false"),
            lambda: accounts.move_key("tavily", key_fingerprint("synthetic-tavily"), "acc_missing"),
            lambda: accounts.move_key("tavily", key_fingerprint("synthetic-missing"), row["id"]),
        ]
        for call in calls:
            with self.subTest(operation=call), self.assertRaises(accounts.AccountError):
                call()
            self.assertEqual(self.path.read_bytes(), before)

    def test_plaintext_cannot_be_saved_as_a_reference_or_echoed_in_errors(self):
        secret = "synthetic-private-credential"
        self.write_keys({"tavily": secret, "exa_admin": secret})
        before = self.path.read_bytes()
        calls = [
            lambda: accounts.create_account("tavily", "New", keys=[secret]),
            lambda: accounts.create_account("tavily", "New", keys=secret),
            lambda: accounts.move_key("tavily", secret, "default"),
            lambda: accounts.upsert_oauth_account("exa", balance_credentials={"exa_admin": secret}),
            lambda: accounts.create_account("exa", "New", balance_credentials={"unknown": key_fingerprint(secret)}),
        ]
        for call in calls:
            with self.subTest(operation=call), self.assertRaises(accounts.AccountError) as raised:
                call()
            self.assertNotIn(secret, str(raised.exception))
            self.assertEqual(self.path.read_bytes(), before)

    def test_stale_and_duplicate_references_are_filtered_without_read_side_effects(self):
        fp = key_fingerprint("synthetic-existing-key")
        row = {"id": "acc_first", "name": "First", "source": "manual",
               "keys": [fp, fp, key_fingerprint("synthetic-gone-key"), "not-a-fingerprint"],
               "balance_credentials": {}, "future_field": {"keep": True}}
        second = {**row, "id": "acc_second"}
        self.write_keys({"tavily": ["synthetic-existing-key"], "accounts": {"tavily": [row, second]}})
        before = self.path.read_bytes()
        rows = self.rows()
        self.assertEqual(rows[0]["keys"], [])
        self.assertEqual(rows[1]["keys"], [fp])
        self.assertEqual(rows[2]["keys"], [])
        self.assertNotIn("future_field", rows[1])
        self.assertEqual(self.path.read_bytes(), before)
        accounts.rename_account("tavily", "acc_first", "Renamed")
        self.assertEqual(self.read_keys()["accounts"]["tavily"][0]["future_field"], {"keep": True})
        saved = self.read_keys()
        saved["tavily"] = []
        self.write_keys(saved)
        self.assertEqual(self.rows()[1]["keys"], [])
        self.assertEqual(self.rows()[2]["keys"], [])

    def test_delete_keep_keys_returns_keys_to_default(self):
        value = ["synthetic-owned", "synthetic-unassigned"]
        self.write_keys({"tavily": value})
        row = accounts.create_account("tavily", "Personal", keys=[key_fingerprint(value[0])])
        removed = accounts.delete_account("tavily", row["id"], keep_keys=True)
        self.assertEqual(removed, row)
        self.assertEqual(self.rows()[0]["keys"], list(map(key_fingerprint, value)))
        self.assertEqual(self.read_keys(), {"tavily": value, "accounts": {"tavily": []}})

    def test_delete_keys_preserves_remaining_provider_entry_formats(self):
        cases = [
            ("tavily", "synthetic-owned", None),
            ("tavily", ["synthetic-owned", "synthetic-keep", "synthetic-owned"], ["synthetic-keep"]),
            ("tavily", ["synthetic-owned"], []),
            ("jina", {"key": "synthetic-owned", "exhausted": True}, None),
            ("jina", ["synthetic-owned", {"key": "synthetic-keep", "exhausted": True, "note": "keep"}],
             [{"key": "synthetic-keep", "exhausted": True, "note": "keep"}]),
            ("jina", [{"key": "synthetic-owned", "exhausted": True}, "synthetic-keep"], ["synthetic-keep"]),
        ]
        for provider, value, remaining in cases:
            with self.subTest(provider=provider, value=value):
                self.write_keys({provider: value, "custom": {"nested": ["keep"]}})
                row = accounts.create_account(provider, "Delete", keys=[key_fingerprint("synthetic-owned")])
                accounts.delete_account(provider, row["id"], keep_keys=False)
                saved = self.read_keys()
                if remaining is None:
                    self.assertNotIn(provider, saved)
                else:
                    self.assertEqual(saved[provider], remaining)
                self.assertEqual(saved["custom"], {"nested": ["keep"]})
                self.assertEqual(saved["accounts"], {provider: []})
                self.assertNotIn("synthetic-owned", self.path.read_text(encoding="utf-8"))

    def test_deleting_an_empty_account_does_not_change_keys(self):
        self.write_keys({"tavily": "synthetic-keep"})
        row = accounts.create_account("tavily", "Empty")
        accounts.delete_account("tavily", row["id"], keep_keys=False)
        self.assertEqual(self.read_keys()["tavily"], "synthetic-keep")

    def test_oauth_reuses_identity_merges_keys_and_preserves_user_name(self):
        values = ["synthetic-firecrawl-one", "synthetic-firecrawl-two"]
        self.write_keys({"firecrawl": values})
        manual = accounts.create_account("firecrawl", "user@example.test")
        first = accounts.upsert_oauth_account("firecrawl", "user@example.test", keys=[key_fingerprint(values[0])])
        self.assertEqual(first["name"], "user@example.test")
        self.assertEqual(first["source"], "oauth")
        self.assertNotEqual(first["id"], manual["id"])
        accounts.rename_account("firecrawl", first["id"], "Company")
        second = accounts.upsert_oauth_account("firecrawl", "user@example.test", name="Ignored name",
                                               keys=[key_fingerprint(values[1])])
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["name"], "Company")
        self.assertEqual(second["keys"], list(map(key_fingerprint, values)))
        third = accounts.upsert_oauth_account("firecrawl", "other@example.test")
        self.assertNotEqual(third["id"], first["id"])
        elsewhere = accounts.upsert_oauth_account("tavily", "user@example.test")
        self.assertNotEqual(elsewhere["id"], first["id"])
        self.assertEqual(self.read_keys()["firecrawl"], values)

    def test_anonymous_oauth_reuses_only_overlapping_credentials(self):
        self.write_keys({"firecrawl": ["synthetic-first", "synthetic-second"]})
        first = accounts.upsert_oauth_account("firecrawl", keys=[key_fingerprint("synthetic-first")])
        same = accounts.upsert_oauth_account("firecrawl", keys=[key_fingerprint("synthetic-first")])
        second = accounts.upsert_oauth_account("firecrawl", keys=[key_fingerprint("synthetic-second")])
        empty = accounts.upsert_oauth_account("firecrawl")
        self.assertEqual(first["id"], same["id"])
        self.assertNotIn("login_identity", first)
        self.assertEqual(first["name"], "Firecrawl 登录")
        self.assertEqual(len({first["id"], second["id"], empty["id"]}), 3)
        identified = accounts.upsert_oauth_account("firecrawl", "user@example.test",
                                                   keys=[key_fingerprint("synthetic-first")])
        self.assertEqual(identified["id"], first["id"])
        self.assertEqual(identified["login_identity"], "user@example.test")

    def test_balance_only_credentials_are_grouped_moved_and_not_revoked(self):
        token = "synthetic-parallel-token"
        admin = "synthetic-exa-admin"
        self.write_keys({"exa_admin": admin, "exa": "synthetic-exa-search"})
        self.oauth_path.write_text(json.dumps({"parallel_account": {"access_token": token}}), encoding="utf-8")
        oauth_before = self.oauth_path.read_bytes()
        exa = accounts.create_account("exa", "Company", balance_credentials={"exa_admin": key_fingerprint(admin)})
        parallel = accounts.upsert_oauth_account("parallel", "user@example.test",
                                                 balance_credentials={"parallel_account": parallel_login_ref()})
        self.assertEqual(parallel["keys"], [])
        self.assertEqual(self.rows("exa")[0]["balance_credentials"], {})
        self.assertEqual(self.rows("parallel")[1], parallel)
        default = accounts.move_key("exa", key_fingerprint(admin), "default", credential="exa_admin")
        self.assertEqual(default["balance_credentials"], {"exa_admin": key_fingerprint(admin)})
        accounts.move_key("exa", key_fingerprint(admin), exa["id"], credential="exa_admin")
        accounts.delete_account("exa", exa["id"], keep_keys=False)
        accounts.delete_account("parallel", parallel["id"], keep_keys=False)
        self.assertEqual(self.read_keys()["exa_admin"], admin)
        self.assertEqual(self.oauth_path.read_bytes(), oauth_before)
        self.assertEqual(self.rows("parallel")[0]["balance_credentials"], {"parallel_account": parallel_login_ref()})
        self.assertNotIn(token, self.path.read_text(encoding="utf-8"))

    def test_rotating_oauth_balance_reference_survives_a_token_refresh(self):
        # A refresh replaces the access token; the login reference, and so the account's
        # balance credential, the balance cache key and history, stay the same.
        self.write_keys({})
        self.oauth_path.write_text(json.dumps({"parallel_account": {"access_token": "synthetic-old-token"}}), encoding="utf-8")
        first = accounts.upsert_oauth_account("parallel", "user@example.test",
                                              balance_credentials={"parallel_account": parallel_login_ref()})
        self.oauth_path.write_text(json.dumps({"parallel_account": {"access_token": "synthetic-new-token"}}), encoding="utf-8")
        self.assertEqual(self.rows("parallel")[1]["balance_credentials"], {"parallel_account": parallel_login_ref()})
        second = accounts.upsert_oauth_account("parallel", "user@example.test",
                                               balance_credentials={"parallel_account": parallel_login_ref()})
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["balance_credentials"], {"parallel_account": parallel_login_ref()})
        self.assertNotIn(key_fingerprint("synthetic-new-token"), json.dumps(self.rows("parallel")))

    def test_corrupt_keys_and_accounts_are_never_overwritten_or_echoed(self):
        self.write_keys({})
        corruptions = [
            '{"tavily": "synthetic-private-malformed"', '[]', 'null', '"synthetic-private-malformed"',
            '{"accounts": []}', '{"accounts": {"tavily": {}}}',
            '{"accounts": {"tavily": [{"id": "default"}]}}',
        ]
        for corrupt in corruptions:
            self.path.write_text(corrupt, encoding="utf-8")
            calls = [
                lambda: accounts.list_accounts("tavily"),
                lambda: accounts.create_account("tavily", "New"),
                lambda: accounts.rename_account("tavily", "acc_missing", "New"),
                lambda: accounts.delete_account("tavily", "acc_missing"),
                lambda: accounts.move_key("tavily", key_fingerprint("synthetic-key"), "default"),
                lambda: accounts.upsert_oauth_account("tavily", "user@example.test"),
            ]
            for call in calls:
                with self.subTest(corrupt=corrupt, operation=call), self.assertRaises(KeysError) as raised:
                    call()
                self.assertNotIn("synthetic-private-malformed", str(raised.exception))
                self.assertEqual(self.path.read_text(encoding="utf-8"), corrupt)

    def test_bom_file_is_supported_and_successful_write_is_owner_only_atomic_replace(self):
        self.write_keys({"tavily": "synthetic-keep"})
        original = '\ufeff{"tavily": "synthetic-keep"}'
        self.path.write_text(original, encoding="utf-8")
        inode = self.path.stat().st_ino
        accounts.create_account("tavily", "New")
        self.assertEqual(self.read_keys()["tavily"], "synthetic-keep")
        if os.name == "posix":
            self.assertNotEqual(self.path.stat().st_ino, inode)
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual([path.name for path in self.path.parent.iterdir()], ["keys.json"])

    def test_failed_atomic_write_keeps_original_bytes_and_leaves_no_temporary_file(self):
        self.write_keys({"tavily": "synthetic-owned"})
        row = accounts.create_account("tavily", "New", keys=[key_fingerprint("synthetic-owned")])
        before = self.path.read_bytes()
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation), mock.patch(
                f"multi_search_mcp.src.state.keys.os.{operation}", side_effect=OSError("disk failure")
            ), self.assertRaises(OSError):
                accounts.delete_account("tavily", row["id"], keep_keys=False)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual([path.name for path in self.path.parent.iterdir()], ["keys.json"])


if __name__ == "__main__":
    unittest.main()

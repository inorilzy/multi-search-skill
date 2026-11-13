"""Account CLI contracts and login ownership through disposable credential files."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.plugins import login as login_module
from multi_search_mcp.src.plugins import oauth, registry
from multi_search_mcp.src.state.key_state import key_fingerprint
from tests.test_login_oauth import (
    FakeClock,
    FakeHTTP,
    FIRECRAWL_STATUS_URL,
    PARALLEL_CREATED_KEY,
    PARALLEL_DEVICE_URL,
    PARALLEL_REGISTER_URL,
    PARALLEL_TOKEN_URL,
    parallel_service_routes,
)


KEY = "fixture-account-search-key"
OTHER_KEY = "fixture-other-search-key"
IDENTITY = "owner@example.com"
DEFAULT = {"id": "default", "name": "默认账号", "source": "manual",
           "keys": [], "balance_credentials": {}}


def account_record(account_id, name="个人", *, source="manual", keys=(), balance=None, identity=None):
    record = {"id": account_id, "name": name, "source": source,
              "keys": list(keys), "balance_credentials": balance or {}}
    if identity is not None:
        record["login_identity"] = identity
    return record


class AccountsCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="accounts-cli-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        for patcher in (
            mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}),
            mock.patch("pathlib.Path.home", return_value=self.home),
            mock.patch.object(login_module, "collect_balances", return_value={"providers": []}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.keys_file = self.home / ".multi-search" / "keys.json"
        self.clock = FakeClock()
        for patcher in (mock.patch.object(oauth, "_now", self.clock.monotonic),
                        mock.patch.object(oauth, "_sleep", self.clock.sleep)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_keys(self, data):
        self.keys_file.parent.mkdir(parents=True, exist_ok=True)
        self.keys_file.write_text(json.dumps(data), encoding="utf-8")

    def read_keys(self):
        return json.loads(self.keys_file.read_text(encoding="utf-8"))

    def invoke(self, *args, key=""):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(key + "\n")):
            code = cli.main(list(args), stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def payload(self, *args, key=""):
        code, stdout, stderr = self.invoke(*args, key=key)
        self.assertEqual(code, 0, stdout + stderr)
        self.assertEqual(stderr, "")
        return json.loads(stdout)

    def add(self, provider="tavily", name="个人"):
        payload = self.payload("accounts", "add", provider, "--name", name)
        account_id = payload["account"]["id"]
        self.assertRegex(account_id, r"^acc_[A-Za-z0-9]+$")
        self.assertEqual(payload, {"provider": provider, "account": account_record(account_id, name)})
        return account_id

    def oauth_login(self, provider, routes):
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", FakeHTTP(routes)):
            code, stdout, stderr = self.invoke(
                "login", provider, "--method", "oauth", "--format", "jsonl", "--no-browser",
            )
        self.assertEqual(code, 0, stdout + stderr)
        self.assertEqual(stderr, "")
        return [json.loads(line) for line in stdout.splitlines()]

    def parallel_routes(self, access, *, identity=IDENTITY, provision=False):
        # These tests are about the balance token; key provisioning is refused unless asked for.
        return {
            **parallel_service_routes(refused=not provision),
            PARALLEL_REGISTER_URL: {"client_id": "fixture-client"},
            PARALLEL_DEVICE_URL: {"device_code": "fixture-device", "user_code": "LOGIN-1234",
                                  "verification_uri": "https://platform.parallel.ai/device", "interval": 1},
            PARALLEL_TOKEN_URL: {"access_token": access, "refresh_token": "fixture-refresh",
                                 "email": identity, "expires_in": 600},
        }

    def test_list_json_contains_virtual_default_and_only_fingerprints_without_writing(self):
        self.write_keys({"tavily": KEY})
        before = self.keys_file.read_bytes()
        self.assertEqual(self.payload("accounts", "list", "--provider", "tavily", "--format", "json"), {
            "accounts": {"tavily": [{**DEFAULT, "keys": [key_fingerprint(KEY)]}]},
        })
        self.assertEqual(self.keys_file.read_bytes(), before)

    def test_list_without_filter_contains_every_registered_provider(self):
        self.assertEqual(self.payload("accounts", "list"), {
            "accounts": {plugin.id: [DEFAULT] for plugin in registry.builtin_plugins()},
        })
        self.assertFalse(self.keys_file.exists())

    def test_add_json_matches_the_persisted_manual_account(self):
        account_id = self.add()
        self.assertEqual(self.read_keys(), {"accounts": {"tavily": [account_record(account_id)]}})

    def test_rename_json_contains_the_new_name_and_preserves_account_id(self):
        account_id = self.add()
        expected = account_record(account_id, "公司")
        self.assertEqual(self.payload("accounts", "rename", "tavily", account_id, "--name", "公司"),
                         {"provider": "tavily", "account": expected})
        self.assertEqual(self.read_keys(), {"accounts": {"tavily": [expected]}})

    def test_move_key_json_contains_destination_with_the_assigned_fingerprint(self):
        self.write_keys({"tavily": [KEY, OTHER_KEY]})
        account_id = self.add()
        expected = account_record(account_id, keys=[key_fingerprint(KEY)])
        self.assertEqual(self.payload("accounts", "move-key", "tavily", key_fingerprint(KEY), "--to", account_id),
                         {"provider": "tavily", "account": expected})
        self.assertEqual(self.payload("accounts", "list", "--provider", "tavily"), {
            "accounts": {"tavily": [{**DEFAULT, "keys": [key_fingerprint(OTHER_KEY)]}, expected]},
        })

    def test_move_key_to_default_unassigns_it_without_deleting_the_key(self):
        self.write_keys({"tavily": KEY})
        account_id = self.add()
        self.payload("accounts", "move-key", "tavily", key_fingerprint(KEY), "--to", account_id)
        self.assertEqual(self.payload("accounts", "move-key", "tavily", key_fingerprint(KEY), "--to", "default"),
                         {"provider": "tavily", "account": {**DEFAULT, "keys": [key_fingerprint(KEY)]}})
        self.assertEqual(self.read_keys(), {"tavily": KEY, "accounts": {"tavily": [account_record(account_id)]}})

    def test_remove_json_keeps_search_keys_in_default_by_default(self):
        self.write_keys({"tavily": KEY})
        account_id = self.add()
        self.payload("accounts", "move-key", "tavily", key_fingerprint(KEY), "--to", account_id)
        self.assertEqual(self.payload("accounts", "remove", "tavily", account_id), {
            "provider": "tavily", "account": account_record(account_id, keys=[key_fingerprint(KEY)]), "removed": True,
        })
        self.assertEqual(self.read_keys(), {"tavily": KEY, "accounts": {"tavily": []}})
        self.assertEqual(self.payload("accounts", "list", "--provider", "tavily"), {
            "accounts": {"tavily": [{**DEFAULT, "keys": [key_fingerprint(KEY)]}]},
        })

    def test_remove_delete_keys_deletes_only_the_removed_accounts_search_keys(self):
        self.write_keys({"tavily": [KEY, OTHER_KEY], "brave": "fixture-retained"})
        account_id = self.add()
        self.payload("accounts", "move-key", "tavily", key_fingerprint(KEY), "--to", account_id)
        self.assertEqual(self.payload("accounts", "remove", "tavily", account_id, "--delete-keys"), {
            "provider": "tavily", "account": account_record(account_id, keys=[key_fingerprint(KEY)]), "removed": True,
        })
        self.assertEqual(self.read_keys(), {"tavily": [OTHER_KEY], "brave": "fixture-retained",
                                           "accounts": {"tavily": []}})

    def test_each_subcommand_accepts_text_format(self):
        self.write_keys({"tavily": KEY})
        account_id = self.add()
        commands = [
            ("list", "--provider", "tavily"),
            ("add", "tavily", "--name", "公司"),
            ("rename", "tavily", account_id, "--name", "个人改名"),
            ("move-key", "tavily", key_fingerprint(KEY), "--to", account_id),
            ("remove", "tavily", account_id),
        ]
        for args, expected_name in zip(commands, ("个人", "公司", "个人改名", "个人改名", "个人改名")):
            with self.subTest(command=args[0]):
                code, stdout, stderr = self.invoke("accounts", *args, "--format", "text")
                self.assertEqual(code, 0, stderr)
                self.assertIn(expected_name, stdout)
                self.assertNotIn(KEY, stdout + stderr)

    def test_each_subcommand_rejects_unknown_provider_with_exit_two_without_writes(self):
        for args in (("list", "--provider", "unknown"), ("add", "unknown", "--name", "个人"),
                     ("rename", "unknown", "acc_missing", "--name", "个人"),
                     ("remove", "unknown", "acc_missing"),
                     ("move-key", "unknown", key_fingerprint(KEY), "--to", "default")):
            with self.subTest(command=args[0]):
                code, stdout, stderr = self.invoke("accounts", *args)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("unknown provider", stderr)
                self.assertFalse(self.keys_file.exists())

    def test_unknown_account_ids_exit_two_without_changing_keys(self):
        self.write_keys({"tavily": KEY})
        before = self.keys_file.read_bytes()
        for args in (("rename", "tavily", "acc_missing", "--name", "个人"),
                     ("remove", "tavily", "acc_missing"),
                     ("move-key", "tavily", key_fingerprint(KEY), "--to", "acc_missing")):
            with self.subTest(command=args[0]):
                code, stdout, stderr = self.invoke("accounts", *args)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("account not found", stderr)
                self.assertEqual(self.keys_file.read_bytes(), before)

    def test_default_account_cannot_be_renamed_or_removed(self):
        for args in (("rename", "tavily", "default", "--name", "个人"), ("remove", "tavily", "default")):
            with self.subTest(command=args[0]):
                code, stdout, stderr = self.invoke("accounts", *args)
                self.assertEqual(code, 2)
                self.assertIn("default account cannot", stderr)
                self.assertEqual(stdout, "")
                self.assertFalse(self.keys_file.exists())

    def test_api_login_assigns_new_key_to_the_requested_account(self):
        account_id = self.add()
        self.assertEqual(self.payload("login", "tavily", "--method", "api", "--account", account_id, key=KEY), {
            "provider": "tavily", "label": "Tavily", "credential": "tavily", "saved": True,
            "balance": {"providers": []},
        })
        self.assertEqual(self.read_keys(), {"tavily": KEY, "accounts": {"tavily": [
            account_record(account_id, keys=[key_fingerprint(KEY)]),
        ]}})

    def test_api_login_without_account_leaves_new_key_under_virtual_default(self):
        self.payload("login", "tavily", "--method", "api", key=KEY)
        self.assertEqual(self.read_keys(), {"tavily": KEY})
        self.assertEqual(self.payload("accounts", "list", "--provider", "tavily"), {
            "accounts": {"tavily": [{**DEFAULT, "keys": [key_fingerprint(KEY)]}]},
        })

    def test_api_login_rejects_missing_account_before_reading_or_writing_key(self):
        self.write_keys({"tavily": OTHER_KEY})
        before = self.keys_file.read_bytes()
        stdin = io.StringIO(KEY + "\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", stdin):
            code = cli.main(["login", "tavily", "--account", "acc_missing"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 2)
        self.assertEqual(stdin.tell(), 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("account not found", stderr.getvalue())
        self.assertEqual(self.keys_file.read_bytes(), before)

    def test_api_login_moves_a_duplicate_key_to_the_requested_account(self):
        self.write_keys({"tavily": KEY})
        account_id = self.add()
        payload = self.payload("login", "tavily", "--account", account_id, key=KEY)
        self.assertFalse(payload["saved"])
        self.assertEqual(self.read_keys(), {"tavily": KEY, "accounts": {"tavily": [
            account_record(account_id, keys=[key_fingerprint(KEY)]),
        ]}})

    def test_api_login_assigns_exa_admin_as_a_balance_only_fingerprint(self):
        account_id = self.add("exa")
        self.payload("login", "exa", "--credential", "exa_admin", "--account", account_id, key=KEY)
        expected = account_record(account_id, balance={"exa_admin": key_fingerprint(KEY)})
        self.assertEqual(self.payload("accounts", "list", "--provider", "exa"),
                         {"accounts": {"exa": [DEFAULT, expected]}})

    def test_oauth_rejects_explicit_account_without_starting_login(self):
        code, stdout, stderr = self.invoke("login", "firecrawl", "--method", "oauth", "--account", "default")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("only supported for api", stderr)
        self.assertFalse(self.keys_file.exists())

    def test_firecrawl_oauth_completion_exposes_persisted_account_and_its_new_key_via_list(self):
        events = self.oauth_login("firecrawl", {
            FIRECRAWL_STATUS_URL: {"status": "complete", "apiKey": KEY, "user": {"email": IDENTITY}},
        })
        self.assertEqual(events[-1], {"event": "complete", "credential": "firecrawl", "needs_search_key": False})
        account_id = self.read_keys()["accounts"]["firecrawl"][0]["id"]
        expected = account_record(account_id, IDENTITY, source="oauth", keys=[key_fingerprint(KEY)], identity=IDENTITY)
        self.assertEqual(self.payload("accounts", "list", "--provider", "firecrawl"), {
            "accounts": {"firecrawl": [DEFAULT, expected]},
        })
        self.assertEqual(self.read_keys(), {"firecrawl": KEY, "accounts": {"firecrawl": [expected]}})

    def test_firecrawl_repeat_identity_reuses_account_and_preserves_renamed_label(self):
        self.oauth_login("firecrawl", {FIRECRAWL_STATUS_URL: {"status": "complete", "apiKey": KEY, "email": IDENTITY}})
        account_id = self.read_keys()["accounts"]["firecrawl"][0]["id"]
        self.payload("accounts", "rename", "firecrawl", account_id, "--name", "公司")
        self.oauth_login("firecrawl", {
            FIRECRAWL_STATUS_URL: {"status": "complete", "apiKey": OTHER_KEY, "email": IDENTITY},
        })
        self.assertEqual(self.read_keys()["accounts"], {"firecrawl": [account_record(
            account_id, "公司", source="oauth", keys=[key_fingerprint(KEY), key_fingerprint(OTHER_KEY)], identity=IDENTITY,
        )]})

    def test_firecrawl_anonymous_repeat_with_same_key_reuses_account(self):
        routes = {FIRECRAWL_STATUS_URL: {"status": "complete", "apiKey": KEY}}
        self.oauth_login("firecrawl", routes)
        before = self.read_keys()
        self.oauth_login("firecrawl", routes)
        self.assertEqual(self.read_keys(), before)

    def test_parallel_completion_requires_search_key_and_attaches_balance_token(self):
        access = "fixture-parallel-access"
        events = self.oauth_login("parallel", self.parallel_routes(access))
        self.assertEqual(events[-1], {"event": "complete", "credential": "parallel_account", "needs_search_key": True})
        account_id = self.read_keys()["accounts"]["parallel"][0]["id"]
        self.assertEqual(self.payload("accounts", "list", "--provider", "parallel"), {
            "accounts": {"parallel": [DEFAULT, account_record(
                account_id, IDENTITY, source="oauth", identity=IDENTITY,
                balance={"parallel_account": key_fingerprint(access)},
            )]},
        })

    def test_parallel_login_creates_a_search_key_under_the_login_account(self):
        access = "fixture-parallel-access"
        events = self.oauth_login("parallel", self.parallel_routes(access, provision=True))
        self.assertEqual(events[-1], {"event": "complete", "credential": "parallel_account", "needs_search_key": False})
        account_id = self.read_keys()["accounts"]["parallel"][0]["id"]
        self.assertEqual(self.payload("accounts", "list", "--provider", "parallel"), {
            "accounts": {"parallel": [DEFAULT, account_record(
                account_id, IDENTITY, source="oauth", identity=IDENTITY,
                keys=[key_fingerprint(PARALLEL_CREATED_KEY)],
                balance={"parallel_account": key_fingerprint(access)},
            )]},
        })

    def test_parallel_repeat_identity_reuses_account_with_the_rotated_token_fingerprint(self):
        self.oauth_login("parallel", self.parallel_routes("fixture-old-access"))
        account_id = self.read_keys()["accounts"]["parallel"][0]["id"]
        self.oauth_login("parallel", self.parallel_routes("fixture-new-access"))
        self.assertEqual(self.read_keys()["accounts"], {"parallel": [account_record(
            account_id, IDENTITY, source="oauth", identity=IDENTITY,
            balance={"parallel_account": key_fingerprint("fixture-new-access")},
        )]})

    def test_account_records_only_expose_public_fields_and_never_raw_credentials_or_logs(self):
        access = "fixture-parallel-access"
        refresh = "fixture-refresh"
        with mock.patch.dict(os.environ, {"MULTI_SEARCH_DEBUG_LOG": "1"}):
            firecrawl_events = self.oauth_login("firecrawl", {
                FIRECRAWL_STATUS_URL: {"status": "complete", "apiKey": KEY, "email": IDENTITY,
                                      "access_token": "fixture-extra-token"},
            })
            parallel_events = self.oauth_login("parallel", self.parallel_routes(access))
            for output_format in ("json", "text"):
                code, stdout, stderr = self.invoke("accounts", "list", "--format", output_format)
                self.assertEqual(code, 0, stderr)
                output = stdout + stderr + json.dumps(firecrawl_events + parallel_events)
                for secret in (KEY, access, refresh, "fixture-extra-token"):
                    self.assertNotIn(secret, output)
        records = self.read_keys()["accounts"]
        for rows in records.values():
            for record in rows:
                self.assertEqual(set(record), {"id", "name", "source", "login_identity", "keys", "balance_credentials"})
        for secret in (KEY, access, refresh, "fixture-extra-token"):
            self.assertNotIn(secret, json.dumps(records))
        logs = self.home / ".multi-search" / "logs" / "runs"
        logged = "\n".join(path.read_text(encoding="utf-8") for path in logs.glob("*.jsonl"))
        for secret in (KEY, access, refresh):
            self.assertNotIn(secret, logged)

    def test_oauth_does_not_copy_a_token_returned_as_identity_into_accounts(self):
        access = "fixture-parallel-access"
        self.oauth_login("parallel", self.parallel_routes(access, identity=access))
        records = self.read_keys()["accounts"]["parallel"]
        self.assertEqual(len(records), 1)
        self.assertNotIn("login_identity", records[0])
        self.assertEqual(records[0]["name"], "Parallel 登录")
        self.assertNotIn(access, json.dumps(records))


if __name__ == "__main__":
    unittest.main()

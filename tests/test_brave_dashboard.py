"""Brave's real monthly usage comes from its API dashboard, not a local estimate.

The dashboard's SvelteKit data endpoint (devalue-encoded, streamed in chunks)
carries each plan's monthly credit, this month's requests and cost, and the days
left in the cycle. It needs the dashboard's login cookie, which the desktop's
Brave login window captures into owner-only oauth.json (or the process supplies
BRAVE_DASHBOARD_COOKIE). All HTTP here is fake; the fixture is synthetic.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.plugins import accounts, oauth_store, usage_report
from multi_search_mcp.src.plugins.balance import collect_balances
from multi_search_mcp.src.plugins.base import BalanceContext
from multi_search_mcp.src.state.key_state import key_fingerprint
from multi_search_mcp.src.state.keys import load_keys, write_keys_file_atomic
from multi_search_mcp.src.plugins.builtin import brave as brave_plugin
from multi_search_mcp.src.plugins.builtin import brave_dashboard

FIXTURE = (Path(__file__).parent / "fixtures" / "brave_dashboard_data.txt").read_text(encoding="utf-8")


PROFILE = {"id": "user-123", "email": "user@example.test", "name": "Synthetic User"}


def dashboard_with_user(user):
    """Add only synthetic user fields to the existing devalue usage fixture."""
    lines = [json.loads(line) for line in FIXTURE.splitlines()]
    data = [{"user": 1}, user]
    if isinstance(user, dict):
        data = [{"user": 1}, {key: index + 2 for index, key in enumerate(user)}, *user.values()]
    lines[0]["nodes"][1]["data"] = data
    return "\n".join(json.dumps(line) for line in lines)


class FakeResponse:
    def __init__(self, body: str, status: int = 200):
        self.body = body.encode()
        self.status = status
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amount=None):
        return self.body if amount is None else self.body[:amount]


class BraveDashboardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="brave-dashboard-")
        self.addCleanup(temporary.cleanup)
        patcher = mock.patch.dict(os.environ, {"HOME": temporary.name, "USERPROFILE": temporary.name}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(brave_dashboard.COOKIE_ENV, None)

    def test_decodes_plans_usage_and_cycle(self):
        data = brave_dashboard.parse_dashboard(FIXTURE)
        self.assertEqual(data["days_left"], 18)
        self.assertEqual({plan["name"]: (plan["credit"], plan["requests"], plan["cost"]) for plan in data["plans"]},
                         {"Search": (5, 52, 0.26), "Answers": (5, 3, 0)})

    def test_profile_keeps_only_validated_identity_fields_without_changing_quota(self):
        data = brave_dashboard.parse_dashboard(dashboard_with_user({
            **PROFILE, "billingInvoiceNotes": "private billing notes", "company": "private company",
            "cookie_header": "private cookie", "access_token": "private token",
        }))
        self.assertEqual(data["profile"], PROFILE)
        self.assertEqual(data["plans"], brave_dashboard.parse_dashboard(FIXTURE)["plans"])
        self.assertEqual(data["days_left"], 18)

    def test_missing_or_invalid_profile_does_not_discard_valid_usage(self):
        for user in (None, {}, {"email": "not-an-email"}, {
            "id": "x" * 129, "email": "user@example.test\r\nCookie: secret", "name": "bad\x00name",
        }, {"id": True, "email": ["user@example.test"], "name": {"name": "Nested"}}, {
            "id": "token=private", "email": "a" * 255 + "@example.test", "name": "Bearer private-token",
        }, {"id": "valid\u200bid", "email": "user@-example.test", "name": "bad\u202ename"}):
            with self.subTest(user=user):
                data = brave_dashboard.parse_dashboard(dashboard_with_user(user))
                self.assertFalse(data["profile"])
                self.assertTrue(data["plans"])
        data = brave_dashboard.parse_dashboard(dashboard_with_user({"email": " valid+tag@example.test ", "name": "  测试用户  "}))
        self.assertEqual(data["profile"], {"email": "valid+tag@example.test", "name": "测试用户"})

    def test_successful_saved_balance_repairs_account_without_rewriting_session_or_assigning_search_keys(self):
        record = {"cookie_header": "auth=synthetic-cookie", "login_id": "saved", "metadata": {"keep": True}}
        oauth_store.set_entry("brave_dashboard", record)
        oauth_store.set_entry("parallel_account", {"access_token": "synthetic-other-token"})
        path = Path.home() / ".multi-search" / "keys.json"
        write_keys_file_atomic(path, {"brave": ["synthetic-search-one", "synthetic-search-two"], "other": {"keep": True}})
        other = accounts.create_account("tavily", "Keep other account")
        reference = oauth_store.balance_credential_ref("brave_dashboard", record)
        before = (path.parent / "oauth.json").read_bytes()
        report = brave_plugin.balance_brave(reference, BalanceContext(http=lambda *a, **k: FakeResponse(dashboard_with_user(PROFILE))))
        self.assertEqual(report.status, "ok")
        self.assertEqual(oauth_store.get_entry("brave_dashboard"), record)
        self.assertEqual((path.parent / "oauth.json").read_bytes(), before)
        self.assertEqual(oauth_store.get_entry("parallel_account"), {"access_token": "synthetic-other-token"})
        rows = accounts.list_accounts("brave")["brave"]
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[1]["name"], rows[1]["login_identity"]), (PROFILE["name"], PROFILE["email"]))
        self.assertEqual(rows[1]["keys"], [])
        self.assertEqual(rows[1]["balance_credentials"], {"brave_dashboard": key_fingerprint(reference)})
        self.assertEqual(len(rows[0]["keys"]), 2)
        self.assertEqual(accounts.list_accounts("tavily")["tavily"][1], other)
        self.assertEqual(json.loads(path.read_text())["other"], {"keep": True})
        self.assertNotIn("synthetic-cookie", json.dumps(rows))
        self.assertNotIn(PROFILE["email"], report.message)

    def test_saved_profile_with_missing_account_is_repaired_by_a_successful_balance(self):
        record = {"cookie_header": "auth=synthetic-cookie", "login_id": "saved", "profile": PROFILE}
        oauth_store.set_entry("brave_dashboard", record)
        report = brave_plugin.balance_brave("search-key", BalanceContext(http=lambda *a, **k: FakeResponse(dashboard_with_user(PROFILE))))
        self.assertEqual(report.status, "ok")
        self.assertEqual(accounts.list_accounts("brave")["brave"][1]["login_identity"], PROFILE["email"])

    def test_a_balance_response_for_an_old_session_cannot_change_the_current_profile_or_owner(self):
        old = {"cookie_header": "auth=old-synthetic-cookie", "login_id": "old"}
        current_profile = {"id": "user-other", "email": "other@example.test", "name": "Other"}
        current = {"cookie_header": "auth=new-synthetic-cookie", "login_id": "new", "profile": current_profile}
        for credential in ("search-key", oauth_store.balance_credential_ref("brave_dashboard", old)):
            with self.subTest(credential=credential):
                oauth_store.set_entry("brave_dashboard", old)
                def http(*args, **kwargs):
                    oauth_store.set_entry("brave_dashboard", current)
                    return FakeResponse(dashboard_with_user(PROFILE))
                report = brave_plugin.balance_brave(credential, BalanceContext(http=http))
                self.assertEqual(report.status, "ok")
                self.assertEqual(oauth_store.get_entry("brave_dashboard"), current)
                self.assertEqual(len(accounts.list_accounts("brave")["brave"]), 1)

    def test_sync_never_rewrites_credentials_when_a_login_changes_after_the_reference_guard(self):
        old = {"cookie_header": "auth=old-synthetic-cookie", "login_id": "old"}
        current = {"cookie_header": "auth=new-synthetic-cookie", "login_id": "new"}
        state = {"record": old}
        reference = oauth_store.balance_credential_ref("brave_dashboard", old)
        def switch_session(*args, **kwargs):
            state["record"] = current
            return PROFILE
        def save_entry(entry, record):
            state["record"] = record
        with mock.patch.object(oauth_store, "get_entry", side_effect=lambda entry: state["record"]), \
             mock.patch.object(oauth_store, "set_entry", side_effect=save_entry) as save, \
             mock.patch.object(brave_dashboard, "_profile", side_effect=switch_session), \
             mock.patch.object(accounts, "list_accounts", return_value={"brave": []}), \
             mock.patch.object(accounts, "upsert_oauth_account", return_value={}):
            brave_dashboard.sync_account(PROFILE, reference)
        self.assertEqual(state["record"], current)
        save.assert_not_called()

    def test_sync_retains_a_manual_owner_of_the_current_balance_reference(self):
        record = {"cookie_header": "auth=synthetic-cookie", "login_id": "saved"}
        reference = oauth_store.balance_credential_ref("brave_dashboard", record)
        owner = {"id": "acc_manual", "name": "My chosen group", "source": "manual", "keys": [],
                 "balance_credentials": {"brave_dashboard": key_fingerprint(reference)}}
        with mock.patch.object(oauth_store, "get_entry", return_value=record), \
             mock.patch.object(oauth_store, "set_entry") as save, \
             mock.patch.object(accounts, "list_accounts", return_value={"brave": [owner]}), \
             mock.patch.object(accounts, "upsert_oauth_account", return_value={}) as upsert:
            result = brave_dashboard.sync_account(PROFILE, reference)
        self.assertEqual(result, owner)
        upsert.assert_not_called()
        save.assert_not_called()

    def test_balance_preserves_a_user_move_to_a_manual_account_without_writing_either_store(self):
        record = {"cookie_header": "auth=synthetic-cookie", "login_id": "saved", "profile": PROFILE}
        oauth_store.set_entry("brave_dashboard", record)
        reference = oauth_store.balance_credential_ref("brave_dashboard", record)
        fingerprint = key_fingerprint(reference)
        original = accounts.upsert_oauth_account("brave", PROFILE["email"], name="Original login",
            balance_credentials={"brave_dashboard": fingerprint})
        manual = accounts.create_account("brave", "User's selected group")
        accounts.move_key("brave", fingerprint, manual["id"], credential="brave_dashboard")
        paths = [Path.home() / ".multi-search" / filename for filename in ("keys.json", "oauth.json")]
        before = [path.read_bytes() for path in paths]
        report = brave_plugin.balance_brave(reference, BalanceContext(http=lambda *a, **k: FakeResponse(dashboard_with_user(PROFILE))))
        self.assertEqual(report.status, "ok")
        rows = accounts.list_accounts("brave")["brave"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["id"], original["id"])
        self.assertEqual(rows[1]["balance_credentials"], {})
        self.assertEqual(rows[2]["id"], manual["id"])
        self.assertEqual(rows[2]["name"], manual["name"])
        self.assertEqual(rows[2]["balance_credentials"], {"brave_dashboard": fingerprint})
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_environment_cookie_never_gets_persistent_profile_or_account_ownership(self):
        for saved in (None, {"cookie_header": "auth=saved-cookie", "login_id": "saved", "profile": PROFILE}):
            with self.subTest(saved=bool(saved)):
                if saved:
                    oauth_store.set_entry("brave_dashboard", saved)
                with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "auth=environment-cookie"}):
                    report = brave_plugin.balance_brave("search-key", BalanceContext(http=lambda *a, **k: FakeResponse(dashboard_with_user(PROFILE))))
                self.assertEqual(report.status, "ok")
                self.assertEqual(oauth_store.get_entry("brave_dashboard"), saved)
                self.assertFalse((Path.home() / ".multi-search" / "keys.json").exists())

    def test_missing_profile_does_not_fabricate_identity_or_change_an_existing_account(self):
        record = {"cookie_header": "auth=saved-cookie", "login_id": "saved", "profile": PROFILE}
        oauth_store.set_entry("brave_dashboard", record)
        reference = oauth_store.balance_credential_ref("brave_dashboard", record)
        row = accounts.upsert_oauth_account("brave", PROFILE["email"], name="Custom name",
            balance_credentials={"brave_dashboard": key_fingerprint(reference)})
        for user in (None, {"name": "Name without identity"}):
            with self.subTest(user=user):
                report = brave_plugin.balance_brave(reference, BalanceContext(http=lambda *a, **k: FakeResponse(dashboard_with_user(user))))
                self.assertEqual(report.status, "ok")
                self.assertEqual(accounts.list_accounts("brave")["brave"][1], row)
                self.assertEqual(oauth_store.get_entry("brave_dashboard"), record)

    def test_profile_cannot_copy_the_verified_cookie_value_into_an_account(self):
        record = {"cookie_header": "auth=synthetic-secret-cookie", "login_id": "saved"}
        oauth_store.set_entry("brave_dashboard", record)
        profile = {"id": "synthetic-secret-cookie", "email": "user@example.test", "name": "synthetic-secret-cookie"}
        report = brave_plugin.balance_brave("search-key", BalanceContext(http=lambda *a, **k: FakeResponse(dashboard_with_user(profile))))
        self.assertEqual(report.status, "ok")
        self.assertEqual(oauth_store.get_entry("brave_dashboard"), record)
        rows = accounts.list_accounts("brave")["brave"]
        self.assertEqual((rows[1]["name"], rows[1]["login_identity"]), ("user@example.test", "user@example.test"))
        self.assertNotIn("synthetic-secret-cookie", json.dumps(rows))

    def test_corrupt_local_storage_does_not_replace_valid_quota_or_echo_private_bodies(self):
        record = {"cookie_header": "auth=synthetic-cookie", "login_id": "saved"}
        paths = [Path.home() / ".multi-search" / filename for filename in ("keys.json", "oauth.json")]
        for path in paths:
            with self.subTest(file=path.name):
                oauth_store.set_entry("brave_dashboard", record)
                corrupt = '{"private": "synthetic-private-malformed"'
                def http(*args, **kwargs):
                    path.write_text(corrupt)
                    return FakeResponse(dashboard_with_user(PROFILE))
                report = brave_plugin.balance_brave("search-key", BalanceContext(http=http))
                self.assertEqual((report.status, report.scope), ("ok", "account"))
                self.assertAlmostEqual(report.remaining, 4.74)
                self.assertIn("账号资料暂未保存", report.message)
                self.assertNotIn("登录已失效", report.message)
                self.assertNotIn("synthetic-private-malformed", report.message)
                self.assertEqual(path.read_text(), corrupt)
                # Reset only this test's synthetic files for the next subcase.
                path.write_text("{}")

    def test_balance_reports_the_real_monthly_spend_when_a_cookie_is_given(self):
        seen = []

        def http(request, **kwargs):
            seen.append(request)
            return FakeResponse(FIXTURE)

        with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "search_api_users_auth=synthetic"}):
            report = brave_plugin.balance_brave("brave-secret", BalanceContext(http=http))
        self.assertEqual((report.status, report.unit, report.scope), ("ok", "usd", "account"))
        self.assertEqual((report.limit, report.used), (5, 0.26))
        self.assertAlmostEqual(report.remaining, 4.74)
        self.assertIn("dashboard", report.message)
        self.assertIn("52 次", report.message)
        self.assertEqual(seen[0].full_url, brave_dashboard.DATA_URL)
        self.assertEqual(seen[0].get_header("Cookie"), "search_api_users_auth=synthetic")
        self.assertNotIn("synthetic", report.message)

    def test_without_a_cookie_no_dashboard_request_is_sent(self):
        report = brave_plugin.balance_brave(
            "brave-secret", BalanceContext(http=lambda *a, **k: self.fail("no dashboard without a cookie")),
        )
        self.assertNotEqual(report.scope, "account")

    def test_a_logged_out_dashboard_falls_back_to_the_local_estimate(self):
        def http(request, **kwargs):
            return FakeResponse('{"type":"redirect","location":"/login"}')

        with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "search_api_users_auth=expired"}):
            report = brave_plugin.balance_brave("brave-secret", BalanceContext(http=http))
        self.assertNotEqual(report.scope, "account")
        self.assertIn("dashboard 登录已失效", report.message)

    def test_saved_session_is_reusable_without_a_browser_and_not_a_search_key(self):
        oauth_store.set_entry("brave_dashboard", {"cookie_header": "search_api_users_auth=saved-fixture", "login_id": "fixture"})
        self.assertEqual(brave_dashboard.cookie_header(), "search_api_users_auth=saved-fixture")
        self.assertNotIn("brave_dashboard", load_keys())
        public = accounts.list_accounts("brave")
        self.assertIn("brave_dashboard", public["brave"][0]["balance_credentials"])
        self.assertNotIn("saved-fixture", json.dumps(public))
        self.assertIn("saved-fixture", oauth_store.secret_values())
        self.assertEqual(oauth_store.balance_credentials()["brave_dashboard"], "oauth-login:brave_dashboard:fixture")

    def test_real_balance_is_cached_and_retained_in_history_for_offline_views(self):
        with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "search_api_users_auth=synthetic"}), \
             mock.patch("multi_search_mcp.src.support.http.urlopen_retry", return_value=FakeResponse(FIXTURE)) as http:
            collect_balances(["brave"], refresh=True, keys={"brave": "search-key-fixture"})
            self.assertEqual(http.call_count, 1)
            view = usage_report.collect_usage(["brave"], keys={"brave": "search-key-fixture"})["providers"][0]
            self.assertEqual(http.call_count, 1, "an offline usage view must not contact the dashboard")
        self.assertAlmostEqual(view["total"]["remaining"], 4.74)
        self.assertEqual(view["current"][0]["scope"], "account")
        self.assertEqual(view["history"][0]["scope"], "account")
        self.assertNotIn("synthetic", json.dumps(view))

    def test_cycles_and_invalid_dashboard_shapes_are_rejected(self):
        cyclic = json.dumps({"type": "data", "nodes": [{"data": [{"daysLeftInCycle": 0}]}]})
        for text in ("not JSON", cyclic, '{"type":"data","nodes":[]}', '<!doctype html><html>Login</html>'):
            with self.subTest(text=text), self.assertRaises(brave_dashboard.DashboardUnavailable):
                brave_dashboard.parse_dashboard(text)

    def test_missing_search_usage_falls_back_instead_of_making_up_zeroes(self):
        lines = [json.loads(line) for line in FIXTURE.splitlines()]
        lines[1]["data"][1] = [2]  # Answers is a separate plan, never Search credit.
        text = "\n".join(json.dumps(line) for line in lines)
        with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "search_api_users_auth=synthetic"}):
            report = brave_plugin.balance_brave("search-key", BalanceContext(http=lambda *a, **k: FakeResponse(text)))
        self.assertNotEqual(report.scope, "account")
        self.assertIn("dashboard 暂不可用", report.message)

    def test_http_auth_rejection_and_network_errors_cannot_echo_the_cookie(self):
        for error in (urllib.error.HTTPError(brave_dashboard.DATA_URL, 401, "synthetic-secret", {}, None),
                      urllib.error.URLError("synthetic-secret")):
            with self.subTest(error=type(error).__name__), mock.patch.dict(os.environ, {
                brave_dashboard.COOKIE_ENV: "search_api_users_auth=synthetic-secret",
            }):
                report = brave_plugin.balance_brave("search-key", BalanceContext(http=mock.Mock(side_effect=error)))
            self.assertNotEqual(report.scope, "account")
            self.assertNotIn("synthetic-secret", report.message)

    def test_non_finite_missing_and_boolean_costs_are_not_real_balances(self):
        for invalid in (None, True, "0.26", float("nan"), float("inf")):
            lines = [json.loads(line) for line in FIXTURE.splitlines()]
            lines[1]["data"][27] = invalid
            text = "\n".join(json.dumps(line) for line in lines)
            with self.subTest(invalid=invalid), mock.patch.dict(os.environ, {
                brave_dashboard.COOKIE_ENV: "search_api_users_auth=synthetic",
            }):
                report = brave_plugin.balance_brave("search-key", BalanceContext(http=lambda *a, **k: FakeResponse(text)))
                self.assertNotEqual(report.scope, "account")

    def test_cookie_header_injection_is_rejected_before_any_request(self):
        with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "auth=x\r\nAuthorization: injected"}):
            report = brave_plugin.balance_brave("search-key", BalanceContext(http=lambda *a, **k: self.fail("invalid header")))
        self.assertNotEqual(report.scope, "account")


if __name__ == "__main__":
    unittest.main()

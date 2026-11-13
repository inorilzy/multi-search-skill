"""Dashboard sessions own their quota identity; search keys and other logins do not."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.plugins import accounts, oauth_store, usage_report
from multi_search_mcp.src.plugins.balance import collect_balances
from multi_search_mcp.src.state.key_state import key_fingerprint
from multi_search_mcp.src.state.keys import write_keys_file_atomic
from tests.test_brave_dashboard import FIXTURE, FakeResponse


class DashboardSessionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="dashboard-sessions-")
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        patcher = mock.patch.dict(os.environ, {"HOME": temp.name, "USERPROFILE": temp.name,
                                               "BRAVE_DASHBOARD_COOKIE": "", "EXA_DASHBOARD_COOKIE": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Empty process overrides mean no override, matching a normal desktop launch.
        os.environ.pop("BRAVE_DASHBOARD_COOKIE")
        self.keys = self.home / ".multi-search" / "keys.json"

    def login(self, provider="brave_dashboard", identity="login-a"):
        record = {"cookie_header": "search_api_users_auth=synthetic-session", "login_id": identity}
        oauth_store.set_entry(provider, record)
        return oauth_store.balance_credential_ref(provider, record)

    def test_one_dashboard_read_owns_one_quota_without_attaching_it_to_each_search_key(self):
        keys = ["search-key-a", "search-key-b"]
        write_keys_file_atomic(self.keys, {"brave": keys})
        group = accounts.create_account("brave", "Search account", keys=[key_fingerprint(keys[0])])
        reference = self.login()
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", return_value=FakeResponse(FIXTURE)) as http:
            provider = collect_balances(["brave"], refresh=True)["providers"][0]
            self.assertEqual(http.call_count, 1)
        self.assertEqual(len(provider["reports"]), 1)
        self.assertEqual(provider["reports"][0]["key_fingerprint"], key_fingerprint(reference))
        self.assertNotIn(provider["reports"][0]["key_fingerprint"], [key_fingerprint(key) for key in keys])
        view = usage_report.collect_usage(["brave"])["providers"][0]
        self.assertAlmostEqual(view["total"]["remaining"], 4.74)
        saved = next(account for account in view["accounts"] if account["id"] == group["id"])
        self.assertIsNone(saved["total"]["remaining"], "an unrelated key account cannot inherit the dashboard's balance")

    def test_dashboard_login_alone_can_read_balance_without_a_search_key(self):
        self.login()
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", return_value=FakeResponse(FIXTURE)):
            report = collect_balances(["brave"], refresh=True)["providers"][0]["reports"][0]
        self.assertEqual(report["status"], "ok")
        self.assertAlmostEqual(report["remaining"], 4.74)

    def test_a_new_login_cannot_reuse_or_claim_an_old_logins_cache_or_account(self):
        first = self.login()
        owner = accounts.create_account("brave", "Old login", balance_credentials={"brave_dashboard": key_fingerprint(first)})
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", return_value=FakeResponse(FIXTURE)):
            collect_balances(["brave"], refresh=True)
        second = self.login(identity="login-b")
        view = usage_report.collect_usage(["brave"])["providers"][0]
        self.assertEqual(view["current"], [])
        self.assertIsNone(view["total"]["remaining"])
        groups = accounts.list_accounts("brave")["brave"]
        self.assertEqual(next(row for row in groups if row["id"] == owner["id"])["balance_credentials"], {})
        self.assertEqual(groups[0]["balance_credentials"], {"brave_dashboard": key_fingerprint(second)})

    def test_rejected_login_cannot_replay_the_previous_real_balance_offline(self):
        self.login()
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", return_value=FakeResponse(FIXTURE)):
            collect_balances(["brave"], refresh=True)
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", return_value=FakeResponse('{"type":"redirect","location":"/login"}')):
            current = collect_balances(["brave"], refresh=True)["providers"][0]["reports"][0]
        self.assertNotEqual(current["scope"], "account")
        self.assertIn("登录已失效", current["message"])
        view = usage_report.collect_usage(["brave"])["providers"][0]
        self.assertIsNone(view["total"]["remaining"])
        self.assertFalse(any(row["scope"] == "account" for row in view["current"]))

    def test_replacing_a_manual_service_key_does_not_assign_it_to_the_old_account(self):
        write_keys_file_atomic(self.keys, {"exa_admin": "service-key-a"})
        owner = accounts.create_account("exa", "Old admin", balance_credentials={"exa_admin": key_fingerprint("service-key-a")})
        data = json.loads(self.keys.read_text())
        data["exa_admin"] = "service-key-b"
        write_keys_file_atomic(self.keys, data)
        groups = accounts.list_accounts("exa")["exa"]
        self.assertEqual(next(row for row in groups if row["id"] == owner["id"])["balance_credentials"], {})
        self.assertEqual(groups[0]["balance_credentials"], {"exa_admin": key_fingerprint("service-key-b")})


if __name__ == "__main__":
    unittest.main()

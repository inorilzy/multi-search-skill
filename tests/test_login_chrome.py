"""Existing Chrome login saves only verified provider sessions and streams no secrets."""
from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.plugins import accounts, oauth_store
from multi_search_mcp.src.plugins.login import LoginError, login
from multi_search_mcp.src.state.key_state import key_fingerprint
from multi_search_mcp.src.state.keys import write_keys_file_atomic
from tests.test_brave_dashboard import FakeResponse, PROFILE, dashboard_with_user

SESSION = {"cookie_header": "search_api_users_auth=synthetic-private-session", "login_id": "new-session-id"}


class ChromeLoginTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="chrome-login-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        environment = mock.patch.dict(os.environ, {"HOME": temporary.name, "USERPROFILE": temporary.name,
                                                   "MULTI_SEARCH_CHROME_DEBUG_PORT": "9222"})
        environment.start()
        self.addCleanup(environment.stop)

    def run_cli(self, provider="brave", *extra):
        out, error = io.StringIO(), io.StringIO()
        code = cli.main(["login", provider, "--method", "chrome", "--format", "jsonl", *extra], stdout=out, stderr=error)
        return code, [json.loads(line) for line in out.getvalue().splitlines()], out.getvalue() + error.getvalue()

    def test_cli_reuses_capture_and_saves_only_after_read_only_quota_verification(self):
        oauth_store.set_entry("parallel_account", {"access_token": "unrelated-private-token"})
        oauth_store.set_entry("brave_dashboard", {"cookie_header": "search_api_users_auth=old-session",
                                                 "login_id": "old-id", "metadata": {"preserve": True}})
        with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session", return_value=SESSION) as capture:
            with mock.patch("multi_search_mcp.src.plugins.chrome_login._verify", return_value=None) as verify:
                code, events, output = self.run_cli("brave", "--no-browser", "--timeout", "60")
        self.assertEqual(code, 0)
        capture.assert_called_once()
        self.assertEqual(capture.call_args.args, ("brave",))
        self.assertEqual(capture.call_args.kwargs["port"], 9222)
        self.assertEqual(capture.call_args.kwargs["timeout"], 60)
        self.assertFalse(capture.call_args.kwargs["cancel_event"].is_set())
        self.assertEqual(verify.call_args.args[:2], ("brave", SESSION["cookie_header"]))
        self.assertEqual(events[-1]["event"], "complete")
        self.assertFalse(any(event["event"] == "open_url" for event in events))
        saved = oauth_store.get_entry("brave_dashboard")
        self.assertEqual(saved["login_id"], "new-session-id")
        self.assertEqual(saved["metadata"], {"preserve": True})
        self.assertEqual(oauth_store.get_entry("parallel_account")["access_token"], "unrelated-private-token")
        self.assertNotIn("synthetic-private-session", output)
        self.assertNotIn("unrelated-private-token", output)
        self.assertFalse((self.home / ".multi-search" / "keys.json").exists())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((self.home / ".multi-search" / "oauth.json").stat().st_mode), 0o600)

    def brave_login(self, session, profile=PROFILE):
        with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session", return_value=session), \
             mock.patch("multi_search_mcp.src.support.http.urlopen_retry", return_value=FakeResponse(dashboard_with_user(profile))):
            return self.run_cli("brave")

    def test_brave_verification_result_saves_private_profile_and_a_named_public_account(self):
        oauth_store.set_entry("parallel_account", {"access_token": "unrelated-private-token"})
        path = self.home / ".multi-search" / "keys.json"
        write_keys_file_atomic(path, {"brave": ["synthetic-search-one", "synthetic-search-two"], "custom": {"keep": True}})
        code, events, output = self.brave_login(SESSION)
        self.assertEqual(code, 0, output)
        self.assertEqual(events[-1]["event"], "complete")
        self.assertEqual(oauth_store.get_entry("brave_dashboard"), {**SESSION, "profile": PROFILE})
        self.assertEqual(oauth_store.get_entry("parallel_account"), {"access_token": "unrelated-private-token"})
        rows = accounts.list_accounts("brave")["brave"]
        self.assertEqual(len(rows), 2)
        account = rows[1]
        self.assertEqual((account["name"], account["login_identity"]), (PROFILE["name"], PROFILE["email"]))
        self.assertEqual(account["balance_credentials"], {"brave_dashboard": key_fingerprint(oauth_store.balance_credential_ref("brave_dashboard", SESSION))})
        self.assertEqual(account["keys"], [])
        self.assertEqual(len(rows[0]["keys"]), 2)
        self.assertEqual(json.loads(path.read_text())["custom"], {"keep": True})
        for private in (SESSION["cookie_header"], "synthetic-private-session", "unrelated-private-token", PROFILE["email"], PROFILE["name"]):
            self.assertNotIn(private, output)
        self.assertNotIn("synthetic-private-session", json.dumps(rows))
        self.assertNotIn("profile", account)

    def test_brave_profile_is_saved_in_the_same_write_as_the_captured_session(self):
        with mock.patch.object(oauth_store, "set_entry", wraps=oauth_store.set_entry) as save:
            code, _, output = self.brave_login(SESSION)
        self.assertEqual(code, 0, output)
        save.assert_called_once_with("brave_dashboard", {**SESSION, "profile": PROFILE})

    def test_saved_profile_cannot_copy_the_captured_cookie_value_even_if_verification_is_mocked(self):
        profile = {"id": "synthetic-private-session", "email": "user@example.test", "name": "synthetic-private-session"}
        with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session", return_value=SESSION), \
             mock.patch("multi_search_mcp.src.plugins.chrome_login._verify", return_value={"profile": profile}):
            code, _, output = self.run_cli("brave")
        self.assertEqual(code, 0, output)
        self.assertEqual(oauth_store.get_entry("brave_dashboard")["profile"], {"email": "user@example.test"})
        self.assertNotIn("synthetic-private-session", json.dumps(accounts.list_accounts("brave")))
        self.assertNotIn("synthetic-private-session", output)

    def test_repeated_user_reuses_account_and_custom_name_while_switching_user_moves_only_balance(self):
        self.assertEqual(self.brave_login(SESSION)[0], 0)
        first = accounts.list_accounts("brave")["brave"][1]
        accounts.rename_account("brave", first["id"], "My custom name")
        second_session = {"cookie_header": "auth=second-synthetic-cookie", "login_id": "second"}
        self.assertEqual(self.brave_login(second_session)[0], 0)
        rows = accounts.list_accounts("brave")["brave"]
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[1]["id"], rows[1]["name"]), (first["id"], "My custom name"))
        self.assertEqual(rows[1]["balance_credentials"], {"brave_dashboard": key_fingerprint(oauth_store.balance_credential_ref("brave_dashboard", second_session))})
        third_session = {"cookie_header": "auth=third-synthetic-cookie", "login_id": "third"}
        profile = {"id": "user-456", "email": "other@example.test", "name": "Other User"}
        self.assertEqual(self.brave_login(third_session, profile)[0], 0)
        rows = accounts.list_accounts("brave")["brave"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["id"], first["id"])
        self.assertEqual(rows[1]["balance_credentials"], {})
        self.assertEqual(rows[1]["name"], "My custom name")
        self.assertNotEqual(rows[2]["id"], first["id"])
        self.assertEqual(rows[2]["login_identity"], profile["email"])
        self.assertEqual(rows[2]["balance_credentials"], {"brave_dashboard": key_fingerprint(oauth_store.balance_credential_ref("brave_dashboard", third_session))})
        self.assertEqual(oauth_store.get_entry("brave_dashboard")["profile"], profile)

    def test_new_login_without_profile_does_not_inherit_the_previous_user(self):
        self.assertEqual(self.brave_login(SESSION)[0], 0)
        first = accounts.list_accounts("brave")["brave"][1]
        session = {"cookie_header": "auth=unidentified-synthetic-cookie", "login_id": "unidentified"}
        code, _, output = self.brave_login(session, None)
        self.assertEqual(code, 0, output)
        self.assertNotIn("profile", oauth_store.get_entry("brave_dashboard"))
        rows = accounts.list_accounts("brave")["brave"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["login_identity"], first["login_identity"])
        self.assertEqual(rows[1]["balance_credentials"], {})

    def test_id_only_profile_can_create_an_account_without_fabricating_email(self):
        profile = {"id": "user-123", "name": "Synthetic User"}
        code, _, output = self.brave_login(SESSION, profile)
        self.assertEqual(code, 0, output)
        row = accounts.list_accounts("brave")["brave"][1]
        self.assertEqual(row["login_identity"], "brave-user:user-123")
        self.assertEqual(row["name"], profile["name"])
        self.assertNotIn("@", json.dumps(row))

    def test_account_storage_failure_reports_saved_session_without_exposing_private_data(self):
        path = self.home / ".multi-search" / "keys.json"
        path.parent.mkdir()
        corrupt = '{"private": "synthetic-private-malformed"'
        path.write_text(corrupt)
        code, events, output = self.brave_login(SESSION)
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]["error_kind"], "storage")
        self.assertIn("会话已保存", events[-1]["message"])
        self.assertIn("账号资料保存失败", events[-1]["message"])
        self.assertFalse(any(event["event"] == "complete" for event in events))
        self.assertEqual(oauth_store.get_entry("brave_dashboard"), {**SESSION, "profile": PROFILE})
        self.assertEqual(path.read_text(), corrupt)
        for secret in ("synthetic-private-session", "synthetic-private-malformed", PROFILE["email"]):
            self.assertNotIn(secret, output)

    def test_exa_uses_web_entry_without_touching_a_manual_management_key(self):
        path = self.home / ".multi-search" / "keys.json"
        path.parent.mkdir()
        path.write_text('{"exa_admin":"synthetic-service-key"}')
        session = {"cookie_header": "__Secure-next-auth.session-token=synthetic-private-session", "login_id": "exa-id"}
        with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session", return_value=session):
            with mock.patch("multi_search_mcp.src.plugins.chrome_login._verify", return_value=None):
                code, events, output = self.run_cli("exa")
        self.assertEqual(code, 0)
        self.assertEqual(events[-1]["credential"], "exa_admin")
        self.assertEqual(oauth_store.get_entry("exa_admin"), session)
        self.assertEqual(json.loads(path.read_text()), {"exa_admin": "synthetic-service-key"})
        self.assertNotIn("synthetic-private-session", output)

    def test_failed_verification_neither_overwrites_a_session_nor_echoes_an_exception(self):
        oauth_store.set_entry("brave_dashboard", {"login_id": "old-id", "cookie_header": "old-secret"})
        with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session", return_value=SESSION):
            with mock.patch("multi_search_mcp.src.plugins.chrome_login._verify", side_effect=ValueError(SESSION["cookie_header"])):
                code, events, output = self.run_cli()
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]["error_kind"], "verification")
        self.assertEqual(oauth_store.get_entry("brave_dashboard")["login_id"], "old-id")
        self.assertNotIn("synthetic-private-session", output)

    def test_quota_rate_limit_preserves_login_without_claiming_verified_quota(self):
        from multi_search_mcp.src.plugins.builtin.exa_dashboard import DashboardUnavailable
        with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session", return_value=SESSION):
            with mock.patch("multi_search_mcp.src.plugins.chrome_login._verify", side_effect=DashboardUnavailable("limited", "rate_limit")):
                code, events, output = self.run_cli("exa")
        self.assertEqual(code, 0)
        self.assertEqual(events[-1]["event"], "complete")
        self.assertIn("限流", events[-1]["message"])
        self.assertNotIn("额度查询已验证", events[-1]["message"])
        self.assertEqual(oauth_store.get_entry("exa_admin"), SESSION)
        self.assertNotIn("synthetic-private-session", output)

    def test_invalid_port_does_not_contact_chrome(self):
        with mock.patch.dict(os.environ, {"MULTI_SEARCH_CHROME_DEBUG_PORT": "http://evil.test:9222"}):
            with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session") as capture:
                code, events, _ = self.run_cli()
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]["error_kind"], "invalid")
        capture.assert_not_called()

    def test_cancellation_does_not_save(self):
        from multi_search_mcp.src.plugins.chrome_session import ChromeSessionCancelled
        with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session", side_effect=ChromeSessionCancelled()):
            code, events, _ = self.run_cli()
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]["error_kind"], "cancelled")
        self.assertFalse((self.home / ".multi-search" / "oauth.json").exists())

    def test_unsupported_provider_or_credential_and_format_fail_before_capture(self):
        for provider, options in (("parallel", {}), ("brave", {"credential": "brave"}),
                                  ("exa", {"account_id": "default"}), ("brave", {"output_format": "json"})):
            with self.subTest(provider=provider, options=options):
                with self.assertRaises(LoginError):
                    login(provider, method="chrome", **options)


if __name__ == "__main__":
    unittest.main()

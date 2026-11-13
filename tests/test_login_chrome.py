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
from multi_search_mcp.src.plugins import oauth_store
from multi_search_mcp.src.plugins.login import LoginError, login

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
            with mock.patch("multi_search_mcp.src.plugins.chrome_login._verify") as verify:
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

    def test_exa_uses_web_entry_without_touching_a_manual_management_key(self):
        path = self.home / ".multi-search" / "keys.json"
        path.parent.mkdir()
        path.write_text('{"exa_admin":"synthetic-service-key"}')
        session = {"cookie_header": "__Secure-next-auth.session-token=synthetic-private-session", "login_id": "exa-id"}
        with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session", return_value=session):
            with mock.patch("multi_search_mcp.src.plugins.chrome_login._verify"):
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

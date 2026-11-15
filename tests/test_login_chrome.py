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


def devalue(value):
    """Flatten a value the way SvelteKit's devalue does: each container refers to entries by index."""
    data = []

    def put(item):
        index = len(data)
        data.append(None)
        if isinstance(item, dict):
            data[index] = {key: put(child) for key, child in item.items()}
        elif isinstance(item, list):
            data[index] = [put(child) for child in item]
        else:
            data[index] = item
        return index

    put(value)
    return data


def brave_keys_page(tokens=(), subscriptions=()):
    nodes = [{"type": "data", "data": devalue({"csrf": "synthetic-csrf", "user": PROFILE})},
             {"type": "data", "data": devalue({"tokens": list(tokens), "subscriptions": list(subscriptions)})}]
    return json.dumps({"type": "data", "nodes": nodes})


def brave_token(token, plan="Search", **extra):
    return {"token": token, "status": "active", "deleted_at": None, "name": token[:8], "plan": {"name": plan}, **extra}


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
             mock.patch("multi_search_mcp.src.plugins.chrome_login._verify", return_value={"profile": profile}), \
             mock.patch("multi_search_mcp.src.plugins.builtin.brave_dashboard.link_account_keys", return_value=None):
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

    def brave_key_login(self, keys_page, saved_keys=None, add_reply=None, groups=None):
        """Log in to Brave against a fake dashboard whose API keys page is ``keys_page``."""
        from multi_search_mcp.src.plugins.builtin import brave_dashboard
        if saved_keys is not None:
            write_keys_file_atomic(self.home / ".multi-search" / "keys.json", {"brave": saved_keys})
        if groups:
            groups()
        posts = []

        def http(request, timeout, retries, deadline=None):
            self.assertEqual(retries, 0)
            if request.full_url == brave_dashboard.ADD_KEY_URL:
                posts.append(request)
                return FakeResponse(json.dumps(add_reply))
            if request.full_url == brave_dashboard.KEYS_DATA_URL:
                return FakeResponse(keys_page)
            return FakeResponse(dashboard_with_user(PROFILE))

        with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session", return_value=SESSION), \
             mock.patch("multi_search_mcp.src.support.http.urlopen_retry", side_effect=http):
            code, events, output = self.run_cli("brave")
        self.assertEqual(code, 0, output)
        self.assertEqual(events[-1]["event"], "complete")
        rows = accounts.list_accounts("brave")["brave"]
        return rows, events[-1]["message"], posts, output

    def test_brave_login_links_a_saved_key_listed_on_the_keys_page(self):
        page = brave_keys_page([brave_token("synthetic-search-key")])
        rows, message, posts, output = self.brave_key_login(page, ["other-synthetic-key", "synthetic-search-key"])
        self.assertEqual(rows[1]["keys"], [key_fingerprint("synthetic-search-key")])
        self.assertEqual(rows[0]["keys"], [key_fingerprint("other-synthetic-key")])
        self.assertEqual(posts, [])
        self.assertNotIn("自动", message)
        self.assertNotIn("synthetic-search-key", output)

    def test_brave_login_saves_the_first_live_search_key_and_skips_other_plans(self):
        page = brave_keys_page([
            brave_token("synthetic-answers-key", plan="Answers"),
            brave_token("synthetic-deleted-key", deleted_at="2026-11-01T00:00:00Z"),
            brave_token("synthetic-first-search-key"), brave_token("synthetic-second-search-key"),
        ])
        rows, _, posts, output = self.brave_key_login(page)
        self.assertEqual(rows[1]["keys"], [key_fingerprint("synthetic-first-search-key")])
        saved = json.loads((self.home / ".multi-search" / "keys.json").read_text())["brave"]
        self.assertEqual(saved, "synthetic-first-search-key")
        self.assertEqual(posts, [])
        self.assertNotIn("synthetic-first-search-key", output)

    def test_brave_login_adds_a_key_to_a_search_subscription_without_one(self):
        page = brave_keys_page([brave_token("synthetic-answers-key", plan="Answers")], [
            {"id": "sub-answers", "status": "active", "deleted_at": None, "plan": {"name": "Answers"}},
            {"id": "sub-search", "status": "active", "deleted_at": None, "plan": {"name": "Search"}},
        ])
        reply = {"type": "success", "status": 200, "data": json.dumps(devalue({"token": "synthetic-created-key"}))}
        rows, message, posts, output = self.brave_key_login(page, add_reply=reply)
        self.assertEqual(rows[1]["keys"], [key_fingerprint("synthetic-created-key")])
        self.assertEqual(len(posts), 1)
        form = dict(item.split("=", 1) for item in posts[0].data.decode().split("&"))
        self.assertEqual(form, {"csrf": "synthetic-csrf", "subscription_id": "sub-search", "name": "multi-search"})
        self.assertEqual(posts[0].get_header("Origin"), "https://api-dashboard.search.brave.com")
        self.assertIn("已自动创建", message)
        self.assertNotIn("synthetic-created-key", output)

    def test_brave_login_never_subscribes_when_no_search_plan_exists(self):
        page = brave_keys_page([], [{"id": "sub-answers", "status": "active", "deleted_at": None, "plan": {"name": "Answers"}}])
        rows, message, posts, _ = self.brave_key_login(page)
        self.assertEqual(posts, [])
        self.assertEqual(rows[1]["keys"], [])
        self.assertIn("订阅", message)

    def test_brave_login_keeps_a_key_the_user_grouped_elsewhere(self):
        def group():
            accounts.create_account("brave", "Manual", keys=[key_fingerprint("synthetic-search-key")])
        page = brave_keys_page([brave_token("synthetic-search-key")])
        rows, _, _, _ = self.brave_key_login(page, ["synthetic-search-key"], groups=group)
        manual = next(row for row in rows if row["name"] == "Manual")
        login = next(row for row in rows if row["source"] == "oauth")
        self.assertEqual((manual["keys"], login["keys"]), ([key_fingerprint("synthetic-search-key")], []))

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

    EXA_SESSION = {"cookie_header": "__Secure-next-auth.session-token=synthetic-private-session", "login_id": "exa-id"}
    EXA_USER = {"id": "cmuser123", "email": "exa-user@example.test", "name": "Exa User"}

    def exa_login(self, routes, saved_keys=None):
        """Run an Exa Chrome login against fake dashboard routes: url -> body or callable(request)."""
        from multi_search_mcp.src.plugins.builtin import exa_dashboard
        if saved_keys is not None:
            write_keys_file_atomic(self.home / ".multi-search" / "keys.json", {"exa": saved_keys})
        requests = []

        def http(request, timeout, retries, deadline=None):
            requests.append((request, retries))
            body = routes[request.full_url]
            if isinstance(body, BaseException):
                raise body
            return FakeResponse(json.dumps(body(request) if callable(body) else body))

        routes = {exa_dashboard.SESSION_URL: {"user": self.EXA_USER}, **routes}
        with mock.patch("multi_search_mcp.src.plugins.chrome_session.capture_session", return_value=self.EXA_SESSION), \
             mock.patch("multi_search_mcp.src.plugins.chrome_login._verify", return_value={"remaining": 10.0, "billing_exempt": False}), \
             mock.patch("multi_search_mcp.src.support.http.urlopen_retry", side_effect=http):
            code, events, output = self.run_cli("exa")
        self.assertEqual(code, 0, output)
        self.assertEqual(events[-1]["event"], "complete")
        named = [row for row in accounts.list_accounts("exa")["exa"] if row["id"] != accounts.DEFAULT_ACCOUNT_ID]
        self.assertEqual(len(named), 1)
        self.assertNotIn("synthetic-private-session", output)
        return named[0], events[-1]["message"], [request for request, _ in requests], output

    def assert_exa_account(self, account, keys):
        self.assertEqual((account["source"], account["login_identity"], account["name"]),
                         ("oauth", self.EXA_USER["email"], self.EXA_USER["name"]))
        self.assertEqual(account["keys"], [key_fingerprint(key) for key in keys])
        self.assertEqual(account["balance_credentials"],
                         {"exa_admin": key_fingerprint(oauth_store.balance_credential_ref("exa_admin", self.EXA_SESSION))})

    def test_exa_login_links_saved_keys_by_bearer_prefix_without_revealing(self):
        from multi_search_mcp.src.plugins.builtin import exa_dashboard
        listed = {"apiKeys": [{"publicId": "key_one", "bearerPrefix": "e648e0", "hasLegacyBearer": True}]}
        account, message, requests, output = self.exa_login(
            {exa_dashboard.KEYS_URL: listed}, ["other-synthetic-key", "e648e0-synthetic-search-key"])
        self.assert_exa_account(account, ["e648e0-synthetic-search-key"])
        self.assertEqual([r.full_url for r in requests], [exa_dashboard.SESSION_URL, exa_dashboard.KEYS_URL])
        default = accounts.list_accounts("exa")["exa"][0]
        self.assertEqual(default["keys"], [key_fingerprint("other-synthetic-key")])
        self.assertNotIn("自动", message)
        self.assertNotIn("e648e0-synthetic-search-key", output)

    def test_exa_login_reveals_the_first_usable_key_and_saves_it(self):
        from multi_search_mcp.src.plugins.builtin import exa_dashboard
        listed = {"apiKeys": [
            {"publicId": "key_vercel", "bearerPrefix": "aaaaaa", "managedBy": "vercel", "hasLegacyBearer": True},
            {"publicId": "key_new_format", "bearerPrefix": "exa_bb", "hasLegacyBearer": False},
            {"publicId": "key_first", "bearerPrefix": "cccccc", "hasLegacyBearer": True},
        ]}
        reveal = mock.Mock(return_value={"legacyBearerSecret": "cccccc-revealed-synthetic-key"})
        account, _, requests, output = self.exa_login(
            {exa_dashboard.KEYS_URL: listed, exa_dashboard.REVEAL_URL: reveal}, ["unrelated-synthetic-key"])
        self.assert_exa_account(account, ["cccccc-revealed-synthetic-key"])
        posted = reveal.call_args.args[0]
        self.assertEqual((posted.get_method(), json.loads(posted.data)), ("POST", {"publicId": "key_first"}))
        self.assertTrue(posted.get_header("Idempotency-key"))
        saved = json.loads((self.home / ".multi-search" / "keys.json").read_text())["exa"]
        self.assertEqual(saved, ["unrelated-synthetic-key", "cccccc-revealed-synthetic-key"])
        self.assertNotIn("cccccc-revealed-synthetic-key", output)

    def test_exa_login_creates_one_key_for_a_team_without_keys_and_reuses_it_next_time(self):
        from multi_search_mcp.src.plugins.builtin import exa_dashboard
        create = mock.Mock(return_value={"apiKey": {"bearer": "dddddd-created-synthetic-key"}})
        account, message, _, output = self.exa_login(
            {exa_dashboard.KEYS_URL: {"apiKeys": []}, exa_dashboard.CREATE_URL: create})
        self.assert_exa_account(account, ["dddddd-created-synthetic-key"])
        posted = create.call_args.args[0]
        self.assertEqual(json.loads(posted.data), {"apiKeyName": exa_dashboard.NEW_KEY_NAME})
        self.assertTrue(posted.get_header("Idempotency-key"))
        self.assertIn("已自动创建", message)
        self.assertNotIn("dddddd-created-synthetic-key", output)
        listed = {"apiKeys": [{"publicId": "key_made", "bearerPrefix": "dddddd", "hasLegacyBearer": True}]}
        again, _, requests, _ = self.exa_login({exa_dashboard.KEYS_URL: listed, exa_dashboard.CREATE_URL: create})
        self.assertEqual(again["id"], account["id"])
        self.assertEqual(create.call_count, 1)
        self.assertNotIn(exa_dashboard.REVEAL_URL, [r.full_url for r in requests])

    def test_exa_login_never_creates_a_key_when_existing_keys_cannot_be_revealed(self):
        from multi_search_mcp.src.plugins.builtin import exa_dashboard
        create = mock.Mock()
        listed = {"apiKeys": [{"publicId": "key_new_format", "bearerPrefix": "exa_bb", "hasLegacyBearer": False}]}
        account, message, _, _ = self.exa_login({exa_dashboard.KEYS_URL: listed, exa_dashboard.CREATE_URL: create})
        self.assert_exa_account(account, [])
        create.assert_not_called()
        self.assertIn("手动添加", message)

    def test_exa_key_lookup_failure_keeps_login_and_account_with_a_fixed_notice(self):
        import urllib.error
        from multi_search_mcp.src.plugins.builtin import exa_dashboard
        failure = urllib.error.HTTPError(exa_dashboard.KEYS_URL, 500, "synthetic-private-session", {}, None)
        account, message, _, output = self.exa_login(
            {exa_dashboard.SESSION_URL: urllib.error.URLError("down"), exa_dashboard.KEYS_URL: failure}, [])
        self.assertEqual((account["name"], account["keys"]), ("Exa 控制台登录", []))
        self.assertIn("自动获取搜索 Key 失败", message)
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

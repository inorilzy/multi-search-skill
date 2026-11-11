"""API login/logout CLI and the Exa Team Management balance credential (ticket 06).

Every case drives the real CLI entry point against a temporary HOME. Exa HTTP
calls are replaced with a recording fake, so the suite never touches the
network and each stdout/stderr assertion proves the plaintext key never leaks.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.plugins import login as login_module
from multi_search_mcp.src.state.keys import CREDENTIAL_STORE_PROVIDERS, KEY_ENV_PAIRS


class FakeResponse:
    """Minimal urllib response: context manager plus bounded ``read``."""

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = {"Content-Length": str(len(self.body))}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, amount=None):
        if amount is None or amount < 0:
            return self.body
        return self.body[:amount]


class RecordingHTTP:
    """Fake ``BalanceContext.http`` that records every request it receives."""

    def __init__(self, result):
        self.result = result
        self.requests = []

    def __call__(self, request, *, timeout, retries, deadline):
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def http_error(status, body=b"", url="https://admin-api.exa.ai/team-management/credits"):
    return urllib.error.HTTPError(url, status, "error", {}, io.BytesIO(body))


class LoginApiTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="login-api-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        env_patcher = mock.patch.dict(os.environ, {
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "TAVILY_API_KEY": "",
            "EXA_API_KEY": "",
            "EXA_SERVICE_KEY": "",
            "JINA_API_KEY": "",
            "JINA_KEY": "",
        })
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        home_patcher = mock.patch("pathlib.Path.home", return_value=self.home)
        home_patcher.start()
        self.addCleanup(home_patcher.stop)
        self.keys_file = self.home / ".multi-search" / "keys.json"

    def write_keys(self, data):
        self.keys_file.parent.mkdir(parents=True, exist_ok=True)
        self.keys_file.write_text(json.dumps(data), encoding="utf-8")

    def read_keys(self):
        return json.loads(self.keys_file.read_text(encoding="utf-8"))

    def run_cli(self, argv, stdin_text=""):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin_text)):
            code = cli.main(argv, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_streams_do_not_contain(self, secret, stdout, stderr):
        self.assertNotIn(secret, stdout)
        self.assertNotIn(secret, stderr)


class LoginApiWriteTests(LoginApiTestCase):
    def test_login_appends_a_new_key_and_turns_a_string_entry_into_a_list(self):
        self.write_keys({"tavily": "existing-key", "brave": "keep-brave"})
        key = "new-tavily-key-123"

        with mock.patch.object(login_module, "collect_balances", return_value={"providers": []}):
            code, stdout, stderr = self.run_cli(
                ["login", "tavily", "--method", "api"], stdin_text=f" {key} \n"
            )

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual((payload["provider"], payload["credential"], payload["saved"]),
                         ("tavily", "tavily", True))
        self.assertEqual(self.read_keys(), {"tavily": ["existing-key", key], "brave": "keep-brave"})
        self.assert_streams_do_not_contain(key, stdout, stderr)

    def test_login_does_not_duplicate_an_existing_key(self):
        self.write_keys({"tavily": ["key-one", "key-two"]})

        with mock.patch.object(login_module, "collect_balances", return_value={"providers": []}):
            code, stdout, stderr = self.run_cli(
                ["login", "tavily", "--method", "api"], stdin_text="key-two\n"
            )

        self.assertEqual(code, 0, stderr)
        self.assertFalse(json.loads(stdout)["saved"])
        self.assertEqual(self.read_keys(), {"tavily": ["key-one", "key-two"]})

    def test_login_preserves_the_jina_key_exhausted_format(self):
        self.write_keys({"jina": ["old-jina-key"], "brave": "keep-brave"})
        key = "new-jina-key"

        with mock.patch.object(login_module, "collect_balances", return_value={"providers": []}):
            code, stdout, stderr = self.run_cli(
                ["login", "jina", "--method", "api"], stdin_text=f"{key}\n"
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.read_keys(), {
            "jina": [
                {"key": "old-jina-key", "exhausted": False},
                {"key": key, "exhausted": False},
            ],
            "brave": "keep-brave",
        })
        self.assert_streams_do_not_contain(key, stdout, stderr)

    def test_login_does_not_duplicate_an_existing_jina_key(self):
        self.write_keys({"jina": [{"key": "jina-key", "exhausted": True}]})

        with mock.patch.object(login_module, "collect_balances", return_value={"providers": []}):
            code, stdout, _stderr = self.run_cli(
                ["login", "jina", "--method", "api"], stdin_text="jina-key\n"
            )

        self.assertEqual(code, 0)
        self.assertFalse(json.loads(stdout)["saved"])
        self.assertEqual(self.read_keys(), {"jina": [{"key": "jina-key", "exhausted": True}]})

    def test_login_refuses_to_overwrite_a_corrupt_keys_file(self):
        self.keys_file.parent.mkdir(parents=True, exist_ok=True)
        corrupt = '{"tavily": "EXISTING-PRIVATE-KEY"'
        self.keys_file.write_text(corrupt, encoding="utf-8")
        key = "do-not-write-this-key"

        code, stdout, stderr = self.run_cli(["login", "baidu"], stdin_text=f"{key}\n")

        self.assertEqual(code, 1)
        self.assertIn("keys file is not valid JSON", stdout + stderr)
        self.assertEqual(self.keys_file.read_text(encoding="utf-8"), corrupt)
        self.assert_streams_do_not_contain(key, stdout, stderr)

    def test_login_refuses_to_overwrite_a_non_object_keys_file(self):
        self.keys_file.parent.mkdir(parents=True, exist_ok=True)
        self.keys_file.write_text("[]", encoding="utf-8")

        code, stdout, stderr = self.run_cli(["login", "baidu"], stdin_text="private-key\n")

        self.assertEqual(code, 1)
        self.assertIn("not a JSON object", stdout + stderr)
        self.assertEqual(self.keys_file.read_text(encoding="utf-8"), "[]")
        self.assertNotIn("private-key", stdout + stderr)

    def test_login_reads_a_tty_key_with_getpass(self):
        stream = mock.Mock()
        stream.isatty.return_value = True
        key = "tty-private-key"

        with (
            mock.patch("sys.stdin", stream),
            mock.patch.object(login_module.getpass, "getpass", return_value=f" {key} ") as prompt,
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            code = cli.main(["login", "baidu"], stdout=stdout, stderr=stderr)

        self.assertEqual(code, 0, stderr.getvalue())
        prompt.assert_called_once()
        stream.readline.assert_not_called()
        self.assertEqual(self.read_keys(), {"baidu": key})
        self.assert_streams_do_not_contain(key, stdout.getvalue(), stderr.getvalue())

    def test_login_rejects_oauth_with_exit_code_two(self):
        code, stdout, stderr = self.run_cli(["login", "tavily", "--method", "oauth"])

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("尚未支持", stderr)
        self.assertFalse(self.keys_file.exists())

    def test_login_rejects_an_undeclared_credential_with_exit_code_two(self):
        code, stdout, stderr = self.run_cli(
            ["login", "tavily", "--credential", "not-declared", "--method", "api"],
            stdin_text="key\n",
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("not-declared", stderr)
        self.assertFalse(self.keys_file.exists())

    def test_login_never_writes_the_key_to_the_debug_log(self):
        key = "debug-log-private-key"
        with mock.patch.dict(os.environ, {"MULTI_SEARCH_DEBUG_LOG": "1"}):
            code, stdout, stderr = self.run_cli(["login", "baidu"], stdin_text=f"{key}\n")

        self.assertEqual(code, 0, stderr)
        logs = self.home / ".multi-search" / "logs" / "runs"
        logged = "\n".join(path.read_text(encoding="utf-8") for path in logs.glob("*.jsonl")) if logs.exists() else ""
        self.assertNotIn(key, logged)
        self.assert_streams_do_not_contain(key, stdout, stderr)


class LogoutTests(LoginApiTestCase):
    def test_logout_removes_the_entry_and_preserves_other_entries(self):
        self.write_keys({"tavily": ["key-one", "key-two"], "brave": "keep-brave"})

        code, stdout, stderr = self.run_cli(["logout", "tavily"])

        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout), {
            "provider": "tavily", "credential": "tavily", "removed": True,
        })
        self.assertEqual(self.read_keys(), {"brave": "keep-brave"})

    def test_logout_of_a_missing_entry_reports_but_exits_zero(self):
        self.write_keys({"brave": "keep-brave"})

        code, stdout, stderr = self.run_cli(["logout", "tavily"])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertFalse(payload["removed"])
        self.assertIn("未找到", payload["message"])
        self.assertEqual(self.read_keys(), {"brave": "keep-brave"})


class ExaBalanceTests(LoginApiTestCase):
    def test_exa_admin_is_a_balance_only_credential_not_a_search_key_pool(self):
        self.assertIn(("EXA_SERVICE_KEY", "exa_admin"), KEY_ENV_PAIRS)
        self.assertNotIn("exa_admin", CREDENTIAL_STORE_PROVIDERS)

    def test_login_reads_credits_usd_from_the_exa_admin_endpoint(self):
        http = RecordingHTTP(FakeResponse({"credits_usd": 42.5}))
        key = "exa-service-key-123"

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "exa", "--credential", "exa_admin", "--method", "api"],
                stdin_text=f"{key}\n",
            )

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(self.read_keys(), {"exa_admin": key})
        provider = payload["balance"]["providers"][0]
        report = provider["reports"][0]
        self.assertEqual(provider["id"], "exa")
        self.assertEqual((report["status"], report["scope"], report["unit"]), ("ok", "team", "usd"))
        self.assertEqual(report["remaining"], 42.5)
        request = http.requests[0]
        self.assertEqual(request.full_url, "https://admin-api.exa.ai/team-management/credits")
        self.assertEqual(request.get_header("X-api-key"), key)
        self.assert_streams_do_not_contain(key, stdout, stderr)

    def test_exa_balance_uses_the_service_key_from_the_environment(self):
        http = RecordingHTTP(FakeResponse({"credits_usd": 7}))
        env_key = "exa-env-service-key"

        with (
            mock.patch.dict(os.environ, {"EXA_SERVICE_KEY": env_key}),
            mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http),
        ):
            code, stdout, stderr = self.run_cli(["balance", "--provider", "exa"])

        self.assertEqual(code, 0, stderr)
        report = json.loads(stdout)["providers"][0]["reports"][0]
        self.assertEqual((report["status"], report["remaining"]), ("ok", 7))
        self.assertEqual(http.requests[0].get_header("X-api-key"), env_key)
        self.assert_streams_do_not_contain(env_key, stdout, stderr)

    def test_exa_balance_without_an_admin_key_needs_a_credential(self):
        code, stdout, stderr = self.run_cli(["balance", "--provider", "exa"])

        self.assertEqual(code, 0, stderr)
        report = json.loads(stdout)["providers"][0]["reports"][0]
        self.assertEqual(report["status"], "needs_credential")
        self.assertIn("exa_admin", report["message"])
        self.assertIn("Team Management", report["message"])
        self.assertIn("service key", report["message"])

    def test_exa_balance_401_is_invalid_and_never_echoes_the_service_key(self):
        key = "exa-rejected-service-key"
        http = RecordingHTTP(http_error(401, json.dumps({"error": f"bad key {key}"}).encode()))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "exa", "--credential", "exa_admin", "--method", "api"],
                stdin_text=f"{key}\n",
            )

        self.assertEqual(code, 0, stderr)
        report = json.loads(stdout)["balance"]["providers"][0]["reports"][0]
        self.assertEqual((report["status"], report["error_kind"]), ("error", "invalid"))
        self.assertEqual(self.read_keys(), {"exa_admin": key})
        self.assert_streams_do_not_contain(key, stdout, stderr)


if __name__ == "__main__":
    unittest.main()

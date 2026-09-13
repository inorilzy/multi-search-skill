import json
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.error import HTTPError

from multi_search_mcp import cli, tools
from multi_search_mcp.src import service
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.search_runner import SearchRunner, SearchRunnerConfig
from multi_search_mcp.src.search.searchers import github
from multi_search_mcp.src.state.key_state import SQLiteKeyManager
from multi_search_mcp.src.state.keys import load_keys
from multi_search_mcp.src.state.state_store import StateStore


PAYLOAD = {"items": [{
    "full_name": "fixture/repository",
    "html_url": "https://github.com/fixture/repository",
    "description": "Repository excerpt",
    "stargazers_count": 12,
}]}


class GitHubKeyPoolTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temp = Path(self.stack.enter_context(TemporaryDirectory(prefix="github-key-pool-")))
        self.keys_path = temp / "keys.json"
        self.store = StateStore(temp / "state.sqlite")
        self.manager = SQLiteKeyManager(self.store)
        self.environ = {}
        self.stack.enter_context(mock.patch.object(
            service, "load_keys",
            side_effect=lambda: load_keys(self.keys_path, environ=self.environ),
        ))
        self.stack.enter_context(mock.patch(
            "socket.getaddrinfo", side_effect=AssertionError("unexpected DNS"),
        ))
        self.stack.enter_context(mock.patch(
            "socket.socket.connect", side_effect=AssertionError("unexpected connection"),
        ))
        self.http = self.stack.enter_context(mock.patch.object(
            github, "urlopen_retry", side_effect=lambda *_args, **_kwargs: BytesIO(json.dumps(PAYLOAD).encode()),
        ))
        self.gh = self.stack.enter_context(mock.patch.object(
            github, "_run_gh", return_value=(0, json.dumps(PAYLOAD), ""),
        ))

    def _search(self, keys, *, use_state=False):
        self.keys_path.write_text(json.dumps(keys), encoding="utf-8")
        return service.run_search_web(
            {"query": "fixture", "sources": ["github"], "count": 1, "use_state": use_state},
            config={}, state_store=self.store,
            scraper=lambda url, **_kwargs: {"url": url, "markdown": "Repository body", "via": "fixture"},
            url_resolver=lambda _host: ["93.184.216.34"],
        )

    def _authorizations(self):
        return [call.args[0].get_header("Authorization") for call in self.http.call_args_list]

    def test_file_single_token_uses_one_authorization(self):
        response = self._search({"github": "fixture-token-one"})
        self.assertEqual(self._authorizations(), ["Bearer fixture-token-one"])
        self.assertEqual(response["errors"], [])
        self.assertEqual(response["results"][0]["url"], PAYLOAD["items"][0]["html_url"])
        self.gh.assert_not_called()

    def test_file_token_array_uses_one_authorization_and_stops_on_success(self):
        response = self._search({"github": ["fixture-token-one", "fixture-token-two"]})
        self.assertEqual(self._authorizations(), ["Bearer fixture-token-one"])
        self.assertEqual(response["errors"], [])
        self.gh.assert_not_called()

    def test_optional_pool_metadata_preserves_required_and_cookie_auth(self):
        registry = build_provider_registry()
        self.assertEqual(registry["github_repos"].key_name, "github")
        self.assertFalse(registry["github_repos"].key_required)
        self.assertEqual(registry["brave"].key_name, "brave")
        self.assertTrue(registry["brave"].key_required)
        self.assertIsNone(registry["twitter"].key_name)

    def test_required_provider_unavailable_keeps_existing_error(self):
        candidate, = self.manager.candidates("brave", "fixture-disabled")
        self.store.execute("UPDATE key_state SET manually_disabled = 1 WHERE key_id = ?", (candidate.key_id,))
        runner = SearchRunner(
            SearchRunnerConfig("default", {"brave": 1}, 10, "google", {"brave": "fixture-disabled"}),
            build_provider_registry(), route_resolver=lambda _route: {"brave"}, key_manager=self.manager,
        )
        self.assertEqual(runner.run("fixture"), [{"source": "brave", "error": "skipped: missing API key"}])

    def test_stateless_auth_and_rate_limit_errors_rotate_then_stop(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                self.http.reset_mock()
                self.http.side_effect = [
                    HTTPError("https://api.github.com/search/repositories", status, "fixture failure", {}, None),
                    BytesIO(json.dumps(PAYLOAD).encode()),
                ]
                with mock.patch.object(service, "SQLiteKeyManager", side_effect=AssertionError("unexpected state")):
                    response = self._search({"github": ["fixture-token-one", "fixture-token-two", "fixture-token-three"]})
                self.assertEqual(self._authorizations(), ["Bearer fixture-token-one", "Bearer fixture-token-two"])
                self.assertEqual(response["errors"], [])
        self.assertEqual(self.manager.status_rows(), [])
        self.gh.assert_not_called()

    def test_stateful_single_token_records_use_and_success(self):
        response = self._search({"github": "fixture-token-one"}, use_state=True)
        self.assertEqual(self._authorizations(), ["Bearer fixture-token-one"])
        row, = self.manager.status_rows("github")
        self.assertEqual((row["use_count"], row["success_count"], row["failure_count"]), (1, 1, 0))
        self.assertEqual(row["status"], "active")
        self.assertEqual(response["errors"], [])
        self.gh.assert_not_called()

    def test_stateful_auth_failure_records_health_and_skips_failed_key_next_search(self):
        tokens = ["fixture-token-one", "fixture-token-two"]
        self.http.side_effect = [
            HTTPError("https://api.github.com/search/repositories", 401, "Unauthorized", {}, None),
            BytesIO(json.dumps(PAYLOAD).encode()),
            BytesIO(json.dumps(PAYLOAD).encode()),
        ]
        first = self._search({"github": tokens}, use_state=True)
        second = self._search({"github": tokens}, use_state=True)
        self.assertEqual(self._authorizations(), [
            "Bearer fixture-token-one", "Bearer fixture-token-two", "Bearer fixture-token-two",
        ])
        rows = {row["key_id"]: row for row in self.manager.status_rows()}
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["provider"] for row in rows.values()}, {"github"})
        failed = next(row for row in rows.values() if row["failure_count"])
        self.assertTrue(failed["key_id"].startswith("github:"))
        self.assertEqual((failed["use_count"], failed["invalid_strikes"]), (1, 1))
        self.assertEqual(failed["status"], "transient_invalid")
        self.assertEqual(failed["last_error_type"], "invalid")
        succeeded = next(row for row in rows.values() if row["success_count"])
        self.assertEqual((succeeded["use_count"], succeeded["success_count"]), (2, 2))
        self.assertEqual(first["errors"], [])
        self.assertEqual(second["errors"], [])
        self.gh.assert_not_called()

    def test_non_key_error_does_not_rotate_or_cool_keys(self):
        self.http.side_effect = HTTPError(
            "https://api.github.com/search/repositories", 422, "invalid query fixture-token-one", {}, None,
        )
        response = self._search({"github": ["fixture-token-one", "fixture-token-two"]}, use_state=True)
        self.assertEqual(self._authorizations(), ["Bearer fixture-token-one"])
        self.assertIn("422", response["errors"][0]["error"])
        self.assertNotIn("fixture-token-one", json.dumps(response))
        rows = self.manager.status_rows("github")
        self.assertEqual(sum(row["use_count"] for row in rows), 1)
        self.assertEqual(sum(row["failure_count"] for row in rows), 1)
        self.assertTrue(all(row["status"] == "active" for row in rows))
        self.gh.assert_not_called()

    def test_stateful_pool_skips_disabled_and_cooling_but_reuses_expired_cooldown(self):
        tokens = ["fixture-disabled", "fixture-cooling", "fixture-expired", "fixture-unused"]
        disabled, cooling, expired, _unused = self.manager.candidates("github", tokens)
        self.store.execute("UPDATE key_state SET manually_disabled = 1 WHERE key_id = ?", (disabled.key_id,))
        limited = self.manager.classify_result("github", [{"error": "HTTP 429"}])
        self.manager.record_result("github", cooling, limited)
        self.manager.record_result("github", expired, limited)
        self.store.execute(
            "UPDATE key_state SET cooldown_until = ? WHERE key_id = ?",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), expired.key_id),
        )
        response = self._search({"github": tokens}, use_state=True)
        self.assertEqual(self._authorizations(), ["Bearer fixture-expired"])
        self.assertEqual(response["errors"], [])
        self.gh.assert_not_called()

    def test_all_configured_keys_unavailable_fails_without_gh(self):
        tokens = ["fixture-disabled", "fixture-cooling"]
        disabled, cooling = self.manager.candidates("github", tokens)
        self.store.execute("UPDATE key_state SET manually_disabled = 1 WHERE key_id = ?", (disabled.key_id,))
        self.manager.record_result("github", cooling, self.manager.classify_result("github", [{"error": "HTTP 429"}]))
        for key_value in (tokens[0], tokens):
            with self.subTest(key_value=key_value):
                response = self._search({"github": key_value}, use_state=True)
                self.assertEqual(response["results"], [])
                self.assertEqual(response["errors"][0]["source"], "github-repos")
                self.assertIn("no usable API keys", response["errors"][0]["error"])
        self.http.assert_not_called()
        self.gh.assert_not_called()

    def test_exhausted_tokens_fail_without_gh_and_redact_errors_and_state(self):
        tokens = ["fixture-token-one", "fixture-token-two"]
        for use_state in (False, True):
            with self.subTest(use_state=use_state):
                self.http.reset_mock()
                self.http.side_effect = [
                    HTTPError("https://api.github.com/search/repositories", 401, f"Unauthorized {token}", {}, None)
                    for token in tokens
                ]
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    response = self._search({"github": tokens}, use_state=use_state)
                self.assertEqual(self._authorizations(), [f"Bearer {token}" for token in tokens])
                self.assertIn("key pool exhausted after 2 key(s)", response["errors"][0]["error"])
                self.assertEqual(response["errors"][0]["source"], "github-repos")
                visible = json.dumps(response) + json.dumps(self.manager.status_rows()) + stdout.getvalue() + stderr.getvalue()
                for token in tokens:
                    self.assertNotIn(token, visible)
        self.gh.assert_not_called()

    def test_no_token_keeps_gh_in_both_state_modes(self):
        for use_state in (False, True):
            for keys in ({}, {"github": ""}, {"github": []}, {"github": None}):
                with self.subTest(use_state=use_state, keys=keys):
                    self.gh.reset_mock()
                    response = self._search(keys, use_state=use_state)
                    self.gh.assert_called_once()
                    self.assertEqual(self.gh.call_args.args[0][:2], ["gh", "api"])
                    self.assertEqual(response["errors"], [])
        self.http.assert_not_called()
        self.assertEqual(self.manager.status_rows(), [])

    def test_environment_precedence_over_file_pool_is_unchanged(self):
        for environ, expected in (
            ({"GITHUB_TOKEN": "fixture-github-env"}, "fixture-github-env"),
            ({"GITHUB_TOKEN": "fixture-github-env", "GH_TOKEN": "fixture-gh-env"}, "fixture-gh-env"),
        ):
            with self.subTest(environ=environ):
                self.environ = environ
                self.http.reset_mock()
                response = self._search({"github": ["fixture-token-one", "fixture-token-two"]})
                self.assertEqual(self._authorizations(), [f"Bearer {expected}"])
                self.assertEqual(response["errors"], [])
        self.gh.assert_not_called()

    def test_search_doctor_and_key_management_share_github_identity(self):
        self._search({"github": "fixture-token-one"}, use_state=True)
        expected = self.manager.status_rows("github")
        self.assertEqual(len(expected), 1)
        with mock.patch.object(service, "StateStore", return_value=self.store), \
             mock.patch.object(service, "load_config", return_value={}), \
             mock.patch.object(service, "resolve_config_path", return_value=self.keys_path.parent / "config.json"), \
             mock.patch.object(tools, "StateStore", return_value=self.store), \
             mock.patch.object(cli, "StateStore", return_value=self.store):
            self.assertEqual(service.doctor_data()["key_status"], expected)
            self.assertEqual(service.list_sources(include_key_status=True)["key_status"], expected)
            self.assertEqual(tools.get_key_status_tool("github")["key_status"], expected)
            stdout, stderr = StringIO(), StringIO()
            code = cli.main(["keys", "status", "--provider", "github"], stdout=stdout, stderr=stderr)
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue())["key_status"], expected)
            self.store.execute("UPDATE key_state SET manually_disabled = 1 WHERE provider = 'github'")
            self.assertEqual(self.manager.candidates("github", "fixture-token-one"), [])
            self.assertEqual(tools.reset_key_state_tool("github"), {"updated": 1})
            self.assertEqual(len(self.manager.candidates("github", "fixture-token-one")), 1)


if __name__ == "__main__":
    unittest.main()

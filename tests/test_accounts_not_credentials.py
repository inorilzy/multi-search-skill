"""Account metadata must not become credentials in diagnostics or redaction."""
import json
import os
import unittest
from unittest import mock

from scripts.test_isolation import isolated_test_environment
from multi_search_mcp.src import diagnostics
from multi_search_mcp.src.plugins import balance, registry
from multi_search_mcp.src.plugins.base import BalanceReport, ProviderPlugin
from multi_search_mcp.src.scrape.fetch import run_fetch_source
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.search_web import run_search_web
from multi_search_mcp.src.state import state_store
from multi_search_mcp.src.state.key_state import key_fingerprint
from multi_search_mcp.src.state.keys import KEY_ENV_NAMES, write_keys_file_atomic
from multi_search_mcp.src.support import debug_log


class AccountsNotCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.env = self.enterContext(isolated_test_environment())
        self.addCleanup(self.env.assert_clean)
        self.enterContext(mock.patch.dict(os.environ, {name: "" for name in KEY_ENV_NAMES}))
        self.enterContext(mock.patch.object(state_store, "DEFAULT_STATE_PATH", self.env.state))
        self.addCleanup(debug_log.disable)
        self.search_key = "fixture-search-credential-12345"
        self.admin_key = "fixture-admin-credential-67890"
        self.account = {
            "id": "acc_a3f9", "name": "个人测试账号", "source": "manual",
            "login_identity": "fixture-user", "keys": [key_fingerprint(self.search_key)],
            "balance_credentials": {"exa_admin": key_fingerprint(self.admin_key)},
        }
        self.metadata = [self.account["name"], self.account["id"], *self.account["keys"],
                         *self.account["balance_credentials"].values()]
        self.message = " / ".join([*self.metadata, self.search_key, self.admin_key])
        self.saved = {"brave": [self.search_key], "exa_admin": self.admin_key,
                      "accounts": {"brave": [self.account]}}
        write_keys_file_atomic(self.env.keys, self.saved)
        self.log_path = self.env.root / "trace.jsonl"

    def assert_redaction(self, text):
        for value in self.metadata:
            self.assertIn(value, text)
        self.assertNotIn(self.search_key, text)
        self.assertNotIn(self.admin_key, text)
        self.assertIn("<redacted>", text)

    def test_doctor_only_lists_credentials_from_keys_file(self):
        data = diagnostics.doctor_data()
        self.assertEqual(data["configured_keys"], {"brave": True, "exa_admin": True})

    def test_debug_log_preserves_metadata_but_redacts_credentials(self):
        debug_log.configure(str(self.log_path))
        self.search(request={"no_fetch": True})
        debug_log.event("account_message", message=self.message)
        event = json.loads(self.log_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assert_redaction(event["message"])

    def search(self, **kwargs):
        provider = ProviderSpec(name="brave", public_name="brave", call=lambda *_args: [{
            "source": "brave", "title": self.message,
            "url": "https://evidence.example/account", "description": self.message,
        }])
        return run_search_web(
            {"query": "account", "sources": ["brave"], "use_state": False,
             **kwargs.pop("request", {})},
            providers={"brave": provider}, config={}, **kwargs,
        )

    def test_search_log_preserves_metadata_from_runtime_keys(self):
        debug_log.configure(str(self.log_path))
        self.search(request={"no_fetch": True})
        events = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]
        response = next(event for event in events if event["event"] == "search_response")
        self.assert_redaction(response["results"][0]["title"])

    def test_fetch_log_preserves_metadata_from_runtime_keys(self):
        debug_log.configure(str(self.log_path))
        run_fetch_source(
            {"url": "https://evidence.example/account", "use_state": False}, config={},
            scraper=lambda *_args, **_kwargs: {"markdown": self.message, "via": "fixture"},
        )
        events = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]
        self.assert_redaction(events[-1]["body_preview"])

    def test_search_fetch_error_preserves_metadata_and_redacts_both_keys(self):
        def broken_scraper(*_args, **_kwargs):
            raise ValueError(self.message)

        result = self.search(scraper=broken_scraper)
        self.assert_redaction(result["results"][0]["body_error"])

    def test_balance_results_match_without_accounts_and_redact_both_keys(self):
        plugin = ProviderPlugin(
            id="exa", label="Exa", key_provider="exa", balance_credential="exa_admin",
            balance=lambda credential, _context: BalanceReport(
                provider="exa", status="ok", scope="team", unit="credits",
                remaining=90, limit=100, used=10, message=self.message,
                fetched_at="2026-01-01T00:00:00+00:00",
            ) if credential == self.admin_key else None,
        )
        with mock.patch.object(registry, "builtin_plugins", return_value=(plugin,)):
            with_accounts = balance.collect_balances(refresh=True, now=1234)
            write_keys_file_atomic(self.env.keys, {"brave": [self.search_key], "exa_admin": self.admin_key})
            without_accounts = balance.collect_balances(refresh=True, now=1234)
        self.assertEqual(with_accounts, without_accounts)
        report = with_accounts["providers"][0]["reports"][0]
        self.assertEqual((report["status"], report["remaining"], report["limit"], report["used"]),
                         ("ok", 90, 100, 10))
        self.assertEqual(report["key_fingerprint"], key_fingerprint(self.admin_key))
        self.assert_redaction(report["message"])

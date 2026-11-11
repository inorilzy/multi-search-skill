"""Balance collection, cache, redaction and CLI behavior; no external network."""
import io
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.plugins import balance as balance_module
from multi_search_mcp.src.plugins import cache as cache_module
from multi_search_mcp.src.plugins import registry
from multi_search_mcp.src.plugins.base import AuthMethod, BalanceReport, ProviderPlugin
from multi_search_mcp.src.state.key_state import key_fingerprint


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_plugin(
    plugin_id="fixture",
    *,
    balance=None,
    balance_note="",
    credential=None,
    ttl_seconds=300,
    auth_methods=(),
):
    return ProviderPlugin(
        id=plugin_id,
        label=plugin_id.upper(),
        key_provider=plugin_id,
        auth_methods=auth_methods,
        balance=balance,
        balance_note=balance_note,
        balance_ttl_seconds=ttl_seconds,
        balance_credential=credential,
    )


def ok_report(provider="fixture", **overrides):
    values = {
        "provider": provider,
        "status": "ok",
        "scope": "key",
        "unit": "credits",
        "remaining": 90,
        "limit": 100,
        "used": 10,
        "resets_at": "2026-02-01T00:00:00+00:00",
        "period": "month",
        "message": "fixture report",
    }
    values.update(overrides)
    return BalanceReport(**values)


class BalanceTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="balance-cli-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        patcher = mock.patch.dict(
            os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_with_plugins(self, plugins, **kwargs):
        with mock.patch.object(registry, "builtin_plugins", return_value=tuple(plugins)):
            return balance_module.collect_balances(**kwargs)

    def cache_file(self):
        return cache_module.default_cache_path()

    def run_cli(self, argv, plugins):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(registry, "builtin_plugins", return_value=tuple(plugins)):
            code = cli.main(argv, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()


class CollectBalancesTests(BalanceTestCase):
    def test_ok_report_matches_the_spec_json_shape(self):
        plugin = make_plugin(
            "acme",
            balance=lambda credential, ctx: ok_report("acme"),
            credential="acme_key",
            auth_methods=(AuthMethod("api", "API Key", "acme_key"),),
            balance_note="acme note",
        )
        payload = self.run_with_plugins(
            [plugin], provider_ids=["acme"], keys={"acme_key": "super-secret"}
        )

        self.assertEqual(payload["schema_version"], 1)
        provider = payload["providers"][0]
        self.assertEqual(
            set(provider), {"id", "label", "auth_methods", "balance_supported", "balance_note", "reports"}
        )
        self.assertEqual(provider["id"], "acme")
        self.assertEqual(provider["label"], "ACME")
        self.assertTrue(provider["balance_supported"])
        self.assertEqual(provider["balance_note"], "acme note")
        self.assertEqual(provider["auth_methods"], [{
            "type": "api", "label": "API Key", "credential": "acme_key", "purpose": "search_key",
        }])
        report = provider["reports"][0]
        self.assertEqual(report["provider"], "acme")
        self.assertEqual(report["status"], "ok")
        self.assertEqual((report["remaining"], report["limit"], report["used"]), (90, 100, 10))
        self.assertEqual(report["key_fingerprint"], key_fingerprint("super-secret"))
        self.assertIsNotNone(report["fetched_at"])
        self.assertEqual(json.loads(json.dumps(payload))["schema_version"], 1)

    def test_each_key_in_a_key_pool_gets_its_own_report(self):
        calls = []

        def fake_balance(credential, ctx):
            calls.append(credential)
            return ok_report("acme")

        plugin = make_plugin("acme", balance=fake_balance, credential="acme_key")
        payload = self.run_with_plugins(
            [plugin], provider_ids=["acme"], keys={"acme_key": ["key-one", "key-two"]}
        )

        self.assertCountEqual(calls, ["key-one", "key-two"])
        reports = payload["providers"][0]["reports"]
        self.assertEqual(
            [report["key_fingerprint"] for report in reports],
            [key_fingerprint("key-one"), key_fingerprint("key-two")],
        )

    def test_missing_credential_is_a_needs_credential_row(self):
        plugin = make_plugin("acme", balance=lambda credential, ctx: ok_report("acme"), credential="acme_key")
        payload = self.run_with_plugins([plugin], provider_ids=["acme"], keys={})

        report = payload["providers"][0]["reports"][0]
        self.assertEqual(report["status"], "needs_credential")
        self.assertIn("acme_key", report["message"])
        self.assertIsNone(report["key_fingerprint"])

    def test_plugin_without_balance_is_unsupported(self):
        plugin = make_plugin("hackernews", balance_note="匿名搜索不提供余额查询。")
        payload = self.run_with_plugins([plugin], provider_ids=["hackernews"], keys={})

        provider = payload["providers"][0]
        self.assertFalse(provider["balance_supported"])
        self.assertEqual(provider["reports"][0]["status"], "unsupported")
        self.assertEqual(provider["reports"][0]["message"], "匿名搜索不提供余额查询。")

    def test_anonymous_plugin_can_query_without_a_credential(self):
        seen = []

        def fake_balance(credential, ctx):
            seen.append(credential)
            return ok_report("github", unit="requests")

        plugin = make_plugin("github", balance=fake_balance, credential="")
        payload = self.run_with_plugins([plugin], provider_ids=["github"], keys={})

        self.assertEqual(seen, [""])
        report = payload["providers"][0]["reports"][0]
        self.assertEqual(report["status"], "ok")
        self.assertIsNone(report["key_fingerprint"])

    def test_one_plugin_failure_does_not_affect_another(self):
        def broken(credential, ctx):
            raise RuntimeError("provider exploded")

        plugins = [
            make_plugin("broken", balance=broken, credential="broken_key"),
            make_plugin("healthy", balance=lambda credential, ctx: ok_report("healthy"), credential="healthy_key"),
        ]
        payload = self.run_with_plugins(
            plugins,
            provider_ids=["broken", "healthy"],
            keys={"broken_key": "broken-secret", "healthy_key": "healthy-secret"},
        )

        reports = {provider["id"]: provider["reports"][0] for provider in payload["providers"]}
        self.assertEqual(reports["broken"]["status"], "error")
        self.assertEqual(reports["broken"]["error_kind"], "error")
        self.assertEqual(reports["healthy"]["status"], "ok")

    def test_timeout_error_is_classified_and_isolated(self):
        def slow(credential, ctx):
            raise TimeoutError("balance request deadline exceeded")

        plugins = [
            make_plugin("slow", balance=slow, credential="slow_key"),
            make_plugin("healthy", balance=lambda credential, ctx: ok_report("healthy"), credential="healthy_key"),
        ]
        payload = self.run_with_plugins(
            plugins,
            provider_ids=["slow", "healthy"],
            keys={"slow_key": "slow-secret", "healthy_key": "healthy-secret"},
        )

        reports = {provider["id"]: provider["reports"][0] for provider in payload["providers"]}
        self.assertEqual(reports["slow"]["status"], "error")
        self.assertEqual(reports["slow"]["error_kind"], "timeout")
        self.assertEqual(reports["healthy"]["status"], "ok")

    def test_total_deadline_marks_a_hung_plugin_as_timeout(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def hung(credential, ctx):
            release.wait()
            return ok_report("hung")

        plugin = make_plugin("hung", balance=hung, credential="hung_key")
        started = time.monotonic()
        with (
            mock.patch.object(balance_module, "BALANCE_TIMEOUT_SECONDS", 0.05),
            mock.patch.object(balance_module, "BALANCE_TOTAL_TIMEOUT_SECONDS", 0.1),
        ):
            payload = self.run_with_plugins([plugin], provider_ids=["hung"], keys={"hung_key": "hung-secret"})
        elapsed = time.monotonic() - started

        report = payload["providers"][0]["reports"][0]
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["error_kind"], "timeout")
        self.assertLess(elapsed, 0.9)

    def test_credentials_come_from_load_keys_environment_before_keys_file(self):
        keys_dir = self.home / ".multi-search"
        keys_dir.mkdir(parents=True, exist_ok=True)
        (keys_dir / "keys.json").write_text(
            json.dumps({"tavily": "file-secret"}), encoding="utf-8"
        )
        calls = []

        def fake_balance(credential, ctx):
            calls.append(credential)
            return ok_report("tavily")

        plugin = make_plugin("tavily", balance=fake_balance, credential="tavily")
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "env-secret"}):
            self.run_with_plugins([plugin], provider_ids=["tavily"])
        self.assertEqual(calls, ["env-secret"])

        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": ""}):
            self.run_with_plugins([plugin], provider_ids=["tavily"], refresh=True)
        self.assertEqual(calls, ["env-secret", "file-secret"])

    def test_provider_calls_run_concurrently(self):
        barrier = threading.Barrier(2)

        def wait_for_peer(credential, ctx):
            barrier.wait(timeout=1)
            return ok_report("acme")

        plugins = [
            make_plugin("one", balance=wait_for_peer, credential="one_key"),
            make_plugin("two", balance=wait_for_peer, credential="two_key"),
        ]
        payload = self.run_with_plugins(
            plugins,
            provider_ids=["one", "two"],
            keys={"one_key": "one-secret", "two_key": "two-secret"},
        )

        self.assertEqual(
            [provider["reports"][0]["status"] for provider in payload["providers"]],
            ["ok", "ok"],
        )

    def test_provider_filter_keeps_registry_order_and_skips_others(self):
        plugins = [
            make_plugin("first", balance_note="first note"),
            make_plugin("second", balance_note="second note"),
            make_plugin("third", balance_note="third note"),
        ]
        payload = self.run_with_plugins(plugins, provider_ids=["third", "first"], keys={})

        self.assertEqual([provider["id"] for provider in payload["providers"]], ["first", "third"])


class BalanceRedactionTests(BalanceTestCase):
    def test_error_message_never_contains_the_plaintext_key_or_email(self):
        secret = "plain-secret-key-12345"

        def broken(credential, ctx):
            raise RuntimeError(
                f"request failed for {credential} owner admin@example.com "
                "Authorization: Bearer abc.def.ghi"
            )

        plugin = make_plugin("acme", balance=broken, credential="acme_key")
        payload = self.run_with_plugins([plugin], provider_ids=["acme"], keys={"acme_key": secret})
        rendered = json.dumps(payload, ensure_ascii=False)

        self.assertNotIn(secret, rendered)
        self.assertNotIn("admin@example.com", rendered)
        self.assertNotIn("abc.def.ghi", rendered)
        self.assertIn("<redacted>", payload["providers"][0]["reports"][0]["message"])

    def test_ok_message_is_redacted_before_it_is_cached(self):
        secret = "plain-secret-key-abcdef"

        def leaky(credential, ctx):
            return ok_report("acme", message=f"owner {credential} admin@example.com")

        plugin = make_plugin("acme", balance=leaky, credential="acme_key")
        payload = self.run_with_plugins([plugin], provider_ids=["acme"], keys={"acme_key": secret})

        message = payload["providers"][0]["reports"][0]["message"]
        self.assertNotIn(secret, message)
        self.assertNotIn("admin@example.com", message)
        cached = self.cache_file().read_text(encoding="utf-8")
        self.assertNotIn(secret, cached)
        self.assertNotIn("admin@example.com", cached)


class BalanceCacheTests(BalanceTestCase):
    def test_second_collection_hits_cache_and_refresh_bypasses_it(self):
        calls = []

        def fake_balance(credential, ctx):
            calls.append(credential)
            return ok_report("acme")

        plugin = make_plugin("acme", balance=fake_balance, credential="acme_key", ttl_seconds=300)
        kwargs = {"provider_ids": ["acme"], "keys": {"acme_key": "cache-secret"}}

        self.run_with_plugins([plugin], now=NOW, **kwargs)
        self.run_with_plugins([plugin], now=NOW + timedelta(seconds=10), **kwargs)
        self.assertEqual(len(calls), 1)

        self.run_with_plugins([plugin], now=NOW + timedelta(seconds=20), refresh=True, **kwargs)
        self.assertEqual(len(calls), 2)

        self.run_with_plugins([plugin], now=NOW + timedelta(seconds=20 + 301), **kwargs)
        self.assertEqual(len(calls), 3)

    def test_only_ok_reports_are_cached(self):
        calls = []

        def broken(credential, ctx):
            calls.append(credential)
            raise RuntimeError("boom")

        plugin = make_plugin("acme", balance=broken, credential="acme_key")
        kwargs = {"provider_ids": ["acme"], "keys": {"acme_key": "error-secret"}}
        self.run_with_plugins([plugin], now=NOW, **kwargs)
        self.run_with_plugins([plugin], now=NOW, **kwargs)

        self.assertEqual(len(calls), 2)
        if self.cache_file().exists():
            payload = json.loads(self.cache_file().read_text(encoding="utf-8"))
            self.assertEqual(payload["entries"], {})

    def test_corrupt_cache_is_ignored_and_rebuilt(self):
        path = self.cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")

        plugin = make_plugin("acme", balance=lambda credential, ctx: ok_report("acme"), credential="acme_key")
        payload = self.run_with_plugins(
            [plugin], provider_ids=["acme"], keys={"acme_key": "rebuild-secret"}, now=NOW
        )

        self.assertEqual(payload["providers"][0]["reports"][0]["status"], "ok")
        rebuilt = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt["schema_version"], cache_module.CACHE_SCHEMA_VERSION)
        self.assertEqual(len(rebuilt["entries"]), 1)


class BalanceCliTests(BalanceTestCase):
    def test_cli_defaults_to_json_with_the_spec_shape(self):
        plugin = make_plugin(
            "acme",
            balance=lambda credential, ctx: ok_report("acme"),
            credential="",
        )
        code, stdout, stderr = self.run_cli(["balance"], [plugin])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["providers"][0]["id"], "acme")
        self.assertEqual(payload["providers"][0]["reports"][0]["status"], "ok")

    def test_cli_text_format_has_one_line_per_report(self):
        plugin = make_plugin(
            "acme",
            balance=lambda credential, ctx: ok_report(
                "acme", remaining=8, limit=10, unit="searches", resets_at="2026-02-01T00:00:00+00:00",
            ),
            credential="",
        )
        code, stdout, stderr = self.run_cli(["balance", "--format", "text"], [plugin])

        self.assertEqual(code, 0, stderr)
        lines = [line for line in stdout.splitlines() if line]
        self.assertEqual(len(lines), 1)
        self.assertIn("ACME", lines[0])
        self.assertIn("剩余 8/10 searches", lines[0])
        self.assertIn("重置 2026-02-01T00:00:00+00:00", lines[0])

    def test_cli_unknown_provider_is_a_usage_error_with_exit_code_2(self):
        code, stdout, stderr = self.run_cli(["balance", "--provider", "not-a-plugin"], [])

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("unknown provider: not-a-plugin", stderr)

    def test_cli_refresh_flag_bypasses_the_cache(self):
        calls = []

        def fake_balance(credential, ctx):
            calls.append(credential)
            return ok_report("acme")

        plugin = make_plugin("acme", balance=fake_balance, credential="")
        self.run_cli(["balance"], [plugin])
        self.run_cli(["balance"], [plugin])
        self.assertEqual(len(calls), 1)
        self.run_cli(["balance", "--refresh"], [plugin])
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()

"""Account usage contracts over disposable keys, cached reports and fixed time."""
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.plugins import registry, usage_report, usage_store
from multi_search_mcp.src.plugins.base import AuthMethod, BalanceReport, ProviderPlugin
from multi_search_mcp.src.plugins.cache import BalanceCache
from multi_search_mcp.src.state.key_state import key_fingerprint


NOW = datetime(2026, 3, 15, 12, tzinfo=timezone.utc)
FIRST = "usage-account-fixture-first"
SECOND = "usage-account-fixture-second"
ADMIN = "usage-account-fixture-admin"
FP1, FP2 = key_fingerprint(FIRST), key_fingerprint(SECOND)
RESET = "2026-04-01T00:00:00+00:00"


def report(**overrides):
    values = dict(provider="fixture", status="ok", scope="key", unit="credits",
                  remaining=40, limit=100, key_fingerprint=FP1, fetched_at=NOW.isoformat())
    values.update(overrides)
    return BalanceReport(**values)


class UsageAccountTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="usage-accounts-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.plugin = ProviderPlugin(id="fixture", label="Fixture", key_provider="fixture",
                                     balance=lambda credential, context: report())
        self.path = self.home / ".multi-search" / "keys.json"
        self.data = {"fixture": [FIRST, SECOND], "accounts": {"fixture": [
            {"id": "acc_work", "name": "工作", "source": "manual", "keys": [FP2],
             "balance_credentials": {}},
        ]}}
        self.save_keys()

    def save_keys(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def cache(self, *reports):
        groups = {}
        for row in reports:
            groups.setdefault(row.key_fingerprint, []).append(row)
        cache = BalanceCache()
        for fingerprint, rows in groups.items():
            cache.put("fixture", rows, ttl_seconds=300, now=NOW)
        cache.flush()

    def history(self, *points, **overrides):
        for days_ago, remaining in points:
            usage_store.append_balance(report(
                fetched_at=(NOW - timedelta(days=days_ago)).isoformat(), remaining=remaining,
                **overrides,
            ), now=NOW)

    def invoke(self, output_format="json", *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (mock.patch.object(registry, "builtin_plugins", return_value=(self.plugin,)),
              mock.patch.object(usage_report, "datetime", wraps=datetime) as clock):
            clock.now.return_value = NOW
            code = cli.main(["usage", "--format", output_format, *args], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        return stdout.getvalue()

    def view(self, *args):
        return json.loads(self.invoke("json", *args))["providers"][0]

    def single_key(self):
        self.data["fixture"] = FIRST
        self.data["accounts"] = {}
        self.save_keys()

    def needs_search_key(self):
        self.data["accounts"]["fixture"].append(
            {"id": "acc_login", "name": "登录", "source": "oauth", "keys": []})
        self.save_keys()

    def test_json_adds_account_contract_without_changing_legacy_reports_or_version(self):
        self.cache(report(), report(key_fingerprint=FP2, remaining=30))
        payload = json.loads(self.invoke())
        self.assertEqual(payload["schema_version"], 1)
        provider = payload["providers"][0]
        self.assertEqual(set(provider), {"id", "label", "balance_supported", "balance_note", "current",
                                         "totals", "history", "pace", "calls", "accounts", "total", "alert"})
        self.assertEqual(provider["current"], [report().to_dict(), report(key_fingerprint=FP2, remaining=30).to_dict()])
        self.assertEqual(provider["totals"], [{"scope": "key", "unit": "credits", "key_count": 2,
                                              "message": "", "remaining": 70, "limit": 200}])
        self.assertEqual(provider["accounts"], [
            {"id": "default", "name": "默认账号", "source": "manual",
             "keys": [{"key_fingerprint": FP1, "report": report().to_dict()}],
             "total": {"remaining": 40, "limit": 100, "percent": 40, "unit": "credits", "relative": False}},
            {"id": "acc_work", "name": "工作", "source": "manual",
             "keys": [{"key_fingerprint": FP2, "report": report(key_fingerprint=FP2, remaining=30).to_dict()}],
             "total": {"remaining": 30, "limit": 100, "percent": 30, "unit": "credits", "relative": False}},
        ])

    def test_provider_total_adds_key_quotas_across_accounts(self):
        self.cache(report(), report(key_fingerprint=FP2, remaining=30, limit=200))
        self.assertEqual(self.view()["total"], {"remaining": 70, "limit": 300, "percent": 70 / 300 * 100,
                                               "unit": "credits", "relative": False})

    def test_account_total_adds_its_keys(self):
        self.data["accounts"]["fixture"][0]["keys"] = [FP1, FP2]
        self.save_keys()
        self.cache(report(), report(key_fingerprint=FP2, remaining=30, limit=200))
        account = self.view()["accounts"][1]
        self.assertEqual((account["total"]["remaining"], account["total"]["limit"]), (70, 300))

    def test_null_remaining_propagates_without_hiding_known_limit(self):
        self.cache(report(), report(key_fingerprint=FP2, remaining=None))
        total = self.view()["total"]
        self.assertIsNone(total["remaining"])
        self.assertIsNone(total["percent"])
        self.assertEqual(total["limit"], 200)

    def test_null_limit_propagates_and_no_history_gives_no_percent(self):
        self.cache(report(), report(key_fingerprint=FP2, limit=None))
        total = self.view()["total"]
        self.assertIsNone(total["limit"])
        self.assertIsNone(total["percent"])
        self.assertEqual(total["remaining"], 80)

    def test_team_and_account_quotas_use_latest_observation_without_adding(self):
        for scope in ("team", "account"):
            with self.subTest(scope=scope):
                self.cache(report(scope=scope, remaining=80, fetched_at=(NOW - timedelta(hours=1)).isoformat()),
                           report(scope=scope, key_fingerprint=FP2, remaining=60))
                self.assertEqual(self.view()["total"], {"remaining": 60, "limit": 100, "percent": 60,
                                                       "unit": "credits", "relative": False})

    def test_shared_quota_takes_precedence_over_key_quota_with_same_unit(self):
        self.single_key()
        self.cache(report(remaining=2), report(scope="account", remaining=60, limit=200))
        view = self.view()
        self.assertEqual(view["total"]["remaining"], 60)
        self.assertEqual(view["total"]["percent"], 30)
        self.assertEqual(len(view["accounts"][0]["keys"]), 1)
        self.assertEqual(view["accounts"][0]["keys"][0]["report"]["scope"], "key")
        self.assertEqual(view["accounts"][0]["total"], view["total"])

    def test_mixed_units_have_unknown_total_with_stable_shape(self):
        self.cache(report(remaining=1), report(key_fingerprint=FP2, unit="usd", remaining=1))
        view = self.view()
        self.assertEqual(view["total"], {"remaining": None, "limit": None, "percent": None,
                                         "unit": None, "relative": False})
        self.assertIsNone(view["alert"])

    def test_uncached_key_keeps_fingerprint_with_null_report(self):
        self.cache(report())
        view = self.view()
        self.assertEqual(view["accounts"][1]["keys"], [{"key_fingerprint": FP2, "report": None}])
        self.assertIsNone(view["total"]["remaining"])
        self.assertIsNone(view["total"]["percent"])

    def test_no_reports_have_unknown_total_with_stable_shape(self):
        self.assertEqual(self.view()["total"], {"remaining": None, "limit": None, "percent": None,
                                               "unit": None, "relative": False})

    def test_balance_only_credential_belongs_to_account_total_without_counting_as_search_key(self):
        self.plugin = ProviderPlugin(
            id="fixture", label="Fixture", key_provider="fixture", balance_credential="fixture_admin",
            auth_methods=(AuthMethod(type="api", label="管理 Key", credential="fixture_admin", purpose="balance_only"),),
            balance=lambda credential, context: report(),
        )
        self.data["fixture_admin"] = ADMIN
        self.data["accounts"]["fixture"][0]["balance_credentials"] = {"fixture_admin": key_fingerprint(ADMIN)}
        self.save_keys()
        self.cache(report(scope="team", key_fingerprint=key_fingerprint(ADMIN), remaining=75))
        view = self.view()
        self.assertEqual(view["accounts"][1]["total"]["remaining"], 75)
        self.assertEqual(view["accounts"][1]["keys"], [{"key_fingerprint": FP2, "report": None}])
        self.assertEqual(sum(len(account["keys"]) for account in view["accounts"]), 2)
        self.assertEqual(view["total"]["remaining"], 75)

    def test_relative_percent_uses_maximum_inside_current_cycle_even_outside_chart_window(self):
        self.single_key()
        self.cache(report(remaining=20, limit=None, resets_at=RESET, period="month"))
        self.history((20, 1000), (10, 80), (2, 40), limit=None, resets_at=RESET, period="month")
        total = self.view("--days", "1")["total"]
        self.assertEqual(total, {"remaining": 20, "limit": None, "percent": 25, "unit": "credits", "relative": True})

    def test_relative_key_totals_add_each_keys_historical_maximum(self):
        self.cache(report(remaining=20, limit=None), report(key_fingerprint=FP2, remaining=30, limit=None))
        self.history((2, 100), limit=None)
        self.history((2, 300), limit=None, key_fingerprint=FP2)
        self.assertEqual(self.view()["total"]["percent"], 12.5)

    def test_relative_percent_requires_history_for_every_key(self):
        self.cache(report(limit=None), report(key_fingerprint=FP2, limit=None))
        self.history((2, 100), limit=None)
        self.assertIsNone(self.view()["total"]["percent"])

    def test_no_history_never_invents_relative_percentage(self):
        self.single_key()
        self.cache(report(limit=None))
        total = self.view()["total"]
        self.assertTrue(total["relative"])
        self.assertIsNone(total["percent"])

    def test_zero_historical_maximum_does_not_divide_by_zero(self):
        self.single_key()
        self.cache(report(remaining=0, limit=None))
        self.history((1, 0), limit=None)
        self.assertIsNone(self.view()["total"]["percent"])

    def test_relative_account_maximum_does_not_include_other_accounts_history(self):
        self.cache(report(scope="account", remaining=20, limit=None),
                   report(scope="account", key_fingerprint=FP2, remaining=10, limit=None))
        self.history((2, 80), scope="account", limit=None)
        self.history((2, 200), scope="account", limit=None, key_fingerprint=FP2)
        self.assertEqual([account["total"]["percent"] for account in self.view()["accounts"]], [25, 5])

    def test_alert_thresholds_are_strictly_below_twenty_and_five_percent(self):
        self.single_key()
        for remaining, alert in ((20, None), (19.9, "low"), (5, "low"), (4.9, "critical"), (0, "critical")):
            with self.subTest(remaining=remaining):
                self.cache(report(remaining=remaining))
                self.assertEqual(self.view()["alert"], alert)

    def test_critical_alert_takes_precedence_over_wont_last_and_missing_credential(self):
        self.needs_search_key()
        self.cache(report(remaining=2, resets_at=RESET, period="month"), report(key_fingerprint=FP2, remaining=2))
        self.history((1, 100), (0, 2), resets_at=RESET, period="month")
        self.assertEqual(self.view()["alert"], "critical")

    def test_wont_last_alert_takes_precedence_over_low_and_missing_credential(self):
        self.needs_search_key()
        self.cache(report(remaining=10, resets_at=RESET, period="month"), report(key_fingerprint=FP2, remaining=10))
        self.history((1, 100), (0, 10), resets_at=RESET, period="month")
        self.assertEqual(self.view()["alert"], "wont_last")

    def test_low_alert_takes_precedence_over_missing_credential(self):
        self.needs_search_key()
        self.cache(report(remaining=10), report(key_fingerprint=FP2, remaining=10))
        self.assertEqual(self.view()["alert"], "low")

    def test_oauth_account_without_search_key_needs_credential(self):
        self.needs_search_key()
        self.cache(report(), report(key_fingerprint=FP2))
        self.assertEqual(self.view()["alert"], "needs_credential")

    def test_manual_named_account_without_search_key_needs_credential(self):
        self.data["accounts"]["fixture"].append(
            {"id": "acc_empty", "name": "待绑", "source": "manual", "keys": [], "balance_credentials": {}})
        self.save_keys()
        self.cache(report(), report(key_fingerprint=FP2))
        self.assertEqual(self.view()["alert"], "needs_credential")

    def test_missing_balance_credential_needs_credential(self):
        self.data["fixture"] = []
        self.save_keys()
        self.assertEqual(self.view()["alert"], "needs_credential")

    def test_unknown_total_still_reports_current_wont_last(self):
        self.cache(report(remaining=50, resets_at=RESET, period="month"),
                   report(key_fingerprint=FP2, unit="usd"))
        self.history((1, 100), (0, 50), resets_at=RESET, period="month")
        self.assertIsNone(self.view()["total"]["percent"])
        self.assertEqual(self.view()["alert"], "wont_last")

    def test_removed_key_history_does_not_trigger_wont_last_alert(self):
        self.single_key()
        self.cache(report())
        self.history((1, 100), (0, 1), key_fingerprint=FP2, resets_at=RESET, period="month")
        self.assertIsNone(self.view()["alert"])

    def test_text_groups_key_fingerprints_under_their_account_names(self):
        self.cache(report(remaining=10), report(key_fingerprint=FP2, remaining=10))
        text = self.invoke("text")
        self.assertIn(f"账号 默认账号（default）：剩余 10/100 credits · 10%\n  Key {FP1}", text)
        self.assertIn(f"账号 工作（acc_work）：剩余 10/100 credits · 10%\n  Key {FP2}", text)
        self.assertIn("提醒：余额偏低", text)
        self.assertIn("本机调用（今天）", text)
        self.assertNotIn("\n\n", text.strip())

    def test_relative_percentage_uses_same_low_balance_thresholds(self):
        self.single_key()
        self.cache(report(remaining=4, limit=None))
        self.history((1, 100), limit=None)
        self.assertEqual(self.view()["alert"], "critical")

    def test_latest_shared_unknown_value_stays_unknown(self):
        self.cache(report(scope="team", remaining=80, fetched_at=(NOW - timedelta(hours=1)).isoformat()),
                   report(scope="team", key_fingerprint=FP2, remaining=None))
        self.assertIsNone(self.view()["total"]["remaining"])
        self.assertIsNone(self.view()["total"]["percent"])

    def test_relative_shared_quota_uses_one_historical_maximum(self):
        self.cache(report(scope="team", remaining=20, limit=None),
                   report(scope="team", key_fingerprint=FP2, remaining=20, limit=None))
        self.history((2, 100), scope="team", limit=None)
        self.history((2, 100), scope="team", limit=None, key_fingerprint=FP2)
        self.assertEqual(self.view()["total"]["percent"], 20)

    def test_expired_cycle_history_does_not_create_a_relative_percentage(self):
        self.single_key()
        self.cache(report(remaining=20, limit=None, resets_at=RESET, period="month"))
        self.history((20, 100), limit=None, resets_at=RESET, period="month")
        self.assertIsNone(self.view()["total"]["percent"])

    def test_text_marks_historical_percentage_as_relative(self):
        self.single_key()
        self.cache(report(remaining=20, limit=None))
        self.history((2, 80), limit=None)
        self.assertIn("25%（相对值）", self.invoke("text"))

    def test_outputs_never_contain_raw_search_or_balance_credentials(self):
        self.data["fixture_admin"] = ADMIN
        self.data["accounts"]["fixture"][0]["name"] = f"工作 {ADMIN} owner@example.com"
        self.save_keys()
        self.cache(report(message=f"search {FIRST} {SECOND} management {ADMIN}"), report(key_fingerprint=FP2))
        for output_format in ("json", "text"):
            with self.subTest(output_format=output_format):
                text = self.invoke(output_format)
                for secret in (FIRST, SECOND, ADMIN, "owner@example.com"):
                    self.assertNotIn(secret, text)

    def test_unsupported_provider_preserves_account_metadata_while_redacting_credentials(self):
        self.plugin = ProviderPlugin(id="fixture", label="Fixture", key_provider="fixture", balance=None,
                                     balance_note=f"search {FIRST} {SECOND} management {ADMIN}")
        self.data["fixture_admin"] = ADMIN
        self.save_keys()
        for output_format in ("json", "text"):
            with self.subTest(output_format=output_format):
                text = self.invoke(output_format)
                for secret in (FIRST, SECOND, ADMIN):
                    self.assertNotIn(secret, text)
                if output_format == "json":
                    account = json.loads(text)["providers"][0]["accounts"][1]
                    self.assertEqual(account["name"], "工作")
                    self.assertEqual(account["id"], "acc_work")
                    self.assertEqual(account["keys"][0]["key_fingerprint"], FP2)
                else:
                    self.assertIn("账号 工作（acc_work）", text)
                    self.assertIn(FP2, text)

    def test_unsupported_balance_keeps_unknown_total_shape(self):
        self.plugin = ProviderPlugin(id="fixture", label="Fixture", key_provider="fixture", balance=None)
        self.assertEqual(self.view()["total"], {"remaining": None, "limit": None, "percent": None,
                                               "unit": None, "relative": False})

    def test_accounts_metadata_is_not_a_provider_or_a_search_key(self):
        self.cache(report(), report(key_fingerprint=FP2))
        payload = json.loads(self.invoke())
        self.assertEqual([provider["id"] for provider in payload["providers"]], ["fixture"])
        view = payload["providers"][0]
        self.assertEqual(sum(len(account["keys"]) for account in view["accounts"]), 2)
        self.assertEqual(view["totals"][0]["key_count"], 2)
        self.assertEqual([row["key_fingerprint"] for row in view["current"]], [FP1, FP2])

    def test_usage_does_not_persist_virtual_default_or_change_keys_file(self):
        before = self.path.read_bytes()
        self.view()
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

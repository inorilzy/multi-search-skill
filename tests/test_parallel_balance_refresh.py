"""Parallel's balance must stay visible after its access token is refreshed.

The access token lives ten minutes and a balance query refreshes it. The balance
cache, the balance history and the owning account used to be keyed by the token's
fingerprint, so right after a refresh the usage view found nothing ("余额未知").
All HTTP here is fake.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.plugins import accounts, oauth_store, usage_report
from multi_search_mcp.src.plugins.balance import collect_balances
from multi_search_mcp.src.state.key_state import key_fingerprint
from tests.test_login_oauth import PARALLEL_BALANCE_URL, PARALLEL_TOKEN_URL, FakeHTTP


class ParallelBalanceAfterRefreshTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="parallel-refresh-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        store = self.home / ".multi-search"
        store.mkdir()
        (store / "keys.json").write_text(json.dumps({"parallel": "synthetic-search-key"}), encoding="utf-8")
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        oauth_store.set_entry("parallel_account", {
            "access_token": "synthetic-expired-access", "refresh_token": "synthetic-refresh",
            "expires_at": expired, "token_type": "Bearer", "scope": "balance:read", "login_id": "0123456789abcdef",
        })
        ref = key_fingerprint(oauth_store.balance_credential_ref("parallel_account", oauth_store.get_entry("parallel_account")))
        accounts.upsert_oauth_account("parallel", "owner@example.test", balance_credentials={"parallel_account": ref})

    def test_usage_reads_the_balance_fetched_with_a_refreshed_token(self):
        http = FakeHTTP({
            PARALLEL_TOKEN_URL: {"access_token": "synthetic-fresh-access", "refresh_token": "synthetic-refresh-2",
                                 "expires_in": 600},
            PARALLEL_BALANCE_URL: {"org_id": "org-1", "credit_balance_cents": 495,
                                   "pending_debit_balance_cents": 0, "will_invoice": False},
        })
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            collect_balances(["parallel"], refresh=True)
        self.assertEqual(oauth_store.get_entry("parallel_account")["access_token"], "synthetic-fresh-access")

        provider = usage_report.collect_usage(["parallel"])["providers"][0]
        self.assertEqual([(row["status"], row["unit"], row["remaining"]) for row in provider["current"]],
                         [("ok", "usd", 4.95)])
        login = next(row for row in provider["accounts"] if row["id"] != "default")
        self.assertEqual(login["total"]["remaining"], 4.95)
        self.assertEqual(provider["total"]["remaining"], 4.95)
        self.assertNotIn("synthetic-fresh-access", json.dumps(provider))


if __name__ == "__main__":
    unittest.main()

"""Firecrawl keys can belong to different teams, each with its own credits.

Every report used to be labelled scope="team", so usage took them for one shared
quota and showed whichever was fetched last (e.g. 1310 left of 1000). A team is
identified by its billing period; keys of one team share one report, keys of
different teams are added up. All HTTP here is fake.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.plugins import usage_report
from multi_search_mcp.src.plugins.balance import collect_balances

URL = "https://api.firecrawl.dev/v2/team/credit-usage"
TEAMS = {
    "fc-team-a-1": ("2026-11-10T03:50:31.367Z", "2026-12-10T03:50:31.367Z", 1105),
    "fc-team-a-2": ("2026-11-10T03:50:31.367Z", "2026-12-10T03:50:31.367Z", 1105),
    "fc-team-b": ("2026-10-29T10:25:09.518Z", "2026-11-29T10:25:09.518Z", 1310),
    "fc-team-c": ("2026-10-29T10:30:43.651Z", "2026-11-29T10:30:43.651Z", 1029),
}


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amount=None):
        return self.body if amount is None else self.body[:amount]


def fake_http(request, **kwargs):
    assert request.full_url == URL
    key = request.get_header("Authorization").removeprefix("Bearer ")
    start, end, remaining = TEAMS[key]
    return FakeResponse({"success": True, "data": {"remainingCredits": remaining, "planCredits": 1000,
                                                   "billingPeriodStart": start, "billingPeriodEnd": end}})


class FirecrawlTeamsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="firecrawl-teams-")
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        (home / ".multi-search").mkdir()
        (home / ".multi-search" / "keys.json").write_text(json.dumps({"firecrawl": list(TEAMS)}), encoding="utf-8")

    def test_three_teams_add_up_and_one_team_counts_once(self):
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", fake_http):
            collect_balances(["firecrawl"], refresh=True)
        provider = usage_report.collect_usage(["firecrawl"])["providers"][0]
        total = provider["total"]
        self.assertEqual((total["remaining"], total["limit"], total["unit"]), (1105 + 1310 + 1029, 3000, "credits"))
        self.assertLessEqual(total["remaining"], total["limit"] + 1000)  # never one team's surplus over another's limit
        teams = {row["key_fingerprint"] for row in provider["current"]}
        self.assertEqual(len(provider["current"]), 4)
        self.assertEqual(len(teams), 4)


if __name__ == "__main__":
    unittest.main()

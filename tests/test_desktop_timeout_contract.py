"""Desktop settings timeout range must cover every CLI route default (review M-10).

The desktop writer (desktop/src-tauri/src/settings.rs) mirrors ROUTE_META timeouts. This check
reads the Rust constants as text so a CLI route change cannot silently make its own default
unsavable from the desktop. No Rust toolchain is required.
"""
import re
import unittest
from pathlib import Path

from multi_search_mcp.src.search.search_runner import ROUTE_META, ROUTE_PROFILES

SETTINGS_RS = Path(__file__).resolve().parents[1] / "desktop" / "src-tauri" / "src" / "settings.rs"


class DesktopTimeoutContractTests(unittest.TestCase):
    def setUp(self):
        self.source = SETTINGS_RS.read_text(encoding="utf-8")

    def constant(self, name):
        match = re.search(rf"pub const {name}: u32 = (\d+);", self.source)
        self.assertIsNotNone(match, f"{name} missing from settings.rs")
        return int(match.group(1))

    def test_desktop_timeout_range_matches_the_widest_cli_route(self):
        widest = max(int(ROUTE_META[route]["timeout"]) for route in ROUTE_PROFILES)
        self.assertEqual(self.constant("TIMEOUT_MAX"), widest)
        self.assertEqual(self.constant("TIMEOUT_MIN"), 1)

    def test_desktop_route_defaults_mirror_route_meta(self):
        body = re.search(r"fn route_default_timeout\(route: &str\) -> u32 \{(.*?)\n\}", self.source, re.S)
        self.assertIsNotNone(body)
        arms = {name: int(value) for name, value in re.findall(r'"(\w+)" => (\d+)', body.group(1))}
        fallback = int(re.search(r"_ => (\d+)", body.group(1)).group(1))
        for route in ROUTE_PROFILES:
            self.assertEqual(arms.get(route, fallback), int(ROUTE_META[route]["timeout"]), route)


if __name__ == "__main__":
    unittest.main()

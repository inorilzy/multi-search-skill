"""Repository hygiene: no personal probes, no tracked ignored files, no sleep timing.

These guard the cleanup in ticket 26 so the repository does not drift back.
"""
import ast
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> list[str]:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise unittest.SkipTest("not running inside a git checkout")
    return [line for line in completed.stdout.splitlines() if line]


class RepositoryHygieneTests(unittest.TestCase):
    def test_no_tracked_file_is_also_gitignored(self):
        # `git ls-files -ci` lists tracked files that .gitignore would exclude.
        self.assertEqual(_git("ls-files", "-ci", "--exclude-standard"), [])

    def test_personal_browser_probe_scripts_are_not_shipped(self):
        tracked = set(_git("ls-files", "scripts"))
        for name in ("scripts/_probe_xhs.py", "scripts/xhs_cloak_fetch.py"):
            self.assertNotIn(name, tracked)
        personal_path = re.compile(r"[A-Za-z]:\\\\?Users\\\\?[A-Za-z0-9_.-]+\\\\?\.codex")
        for name in tracked:
            if name.endswith(".py"):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIsNone(personal_path.search(text), name)
                self.assertNotIn("cloakbrowser", text, name)

    def test_tests_do_not_use_time_sleep_for_synchronisation(self):
        offenders = []
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "sleep"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "time"
                ):
                    offenders.append(f"{path.name}:{node.lineno}")
                if (
                    path.name != Path(__file__).name
                    and isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and "time.sleep(" in node.value
                ):
                    offenders.append(f"{path.name}:{node.lineno} (child script)")
        self.assertEqual(offenders, [], "use threading.Event/Barrier or a controlled clock")

    def test_desktop_test_fixtures_are_feature_gated(self):
        lib = (ROOT / "desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
        for module in ("settings_fixture", "credential_fixture"):
            declaration = re.search(
                r"((?:#\[[^\]]+\]\s*)+)pub mod " + module + r"\b", lib,
            )
            self.assertIsNotNone(declaration, module)
            self.assertIn('#[cfg(feature = "test-fixtures")]', declaration.group(1), module)
        manifest = (ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
        self.assertRegex(manifest, r"(?m)^test-fixtures = \[\]$")
        self.assertNotRegex(manifest, r'default = \[[^\]]*"test-fixtures"')
        for test in ("credentials", "credential_sources", "settings"):
            block = re.search(
                r'\[\[test\]\]\nname = "' + test + r'"\npath = "[^"]+"\n((?:[a-z-]+ = .*\n)*)', manifest,
            )
            self.assertIsNotNone(block, test)
            self.assertIn('required-features = ["test-fixtures"]', block.group(1), test)
        build = (ROOT / "desktop/src-tauri/build.rs").read_text(encoding="utf-8")
        self.assertIn("CARGO_FEATURE_TEST_FIXTURES", build)


if __name__ == "__main__":
    unittest.main()

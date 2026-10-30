"""The managed Skill discovers routes from the CLI rather than cached profiles."""
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "multi-search"
BUILTIN_IDS = r"(?:default|web|fast|all|social|dev)"


class SkillRouteDiscoveryTests(unittest.TestCase):
    def test_no_shipped_file_prescribes_builtin_routes(self):
        for path in SKILL_DIR.rglob("*"):
            if not path.is_file():
                continue
            with self.subTest(file=str(path.relative_to(SKILL_DIR))):
                text = path.read_text(encoding="utf-8")
                # CLI examples, including equals forms and quoted values.
                self.assertNotRegex(
                    text, rf"--route(?:\s+|=)[`'\"]?{BUILTIN_IDS}\b"
                )
                # Route-purpose lists and inline lists of route ids.
                self.assertNotRegex(
                    text, rf"(?m)^\s*-\s+`{BUILTIN_IDS}`\s*:"
                )
                self.assertNotRegex(text, rf"`{BUILTIN_IDS}`\s*[,;/]\s*`{BUILTIN_IDS}`")

    def test_route_selection_uses_current_cli_descriptions_and_help(self):
        for name in ("cli.md", "executor.md"):
            with self.subTest(reference=name):
                text = (SKILL_DIR / "references" / name).read_text(encoding="utf-8")
                self.assertIn("multi-search routes --format json", text)
                for field in ("description", "label", "sources", "default_route"):
                    self.assertIn(f"`{field}`", text)
        cli = (SKILL_DIR / "references" / "cli.md").read_text(encoding="utf-8")
        self.assertIn("multi-search <command> --help", cli)
        self.assertNotIn('"routes": {', cli)


if __name__ == "__main__":
    unittest.main()

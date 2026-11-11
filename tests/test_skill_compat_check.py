"""The Skill documents links-only searches and the released 0.4.1 CLI."""
from __future__ import annotations

import re
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "multi-search"


def _read(name: str) -> str:
    return (SKILL_DIR / name).read_text(encoding="utf-8")


class SkillCompatCheckTests(unittest.TestCase):
    def test_executor_uses_no_fetch_for_links_only_requests(self):
        executor = _read("references/executor.md")
        normalized = re.sub(r"\s+", " ", executor)
        self.assertRegex(
            normalized,
            r"(?i)links-only[^.]{0,200}--no-fetch",
            "executor.md must tell the executor to use --no-fetch for links-only requests",
        )

    def test_cli_install_section_describes_the_released_0_4_1(self):
        cli = _read("references/cli.md")
        install = cli.split("## Install", 1)[1].split("\n## ", 1)[0]
        self.assertIn("0.4.1", install)
        self.assertIn("released", install.lower())
        self.assertNotIn("local candidate", cli.lower())
        self.assertNotIn("0.4.0", cli)


if __name__ == "__main__":
    unittest.main()

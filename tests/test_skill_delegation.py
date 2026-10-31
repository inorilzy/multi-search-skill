"""The Skill keeps page bodies in the explore executor, not the main Agent."""
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "multi-search"


def _read(name: str) -> str:
    return (SKILL_DIR / name).read_text(encoding="utf-8")


class SkillDelegationTests(unittest.TestCase):
    def test_executor_returns_positioned_verbatim_excerpts(self):
        executor = _read("references/executor.md")
        for token in ("explore subagent", "`evidence`", "`start`", "`end`", "verbatim"):
            with self.subTest(token=token):
                self.assertIn(token, executor)
        self.assertIn("multi-search fetch <source_id> --full-content", executor)

    def test_main_agent_spot_checks_slices_instead_of_full_bodies(self):
        verification = _read("references/verification.md")
        self.assertIn("--offset", verification)
        self.assertIn("Full bodies stay out of the main Agent's context", verification)
        self.assertNotIn("inspect the entire", verification)

    def test_known_urls_are_delegated_too(self):
        skill = _read("SKILL.md")
        self.assertIn("已知 URL 或 `source_id` 的正文", skill)
        self.assertNotIn("**已知 URL 或已缓存来源：**", skill)


if __name__ == "__main__":
    unittest.main()

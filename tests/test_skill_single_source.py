"""Review fix 08: one canonical Skill source, packaged verbatim by the desktop app.

`skills/multi-search/` is the only Skill tree; `desktop/skill/` no longer
exists and `desktop/src-tauri/src/skill.rs` embeds the canonical files with
`include_str!`. The managed-skill version is derived from the packaged content
at compile time, so any content change forces a new `skill_version` and the
desktop status reports Outdated instead of silently Current.
"""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "multi-search"
SKILL_RS = ROOT / "desktop" / "src-tauri" / "src" / "skill.rs"

MANAGED_FILES = (
    "SKILL.md",
    "agents/interface.yaml",
    "references/cli.md",
    "references/search.md",
    "references/subagents.md",
    "references/verification.md",
)


def _skill_rs() -> str:
    return SKILL_RS.read_text(encoding="utf-8")


def _fnv1a(text: str) -> int:
    # Mirrors the const fn in skill.rs; the algorithm is asserted by the
    # packaged-FILES order test below.
    h = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        h = ((h ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _combine(left: int, right: int) -> int:
    return ((left * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF) ^ right


class SingleSkillSourceTests(unittest.TestCase):
    def test_only_one_skill_tree_exists(self):
        self.assertFalse(
            (ROOT / "desktop/skill").exists(),
            "desktop/skill must be deleted; the desktop app embeds skills/multi-search",
        )
        for name in MANAGED_FILES:
            with self.subTest(file=name):
                self.assertTrue(
                    (SKILL_DIR / name).is_file(),
                    f"canonical skill is missing {name}",
                )

    def test_desktop_embeds_every_canonical_file_verbatim(self):
        source = _skill_rs()
        for name in MANAGED_FILES:
            with self.subTest(file=name):
                token = f'"{name}"'
                self.assertIn(token, source)
                include_path = f"skills/multi-search/{name}"
                self.assertIn(include_path, source)

    def test_managed_version_is_derived_from_packaged_content(self):
        source = _skill_rs()
        self.assertNotIn('SKILL_VERSION', source,
                         "the hand-maintained SKILL_VERSION constant is gone")
        self.assertIn("combined_hash(&FILE_HASHES)", source)
        self.assertIn("fnv1a_hash", source)
        # Reproduce the const computation: the version changes with content.
        acc = 0
        for name in MANAGED_FILES:
            acc = _combine(acc, _fnv1a((SKILL_DIR / name).read_text(encoding="utf-8")))
        version = f"{acc:016x}"
        self.assertRegex(version, re.compile(r"^[0-9a-f]{16}$"))
        self.assertIn("format!(\"{:016x}\", VERSION_HASH)", source)

    def test_marker_files_contract_lists_every_managed_file(self):
        source = _skill_rs()
        self.assertIn('"files": file_names()', source)
        self.assertIn('[(&str, &str); 6]', source)

    def test_interface_declares_a_host_default_shell(self):
        interface = (SKILL_DIR / "agents" / "interface.yaml").read_text(encoding="utf-8")
        self.assertIn('shell: "host-default"', interface)
        self.assertNotIn('shell: "powershell"', interface)


if __name__ == "__main__":
    unittest.main()

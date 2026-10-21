"""Guardrail: the desktop-packaged skill must mirror `skills/multi-search/`.

Ticket 01 makes `skills/multi-search/` the single authoritative copy. The
desktop crate embeds the same files via `include_str!` in
`desktop/src-tauri/src/skill.rs`. This test asserts:

- Every file `include_str!`'d by `skill.rs` exists under `skills/multi-search/`.
- The deployed file list (entries inside `FILES`) covers every file under
  `skills/multi-search/` that is meant to ship, so a new reference cannot be
  added to the source directory without being exposed to the desktop installer.

`agents/interface.yaml` is adapter-generation metadata and is intentionally
not shipped to host skill folders; it is the only file allowed to remain
unshipped.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "skills" / "multi-search"
SKILL_RS = ROOT / "desktop" / "src-tauri" / "src" / "skill.rs"

# Adapter manifests are not deployed to host skill folders; they inform how the
# skill is wrapped for each agent host (Codex, Pi, Claude Code).
UNSHIPPED_ALLOWED = {"agents/interface.yaml"}

INCLUDE_RE = re.compile(
    r'include_str!\("\.\./\.\./\.\./skills/multi-search/([^"]+)"\)'
)


def _files_block(source: str) -> str:
    match = re.search(r"const FILES[^=]*=\s*\[(.*?)\];", source, re.DOTALL)
    if not match:
        raise AssertionError("skill.rs: cannot locate FILES table")
    return match.group(1)


class SkillPackagingParityTest(unittest.TestCase):
    def test_every_include_str_resolves_to_a_source_file(self) -> None:
        text = SKILL_RS.read_text(encoding="utf-8")
        includes = INCLUDE_RE.findall(text)
        self.assertTrue(includes, "no include_str! entries pointing at skills/multi-search/")
        for rel in includes:
            with self.subTest(path=rel):
                self.assertTrue(
                    (SOURCE_DIR / rel).is_file(),
                    f"skills/multi-search/{rel} is missing",
                )

    def test_files_table_covers_all_shippable_sources(self) -> None:
        text = SKILL_RS.read_text(encoding="utf-8")
        body = _files_block(text)
        # Each FILES entry is a ("name", include_str!(...)) tuple.
        names = re.findall(r'\(\s*"([^"]+)"\s*,\s*include_str!', body)
        self.assertTrue(names, "no FILES entries found in skill.rs")
        declared = set(names)

        shipped = {
            str(p.relative_to(SOURCE_DIR)).replace("\\", "/")
            for p in SOURCE_DIR.rglob("*")
            if p.is_file()
        }
        expected = shipped - UNSHIPPED_ALLOWED
        missing = expected - declared
        extras = declared - shipped
        self.assertEqual(
            missing,
            set(),
            f"source files not covered by FILES: {sorted(missing)}",
        )
        self.assertEqual(
            extras,
            set(),
            f"FILES entries without a matching source file: {sorted(extras)}",
        )

    def test_no_second_skill_tree_under_desktop(self) -> None:
        duplicate = ROOT / "desktop" / "skill" / "multi-search"
        self.assertFalse(
            duplicate.exists(),
            "desktop/skill/multi-search must not be re-introduced; "
            "skills/multi-search/ is the only source of truth.",
        )


if __name__ == "__main__":
    unittest.main()

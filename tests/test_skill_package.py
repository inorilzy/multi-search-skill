"""Guardrail: the desktop-packaged skill must mirror `skills/multi-search/`.

Ticket 01 makes `skills/multi-search/` the single authoritative copy. The
desktop crate embeds the same files via `include_str!` on the Rust side; ticket
10 moved that definition from `skill.rs` into `skill_common.rs`, so this test
locates the FILES table in either module. It asserts:

- Every file `include_str!`'d from `skills/multi-search/` exists there.
- The deployed file list (entries inside `FILES`) covers every file under
  `skills/multi-search/` that is meant to ship, so a new reference cannot be
  added to the source directory without being exposed to the desktop installer.

`agents/interface.yaml` is part of the installed five-file Skill and its
content participates in the managed version hash.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "skills" / "multi-search"
SRC_DIR = ROOT / "desktop" / "src-tauri" / "src"
# The FILES table may live in skill.rs (pre-ticket-10) or skill_common.rs
# (after ticket 10 centralised the shared Skill definition).
FILES_CANDIDATES = (SRC_DIR / "skill_common.rs", SRC_DIR / "skill.rs")

UNSHIPPED_ALLOWED = set()

INCLUDE_RE = re.compile(
    r'include_str!\("\.\./\.\./\.\./skills/multi-search/([^"]+)"\)'
)


def _files_block(source: str) -> str:
    match = re.search(r"const FILES[^=]*=\s*\[(.*?)\];", source, re.DOTALL)
    if not match:
        raise AssertionError("cannot locate FILES table in skill_common.rs or skill.rs")
    return match.group(1)


def _files_source() -> tuple[Path, str]:
    """Return the module that currently declares FILES, plus its text."""
    for path in FILES_CANDIDATES:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"const FILES[^=]*=\s*\[", text):
            return path, text
    raise AssertionError("FILES table not found in any known Skill module")


class SkillPackagingParityTest(unittest.TestCase):
    def test_every_include_str_resolves_to_a_source_file(self) -> None:
        includes: list[str] = []
        for path in FILES_CANDIDATES:
            if path.is_file():
                includes.extend(INCLUDE_RE.findall(path.read_text(encoding="utf-8")))
        self.assertTrue(includes, "no include_str! entries pointing at skills/multi-search/")
        for rel in includes:
            with self.subTest(path=rel):
                self.assertTrue(
                    (SOURCE_DIR / rel).is_file(),
                    f"skills/multi-search/{rel} is missing",
                )

    def test_files_table_covers_all_shippable_sources(self) -> None:
        path, text = _files_source()
        body = _files_block(text)
        # Each FILES entry is a ("name", include_str!(...)) tuple.
        names = re.findall(r'\(\s*"([^"]+)"\s*,\s*include_str!', body)
        self.assertTrue(names, f"no FILES entries found in {path.name}")
        declared = set(names)

        shipped = {
            str(p.relative_to(SOURCE_DIR)).replace("\\", "/")
            for p in SOURCE_DIR.rglob("*")
            if p.is_file()
        }
        expected = shipped - UNSHIPPED_ALLOWED
        self.assertEqual(shipped, {
            "SKILL.md", "agents/interface.yaml", "references/cli.md",
            "references/executor.md", "references/verification.md",
        })
        self.assertIn("agents/interface.yaml", declared)
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

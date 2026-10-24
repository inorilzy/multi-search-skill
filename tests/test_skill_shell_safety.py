"""Regression checks for the Skill's shell-safety contract (review fix 07)."""
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# A single canonical skill source (review fix 08); desktop/skill is gone.
SKILL_ROOTS = (ROOT / "skills/multi-search",)

UNSAFE_PATTERNS = (
    (re.compile(r'--url\s+"'), "double-quoted --url example"),
    (re.compile(r"--url\s+<[^>]+>"), "unquoted --url placeholder"),
    (re.compile(r'--keyword\s+"'), "double-quoted --keyword example"),
    (re.compile(r'--expand\s+"'), "double-quoted --expand example"),
    (re.compile(r'multi-search search\s+"'), "double-quoted query example"),
)


class SkillDocSafetyTests(unittest.TestCase):
    def test_canonical_skill_documents_the_safe_url_path(self):
        for root in SKILL_ROOTS:
            with self.subTest(skill=str(root.relative_to(ROOT))):
                cli_doc = (root / "references/cli.md").read_text(encoding="utf-8")
                skill_doc = (root / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("--url-file", cli_doc)
                self.assertIn("--url-file", skill_doc)
                self.assertIn("single quotes", cli_doc)
                self.assertIn("double quotes", cli_doc)

    def test_no_skill_doc_teaches_unquoted_or_double_quoted_untrusted_values(self):
        for root in SKILL_ROOTS:
            for path in sorted(root.rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                for pattern, label in UNSAFE_PATTERNS:
                    with self.subTest(document=str(path.relative_to(ROOT)), rule=label):
                        self.assertNotRegex(text, pattern)


@unittest.skipUnless(Path("/bin/sh").exists(), "POSIX shell is required")
class SingleQuoteShellTests(unittest.TestCase):
    def test_single_quoted_url_is_not_command_substituted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            captured = root / "argv"
            stub = root / "multi-search"
            stub.write_text(
                '#!/bin/sh\nprintf \'%s\\n\' "$@" > ' + shlex.quote(str(captured)) + "\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
            hostile = f"https://example.com/$(touch {marker})?q=`touch {marker}.backtick`"

            subprocess.run(
                ["/bin/sh", "-c", f"{shlex.quote(str(stub))} fetch --url '{hostile}'"],
                check=True,
            )

            self.assertFalse(marker.exists())
            self.assertFalse(Path(str(marker) + ".backtick").exists())
            self.assertEqual(
                captured.read_text(encoding="utf-8").splitlines(),
                ["fetch", "--url", hostile],
            )


if __name__ == "__main__":
    unittest.main()

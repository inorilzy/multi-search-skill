"""Review fix 19: README, docs index, and CONTEXT stay in sync with the code."""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DOCS = ROOT / "docs"
DOC_INDEX = DOCS / "README.md"
CONTEXT = ROOT / "CONTEXT.md"
PAGES_JS = ROOT / "desktop" / "ui" / "pages.js"

PAGE_PATTERN = re.compile(
    r"\{\s*id:\s*'([^']+)',\s*label:\s*'([^']+)',\s*number:\s*'([^']+)'"
)
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _pages():
    source = PAGES_JS.read_text(encoding="utf-8")
    return [
        {"id": match.group(1), "label": match.group(2), "number": match.group(3)}
        for match in PAGE_PATTERN.finditer(source)
    ]


def _readme_rows(readme_text):
    return [
        (number, label.strip())
        for number, label in re.findall(r"^\| (\d{2}) ([^|]+?) \|", readme_text, re.MULTILINE)
    ]


def _local_links(path):
    text = path.read_text(encoding="utf-8")
    for raw in LINK_PATTERN.findall(text):
        target = raw.strip()
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        yield target.split("#", 1)[0]


class ReadmeDesktopTests(unittest.TestCase):
    def test_desktop_section_lists_exactly_the_pages_the_ui_mounts(self):
        pages = _pages()
        self.assertEqual(len(pages), 6, "pages.js must define the six management pages")
        readme = README.read_text(encoding="utf-8")
        self.assertIn("共 6 个页面", readme)
        rows = _readme_rows(readme)
        self.assertEqual(
            rows,
            [(page["number"], page["label"]) for page in pages],
            "README desktop table must match desktop/ui/pages.js in order and label",
        )

    def test_desktop_capabilities_are_described(self):
        readme = README.read_text(encoding="utf-8")
        for capability in (
            "安装 CLI",
            "Claude Code Skill",
            "搜索源与凭据",
            "搜索设置",
            "旧配置迁移",
            "Windows 凭据库",
            "bundle 的信任锚",
            "Job Object",
        ):
            with self.subTest(capability=capability):
                self.assertIn(capability, readme)

    def test_stale_claims_are_gone(self):
        readme = README.read_text(encoding="utf-8")
        self.assertNotIn("尚不提供 UI 安装", readme)
        self.assertNotIn("doctor` tool", readme)
        self.assertNotIn("doctor tool", readme)


class ReadmeCredentialTests(unittest.TestCase):
    def test_credential_precedence_matches_the_core(self):
        readme = README.read_text(encoding="utf-8")
        self.assertIn(
            "环境变量（`env`）> Windows 凭据库（`credential_store`）> `~/.search-keys.json`（`keys_file`）",
            readme,
        )
        self.assertIn("不会回退到明文文件", readme)
        self.assertIn("multi-search/<provider>", readme)

    def test_migrate_legacy_is_documented_with_both_steps(self):
        readme = README.read_text(encoding="utf-8")
        self.assertIn("multi-search migrate-legacy plan", readme)
        self.assertIn("multi-search migrate-legacy apply", readme)
        self.assertIn("plan_token", readme)
        self.assertIn("legacy_file_has_plaintext", readme)

    def test_documented_subcommands_exist_in_the_cli(self):
        from multi_search_mcp.cli import build_parser

        parser = build_parser()
        subcommands = set(parser._subparsers._group_actions[0].choices)
        readme = README.read_text(encoding="utf-8")
        for name in subcommands:
            with self.subTest(subcommand=name):
                self.assertIn(f"`{name}", readme)


class DocsIndexTests(unittest.TestCase):
    def test_index_exists_and_covers_every_document(self):
        self.assertTrue(DOC_INDEX.is_file(), "docs/README.md index is missing")
        index = DOC_INDEX.read_text(encoding="utf-8")
        documents = sorted(
            path.name for path in DOCS.glob("*.md") if path.name != "README.md"
        )
        self.assertGreater(len(documents), 20)
        for name in documents:
            with self.subTest(document=name):
                self.assertIn(name, index, f"docs/README.md does not list {name}")

    def test_archived_architecture_lives_under_history_and_is_labelled(self):
        for name in ("architecture-simple.md", "mcp-dispatch.md"):
            with self.subTest(document=name):
                self.assertFalse((DOCS / name).exists(), f"{name} must be archived")
                archived = DOCS / "history" / name
                self.assertTrue(archived.is_file())
                self.assertIn("已归档", archived.read_text(encoding="utf-8"))
        for name in (
            "current-architecture.html",
            "current-architecture.mmd",
            "current-architecture.svg",
        ):
            with self.subTest(document=name):
                self.assertFalse((DOCS / name).exists(), f"{name} must be archived")
                self.assertTrue((DOCS / "history" / name).is_file())
        index = DOC_INDEX.read_text(encoding="utf-8")
        self.assertIn("历史架构（已归档）", index)
        for name in (
            "architecture-simple.md",
            "mcp-dispatch.md",
            "current-architecture.html",
            "current-architecture.mmd",
            "current-architecture.svg",
        ):
            with self.subTest(document=name):
                self.assertIn(name, index)

    def test_index_marks_historical_mcp_context(self):
        index = DOC_INDEX.read_text(encoding="utf-8")
        self.assertIn("server.py", index)
        self.assertIn("历史记录", index)


class ContextTests(unittest.TestCase):
    def test_context_covers_desktop_concepts(self):
        text = CONTEXT.read_text(encoding="utf-8")
        for term in (
            "受管 CLI",
            "bundle 锚点",
            "Windows 凭据库",
            "受管 Skill",
            "skill_version",
            "Credential store",
        ):
            with self.subTest(term=term):
                self.assertIn(term, text)
        self.assertIn("docs/README.md", text)


class LocalLinkTests(unittest.TestCase):
    def test_readme_local_links_resolve(self):
        for target in _local_links(README):
            with self.subTest(link=target):
                self.assertTrue((ROOT / target).exists(), f"README link does not resolve: {target}")

    def test_docs_index_local_links_resolve(self):
        for target in _local_links(DOC_INDEX):
            with self.subTest(link=target):
                self.assertTrue(
                    (DOC_INDEX.parent / target).exists(),
                    f"docs/README.md link does not resolve: {target}",
                )

    def test_context_local_links_resolve(self):
        for target in _local_links(CONTEXT):
            with self.subTest(link=target):
                self.assertTrue(
                    (ROOT / target).exists(),
                    f"CONTEXT.md link does not resolve: {target}",
                )


if __name__ == "__main__":
    unittest.main()

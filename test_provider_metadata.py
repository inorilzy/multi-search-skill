import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.search import capabilities as capabilities_module
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.search_runner import ALL_SOURCE_NAMES


ROOT = Path(__file__).resolve().parent


class ProviderMetadataTests(unittest.TestCase):
    def test_source_catalog_matches_searchable_capabilities(self):
        expected = {
            name
            for name, capability in capabilities_module.PROVIDER_CAPABILITIES.items()
            if capability.search.can_search
        }
        self.assertEqual(ALL_SOURCE_NAMES, expected)

    def test_registry_metadata_is_driven_by_capabilities(self):
        original = capabilities_module.PROVIDER_CAPABILITIES["brave"]
        patched = replace(
            original,
            public_name="brave-public",
            timeout_default=99,
            operation=replace(original.operation, key_name="brave_override"),
        )

        with mock.patch.dict(
            capabilities_module.PROVIDER_CAPABILITIES,
            {"brave": patched},
            clear=False,
        ):
            registry = build_provider_registry()

        spec = registry["brave"]
        self.assertEqual(spec.public_name, "brave-public")
        self.assertEqual(spec.key_name, "brave_override")
        self.assertEqual(spec.timeout_default, 99)


class VerticalRouteDocsTests(unittest.TestCase):
    def test_vertical_route_is_documented_across_user_facing_docs(self):
        expected_snippets = {
            ROOT / "README.md": ("`vertical`", "reddit-browser"),
            ROOT / "docs" / "glossary.md": ("`vertical`", "reddit_browser"),
            ROOT / "skills" / "multi-search" / "SKILL.md": ("`vertical`", "reddit"),
        }

        for path, snippets in expected_snippets.items():
            text = path.read_text(encoding="utf-8")
            for snippet in snippets:
                self.assertIn(snippet, text, f"{path} missing {snippet!r}")


if __name__ == "__main__":
    unittest.main()

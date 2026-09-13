import unittest
from dataclasses import replace
from unittest import mock

from multi_search_mcp.src.search import capabilities as capabilities_module
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.search_runner import ALL_SOURCE_NAMES


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


if __name__ == "__main__":
    unittest.main()

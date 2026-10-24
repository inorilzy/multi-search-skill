"""Architecture guard for the split Core service (issue 22 / review M-16, M-17, L-02).

These tests pin the public seams and layering so the service cannot quietly
return to one large module, private candidate calls, duck-typed planning, or a
reverse dependency from snapshot capture into ``service``.
"""
from __future__ import annotations

import ast
import inspect
import unittest
from typing import get_type_hints
from pathlib import Path
from types import SimpleNamespace

from multi_search_mcp.src import service
from multi_search_mcp.src.search.resolve import SearchPlanRequest, resolve_search_plan


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "multi_search_mcp" / "src"
SERVICE = SRC / "service.py"
SNAPSHOTS = SRC / "search" / "snapshots.py"
TOP_LEVEL_SERVICE_MODULES = {
    "service", "read", "search_web", "multi_search", "diagnostics",
}
# Known pre-existing edge outside this ticket's scope: the legacy key-file
# migration adapter needs the keys parser. Everything else must point downward.
KNOWN_SUPPORT_UPWARD = {"legacy_migration.py"}


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.append((node.level, node.module or ""))
        elif isinstance(node, ast.Import):
            found.extend((0, alias.name) for alias in node.names)
    return found


class ServiceFacadeTests(unittest.TestCase):
    def test_service_facade_is_thin_and_logic_free(self):
        text = SERVICE.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 150, "service.py must stay a facade")
        tree = ast.parse(text)
        definitions = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        self.assertEqual(definitions, [], "implementations belong in focused modules, not service.py")
        imported = {
            (node.module or "").split(".")[-1]
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
        }
        for module in (
            "candidates", "resolve", "requests", "fetch", "service", "read",
            "search_web", "multi_search", "diagnostics", "formatting",
        ):
            self.assertIn(module, imported, f"facade must re-export the {module} seam")

    def test_public_candidate_seam_replaces_private_name(self):
        self.assertTrue(callable(service.run_search_candidates))
        self.assertFalse(hasattr(service, "_run_search_candidates"))
        for path in (ROOT / "tests").glob("*.py"):
            if path.name == "test_service_structure.py":
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "_run_search_candidates", text,
                f"{path.name} must call the public run_search_candidates seam",
            )

    def test_snapshot_capture_has_no_reverse_service_dependency(self):
        imports = _imports(SNAPSHOTS)
        for level, module in imports:
            self.assertFalse(
                level >= 2 and (module == "service" or module.startswith("service.")),
                "search/snapshots.py must not import the top-level service module",
            )
            self.assertFalse(
                module == "multi_search_mcp.src.service"
                or module.startswith("multi_search_mcp.src.service."),
                "search/snapshots.py must not import the top-level service module",
            )
        source = SNAPSHOTS.read_text(encoding="utf-8")
        self.assertIn("from .candidates import run_search_candidates", source)
        self.assertIn("SearchPlanRequest", source)
        self.assertNotIn("_load_runtime_keys", source)


class PlanningRequestTests(unittest.TestCase):
    def test_resolve_search_plan_requires_explicit_request_type(self):
        request_type = get_type_hints(resolve_search_plan)["request"]
        self.assertIs(request_type, SearchPlanRequest)
        signature = inspect.signature(resolve_search_plan)
        self.assertIn("request", signature.parameters)
        for duck in (
            SimpleNamespace(route="default", sources=None, count=None, timeout=None),
            service.MultiSearchRequest(query="q"),
        ):
            with self.assertRaises(TypeError, msg=f"{type(duck).__name__} must not be duck-typed"):
                resolve_search_plan(duck, {})
        plan = resolve_search_plan(SearchPlanRequest(route="fast"), {})
        self.assertEqual(plan.route, "fast")


class LayerDirectionTests(unittest.TestCase):
    def _violations(
        self, directory: Path, forbidden: set[str], *, allowed: set[str] = frozenset(),
    ) -> list[str]:
        violations = []
        for path in sorted(directory.rglob("*.py")):
            if path.name in allowed:
                continue
            for level, module in _imports(path):
                if level < 2:
                    continue
                first = module.split(".")[0]
                dotted = ".".join(module.split(".")[:2])
                if first in forbidden or dotted in forbidden:
                    violations.append(f"{path.relative_to(SRC)} -> {'.' * level}{module}")
        return violations

    def test_support_imports_nothing_above_it(self):
        self.assertEqual(
            self._violations(SRC / "support", {
                "state", "search", "scrape", *TOP_LEVEL_SERVICE_MODULES,
            }, allowed=KNOWN_SUPPORT_UPWARD),
            [],
        )

    def test_state_does_not_import_search_scrape_or_service_layer(self):
        self.assertEqual(
            self._violations(SRC / "state", {
                "search", "scrape", *TOP_LEVEL_SERVICE_MODULES,
            }),
            [],
        )

    def test_search_and_scrape_do_not_import_service_layer(self):
        self.assertEqual(
            self._violations(SRC / "search", set(TOP_LEVEL_SERVICE_MODULES)),
            [],
        )
        self.assertEqual(
            self._violations(SRC / "scrape", set(TOP_LEVEL_SERVICE_MODULES)),
            [],
        )

    def test_top_level_orchestration_modules_exist_and_are_below_facade_size(self):
        for name, maximum in (
            ("read.py", 120),
            ("search_web.py", 200),
            ("multi_search.py", 180),
            ("diagnostics.py", 160),
            ("search/candidates.py", 400),
            ("search/formatting.py", 250),
            ("scrape/fetch.py", 260),
            ("scrape/service.py", 160),
        ):
            path = SRC / name
            self.assertTrue(path.is_file(), f"{name} must exist")
            self.assertLessEqual(
                len(path.read_text(encoding="utf-8").splitlines()), maximum,
                f"{name} grew beyond its focused responsibility",
            )
        self.assertGreaterEqual(len(list((SRC / "search").glob("*.py"))), 8)


if __name__ == "__main__":
    unittest.main()

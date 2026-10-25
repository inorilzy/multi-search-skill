"""CI contract: every test suite runs on push/PR and third-party actions are SHA-pinned.

Parsed without a YAML dependency: the workflows are plain block YAML, and these checks
only need job boundaries, `uses:` lines, matrix lists and `run:` commands.
"""
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
TEST_WORKFLOW = WORKFLOWS / "test.yml"
PINNED_USE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}(?:\s+#\s*v\d[\w.-]*)?$")


def _jobs(text: str) -> dict[str, str]:
    """Split the top-level `jobs:` mapping into {job id: job body}."""
    body = text.split("\njobs:\n", 1)[1]
    jobs: dict[str, str] = {}
    current = None
    for line in body.splitlines():
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            current = match.group(1)
            jobs[current] = ""
        elif current is not None:
            jobs[current] += line + "\n"
    return jobs


def _commands(job: str) -> str:
    """All run commands of a job, with folded (`>`/`|`) continuations joined."""
    return re.sub(r"\s+", " ", " ".join(
        re.findall(r"run:\s*[>|]?-?\s*\n?((?:.*\n?)(?:\s{10,}.*\n?)*)", job)
    ))


def _cargo_tests(manifest: str) -> list[tuple[str, set[str]]]:
    """[[test]] targets with their required features (tomllib is unavailable on 3.10)."""
    return [(name, features) for name, features, _ in _cargo_test_targets(manifest)]


def _cargo_test_targets(manifest: str) -> list[tuple[str, set[str], str]]:
    """[[test]] targets with their required features and source path."""
    targets = []
    for block in re.split(r"(?m)^\[\[test\]\]\s*$", manifest)[1:]:
        block = re.split(r"(?m)^\[", block, maxsplit=1)[0]
        name = re.search(r'(?m)^name\s*=\s*"([^"]+)"', block).group(1)
        required = re.search(r"(?m)^required-features\s*=\s*\[([^\]]*)\]", block)
        features = set(re.findall(r'"([^"]+)"', required.group(1))) if required else set()
        path = re.search(r'(?m)^path\s*=\s*"([^"]+)"', block).group(1)
        targets.append((name, features, path))
    return targets


def _windows_exempt(manifest: str) -> set[str]:
    """Targets whose source is compiled out on Windows (`#![cfg(not(windows))]`).

    They still must be selected somewhere: `test_managed_install_runs_on_macos_and_windows`
    checks the macOS job, so the Windows job assertion skips them instead of pretending
    a macOS-only acceptance target runs there.
    """
    exempt = set()
    base = ROOT / "desktop/src-tauri"
    for name, _, path in _cargo_test_targets(manifest):
        if re.search(r"#!\[cfg\(not\(windows\)\)\]", (base / path).read_text(encoding="utf-8")):
            exempt.add(name)
    return exempt


def _matrix(job: str, key: str) -> list[str]:
    match = re.search(r"^\s+" + key + r":\s*\[([^\]]*)\]", job, re.M)
    if not match:
        return []
    return [item.strip().strip("'\"") for item in match.group(1).split(",")]


class CiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = TEST_WORKFLOW.read_text(encoding="utf-8")
        self.jobs = _jobs(self.text)

    def test_runs_on_every_push_and_pull_request(self):
        self.assertRegex(self.text, r"(?m)^on:\n(?:\s+.*\n)*?\s+push:")
        self.assertRegex(self.text, r"(?m)^on:\n(?:\s+.*\n)*?\s+pull_request:")

    def test_every_third_party_action_is_pinned_to_a_commit_sha(self):
        for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
            for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
                match = re.match(r"^\s*-?\s*uses:\s*(.+?)\s*$", line)
                if not match or match.group(1).startswith("./"):
                    continue
                with self.subTest(workflow=workflow.name, line=number):
                    self.assertRegex(match.group(1), PINNED_USE)

    def test_python_job_covers_lowest_and_highest_python_on_macos_and_windows(self):
        job = self.jobs["python"]
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        lowest = re.search(r'(?m)^requires-python\s*=\s*">=\s*(3\.\d+)"', pyproject).group(1)
        versions = _matrix(job, "python")
        self.assertIn(lowest, versions)
        self.assertEqual(max(versions, key=lambda v: tuple(map(int, v.split(".")))), "3.14")
        for os_name in ("windows-latest", "macos-latest", "ubuntu-latest"):
            self.assertIn(os_name, _matrix(job, "os"))
        self.assertIn("python scripts/run_tests.py", _commands(job))

    def test_scripts_tests_are_discovered_not_listed(self):
        commands = _commands(self.jobs["python"])
        self.assertIn("unittest discover -s scripts", commands)
        # Every scripts/test_*.py other than the isolation helper is a real test module.
        modules = {p.stem for p in (ROOT / "scripts").glob("test_*.py")} - {"test_isolation"}
        self.assertGreaterEqual(modules, {"test_build_cli_bundle", "test_bundle_manifest"})

    def test_desktop_js_job_installs_locked_deps_and_runs_tests(self):
        job = self.jobs["desktop-js"]
        self.assertIn("working-directory: desktop", job)
        self.assertRegex(job, r"node-version:\s*\"?(2[0-9]|[3-9][0-9])")
        commands = _commands(job)
        self.assertIn("npm ci", commands)
        self.assertIn("npm test", commands)

    def test_managed_install_runs_on_macos_and_windows(self):
        manifest = (ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
        targets = dict(_cargo_tests(manifest))
        self.assertIn("install_platform", targets, "autotests=false requires explicit registration")
        for job_name, runner in (("desktop-rust", "windows-latest"),
                                 ("desktop-macos", "macos-latest")):
            with self.subTest(runner=runner):
                job = self.jobs[job_name]
                self.assertIn(f"runs-on: {runner}", job)
                commands = _commands(job)
                self.assertIn("--features test-fixtures,install-test-boundary", commands)
                self.assertIn("--test install_platform", commands)
                self.assertIn("--test install_release_boundary", commands)
                if runner == "macos-latest":
                    # macOS-only sources (`#![cfg(not(windows))]`): they must at least
                    # compile there — the env-override real-bundle check and the
                    # compiled-anchor/real-platform-root check.
                    self.assertIn("--test install_real_bundle", commands)
                    self.assertIn("--test install_production_path", commands)
                self.assertIn("--features test-fixtures,ts", commands)

    def test_desktop_rust_job_runs_every_feature_gated_test_on_windows(self):
        job = self.jobs["desktop-rust"]
        self.assertIn("runs-on: windows-latest", job)
        commands = _commands(job)
        manifest = (ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
        targets = _cargo_tests(manifest)
        exempt = _windows_exempt(manifest)
        self.assertGreaterEqual(len(targets), 10)
        self.assertIn("--locked", commands)
        self.assertIn("--no-default-features", commands)
        runs = []
        for run in re.findall(r"cargo test ([^`]*?)(?=cargo test|$)", commands):
            features = re.findall(r"--features ([\w,-]+)", run)
            selected = set(re.findall(r"--test ([\w-]+)", run))  # empty: every target
            runs.append((set(features[0].split(",")) if features else set(), selected))
        self.assertTrue(runs, "no cargo test run")
        for name, required in targets:
            if name in exempt:
                continue  # macOS-only source; covered by the macOS job assertion
            with self.subTest(test=name):
                # Some cargo test run must select this target and enable every feature it requires.
                self.assertTrue(any(
                    required <= features and (not selected or name in selected)
                    for features, selected in runs
                ), required)


class DesktopPackageTests(unittest.TestCase):
    def test_happy_dom_is_a_locked_dev_dependency(self):
        package = json.loads((ROOT / "desktop/package.json").read_text(encoding="utf-8"))
        self.assertIn("happy-dom", package.get("devDependencies", {}))
        self.assertNotIn("happy-dom", package.get("dependencies", {}))
        lock = json.loads((ROOT / "desktop/package-lock.json").read_text(encoding="utf-8"))
        self.assertIn("happy-dom", lock["packages"][""]["devDependencies"])
        self.assertTrue(lock["packages"]["node_modules/happy-dom"].get("dev"))


if __name__ == "__main__":
    unittest.main()

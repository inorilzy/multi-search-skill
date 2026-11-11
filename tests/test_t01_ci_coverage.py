"""T01 regression: optional Twitter tests and Linux Rust tests must run in CI."""
import unittest

from tests.test_ci_workflow import ROOT, TEST_WORKFLOW, _cargo_tests, _commands, _jobs


class TestCoverageRegressionTests(unittest.TestCase):
    def setUp(self):
        self.jobs = _jobs(TEST_WORKFLOW.read_text(encoding="utf-8"))

    def test_twitter_job_installs_pinned_xkit_and_requires_import_before_tests(self):
        job = self.jobs.get("python-twitter", "")
        self.assertIn("runs-on: ubuntu-latest", job)
        self.assertIn("repository: inorilzy/xkit-py", job)
        self.assertIn("ref: c02ff46efd0264b4bc85968e3f5732561ffdbaf3", job)
        self.assertIn("token: ${{ secrets.XKIT_READ_TOKEN }}", job)
        self.assertIn("persist-credentials: false", job)
        commands = _commands(job)
        self.assertIn("python -m pip install . ./.xkit-source", commands)
        self.assertIn("from xkit import Client; from twikit.tweet import Tweet", commands)
        self.assertIn("python -m unittest tests.test_twitter_scraper -v", commands)
        self.assertLess(commands.index("from xkit import Client"),
                        commands.index("python -m unittest"))
        self.assertNotIn("continue-on-error:", job)
        self.assertNotIn("if:", job)

    def test_linux_job_runs_every_rust_test_with_locked_python_dependencies(self):
        job = self.jobs.get("desktop-linux", "")
        self.assertIn("runs-on: ubuntu-latest", job)
        commands = _commands(job)
        self.assertIn("uv sync --locked --python 3.12", commands)
        self.assertIn('echo "$GITHUB_WORKSPACE/.venv/bin" >> "$GITHUB_PATH"', commands)
        self.assertIn("rustup toolchain install", commands)
        manifest = (ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
        self.assertIn('cargo test --locked --manifest-path "$MANIFEST" --no-default-features '
                      '--features test-fixtures,ts', commands)
        for name, required in _cargo_tests(manifest):
            if "install-test-boundary" in required:
                with self.subTest(target=name):
                    self.assertIn(f"--test {name}", commands)
        self.assertIn("--features test-fixtures,install-test-boundary", commands)
        self.assertIn("--test install_release_boundary", commands)
        self.assertNotIn("continue-on-error:", job)
        self.assertNotIn("if:", job)


if __name__ == "__main__":
    unittest.main()

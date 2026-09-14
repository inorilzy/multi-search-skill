import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from scripts.test_isolation import isolated_test_environment


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(POWERSHELL, "PowerShell is required to execute setup scripts")
class InitSetupTests(unittest.TestCase):
    def run_init(self, *arguments, failure=""):
        with isolated_test_environment(source_root=ROOT) as isolation:
            project = isolation.root / "project's [copy]"
            support = project / "multi_search_mcp" / "src" / "support"
            support.mkdir(parents=True)
            shutil.copyfile(ROOT / "multi_search_mcp/src/support/init.ps1", support / "init.ps1")
            (project / "pyproject.toml").write_text('[project]\nname = "setup-test"\nversion = "0.0.0"\n')
            (project / "uv.lock").write_text("version = 1\n")
            log = isolation.root / "uv.jsonl"
            wrapper = isolation.root / "run-init.ps1"
            wrapper.write_text(
                "function global:uv {\n"
                "    $invocation = @($args)\n"
                "    @{ arguments = $invocation; cwd = (Get-Location).Path } | "
                "ConvertTo-Json -Compress | Add-Content -LiteralPath $env:MOCK_UV_LOG\n"
                "    $global:LASTEXITCODE = if ($invocation[0] -eq $env:MOCK_UV_FAILURE) { 23 } else { 0 }\n"
                "}\n"
                "& (Join-Path $env:MOCK_PROJECT 'multi_search_mcp/src/support/init.ps1') @args\n",
                encoding="utf-8",
            )
            environment = dict(os.environ, MOCK_UV_LOG=str(log), MOCK_PROJECT=str(project), MOCK_UV_FAILURE=failure)
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper), *arguments],
                cwd=isolation.root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            calls = [json.loads(line) for line in log.read_text(encoding="utf-8-sig").splitlines()]
            self.assertTrue(all(Path(call["cwd"]).resolve() == project.resolve() for call in calls), calls)
            isolation.assert_clean()
            return result, [call["arguments"] for call in calls]

    def test_syncs_locked_project_before_running_installed_doctor(self):
        result, calls = self.run_init("-PythonVersion", "3.11")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            ["python", "install", "3.11"],
            ["sync", "--locked", "--python", "3.11"],
            ["run", "--no-sync", "multi-search", "doctor"],
        ])
        self.assertIn("uv run --no-sync multi-search doctor", result.stdout)
        self.assertIn("uv run --no-sync multi-search-mcp", result.stdout)
        self.assertNotIn("twikit-ng", result.stdout)

    def test_skip_twitter_is_compatible_but_does_not_skip_dependencies(self):
        result, calls = self.run_init("-SkipTwitter")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["sync", "--locked", "--python", "3.12"], calls)
        self.assertIn("deprecated", result.stdout)
        self.assertIn("all project dependencies", result.stdout)

    def test_failed_sync_stops_before_doctor_and_success_message(self):
        result, calls = self.run_init(failure="sync")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [
            ["python", "install", "3.12"],
            ["sync", "--locked", "--python", "3.12"],
        ])
        self.assertIn("exit code 23", result.stderr)
        self.assertNotIn("Done.", result.stdout)

    def test_failed_doctor_does_not_claim_success(self):
        result, calls = self.run_init(failure="run")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls[-1], ["run", "--no-sync", "multi-search", "doctor"])
        self.assertIn("exit code 23", result.stderr)
        self.assertNotIn("Done.", result.stdout)


if __name__ == "__main__":
    unittest.main()

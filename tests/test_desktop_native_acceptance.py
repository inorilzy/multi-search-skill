"""Focused checks for the T2 installed-CLI acceptance runner."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import desktop_native_acceptance as runner


class DesktopNativeAcceptanceRunnerTests(unittest.TestCase):
    def test_sha256_matches_file_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "payload.bin"
            payload = b"installed-cli-acceptance\x00"
            path.write_bytes(payload)
            self.assertEqual(runner.sha256(path), hashlib.sha256(payload).hexdigest())

    def test_compile_requires_exactly_one_test_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target"
            deps = target / "debug" / "deps"
            deps.mkdir(parents=True)
            evidence = Path(temp) / "evidence"
            completed = runner.subprocess.CompletedProcess(
                ["cargo"],
                0,
                stdout='{"reason":"compiler-artifact","profile":{"test":false},"target":{"name":"installed_cli"},"executable":""}\n',
                stderr="",
            )
            with mock.patch.object(runner.subprocess, "run", return_value=completed) as run:
                with self.assertRaises(RuntimeError) as error:
                    runner.compile_native_test(target, evidence)
            self.assertIn("expected Cargo to report exactly one", str(error.exception))
            self.assertEqual(run.call_args.kwargs["env"]["CARGO_TARGET_DIR"], str(target))

            binary = deps / "installed_cli-fixture.exe"
            binary.write_bytes(b"test")
            completed.stdout = json.dumps({
                "reason": "compiler-artifact",
                "profile": {"test": True},
                "target": {"name": "installed_cli"},
                "executable": str(binary),
            })
            with mock.patch.object(runner.subprocess, "run", return_value=completed):
                self.assertEqual(runner.compile_native_test(target, evidence), binary)

    def test_compile_enables_acceptance_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target"
            deps = target / "debug" / "deps"
            deps.mkdir(parents=True)
            binary = deps / "installed_cli-fixture.exe"
            binary.write_bytes(b"test")
            completed = runner.subprocess.CompletedProcess(
                ["cargo"],
                0,
                stdout='{"reason":"compiler-artifact","profile":{"test":true},"target":{"name":"installed_cli"},"executable":"%s"}\n'
                % binary.as_posix(),
                stderr="",
            )
            with mock.patch.object(runner.subprocess, "run", return_value=completed) as run:
                self.assertEqual(runner.compile_native_test(target, Path(temp)), binary)
            command = run.call_args.args[0]
            self.assertIn("--features", command)
            self.assertIn("install-test-boundary", command)

    def test_install_uses_no_index_and_no_deps_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wheel = root / "multi_search_mcp-0.4.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel")
            base = root / "python.exe"
            base.write_bytes(b"python")
            venv = root / ".wheel-venv"
            scripts = venv / ("Scripts" if os.name == "nt" else "bin")
            calls = []

            def fake_run(command, *, cwd, env=None, log=None):
                calls.append(command)
                if "venv" in command:
                    scripts.mkdir(parents=True, exist_ok=True)
                    (scripts / ("multi-search.exe" if os.name == "nt" else "multi-search")).write_bytes(b"cli")
                return runner.subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(runner, "run", side_effect=fake_run):
                self.assertEqual(
                    runner.install_wheel(wheel, venv, base, root),
                    scripts / ("multi-search.exe" if os.name == "nt" else "multi-search"),
                )
            self.assertTrue((venv / runner.OWNER_MARKER).is_file())
            install_command = calls[1]
            self.assertIn("--no-index", install_command)
            self.assertIn("--no-deps", install_command)
            self.assertEqual(install_command[-1], str(wheel))


    def test_nonmatching_filter_is_rejected_even_with_zero_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            completed = runner.subprocess.CompletedProcess(
                ["installed_cli"],
                0,
                stdout="running 0 tests\ntest result: ok. 0 passed; 0 failed;",
                stderr="",
            )
            with mock.patch.object(runner, "run", return_value=completed):
                with self.assertRaises(RuntimeError) as error:
                    runner.execute_native_test(
                        Path("installed_cli.exe"),
                        "missing_filter",
                        cwd=Path(temp),
                        environment={},
                        log=Path(temp) / "run.log",
                    )
            self.assertIn("exactly one passing test", str(error.exception))

    def test_bootstrap_marker_is_required(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError) as error:
                runner.read_bootstrap_proof(Path(temp) / "missing.json")
            self.assertIn("did not write bootstrap receipt", str(error.exception))

    def test_bad_bootstrap_marker_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "marker.json"
            marker.write_text(json.dumps({
                "argv": ["multi-search.exe"],
                "guard_active": True,
                "http": "site-packages/http.py",
                "isolation": "1",
                "pid": 1,
                "pythonpath": "bootstrap",
                "sitecustomize": True,
            }), encoding="utf-8")
            self.assertEqual(runner.read_bootstrap_proof(marker)["pid"], 1)
            marker.write_text(json.dumps({
                "argv": ["multi-search.exe"],
                "guard_active": False,
                "http": "site-packages/http.py",
                "isolation": "1",
                "pid": 1,
                "pythonpath": "bootstrap",
                "sitecustomize": True,
            }), encoding="utf-8")
            with self.assertRaises(RuntimeError) as error:
                runner.read_bootstrap_proof(marker)
            self.assertIn("invalid Rust-spawned bootstrap proof", str(error.exception))

    def test_guard_violation_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            isolation = mock.Mock()
            isolation.report = Path(temp) / "violations.log"
            isolation.report.write_text("socket.create_connection\n", encoding="utf-8")
            with self.assertRaises(RuntimeError) as error:
                runner.require_clean_guard(isolation, Path(temp))
            self.assertIn("socket.create_connection", str(error.exception))


    def test_unowned_existing_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = Path(temp) / "evidence"
            evidence.mkdir()
            with self.assertRaises(RuntimeError) as error:
                runner.prepare_evidence(evidence)
            self.assertIn("unowned evidence directory", str(error.exception))

    def test_owned_existing_venv_is_reused_but_unowned_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = runner.prepare_evidence(Path(temp) / "evidence")
            owned = runner.prepare_owned_child(evidence / ".wheel-venv", evidence, ".wheel-venv")
            self.assertTrue((owned / runner.OWNER_MARKER).is_file())
            unowned = evidence / "unowned"
            unowned.mkdir()
            with self.assertRaises(RuntimeError) as error:
                runner.prepare_owned_child(unowned, evidence, "unowned")
            self.assertIn("unowned acceptance child", str(error.exception))

    def test_venv_outside_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = runner.prepare_evidence(root / "evidence")
            outside = root / ".wheel-venv"
            outside.mkdir()
            with self.assertRaises(RuntimeError) as error:
                runner.prepare_owned_child(outside, evidence, ".wheel-venv")
            self.assertIn("outside its owned root", str(error.exception))


if __name__ == "__main__":
    unittest.main()

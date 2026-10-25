"""Focused checks for the T2 installed-CLI acceptance runner."""
from __future__ import annotations

import hashlib
import io
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
            site_packages = (
                venv / "Lib" / "site-packages"
                if os.name == "nt"
                else venv / "lib" / "python3.12" / "site-packages"
            )
            calls = []

            def fake_run(command, *, cwd, env=None, log=None):
                calls.append(command)
                if "venv" in command:
                    scripts.mkdir(parents=True, exist_ok=True)
                    (scripts / "python.exe").write_bytes(b"py")
                    (scripts / ("multi-search.exe" if os.name == "nt" else "multi-search")).write_bytes(b"cli")
                if "install" in command:
                    # Second install into the same-version owned venv is the
                    # regression the runner must survive.
                    site_packages.mkdir(parents=True, exist_ok=True)
                return runner.subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(runner, "run", side_effect=fake_run):
                self.assertEqual(
                    runner.install_wheel(wheel, venv, base, root),
                    scripts / ("multi-search.exe" if os.name == "nt" else "multi-search"),
                )
            self.assertTrue((venv / runner.OWNER_MARKER).is_file())
            install_command = calls[1]
            self.assertIn("-I", install_command)
            self.assertIn("--no-index", install_command)
            self.assertIn("--no-deps", install_command)
            self.assertIn("--force-reinstall", install_command)
            self.assertEqual(install_command[-1], str(wheel))
            venv_command = calls[0]
            self.assertIn("-I", venv_command)

            # Re-running on the already-owned, already-installed venv must
            # reuse it (no second creation) and still pass --force-reinstall.
            calls.clear()
            with mock.patch.object(runner, "run", side_effect=fake_run):
                runner.install_wheel(wheel, venv, base, root)
            self.assertEqual(len(calls), 1)
            self.assertIn("--force-reinstall", calls[0])


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

    def test_installed_environment_removes_only_pythonhome_case_insensitively(self):
        environment = {
            "PythonHome": r"C:\stale\pythonhome",
            "PYTHONHOME": r"C:\other\pythonhome",
            "PYTHONPATH": r"C:\bootstrap",
            "PYTHONHOME2": "kept",
            "MULTI_SEARCH_TEST_ISOLATION": "1",
            "MULTI_SEARCH_TEST_GUARD_REPORT": "guard.log",
        }
        with mock.patch.object(runner.os, "environ", environment):
            actual = runner.installed_environment()
        self.assertEqual(
            actual,
            {k: v for k, v in environment.items() if k.upper() != "PYTHONHOME"},
        )
        self.assertIn("PythonHome", environment)

    def test_import_proof_strips_pythonhome_but_preserves_pythonpath(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            venv = root / "venv"
            scripts = venv / ("Scripts" if os.name == "nt" else "bin")
            scripts.mkdir(parents=True)
            (scripts / "python.exe").write_bytes(b"py")
            isolation = mock.Mock()
            isolation.root = root
            seen = {}

            def fake_run(command, *, cwd, env=None, log=None):
                seen["command"] = command
                seen["env"] = env
                return runner.subprocess.CompletedProcess(
                    command,
                    0,
                    '{"version":"0.4.0","package":"x","http":"y"}\n',
                    "",
                )

            environment = {
                "PYTHONHOME": r"C:\stale\pythonhome",
                "pythonHOME2": "kept-not-pythonhome",
                "PYTHONPATH": r"C:\bootstrap",
                "MULTI_SEARCH_TEST_ISOLATION": "1",
                "MULTI_SEARCH_TEST_GUARD_REPORT": "guard.log",
            }
            with mock.patch.dict(runner.os.environ, environment, clear=True):
                with mock.patch.object(runner, "run", side_effect=fake_run):
                    runner.prove_installed_import(venv, isolation, root)
            env = seen["env"]
            self.assertFalse(any(key.upper() == "PYTHONHOME" for key in env))
            self.assertEqual(env["PYTHONPATH"], r"C:\bootstrap")
            self.assertEqual(env["MULTI_SEARCH_TEST_ISOLATION"], "1")
            self.assertEqual(env["MULTI_SEARCH_TEST_GUARD_REPORT"], "guard.log")
            self.assertEqual(
                next(v for k, v in env.items() if k.upper() == "PYTHONHOME2"),
                "kept-not-pythonhome",
            )
            self.assertNotIn("-I", seen["command"])

    def test_main_passes_clean_environment_to_rust_test_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "bootstrap").mkdir()
            isolation = mock.Mock(root=root, home=root / "home")
            context = mock.MagicMock()
            context.__enter__.return_value = isolation
            native_test = mock.Mock(side_effect=RuntimeError("stop at test boundary"))
            environment = {
                "PythonHome": r"C:\stale\pythonhome",
                "PYTHONPATH": str(root / "bootstrap"),
                "MULTI_SEARCH_TEST_ISOLATION": "1",
                "MULTI_SEARCH_TEST_GUARD_REPORT": str(root / "guard.log"),
                "PATH": "original-path",
            }
            with mock.patch.object(runner, "os", mock.Mock(wraps=os)) as fake_os:
                fake_os.name = "nt"
                fake_os.environ = environment
                fake_os.pathsep = os.pathsep
                with mock.patch.multiple(
                    runner,
                    build_wheel=mock.Mock(return_value=root / "current.whl"),
                    install_wheel=mock.Mock(return_value=root / "Scripts" / "multi-search.exe"),
                    prove_wheel_installed=mock.Mock(return_value={}),
                    compile_native_test=mock.Mock(return_value=root / "native-test.exe"),
                    sha256=mock.Mock(return_value="wheel-hash"),
                    isolated_test_environment=mock.Mock(return_value=context),
                    prove_installed_import=mock.Mock(return_value={}),
                    execute_native_test=native_test,
                ):
                    with mock.patch("sys.stderr", new=io.StringIO()):
                        self.assertEqual(runner.main([
                            "--evidence", str(root / "evidence"),
                            "--cargo-target-dir", str(root / "target"),
                        ]), 1)
            native_test.assert_called_once()
            actual = native_test.call_args.kwargs["environment"]
            self.assertFalse(any(k.upper() == "PYTHONHOME" for k in actual))
            for key, value in environment.items():
                if key not in ("PythonHome", "PATH"):
                    self.assertEqual(actual[key], value)
            self.assertEqual(actual["MULTI_SEARCH_TEST_PYTHONPATH"], environment["PYTHONPATH"])
            self.assertIn("PythonHome", environment)


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

    def test_prove_wheel_installed_matches_and_rejects_stale_bytes(self):
        import io
        import zipfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = "multi_search_mcp/src/support/http.py"
            fresh = b"# fresh wheel payload\n"
            wheel = root / "multi_search_mcp-0.4.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(package, fresh)
                archive.writestr(
                    "multi_search_mcp-0.4.0.dist-info/METADATA", "Name: x\n"
                )
            venv = root / ".wheel-venv"
            site_packages = venv / ("Lib/site-packages" if os.name == "nt" else "lib/python3.12/site-packages")
            site_packages.mkdir(parents=True)
            self.assertEqual(runner._site_packages(venv), site_packages)
            installed = site_packages / package
            installed.parent.mkdir(parents=True, exist_ok=True)
            installed.write_bytes(fresh)
            proof = runner.prove_wheel_installed(wheel, venv)
            self.assertEqual(proof["wheel_py_files"], 1)

            installed.write_bytes(b"# stale same-version build\n")
            with self.assertRaises(RuntimeError) as error:
                runner.prove_wheel_installed(wheel, venv)
            self.assertIn("diverges from built wheel", str(error.exception))
            self.assertIn(package, str(error.exception))

    def test_main_rejected_evidence_preserves_preexisting_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = root / "evidence"
            evidence.mkdir()
            foreign_manifest = evidence / "acceptance-manifest.json"
            foreign_bytes = b'{"status":"PASS","foreign":true}\n'
            foreign_manifest.write_bytes(foreign_bytes)
            stderr = io.StringIO()
            argv = [
                "--evidence",
                str(evidence),
                "--cargo-target-dir",
                str(root / "target"),
                "--base-python",
                str(root / "python.exe"),
            ]
            with mock.patch.object(runner, "os", mock.Mock(wraps=os, name="nt")) as fake_os:
                fake_os.name = "nt"
                with mock.patch("sys.stderr", stderr):
                    self.assertEqual(runner.main(argv), 1)
            self.assertEqual(foreign_manifest.read_bytes(), foreign_bytes)
            self.assertIn("unowned evidence directory", stderr.getvalue())
            self.assertEqual(sorted(p.name for p in evidence.iterdir()), ["acceptance-manifest.json"])
            self.assertFalse(
                (root / "evidence.acceptance-manifest.json").exists()
            )

    def test_main_owned_early_failure_writes_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = root / "evidence"
            stderr = io.StringIO()
            argv = [
                "--evidence",
                str(evidence),
                "--cargo-target-dir",
                str(root / "target"),
                "--base-python",
                str(root / "missing-python.exe"),
            ]

            def fail_build(owned):
                raise RuntimeError("wheel build failed")

            with mock.patch.object(runner, "os", mock.Mock(wraps=os, name="nt")) as fake_os:
                fake_os.name = "nt"
                with mock.patch.object(runner, "build_wheel", side_effect=fail_build):
                    with mock.patch("sys.stderr", stderr):
                        self.assertEqual(runner.main(argv), 1)
            manifest = evidence / "acceptance-manifest.json"
            self.assertTrue(manifest.is_file())
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "FAIL")
            self.assertIn("wheel build failed", data["error"])
            self.assertIn("wheel build failed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

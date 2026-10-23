"""Exercise the native public API with an installed CLI in a disposable profile."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test_isolation import isolated_test_environment
from tests.test_cli_process import BOOTSTRAP

DEFAULT_BASE_PYTHON = Path(
    os.environ.get(
        "MULTI_SEARCH_ACCEPTANCE_PYTHON",
        os.path.expandvars(
            r"%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe"
        ),
    )
)


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    log: Path | None = None,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            f"$ {' '.join(command)}\nexit={result.returncode}\n{result.stdout}",
            encoding="utf-8",
        )
    return result


def require_success(result: subprocess.CompletedProcess, label: str) -> None:
    if result.returncode:
        raise RuntimeError(f"{label} failed with exit {result.returncode}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wheel_metadata(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        entry_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        metadata = wheel.read(metadata_name).decode("utf-8")
        entries = wheel.read(entry_name).decode("utf-8")
    fields = {"entry_points": entries}
    for line in metadata.splitlines():
        if line.startswith(("Name:", "Version:")):
            key, value = line.split(":", 1)
            fields[key.lower()] = value.strip()
    return fields


OWNER_MARKER = ".t2-acceptance-owner"
OWNER_TEXT = "multi-search T2 installed CLI acceptance\n"


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or path.is_junction()
    except (AttributeError, OSError):
        return path.is_symlink()


def _require_plain_ancestors(path: Path, root: Path) -> None:
    current = path
    while current != root:
        if _is_link(current):
            raise RuntimeError(f"acceptance path contains link/junction: {current}")
        current = current.parent


def prepare_evidence(path: Path) -> Path:
    """Create or reuse only a runner-owned evidence directory."""
    path = path.absolute()
    if path.exists() and not path.is_dir():
        raise RuntimeError(f"evidence path is not a directory: {path}")
    if path.exists() and _is_link(path):
        raise RuntimeError(f"evidence path must not be a link/junction: {path}")
    marker = path / OWNER_MARKER
    if path.exists() and not marker.is_file():
        raise RuntimeError(f"refusing to reuse unowned evidence directory: {path}")
    if path.exists() and marker.read_text(encoding="utf-8") != OWNER_TEXT:
        raise RuntimeError(f"refusing evidence with invalid ownership marker: {marker}")
    path.mkdir(parents=True, exist_ok=True)
    if not marker.is_file():
        marker.write_text(OWNER_TEXT, encoding="utf-8")
    return path


def prepare_owned_child(path: Path, evidence: Path, name: str) -> Path:
    """Validate a runner-owned child path without clearing it implicitly."""
    if path.parent.resolve() != evidence.resolve() or path.name != name:
        raise RuntimeError(f"acceptance child path is outside its owned root: {path}")
    _require_plain_ancestors(path, evidence)
    if path.exists() and not path.is_dir():
        raise RuntimeError(f"acceptance child is not a directory: {path}")
    if path.exists() and _is_link(path):
        raise RuntimeError(f"acceptance child must not be a link/junction: {path}")
    marker = path / OWNER_MARKER
    if path.exists() and not marker.is_file():
        raise RuntimeError(f"refusing to clear unowned acceptance child: {path}")
    if path.exists() and marker.read_text(encoding="utf-8") != OWNER_TEXT:
        raise RuntimeError(f"refusing invalid acceptance child marker: {marker}")
    path.mkdir(parents=True, exist_ok=True)
    marker.write_text(OWNER_TEXT, encoding="utf-8")
    return path


def build_wheel(evidence: Path) -> Path:
    wheel_dir = prepare_owned_child(evidence / "wheel", evidence, "wheel")
    for stale in wheel_dir.glob("*.whl"):
        stale.unlink()
    command = ["uv", "build", "--offline", "--wheel", "--out-dir", str(wheel_dir)]
    built = run(command, cwd=ROOT, log=evidence / "uv-build.log")
    require_success(built, "current-source wheel build")
    wheels = list(wheel_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one wheel in {wheel_dir}, found {len(wheels)}")
    wheel = wheels[0]
    (evidence / "wheel-manifest.json").write_text(
        json.dumps(
            {
                "wheel": str(wheel),
                "name": wheel.name,
                "sha256": sha256(wheel),
                "metadata": wheel_metadata(wheel),
                "build_command": command,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return wheel


def install_wheel(wheel: Path, venv: Path, base_python: Path, evidence: Path) -> Path:
    if not base_python.is_file():
        raise RuntimeError(f"base Python does not exist: {base_python}")
    venv = prepare_owned_child(venv, evidence, ".wheel-venv")
    # Never clear a directory wholesale: --clear also removes the ownership
    # marker. A fresh or already-owned venv is safe to populate in place.
    python_candidate = venv / ("Scripts" if os.name == "nt" else "bin") / "python.exe"
    if not python_candidate.is_file():
        created = run(
            [str(base_python), "-m", "venv", str(venv)],
            cwd=ROOT,
            log=evidence / "venv-create.log",
        )
        require_success(created, "disposable wheel venv creation")
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    installed = run(
        [
            str(scripts / "python.exe"),
            "-B",
            "-m",
            "pip",
            "install",
            "--no-input",
            "--no-index",
            "--no-deps",
            str(wheel),
        ],
        cwd=ROOT,
        log=evidence / "pip-install.log",
    )
    require_success(installed, "installed CLI wheel setup")
    console = scripts / ("multi-search.exe" if os.name == "nt" else "multi-search")
    if not console.is_file():
        raise RuntimeError(f"installed CLI executable is missing: {console}")
    return console


def compile_native_test(target_dir: Path, evidence: Path) -> Path:
    command = [
        "cargo",
        "test",
        "--offline",
        "--locked",
        "--no-default-features",
        "--features",
        "install-test-boundary",
        "--manifest-path",
        str(ROOT / "desktop" / "src-tauri" / "Cargo.toml"),
        "--test",
        "installed_cli",
        "--no-run",
        "--message-format=json",
    ]
    compiled = run(
        command,
        cwd=ROOT,
        env=dict(os.environ, CARGO_TARGET_DIR=str(target_dir)),
        log=evidence / "cargo-test-no-run.log",
    )
    require_success(compiled, "installed_cli native test compile")
    executables = []
    for line in compiled.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            message.get("reason") == "compiler-artifact"
            and message.get("profile", {}).get("test")
            and message.get("target", {}).get("name") == "installed_cli"
            and message.get("executable")
        ):
            executables.append(Path(message["executable"]))
    unique = sorted(set(executables))
    if len(unique) != 1:
        raise RuntimeError(
            "expected Cargo to report exactly one installed_cli executable, "
            f"found {len(unique)}"
        )
    if not unique[0].is_file():
        raise RuntimeError(f"Cargo reported missing installed_cli executable: {unique[0]}")
    return unique[0]


def prove_installed_import(venv: Path, isolation, evidence: Path) -> dict[str, str]:
    python = venv / ("Scripts" if os.name == "nt" else "bin") / "python.exe"
    source = """
import importlib.metadata
import json
import multi_search_mcp
from multi_search_mcp.src.support import http
assert 'site-packages' in str(multi_search_mcp.__file__), multi_search_mcp.__file__
assert 'site-packages' in str(http.__file__), http.__file__
print(json.dumps({
    'version': importlib.metadata.version('multi-search-mcp'),
    'package': str(multi_search_mcp.__file__),
    'http': str(http.__file__),
}))
"""
    result = run(
        [str(python), "-B", "-c", source],
        cwd=isolation.root,
        env=dict(os.environ),
        log=evidence / "installed-import.log",
    )
    require_success(result, "installed site-packages import proof")
    return json.loads([line for line in result.stdout.splitlines() if line.startswith("{")][-1])


def guard_summary(isolation, evidence: Path) -> dict[str, object]:
    report = (
        isolation.report.read_text(encoding="utf-8")
        if isolation.report.exists()
        else ""
    )
    (evidence / "network-guard-report.txt").write_text(report, encoding="utf-8")
    lines = [line for line in report.splitlines() if line]
    summary = {"violation_lines": len(lines), "boundaries": lines}
    (evidence / "network-guard-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def bootstrap_suffix() -> str:
    return """


# Acceptance bootstrap receipt. This runs inside the CLI child's interpreter and
# is asserted by the Rust-spawned installed_cli test, not by this parent script.
marker = os.environ.get("MULTI_SEARCH_TEST_BOOTSTRAP_MARK")
if marker:
    from pathlib import Path as _AcceptancePath
    _AcceptancePath(marker).write_text(json.dumps({
        "argv": sys.argv[:1],
        "guard_active": test_isolation.active_guard() is not None,
        "http": str(http.__file__),
        "isolation": os.environ.get("MULTI_SEARCH_TEST_ISOLATION", ""),
        "pid": os.getpid(),
        "pythonpath": os.environ.get("PYTHONPATH", ""),
        "sitecustomize": True,
    }), encoding="utf-8")
"""


def execute_native_test(
    binary: Path,
    name: str,
    *,
    cwd: Path,
    environment: dict[str, str],
    log: Path,
) -> subprocess.CompletedProcess:
    result = run(
        [str(binary), "--ignored", "--nocapture", "--exact", name],
        cwd=cwd,
        env=environment,
        log=log,
    )
    if "running 1 test" not in result.stdout or ". 1 passed;" not in result.stdout:
        raise RuntimeError(f"{name} did not execute exactly one passing test")
    require_success(result, name)
    return result


def read_bootstrap_proof(marker: Path) -> dict[str, object]:
    if not marker.is_file():
        raise RuntimeError(
            f"Rust-spawned CLI child did not write bootstrap receipt: {marker}"
        )
    proof = json.loads(marker.read_text(encoding="utf-8"))
    required = {
        "argv",
        "guard_active",
        "http",
        "isolation",
        "pid",
        "pythonpath",
        "sitecustomize",
    }
    if set(proof) != required:
        raise RuntimeError(f"invalid bootstrap proof fields: {sorted(proof)}")
    if (
        proof["isolation"] != "1"
        or proof["sitecustomize"] is not True
        or proof["guard_active"] is not True
        or "site-packages" not in proof["http"]
        or "multi-search.exe" not in proof["argv"][0]
        or not proof["pythonpath"]
        or not isinstance(proof["pid"], int)
        or proof["pid"] <= 0
    ):
        raise RuntimeError(f"invalid Rust-spawned bootstrap proof: {proof}")
    return proof


def require_clean_guard(isolation, evidence: Path) -> dict[str, object]:
    summary = guard_summary(isolation, evidence)
    if summary["violation_lines"]:
        raise RuntimeError(
            "test isolation recorded network operation(s): "
            + ", ".join(summary["boundaries"])
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    if os.name != "nt":
        raise SystemExit("Windows native acceptance only")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path(
            os.environ.get(
                "T2_EVIDENCE_DIR",
                os.path.join(os.environ.get("TEMP", str(ROOT)), "multi-search-T2-evidence"),
            )
        ),
    )
    parser.add_argument(
        "--cargo-target-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "CARGO_TARGET_DIR",
                os.path.join(os.environ.get("TEMP", str(ROOT)), "multi-search-T2-installed"),
            )
        ),
    )
    parser.add_argument("--base-python", type=Path, default=DEFAULT_BASE_PYTHON)
    options = parser.parse_args(argv)

    evidence_path = options.evidence
    target_dir = options.cargo_target_dir.resolve()
    started = time.time()
    manifest = {
        "root": str(ROOT),
        "evidence": str(evidence_path),
        "cargo_target_dir": str(target_dir),
        "base_python": str(options.base_python),
        "install_deps": False,
        "controlled_network": "loopback only; provider HTTP replaced at Python urllib boundary",
        "real_profile_registry_deployment": "untouched; disposable isolated profile only",
    }

    try:
        evidence = prepare_evidence(evidence_path)
        manifest["evidence"] = str(evidence)
        wheel = build_wheel(evidence)
        venv = evidence / ".wheel-venv"
        console = install_wheel(
            wheel, venv, options.base_python.resolve(), evidence
        )
        binary = compile_native_test(target_dir, evidence)
        manifest.update(
            {
                "wheel": str(wheel),
                "wheel_sha256": sha256(wheel),
                "venv": str(venv),
                "console": str(console),
                "native_test_binary": str(binary),
            }
        )

        with isolated_test_environment(include_inherited_pythonpath=False) as isolation:
            bootstrap = (
                BOOTSTRAP.replace(
                    'query = urllib.parse.parse_qs(parsed.query)["query"][0]',
                    'query = urllib.parse.parse_qs(parsed.query)["query"][0]\n'
                    '            if query == "hang":\n'
                    '                import time\n'
                    '                time.sleep(60)',
                )
                + bootstrap_suffix()
            )
            (isolation.root / "bootstrap" / "sitecustomize.py").write_text(
                bootstrap, encoding="utf-8"
            )
            runtime = console.parent
            marker = isolation.root / "bootstrap-active.json"
            rust_environment = dict(
                os.environ,
                PATH=str(runtime) + os.pathsep + os.environ.get("PATH", ""),
                MULTI_SEARCH_ACCEPTANCE_INSTALLED="1",
                MULTI_SEARCH_DESKTOP_TEST_USER_PATH=str(runtime),
                MULTI_SEARCH_TEST_PYTHONPATH=os.environ["PYTHONPATH"],
                MULTI_SEARCH_TEST_BOOTSTRAP_MARK=str(marker),
            )
            manifest["installed_provenance"] = prove_installed_import(
                venv, isolation, evidence
            )
            manifest["isolated_profile"] = {
                "root": str(isolation.root),
                "home": str(isolation.home),
                "config_db": str(isolation.home / ".multi-search" / "config.sqlite"),
            }
            proof_result = execute_native_test(
                binary,
                "rust_child_bootstrap_active_proof",
                cwd=isolation.root,
                environment=rust_environment,
                log=evidence / "child-bootstrap-proof.log",
            )
            manifest["bootstrap_test_exit"] = proof_result.returncode
            manifest["child_bootstrap_proof"] = read_bootstrap_proof(marker)
            result = execute_native_test(
                binary,
                "actual_installed_cli_detection_search_partial_failure_and_cancellation",
                cwd=isolation.root,
                environment=rust_environment,
                log=evidence / "installed-native-api.log",
            )
            manifest["native_test_exit"] = result.returncode
            manifest["network_guard"] = require_clean_guard(isolation, evidence)
    except Exception as error:
        manifest["status"] = "FAIL"
        manifest["error"] = str(error)
        if evidence_path.exists() and evidence_path.is_dir() and not evidence_path.is_symlink():
            failure_manifest = evidence_path / "acceptance-manifest.json"
        else:
            failure_manifest = evidence_path.with_name(
                evidence_path.name + ".acceptance-manifest.json"
            )
        failure_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"T2 installed CLI acceptance FAIL: {error}", file=sys.stderr)
        return 1

    manifest["status"] = "PASS"
    manifest["duration_seconds"] = round(time.time() - started, 3)
    (evidence / "acceptance-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"T2 installed CLI acceptance PASS: {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

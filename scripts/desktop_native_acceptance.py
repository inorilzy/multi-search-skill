"""Exercise the native public API with the installed CLI; not window acceptance."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test_isolation import isolated_test_environment
from tests.test_cli_process import BOOTSTRAP


def main():
    evidence = ROOT / "dist" / "acceptance-02"
    evidence.mkdir(parents=True, exist_ok=True)
    command = ["cargo", "test", "--offline", "--locked", "--no-default-features", "--manifest-path",
               str(ROOT / "desktop/src-tauri/Cargo.toml"), "--test", "installed_cli", "--", "--ignored", "--nocapture"]
    # Build outside disposable HOME because Rust's cache/toolchain is not product state.
    built = subprocess.run(command[:-3] + ["--no-run"], cwd=ROOT)
    if built.returncode:
        return built.returncode
    with isolated_test_environment(include_inherited_pythonpath=False) as isolation:
        bootstrap = BOOTSTRAP.replace('query = urllib.parse.parse_qs(parsed.query)["query"][0]', 'query = urllib.parse.parse_qs(parsed.query)["query"][0]\n            if query == "hang":\n                import time\n                time.sleep(60)')
        (isolation.root / "bootstrap" / "sitecustomize.py").write_text(bootstrap, encoding="utf-8")
        runtime = ROOT / ".wheel-venv" / "Scripts"
        environment = dict(os.environ, PATH=str(runtime) + os.pathsep + os.environ.get("PATH", ""), MULTI_SEARCH_ACCEPTANCE_INSTALLED="1",
                           MULTI_SEARCH_DESKTOP_TEST_USER_PATH=str(runtime))
        # Run the compiled native test directly, avoiding toolchain writes in disposable HOME.
        matches = list((ROOT / "desktop/src-tauri/target/debug/deps").glob("installed_cli-*.exe"))
        binary = max(matches, key=lambda path: path.stat().st_mtime_ns)
        with (evidence / "installed-native-api.log").open("w", encoding="utf-8") as output:
            result = subprocess.run([str(binary), "--ignored", "--nocapture"], cwd=isolation.root, env=environment, stdout=output, stderr=subprocess.STDOUT, timeout=90)
        isolation.assert_clean()
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

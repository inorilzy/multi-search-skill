"""Launch the actual Windows desktop with a disposable, installed CLI profile.

Only the provider HTTP/time boundaries are replaced. Close the window to finish;
the launcher then proves an independent terminal CLI still works and saves logs.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test_isolation import isolated_test_environment
from tests.test_cli_process import BOOTSTRAP


def main():
    if os.name != "nt":
        raise SystemExit("Windows native acceptance only")
    evidence = ROOT / "dist" / "acceptance-02"
    evidence.mkdir(parents=True, exist_ok=True)
    runtime = ROOT / ".wheel-venv" / "Scripts"
    console = runtime / "multi-search.exe"
    desktop = ROOT / "desktop" / "src-tauri" / "target" / "debug" / "multi-search-desktop.exe"
    with isolated_test_environment(include_inherited_pythonpath=False) as isolation:
        # Extend only disposable sitecustomize; product installation is unmodified.
        bootstrap = BOOTSTRAP.replace('query = urllib.parse.parse_qs(parsed.query)["query"][0]', 'query = urllib.parse.parse_qs(parsed.query)["query"][0]\n            if query == "hang":\n                import time\n                time.sleep(60)')
        (isolation.root / "bootstrap" / "sitecustomize.py").write_text(bootstrap, encoding="utf-8")
        environment = dict(os.environ, PATH=str(runtime) + os.pathsep + os.environ.get("PATH", ""),
                           MULTI_SEARCH_ACCEPTANCE_INSTALLED="1", MULTI_SEARCH_DESKTOP_TEST_USER_PATH=str(runtime))
        (evidence / "launch.json").write_text(json.dumps({"desktop": str(desktop), "console": str(console), "profile": str(isolation.home), "provider_boundary": "controlled HTTP only; imports must be site-packages", "user_path_probe": "disposable user PATH; production registry unmodified"}, indent=2), encoding="utf-8")
        with (evidence / "window.log").open("w", encoding="utf-8") as output:
            result = subprocess.run([str(desktop)], cwd=isolation.root, env=environment, stdout=output, stderr=subprocess.STDOUT)
        terminal = subprocess.run([str(console), "search", "fixture", "--source", "hackernews"], cwd=isolation.root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
        payload = json.loads(terminal.stdout)
        assert terminal.returncode == 0 and payload["outcome"] == "success", terminal.stderr
        assert payload["results"][0]["source_id"].startswith("src_")
        (evidence / "after-close-terminal.json").write_text(json.dumps({"desktop_exit": result.returncode, "command": [str(console), "search", "fixture", "--source", "hackernews"], "exit_code": terminal.returncode, "payload": payload}, ensure_ascii=False, indent=2), encoding="utf-8")
        # Preserve the only guard record before the disposable temp directory is removed.
        report_text = isolation.report.read_text(encoding="utf-8") if isolation.report.exists() else ""
        (evidence / "network-guard-report.txt").write_text(report_text, encoding="utf-8")
        (evidence / "network-guard-summary.json").write_text(json.dumps({"violation_lines": len([line for line in report_text.splitlines() if line]), "boundaries": [line for line in report_text.splitlines() if line]}, indent=2), encoding="utf-8")
        isolation.assert_clean()


if __name__ == "__main__":
    main()

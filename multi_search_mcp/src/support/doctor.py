"""Environment checks for the multi-search skill."""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from ..state.keys import count_jina_keys, load_keys


def _status(ok: bool, label: str, detail: str = "") -> str:
    mark = "OK" if ok else "WARN"
    suffix = f" - {detail}" if detail else ""
    return f"[{mark}] {label}{suffix}"


def _has_twitter_cookies(keys: dict) -> tuple[bool, str]:
    tw = keys.get("twitter")
    if isinstance(tw, dict):
        missing = [name for name in ("auth_token", "ct0") if not tw.get(name)]
        if missing:
            return False, f"~/.search-keys.json twitter dict missing: {', '.join(missing)}"
        return True, "~/.search-keys.json twitter dict has auth_token + ct0"

    cookie_path = tw if isinstance(tw, str) and tw else keys.get("twitter_cookies") or os.path.expanduser("~/.mcp-twikit/cookies.json")
    path = Path(cookie_path).expanduser()
    if not path.exists():
        return False, f"cookies file not found: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return False, f"cookies file unreadable: {exc}"
    if not isinstance(data, dict):
        return False, f"cookies file must contain a JSON object: {path}"
    missing = [name for name in ("auth_token", "ct0") if not data.get(name)]
    if missing:
        return False, f"cookies file missing: {', '.join(missing)} ({path})"
    return True, f"cookies file has auth_token + ct0: {path}"


def _gh_auth_status() -> tuple[bool, str]:
    if not shutil.which("gh"):
        return False, "gh CLI not found; set GITHUB_TOKEN/GH_TOKEN or install/login gh"
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
    except Exception as exc:
        return False, f"gh auth status failed: {exc}"
    return proc.returncode == 0, "gh auth login available" if proc.returncode == 0 else "gh CLI found but not logged in"


def doctor() -> int:
    """Print a compact health report. Returns 0 when core runtime is usable."""
    print("# multi-search doctor")
    print(_status(sys.version_info >= (3, 10), "Python", f"{platform.python_version()} at {sys.executable}"))

    keys_file = Path.home() / ".search-keys.json"
    print(_status(keys_file.exists(), "keys file", str(keys_file) if keys_file.exists() else f"not found: {keys_file}"))

    keys = load_keys()
    for key_name, label in [
        ("brave", "Brave key"),
        ("tavily", "Tavily key"),
        ("exa", "Exa key"),
        ("firecrawl", "Firecrawl key"),
        ("serpapi", "SerpAPI key"),
        ("zhihu", "Zhihu Access Secret"),
        ("youtube", "YouTube API key"),
    ]:
        missing = "missing; source will be skipped"
        print(_status(bool(keys.get(key_name)), label, "configured" if keys.get(key_name) else missing))
    print(_status(True, "Bilibili cookie", "configured" if keys.get("bilibili") else "optional; anonymous public search will be used"))

    jina_active, jina_total = count_jina_keys(keys.get("jina"))
    if jina_total:
        jina_detail = f"{jina_active}/{jina_total} active; anonymous fallback still available"
    else:
        jina_detail = "missing; anonymous fallback only"
    print(_status(jina_active > 0 or jina_total == 0, "Jina key pool", jina_detail))

    gh_ok, gh_detail = _gh_auth_status()
    github_ok = bool(keys.get("github")) or gh_ok
    github_detail = "GITHUB_TOKEN/GH_TOKEN configured" if keys.get("github") else gh_detail
    print(_status(github_ok, "GitHub auth", github_detail))

    twikit_ok = importlib.util.find_spec("twikit") is not None
    print(_status(twikit_ok, "Twitter dependency", "twikit-ng installed" if twikit_ok else "missing; run: python -m pip install twikit-ng"))

    cookies_ok, cookies_detail = _has_twitter_cookies(keys)
    print(_status(cookies_ok, "Twitter cookies", cookies_detail))

    if not twikit_ok or not cookies_ok:
        print("Twitter/X route will report an error item until dependency and cookies are both available.")

    return 0 if sys.version_info >= (3, 10) else 1


if __name__ == "__main__":
    raise SystemExit(doctor())

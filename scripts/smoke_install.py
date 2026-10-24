"""Verify a non-editable, MCP-free CLI installation outside the source tree."""
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from test_isolation import isolated_test_environment


CLIENT = r'''
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import multi_search_mcp

try:
    from xkit import Client
except ImportError:  # xkit-py is optional while the private dependency is disabled
    Client = None

module_path = Path(multi_search_mcp.__file__).resolve()
assert "site-packages" in module_path.parts, module_path
assert importlib.util.find_spec("mcp") is None, "smoke runtime must not include MCP"
assert importlib.util.find_spec("multi_search_mcp.server") is None
metadata = importlib.metadata.distribution("multi-search-mcp")
entries = {entry.name: entry.value for entry in metadata.entry_points if entry.group == "console_scripts"}
assert entries == {"multi-search": "multi_search_mcp.cli:entrypoint"}, entries
assert not any(requirement.lower().startswith("mcp") for requirement in metadata.requires or [])
xkit_version = None
if Client is not None:
    try:
        importlib.metadata.distribution("twikit-ng")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError("twikit-ng and xkit-py must not share the installed twikit namespace")
    client = Client("en-US", timeout=1)
    client.set_cookies({"auth_token": "installation-fixture", "ct0": "installation-fixture"})
    assert callable(client.search_tweet) and callable(client.get_tweet_by_id)
    import asyncio
    asyncio.run(client.http.aclose())
    xkit_version = importlib.metadata.version("xkit-py")
print(json.dumps({"version": metadata.version, "xkit_version": xkit_version,
                  "module_path": str(module_path), "console_scripts": entries, "mcp_installed": False}))
'''


def main():
    scripts = Path(sysconfig.get_path("scripts"))
    suffix = ".exe" if os.name == "nt" else ""
    cli = scripts / ("multi-search" + suffix)
    with isolated_test_environment(
        prefix="multi-search-install-", include_inherited_pythonpath=False,
    ) as isolation:
        env = dict(os.environ)
        with tempfile.TemporaryDirectory(prefix="multi-search-smoke-cwd-") as temp:
            for args in ([str(cli), "--help"], [str(cli), "fetch", "--help"],
                         [str(cli), "doctor", "--no-keys"],
                         [sys.executable, "-m", "multi_search_mcp.cli", "--help"],
                         [sys.executable, "-c", CLIENT]):
                result = subprocess.run(args, cwd=temp, env=env, text=True, encoding="utf-8",
                                        capture_output=True, timeout=30)
                if result.returncode:
                    raise RuntimeError(result.stderr or result.stdout)
                if args[-1] == CLIENT:
                    print(result.stdout.strip())
        isolation.assert_clean()


if __name__ == "__main__":
    main()

"""Verify a non-editable CLI/MCP installation outside the source tree."""
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
import asyncio
import importlib.metadata
import json
import os
import sys
from pathlib import Path
import multi_search_mcp
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from xkit import Client

async def main():
    module_path = Path(multi_search_mcp.__file__).resolve()
    assert "site-packages" in module_path.parts, module_path
    xkit_version = importlib.metadata.version("xkit-py")
    try:
        importlib.metadata.distribution("twikit-ng")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError("twikit-ng and xkit-py must not share the installed twikit namespace")
    client = Client("en-US", timeout=1)
    try:
        client.set_cookies({"auth_token": "installation-fixture", "ct0": "installation-fixture"})
        assert callable(client.search_tweet) and callable(client.get_tweet_by_id)
    finally:
        await client.http.aclose()
    async with stdio_client(StdioServerParameters(
        command=sys.argv[1], args=[], env=os.environ.copy(),
    )) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert {"search_web", "fetch_source", "read_source", "doctor"} <= names, names
            result = await session.call_tool("list_sources", {})
            assert not result.isError, result
            sources = json.loads(result.content[0].text)["sources"]
            assert "sov2ex" in sources and "v2ex" not in sources, sources
            print(json.dumps({"version": importlib.metadata.version("multi-search-mcp"),
                              "mcp_version": importlib.metadata.version("mcp"),
                              "xkit_version": xkit_version,
                              "module_path": str(module_path), "registered_tools": sorted(names)}))

asyncio.run(main())
'''


def main():
    scripts = Path(sysconfig.get_path("scripts"))
    suffix = ".exe" if os.name == "nt" else ""
    cli = scripts / ("multi-search" + suffix)
    server = scripts / ("multi-search-mcp" + suffix)
    with isolated_test_environment(
        prefix="multi-search-install-",
        include_inherited_pythonpath=False,
    ) as isolation:
        env = dict(os.environ)
        with tempfile.TemporaryDirectory(prefix="multi-search-smoke-cwd-") as temp:
            for args in ([str(cli), "--help"], [str(cli), "fetch", "--help"],
                         [sys.executable, "-c", CLIENT, str(server)]):
                result = subprocess.run(args, cwd=temp, env=env, text=True, capture_output=True, timeout=30)
                if result.returncode:
                    raise RuntimeError(result.stderr or result.stdout)
                if args[0] == sys.executable:
                    print(result.stdout.strip())
        isolation.assert_clean()


if __name__ == "__main__":
    main()

"""GitHub repository search via REST API (or gh CLI fallback)."""
import json
import subprocess
import urllib.parse
import urllib.request

from ..http import urlopen_retry
from ..secrets import scrub_secrets


def _run_gh(args: list, timeout: int = 20, retries: int = 2) -> tuple[int, str, str]:
    """Run a gh CLI command, returning (returncode, stdout, stderr)."""
    for attempt in range(retries + 1):
        try:
            result = subprocess.run(args, capture_output=True, timeout=timeout)
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")
            if result.returncode != 0 and "EOF" in stderr and attempt < retries:
                continue
            return result.returncode, stdout, stderr
        except subprocess.TimeoutExpired:
            return -1, "", "timeout"
        except Exception as e:
            return -1, "", str(e)
    return -1, "", "EOF after retries"


def _github_api(endpoint: str, token: str = "", timeout: float = 20) -> tuple[int, str, str]:
    """Call GitHub REST API directly when token provided, else fall back to gh CLI."""
    if token:
        url = f"https://api.github.com/{endpoint}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "multi-search/1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen_retry(req, timeout=timeout) as resp:
                return 0, resp.read().decode("utf-8", errors="replace"), ""
        except Exception as e:
            return -1, "", scrub_secrets(e, token)
    return _run_gh(["gh", "api", endpoint], timeout=timeout)


def search_github_repos(query: str, count: int = 10, token: str = "", timeout: float = 20) -> list:
    """Search GitHub repositories. Uses token directly if provided, else gh CLI."""
    endpoint = f"search/repositories?q={urllib.parse.quote_plus(query)}&sort=stars&per_page={count}"
    rc, stdout, stderr = _github_api(endpoint, token, timeout=timeout)
    if rc != 0:
        return [{"source": "github-repos", "error": stderr.strip() or f"exit {rc}"}]
    try:
        data = json.loads(stdout)
    except Exception as e:
        return [{"source": "github-repos", "error": f"JSON parse error: {e}"}]
    items = []
    for item in data.get("items", []):
        items.append(
            {
                "source": "github-repos",
                "title": item.get("full_name", ""),
                "url": item.get("html_url", ""),
                "description": item.get("description") or "",
                "stars": item.get("stargazers_count"),
            }
        )
    return items

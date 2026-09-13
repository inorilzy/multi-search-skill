"""GitHub repository search via REST API (or gh CLI fallback)."""
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets


_GITHUB_ERROR_BODY_LIMIT = 4096
_GITHUB_RATE_LIMIT_HEADERS = frozenset({
    "retry-after",
    "x-ratelimit-remaining",
})


class _GitHubHTTPError(Exception):
    """Redacted GitHub HTTP failure with key-pool classification."""

    def __init__(self, message: str, *, error_type: str, rate_limited: bool = False):
        super().__init__(message)
        self.error_type = error_type
        self.rate_limited = rate_limited


def _github_error_body_text(raw) -> str:
    if isinstance(raw, bytes):
        text = raw[:_GITHUB_ERROR_BODY_LIMIT].decode("utf-8", errors="replace")
    else:
        text = str(raw or "")[:_GITHUB_ERROR_BODY_LIMIT]
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return text
    if not isinstance(payload, dict):
        return text
    detail = payload.get("message") or payload.get("error")
    if isinstance(detail, (dict, list)):
        return json.dumps(detail, ensure_ascii=False)[:_GITHUB_ERROR_BODY_LIMIT]
    return str(detail)[:_GITHUB_ERROR_BODY_LIMIT] if detail else text


def _github_rate_limit_headers(headers) -> dict[str, str]:
    try:
        items = headers.items()
    except (AttributeError, TypeError):
        return {}
    return {
        str(name).lower(): str(value).strip()
        for name, value in items
        if str(name).lower() in _GITHUB_RATE_LIMIT_HEADERS
    }


def _has_explicit_rate_limit_message(message: str) -> bool:
    normalized = " ".join(str(message or "").lower().split())
    return any(signal in normalized for signal in (
        "api rate limit exceeded",
        "rate limit exceeded",
        "secondary rate limit",
        "abuse detection mechanism",
    ))


def _classify_github_error(status: int | None, message: str = "", headers=None) -> str:
    """Classify only GitHub's explicit auth and rate-limit responses."""
    if status == 401:
        return "invalid"
    if status == 429:
        return "rate_limit"
    if status != 403:
        return "error"
    rate_headers = _github_rate_limit_headers(headers or {})
    if rate_headers.get("x-ratelimit-remaining") == "0":
        return "rate_limit"
    if rate_headers.get("retry-after", "").isdigit():
        return "rate_limit"
    return "rate_limit" if _has_explicit_rate_limit_message(message) else "invalid"


def _request_timeout(timeout: float, deadline: float | None) -> float | None:
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    return min(float(timeout), remaining) if remaining > 0 else None


def _read_github_error_body(exc: urllib.error.HTTPError, *, deadline: float | None = None) -> tuple[str, str]:
    body = ""
    diagnostic = ""
    if exc.fp is not None:
        try:
            if deadline is not None and time.monotonic() >= deadline:
                diagnostic = "error body unavailable (deadline exceeded)"
            else:
                body = _github_error_body_text(exc.read(_GITHUB_ERROR_BODY_LIMIT))
                if deadline is not None and time.monotonic() >= deadline:
                    body = ""
                    diagnostic = "error body unavailable (deadline exceeded)"
        except Exception as read_error:
            diagnostic = f"error body unavailable ({type(read_error).__name__})"
        finally:
            try:
                exc.close()
            except Exception as close_error:
                diagnostic = diagnostic or f"error body close failed ({type(close_error).__name__})"
    return body, diagnostic


def _github_http_error(
    exc: urllib.error.HTTPError,
    token: str,
    *,
    deadline: float | None = None,
) -> _GitHubHTTPError:
    headers = _github_rate_limit_headers(getattr(exc, "headers", None) or {})
    body, body_diagnostic = _read_github_error_body(exc, deadline=deadline)
    status = getattr(exc, "code", None)
    fallback = str(exc) or f"HTTP Error {status}"
    error_type = _classify_github_error(status, body or fallback, headers)
    if body_diagnostic.startswith("error body unavailable") and status == 403 and error_type == "invalid":
        error_type = "error"
    message = f"HTTP Error {status}: {body}" if body else fallback
    if body_diagnostic:
        message = f"{message}; {body_diagnostic}"
    return _GitHubHTTPError(
        scrub_secrets(message, token),
        error_type=error_type,
        rate_limited=error_type == "rate_limit",
    )


def _github_error_row(
    message: str,
    token: str,
    *,
    error_type: str = "",
    rate_limited: bool = False,
) -> dict:
    result = {"source": "github-repos", "error": scrub_secrets(message, token)}
    if error_type:
        result.update({"error_origin": "provider", "error_type": error_type})
    if rate_limited:
        result["rate_limited"] = True
    return result


def _github_cli_error_type(message: str) -> str:
    text = str(message or "")
    match = re.search(r"\b(?:http(?: status)?|status(?: code)?)?\s*(401|403|429)\b", text, re.I)
    if match:
        return _classify_github_error(int(match.group(1)), text)
    return "rate_limit" if _has_explicit_rate_limit_message(text) else ""


def _run_gh(
    args: list, timeout: float = 20, retries: int = 2, *, deadline: float | None = None,
) -> tuple[int, str, str]:
    """Run gh with retries sharing a deadline; timeout caps each process.

    Without a caller deadline, timeout is also the total retry budget.
    """
    if deadline is None:
        deadline = time.monotonic() + timeout
    for attempt in range(retries + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return -1, "", "timeout"
        try:
            result = subprocess.run(args, capture_output=True, timeout=min(timeout, remaining))
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


def _github_api(
    endpoint: str, token: str = "", timeout: float = 20, *, deadline: float | None = None,
) -> tuple[int, str, str]:
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
        request_timeout = _request_timeout(timeout, deadline)
        if request_timeout is None:
            return -1, "", "timeout"
        try:
            with urlopen_retry(req, timeout=request_timeout) as resp:
                return 0, resp.read().decode("utf-8", errors="replace"), ""
        except urllib.error.HTTPError as e:
            raise _github_http_error(e, token, deadline=deadline) from None
        except Exception as e:
            return -1, "", scrub_secrets(e, token)
    return _run_gh(["gh", "api", endpoint], timeout=timeout, deadline=deadline)


def search_github_repos(
    query: str, count: int = 10, token: str = "", timeout: float = 20, *, deadline: float | None = None,
) -> list:
    """Search GitHub repositories. Uses token directly if provided, else gh CLI."""
    endpoint = f"search/repositories?q={urllib.parse.quote_plus(query)}&sort=stars&per_page={count}"
    try:
        rc, stdout, stderr = _github_api(endpoint, token, timeout=timeout, deadline=deadline)
    except _GitHubHTTPError as exc:
        return [_github_error_row(
            str(exc), token, error_type=exc.error_type, rate_limited=exc.rate_limited,
        )]
    if rc != 0:
        message = stderr.strip() or f"exit {rc}"
        error_type = _github_cli_error_type(message)
        return [_github_error_row(
            message, token, error_type=error_type, rate_limited=error_type == "rate_limit",
        )]
    try:
        data = json.loads(stdout)
    except Exception as e:
        return [{"source": "github-repos", "error": f"JSON parse error: {e}"}]
    items = []
    for item in data.get("items", []):
        description = item.get("description") or ""
        items.append(
            {
                "source": "github-repos",
                "title": item.get("full_name", ""),
                "url": item.get("html_url", ""),
                "description": description,
                "content_kind": "excerpt" if description else "metadata",
                "stars": item.get("stargazers_count"),
            }
        )
    return items

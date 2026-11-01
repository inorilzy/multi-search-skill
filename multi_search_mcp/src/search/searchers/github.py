"""GitHub repository and code search via the REST API.

Repository search falls back to the gh CLI without a token; code search
requires a token (GitHub rejects anonymous code search) and never uses gh.
"""
import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from ...support.http import read_limited, urlopen_retry
from ...support.secrets import scrub_secrets


_GITHUB_ERROR_BODY_LIMIT = 4096
_GITHUB_RATE_LIMIT_HEADERS = frozenset({
    "retry-after",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
})
_GITHUB_QUERY_MAX_CHARS = 256
_GITHUB_QUERY_MAX_OPERATORS = 5
_GITHUB_QUERY_OPERATORS = frozenset({"AND", "OR", "NOT"})
_GITHUB_QUALIFIER_RE = re.compile(r"-?[A-Za-z][\w.-]*:\S")
GITHUB_QUERY_TRUNCATED_MESSAGE = "query truncated to GitHub's 256-character / 5-operator limit"
GITHUB_INCOMPLETE_RESULTS_MESSAGE = "GitHub search timed out; results may be incomplete"
_CODE_FRAGMENT_MAX_CHARS = 300


class _GitHubHTTPError(Exception):
    """Redacted GitHub HTTP failure with key-pool classification."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        rate_limited: bool = False,
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.rate_limited = rate_limited
        self.retry_after = retry_after


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


def _github_retry_after(headers: dict[str, str], *, now: float | None = None) -> int | None:
    """Seconds to wait from ``retry-after`` or ``x-ratelimit-reset`` (epoch)."""
    retry_after = headers.get("retry-after", "")
    if retry_after.isdigit():
        return int(retry_after)
    reset = headers.get("x-ratelimit-reset", "")
    if reset.isdigit():
        current = time.time() if now is None else now
        return max(0, int(reset) - int(current))
    return None


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
    rate_limited = error_type == "rate_limit"
    return _GitHubHTTPError(
        scrub_secrets(message, token),
        error_type=error_type,
        rate_limited=rate_limited,
        retry_after=_github_retry_after(headers) if rate_limited else None,
    )


def _github_error_row(
    message: str,
    token: str,
    *,
    error_type: str = "",
    rate_limited: bool = False,
    retry_after: int | None = None,
    source: str = "github-repos",
) -> dict:
    result = {"source": source, "error": scrub_secrets(message, token)}
    if error_type:
        result.update({"error_origin": "provider", "error_type": error_type})
    if rate_limited:
        result["rate_limited"] = True
        if retry_after is not None:
            result["retry_after"] = int(retry_after)
    return result


def _github_exception_row(exc: _GitHubHTTPError, token: str, *, source: str) -> dict:
    return _github_error_row(
        str(exc), token, error_type=exc.error_type, rate_limited=exc.rate_limited,
        retry_after=exc.retry_after, source=source,
    )


def _github_target_row(source: str, message: str) -> dict:
    """Warning row that never counts as evidence about the token."""
    return {"source": source, "error": message, "error_type": "target"}


def limit_github_query(query: str) -> tuple[str, bool]:
    """Fit a query to GitHub's search limits; return (query, truncated).

    GitHub rejects queries longer than 256 characters (operators and
    qualifiers excluded) or with more than five AND/OR/NOT operators. Keep
    every qualifier, the first five operators, and search text up to 256
    characters, preserving token order.
    """
    tokens = str(query or "").split()
    kept: list[str] = []
    operators = 0
    text_chars = 0
    truncated = False
    for token in tokens:
        if token in _GITHUB_QUERY_OPERATORS:
            operators += 1
            if operators > _GITHUB_QUERY_MAX_OPERATORS:
                truncated = True
                continue
            kept.append(token)
            continue
        if _GITHUB_QUALIFIER_RE.match(token):
            kept.append(token)
            continue
        separator = 1 if text_chars else 0
        remaining = _GITHUB_QUERY_MAX_CHARS - text_chars - separator
        if remaining <= 0:
            truncated = True
            continue
        if len(token) > remaining:
            token = token[:remaining]
            truncated = True
        kept.append(token)
        text_chars += separator + len(token)
    limited = " ".join(kept)
    if not truncated:
        # Whitespace-only normalization is not a truncation; send the original.
        return str(query or ""), False
    return limited, True


def _github_incomplete_row(data: dict, source: str) -> list[dict]:
    if isinstance(data, dict) and data.get("incomplete_results") is True:
        return [_github_target_row(source, GITHUB_INCOMPLETE_RESULTS_MESSAGE)]
    return []


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
    # Resolve the executable to give an explicit message when gh is absent;
    # keep the original argv so the child still resolves through PATH.
    if shutil.which(args[0]) is None:
        return -1, "", "gh CLI not found on PATH"
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
    endpoint: str,
    token: str = "",
    timeout: float = 20,
    *,
    deadline: float | None = None,
    accept: str = "application/vnd.github+json",
) -> tuple[int, str, str]:
    """Call GitHub REST API directly when token provided, else fall back to gh CLI."""
    if token:
        url = f"https://api.github.com/{endpoint}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": accept,
                "User-Agent": "multi-search/1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        request_timeout = _request_timeout(timeout, deadline)
        if request_timeout is None:
            return -1, "", "timeout"
        try:
            with urlopen_retry(req, timeout=request_timeout) as resp:
                return 0, read_limited(resp).decode("utf-8", errors="replace"), ""
        except urllib.error.HTTPError as e:
            raise _github_http_error(e, token, deadline=deadline) from None
        except Exception as e:
            return -1, "", scrub_secrets(e, token)
    return _run_gh(["gh", "api", endpoint], timeout=timeout, deadline=deadline)


def search_github_repos(
    query: str, count: int = 10, token: str = "", timeout: float = 20, *, deadline: float | None = None,
) -> list:
    """Search GitHub repositories. Uses token directly if provided, else gh CLI."""
    source = "github-repos"
    query, truncated = limit_github_query(query)
    notices = [_github_target_row(source, GITHUB_QUERY_TRUNCATED_MESSAGE)] if truncated else []
    endpoint = f"search/repositories?q={urllib.parse.quote_plus(query)}&sort=stars&per_page={count}"
    try:
        rc, stdout, stderr = _github_api(endpoint, token, timeout=timeout, deadline=deadline)
    except _GitHubHTTPError as exc:
        return [_github_exception_row(exc, token, source=source)]
    if rc != 0:
        message = stderr.strip() or f"exit {rc}"
        error_type = _github_cli_error_type(message)
        return [_github_error_row(
            message, token, error_type=error_type, rate_limited=error_type == "rate_limit",
        )]
    try:
        data = json.loads(stdout)
    except Exception as e:
        return [{"source": source, "error": f"JSON parse error: {e}"}]
    items = []
    for item in data.get("items", []):
        description = item.get("description") or ""
        items.append(
            {
                "source": source,
                "title": item.get("full_name", ""),
                "url": item.get("html_url", ""),
                "description": description,
                "content_kind": "excerpt" if description else "metadata",
                "stars": item.get("stargazers_count"),
            }
        )
    return items + _github_incomplete_row(data, source) + notices


def _code_fragment(item: dict) -> str:
    for match in item.get("text_matches") or []:
        if not isinstance(match, dict):
            continue
        fragment = " ".join(str(match.get("fragment") or "").split())
        if fragment:
            return fragment
    return ""


def _code_description(path: str, fragment: str) -> str:
    if not fragment:
        return ""
    text = f"{path}: {fragment}" if path else fragment
    if len(text) > _CODE_FRAGMENT_MAX_CHARS:
        text = text[: _CODE_FRAGMENT_MAX_CHARS - 1].rstrip() + "…"
    return text


def search_github_code(
    query: str, count: int = 10, token: str = "", timeout: float = 20, *, deadline: float | None = None,
) -> list:
    """Search code on GitHub and return one row per repository.

    ``GET /search/code`` requires authentication, so a missing token yields a
    missing-key row instead of a gh CLI fallback.
    """
    source = "github-code"
    if not token:
        return [{
            "source": source,
            "error": "skipped: missing GITHUB_TOKEN / GH_TOKEN (GitHub code search requires a token)",
            "error_type": "missing_key",
        }]
    query, truncated = limit_github_query(query)
    notices = [_github_target_row(source, GITHUB_QUERY_TRUNCATED_MESSAGE)] if truncated else []
    per_page = max(1, min(int(count), 100))
    endpoint = f"search/code?q={urllib.parse.quote_plus(query)}&per_page={per_page}"
    try:
        rc, stdout, stderr = _github_api(
            endpoint, token, timeout=timeout, deadline=deadline,
            accept="application/vnd.github.text-match+json",
        )
    except _GitHubHTTPError as exc:
        return [_github_exception_row(exc, token, source=source)]
    if rc != 0:
        return [_github_error_row(stderr.strip() or f"exit {rc}", token, source=source)]
    try:
        data = json.loads(stdout)
    except Exception as e:
        return [{"source": source, "error": f"JSON parse error: {e}"}]
    if not isinstance(data, dict):
        return [{"source": source, "error": "JSON parse error: expected an object"}]
    rows = []
    seen: set[str] = set()
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        repository = item.get("repository") or {}
        if not isinstance(repository, dict):
            continue
        full_name = str(repository.get("full_name") or "")
        if not full_name or full_name in seen:
            continue
        seen.add(full_name)
        path = str(item.get("path") or "")
        description = _code_description(path, _code_fragment(item))
        rows.append({
            "source": source,
            "title": full_name,
            "url": repository.get("html_url", ""),
            "description": description,
            "content_kind": "excerpt" if description else "metadata",
            "path": path,
        })
    return rows + _github_incomplete_row(data, source) + notices

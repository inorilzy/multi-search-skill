"""Cookie loading and error redaction shared by X search and detail fetching."""
import json
import os
import re

from ..support.secrets import scrub_secrets


_CRED_RE = re.compile(
    r"(auth_token|ct0|kdt|guest_id|twid|personalization_id|att)=[A-Za-z0-9%_+\-./]+",
    re.I,
)


class TwitterCookiesMissing(ValueError):
    """The Twitter cookie file does not exist (the source is not configured)."""


def _display_path(path) -> str:
    """Shorten a path under the home directory so errors do not leak it."""
    value = os.fspath(path)
    home = os.path.expanduser("~")
    if home and home not in {"~", os.sep}:
        home_path = os.path.normpath(home)
        candidate = os.path.normpath(value)
        if candidate == home_path:
            return "~"
        prefix = home_path.rstrip(os.sep) + os.sep
        if candidate.startswith(prefix):
            return "~" + candidate[len(home_path):]
    return value


def scrub_twitter_error(error, cookies=None) -> str:
    message = str(error) or type(error).__name__
    home = os.path.expanduser("~")
    if home and home not in {"~", os.sep}:
        message = message.replace(home, "~")
    return scrub_secrets(_CRED_RE.sub(r"\1=<redacted>", message), cookies, limit=300)


def load_twitter_cookies(cookies: dict | str = "") -> dict:
    if isinstance(cookies, dict):
        return cookies
    path = cookies or os.path.expanduser("~/.mcp-twikit/cookies.json")
    if not os.path.exists(path):
        raise TwitterCookiesMissing(f"cookies file not found: {_display_path(path)}")
    try:
        # utf-8-sig tolerates the BOM that PowerShell/Notepad prepend.
        with open(path, encoding="utf-8-sig") as source:
            loaded = json.load(source)
    except Exception as exc:
        raise ValueError(f"cookies load failed: {scrub_twitter_error(exc)}") from None
    if not isinstance(loaded, dict):
        raise ValueError("cookies must be a JSON object")
    return loaded

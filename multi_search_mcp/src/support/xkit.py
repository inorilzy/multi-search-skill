"""Cookie loading and error redaction shared by X search and detail fetching."""
import json
import os
import re

from .secrets import scrub_secrets


_CRED_RE = re.compile(
    r"(auth_token|ct0|kdt|guest_id|twid|personalization_id|att)=[A-Za-z0-9%_+\-./]+",
    re.I,
)


def scrub_twitter_error(error, cookies=None) -> str:
    message = str(error) or type(error).__name__
    return scrub_secrets(_CRED_RE.sub(r"\1=<redacted>", message), cookies, limit=300)


def load_twitter_cookies(cookies: dict | str = "") -> dict:
    if isinstance(cookies, dict):
        return cookies
    path = cookies or os.path.expanduser("~/.mcp-twikit/cookies.json")
    if not os.path.exists(path):
        raise ValueError(f"cookies file not found: {path}")
    try:
        with open(path, encoding="utf-8") as source:
            loaded = json.load(source)
    except Exception as exc:
        raise ValueError(f"cookies load failed: {scrub_twitter_error(exc)}") from None
    if not isinstance(loaded, dict):
        raise ValueError("cookies must be a JSON object")
    return loaded

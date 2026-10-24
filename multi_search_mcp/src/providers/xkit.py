"""Cookie loading and error redaction shared by X search and detail fetching."""
import json
import os
import re
import sys
from dataclasses import dataclass

from ..support.secrets import scrub_secrets


_CRED_RE = re.compile(
    r"(auth_token|ct0|kdt|guest_id|twid|personalization_id|att)=[A-Za-z0-9%_+\-./]+",
    re.I,
)


def scrub_twitter_error(error, cookies=None) -> str:
    message = str(error) or type(error).__name__
    return scrub_secrets(_CRED_RE.sub(r"\1=<redacted>", message), cookies, limit=300)


@dataclass(frozen=True)
class ManagedTwitterCookies:
    """Non-secret lazy reference; decrypted only inside an actual X call."""
    pass


def load_twitter_cookies(cookies: dict | str | ManagedTwitterCookies = "") -> dict:
    if isinstance(cookies, ManagedTwitterCookies):
        if sys.platform != "win32":
            raise ValueError("managed Twitter cookies require Windows DPAPI")
        from ..support.credential_store import default_store, validate_twitter_cookies
        try:
            value = default_store().get("twitter_cookies")
            return validate_twitter_cookies(value)
        except Exception:
            # No fallback to the legacy file, and no provider exception text.
            raise ValueError("managed Twitter cookies unavailable or invalid; import again in desktop") from None
    if isinstance(cookies, dict):
        return cookies
    path = cookies or os.path.expanduser("~/.mcp-twikit/cookies.json")
    if not os.path.exists(path):
        raise ValueError(f"cookies file not found: {path}")
    try:
        # utf-8-sig tolerates the BOM that PowerShell/Notepad prepend.
        with open(path, encoding="utf-8-sig") as source:
            loaded = json.load(source)
    except Exception as exc:
        raise ValueError(f"cookies load failed: {scrub_twitter_error(exc)}") from None
    if not isinstance(loaded, dict):
        raise ValueError("cookies must be a JSON object")
    return loaded

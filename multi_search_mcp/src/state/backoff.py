"""Cross-process "do not call before" marks for keyless provider methods.

Some APIs send a mandatory wait (Stack Exchange ``backoff``, a 429 without a
key to rotate). Every CLI run is a fresh process, so the mark lives in a tiny
JSON file beside ``state.sqlite``. Writes are atomic replacements; a missing,
unreadable or corrupt file simply means "no wait" so a broken mark can never
disable a source for good.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

# A server-requested wait longer than this is clamped.
MAX_BACKOFF_SECONDS = 24 * 3600


def backoff_path() -> Path:
    # Resolved per call (not at import) so an isolated HOME is always honoured.
    return Path.home() / ".multi-search" / "provider-backoff.json"


def _load(path: Path) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}


def remaining(name: str, *, now: float | None = None, path: Path | None = None) -> int:
    """Seconds left before ``name`` may be called again (0 = allowed)."""
    current = time.time() if now is None else now
    until = _load(path or backoff_path()).get(name, 0.0)
    return max(0, int(until - current + 0.999)) if until > current else 0


def record(name: str, seconds: float, *, now: float | None = None, path: Path | None = None) -> None:
    """Forbid calling ``name`` for ``seconds``; never shortens an existing wait."""
    if seconds is None or seconds <= 0:
        return
    target = path or backoff_path()
    current = time.time() if now is None else now
    data = {k: v for k, v in _load(target).items() if v > current}
    data[name] = max(data.get(name, 0.0), current + min(float(seconds), MAX_BACKOFF_SECONDS))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".backoff.", dir=str(target.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(temp, target)
    except OSError:
        # Best effort: losing a backoff mark only risks one extra early call.
        try:
            os.unlink(temp)  # type: ignore[possibly-undefined]
        except (OSError, NameError):
            pass

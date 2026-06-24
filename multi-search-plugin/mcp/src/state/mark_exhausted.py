"""Statically disable a Jina key by setting ``exhausted: true`` in the config.

Live key health (cooldown / quota / invalid) is owned by the SQLite key-state
store; this CLI only flips the operator-controlled static opt-out flag in
``~/.search-keys.json`` so a known-dead key never enters rotation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _mark_config_exhausted(key_to_mark: str) -> bool:
    keys_file = Path.home() / ".search-keys.json"
    if not keys_file.exists():
        return False
    try:
        data = json.loads(keys_file.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    if not isinstance(data, dict) or not data.get("jina"):
        return False

    changed = False

    def _mark(val):
        nonlocal changed
        if isinstance(val, str):
            if val == key_to_mark:
                changed = True
                return {"key": val, "exhausted": True}
            return val
        if isinstance(val, dict):
            if val.get("key") == key_to_mark and not val.get("exhausted"):
                val["exhausted"] = True
                changed = True
            return val
        if isinstance(val, list):
            return [_mark(item) for item in val]
        return val

    data["jina"] = _mark(data["jina"])
    if not changed:
        return False
    try:
        keys_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or not args[0].strip():
        print("Usage: python -m src.mark_exhausted <jina-key>", file=sys.stderr)
        return 2

    if _mark_config_exhausted(args[0].strip()):
        print("Marked Jina key as exhausted.")
        return 0

    print("Jina key was not found or ~/.search-keys.json could not be updated.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

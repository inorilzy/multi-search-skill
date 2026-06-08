"""Mark a Jina key as exhausted in ~/.search-keys.json."""
from __future__ import annotations

import sys

from .keys import mark_jina_exhausted_persistent, mark_jina_exhausted_runtime


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or not args[0].strip():
        print("Usage: python -m scripts.mark_exhausted <jina-key>", file=sys.stderr)
        return 2

    key = args[0].strip()
    mark_jina_exhausted_runtime(key)
    if mark_jina_exhausted_persistent(key):
        print("Marked Jina key as exhausted.")
        return 0

    print("Jina key was not found or ~/.search-keys.json could not be updated.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

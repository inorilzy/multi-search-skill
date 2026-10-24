"""Small request-validation helpers shared by public service entry points."""
from __future__ import annotations

from typing import Any


def request_int(value: Any, field: str) -> int:
    """Parse an integer request field, naming the field when it is not one."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer, got {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer, got {value!r}") from None

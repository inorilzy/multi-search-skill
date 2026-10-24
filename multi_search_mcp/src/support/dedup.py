"""Presentation helpers for fused results."""
# Re-exported here for existing callers.
from .urlutil import _norm_url


def consensus_weight(item: dict) -> int:
    """Number of sources that agreed on a URL (1 + cross-source duplicates)."""
    if item.get("providers"):
        return len(set(item["providers"]))
    return 1 + len(item.get("also_from") or [])

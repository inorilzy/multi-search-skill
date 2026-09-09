"""Deterministic query identities shared by execution and replay."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class LogicalQueryPlan:
    primary_query: str
    variants: tuple[str, ...]
    duplicate_count: int = 0
    discarded_blank_count: int = 0

    @property
    def queries(self) -> tuple[str, ...]:
        return (self.primary_query, *self.variants)


def build_query_plan(primary_query: str, variants: Iterable[str]) -> LogicalQueryPlan:
    """Trim only variant boundaries; preserve the user's primary query verbatim."""
    unique = set()
    duplicates = 0
    blanks = 0
    for raw_query in variants:
        query = raw_query.strip()
        if not query:
            blanks += 1
        elif query == primary_query.strip() or query in unique:
            duplicates += 1
        else:
            unique.add(query)
    return LogicalQueryPlan(primary_query, tuple(sorted(unique)), duplicates, blanks)

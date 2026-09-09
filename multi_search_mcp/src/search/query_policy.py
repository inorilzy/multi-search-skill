"""Explicit query-level fusion experiments; provider ranking is unchanged."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..support.config import ConfigError


@dataclass(frozen=True)
class QueryFusionPolicy:
    mode: str = "equal"
    primary_weight: float | None = None
    variant_budget: float | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"equal", "weighted"}:
            raise ConfigError("query_fusion.mode must be equal or weighted")
        if self.mode == "equal":
            if self.primary_weight is not None or self.variant_budget is not None:
                raise ConfigError("equal query fusion does not accept weights")
            return
        for name, value in (("primary_weight", self.primary_weight),
                            ("variant_budget", self.variant_budget)):
            if (isinstance(value, bool) or not isinstance(value, (float, int))
                    or not math.isfinite(value) or value <= 0):
                raise ConfigError(f"query_fusion.{name} must be finite and positive")

    @classmethod
    def from_config(cls, config: dict) -> QueryFusionPolicy:
        if "query_fusion" not in config:
            return cls()
        value = config["query_fusion"]
        if not isinstance(value, dict):
            raise ConfigError("query_fusion must be an object")
        if set(value) - {"mode", "primary_weight", "variant_budget"}:
            raise ConfigError("query_fusion contains unsupported fields")
        return cls(**value)

    def weights(self, queries: list[str], primary_query: str) -> dict[str, float]:
        if primary_query not in queries or len(set(queries)) != len(queries):
            raise ValueError("fusion requires a unique query set with explicit primary identity")
        if self.mode == "equal" or len(queries) == 1:
            return dict.fromkeys(queries, 1.0)
        assert self.primary_weight is not None and self.variant_budget is not None
        variant_weight = self.variant_budget / (len(queries) - 1)
        if self.primary_weight <= variant_weight:
            raise ConfigError("primary_weight must exceed each variant's allocated weight")
        return {query: self.primary_weight if query == primary_query else variant_weight
                for query in queries}

    def to_dict(self) -> dict[str, Any]:
        if self.mode == "equal":
            return {"mode": self.mode}
        return {"mode": self.mode, "primary_weight": self.primary_weight,
                "variant_budget": self.variant_budget}

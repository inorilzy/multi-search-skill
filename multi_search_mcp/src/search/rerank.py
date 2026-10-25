"""Optional model reranking after RRF fusion, before body fetch.

The default ranking pipeline is pure two-level RRF (``ranking.mode="rrf"``).
Setting ``ranking.mode="rrf_model"`` lets a ``Reranker`` adapter reorder the
fused candidates; the fetch stage then spends its budget on the reranked top
``SEARCH_RESULT_LIMIT`` instead of fetching the RRF order.

Deliberately *not* implemented, by design review:

- ``rrf_k``: the RRF rank constant is frozen at 40 and is baked into the
  ``FUSION_ALGORITHM`` snapshot fingerprint.  A configurable ``k`` would
  silently invalidate every frozen evaluation asset, so it is not a knob.
- ``top_k``: this repository has no top-k concept; the output is always the
  final ``SEARCH_RESULT_LIMIT`` (15) after reranking.
- ``keep_per_source``: with ``candidate_limit`` around 50 and each provider
  returning only 10-20 rows, a per-source floor is almost always a no-op, so
  it would be dead configuration surface.

Adapter construction lives in core: when the merged policy (config file plus
per-request override) selects ``rrf_model`` and no reranker was injected,
``run_search_candidates`` builds one via :func:`build_reranker` from the
single :data:`RERANKER_PROFILES` registry (v1: ``jev_default``).  With
``mode="rrf"`` nothing is constructed, no key is read, and no request is sent.
Numeric bounds (``candidate_limit`` 10-200, ``batch_size`` 1-50,
``rerank_timeout`` 1-60 s) match the desktop settings editor exactly.

Failure semantics: *any* batch failure — a missing candidate id, an unknown
id, a non-finite or out-of-range score, a timeout, rate limiting, or an auth
failure — fails the whole rerank stage.  ``apply_rerank`` never raises and
never partially applies: the response keeps the complete RRF order and
reports ``mode_used="rrf"`` with a short ``fallback_reason`` code
(``timeout`` / ``rate_limit`` / ``auth`` / ``invalid_response`` /
``unavailable``).  Reason codes never carry secrets or raw service errors.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..support.concurrency import BoundedDaemonExecutor
from ..support.config import ConfigError
from ..support.http import read_limited, urlopen_retry


class RerankError(Exception):
    """A rerank-stage failure described by a secret-free reason code."""

    REASONS = frozenset(
        {"timeout", "rate_limit", "auth", "invalid_response", "unavailable"}
    )

    def __init__(self, reason: str = "unavailable", detail: str | None = None):
        super().__init__(detail or reason)
        self.reason = reason if reason in self.REASONS else "unavailable"


# At most two scoring batches may be in flight at once.  The pool is shared so
# abandoned work cannot spawn unbounded threads across requests.
_RERANK_POOL = BoundedDaemonExecutor(
    max_workers=2,
    thread_name_prefix="multi-search-rerank",
)

_RANKING_KEYS = frozenset(
    {"mode", "reranker_profile_id", "candidate_limit", "batch_size", "rerank_timeout"}
)

DEFAULT_RERANKER_PROFILE = "jev_default"

# Inclusive bounds, identical to the desktop editor
# (desktop/src-tauri/src/settings.rs RANKING_*_MIN/MAX) so a config accepted
# here is never shown as ``ranking_invalid`` there, and vice versa.
CANDIDATE_LIMIT_RANGE = (10, 200)
BATCH_SIZE_RANGE = (1, 50)
RERANK_TIMEOUT_RANGE = (1, 60)  # seconds


@dataclass(frozen=True)
class RerankPolicy:
    mode: str = "rrf"  # "rrf" | "rrf_model"
    profile_id: str = DEFAULT_RERANKER_PROFILE
    candidate_limit: int = 50
    batch_size: int = 20
    rerank_timeout: float = 5.0  # seconds; total budget for the rerank stage

    def __post_init__(self) -> None:
        if self.mode not in {"rrf", "rrf_model"}:
            raise ConfigError("ranking.mode must be rrf or rrf_model")
        if not isinstance(self.profile_id, str) or self.profile_id not in RERANKER_PROFILES:
            raise ConfigError(
                "ranking.reranker_profile_id must be one of: "
                + ", ".join(sorted(RERANKER_PROFILES))
            )
        for name, value, (low, high) in (
            ("candidate_limit", self.candidate_limit, CANDIDATE_LIMIT_RANGE),
            ("batch_size", self.batch_size, BATCH_SIZE_RANGE),
        ):
            if (
                isinstance(value, bool) or not isinstance(value, int)
                or not low <= value <= high
            ):
                raise ConfigError(f"ranking.{name} must be an integer in {low}-{high}")
        low, high = RERANK_TIMEOUT_RANGE
        if (
            isinstance(self.rerank_timeout, bool)
            or not isinstance(self.rerank_timeout, (int, float))
            or not math.isfinite(self.rerank_timeout)
            or not low <= self.rerank_timeout <= high
        ):
            raise ConfigError(f"ranking.rerank_timeout must be a number in {low}-{high}")

    @property
    def enabled(self) -> bool:
        return self.mode != "rrf"

    @classmethod
    def from_config(
        cls, config: dict, request_override: dict | None = None
    ) -> "RerankPolicy":
        """Merge ``ranking`` config with a per-request override and validate.

        Unknown fields, wrong types, and out-of-range values are
        ``ConfigError``s — nothing is silently ignored, matching
        ``QueryFusionPolicy.from_config``.
        """
        merged: dict = {}
        if "ranking" in config:
            value = config["ranking"]
            if not isinstance(value, dict):
                raise ConfigError("ranking must be an object")
            merged.update(value)
        if request_override is not None:
            if not isinstance(request_override, dict):
                raise ConfigError("ranking request override must be an object")
            merged.update(request_override)
        if set(merged) - _RANKING_KEYS:
            raise ConfigError("ranking contains unsupported fields")
        if "reranker_profile_id" in merged:
            merged["profile_id"] = merged.pop("reranker_profile_id")
        return cls(**merged)


@runtime_checkable
class Reranker(Protocol):
    def score(
        self, query: str, candidates: list[dict], *, deadline: float
    ) -> dict[str, float]:
        """Map each candidate ``source_id`` to a relevance in ``[0, 1]``.

        Implementations raise :class:`RerankError` on any failure; the whole
        rerank stage then falls back to the RRF order.
        """


# Only these hit fields may reach the model.  ``provider_ranks``, ``rrf_score``
# and support counts are withheld so the scorer cannot anchor on the very
# ordering it is asked to improve.
_CANDIDATE_FIELDS = ("source_id", "url", "title", "content", "published_at")


def _candidate_view(hit: dict) -> dict:
    return {key: hit.get(key) for key in _CANDIDATE_FIELDS}


def _reason_for(exc: BaseException) -> str:
    if isinstance(exc, RerankError):
        return exc.reason
    if isinstance(exc, (TimeoutError, FutureTimeoutError)):
        return "timeout"
    return "unavailable"


def _score_batch(
    reranker: Reranker,
    query: str,
    batch: list[dict],
    deadline: float,
) -> dict[str, float]:
    """Score one batch and validate the response defensively."""
    ids = {str(candidate["source_id"]) for candidate in batch}
    result = reranker.score(query, batch, deadline=deadline)
    if not isinstance(result, Mapping):
        raise RerankError("invalid_response")
    result = {str(key): value for key, value in result.items()}
    if set(result) != ids:
        # An unknown id or a missing id invalidates the whole stage; partial
        # batch results are never applied.
        raise RerankError("invalid_response")
    scores: dict[str, float] = {}
    for source_id, value in result.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0.0 <= value <= 1.0
        ):
            raise RerankError("invalid_response")
        scores[source_id] = float(value)
    return scores


def apply_rerank(
    hits: list[dict],
    query: str,
    reranker: Reranker | None,
    *,
    policy: RerankPolicy,
    deadline: float,
) -> tuple[list[dict], dict]:
    """Reorder ``hits`` with model scores, or fall back to the RRF order.

    Never raises.  The scored candidates are sorted by ``relevance_score``
    descending (ties keep RRF order) and placed back into the exact RRF slots
    they occupied; unscored hits do not move.  Model scores are never added to
    RRF scores and appearance counts earn no bonus.
    """
    meta = {
        "mode_requested": policy.mode,
        "mode_used": "rrf",
        "fallback_reason": None,
    }
    for hit in hits:
        hit["relevance_score"] = None

    def fail(reason: str) -> tuple[list[dict], dict]:
        meta["fallback_reason"] = reason
        return list(hits), meta

    if reranker is None:
        return fail("unavailable")
    candidates = hits[: max(0, policy.candidate_limit)]
    if not candidates:
        meta["mode_used"] = policy.mode
        return list(hits), meta

    batches = [
        candidates[index : index + policy.batch_size]
        for index in range(0, len(candidates), policy.batch_size)
    ]
    views = [[_candidate_view(hit) for hit in batch] for batch in batches]

    submitted: list[tuple[int, Future]] = []
    for index, batch in enumerate(views):
        future = _RERANK_POOL.submit_before(
            deadline, _score_batch, reranker, query, batch, deadline
        )
        if future is None:
            reason = (
                "timeout" if deadline - time.monotonic() <= 0 else "unavailable"
            )
            for _index, pending in submitted:
                _RERANK_POOL.abandon(pending)
            return fail(reason)
        submitted.append((index, future))

    scores: dict[str, float] = {}
    failure: str | None = None
    for _index, future in submitted:
        remaining = deadline - time.monotonic()
        try:
            scores.update(future.result(timeout=max(0.0, remaining)))
        except BaseException as exc:  # noqa: BLE001 - any failure falls back
            failure = _reason_for(exc)
            break
    if failure is not None:
        for _index, pending in submitted:
            _RERANK_POOL.abandon(pending)
        return fail(failure)

    # Highest relevance first; equal scores keep their RRF order.  The scored
    # hits are then written back into the RRF slots they originally occupied.
    scored_positions = [
        index
        for index, hit in enumerate(hits)
        if str(hit["source_id"]) in scores
    ]
    ranked_positions = sorted(
        scored_positions,
        key=lambda index: (-scores[str(hits[index]["source_id"])], index),
    )
    reordered = list(hits)
    for slot, source_index in zip(scored_positions, ranked_positions):
        reordered[slot] = hits[source_index]
    for hit in reordered:
        source_id = str(hit["source_id"])
        if source_id in scores:
            hit["relevance_score"] = scores[source_id]
    meta["mode_used"] = policy.mode
    return reordered, meta


class JevReranker:
    """``Reranker`` adapter for Typesafe's Jev scoring endpoint.

    The API key is read from the environment only (``TYPESAFE_API_KEY`` by
    default); a missing key fails closed with ``RerankError("auth")``.  The
    key is deliberately *not* registered in ``CREDENTIAL_STORE_PROVIDERS``:
    that table also drives the Rust provider list, ``source_catalog`` and
    ``provider_parity`` tests, so wiring it in would pretend Jev is a search
    provider.  Keeping the credential env-only is a known v1 limitation.

    .. warning::
        The author could not reach docs.typesafe.ai (it resolves to a
        non-public address from this network), so the wire format in
        :meth:`_build_payload` and :meth:`_parse_response` is *unverified*.
        Both are kept in one place so a corrected schema only touches this
        class.
    """

    MODEL_VERSION = "jev-1.14.0"  # pinned; aliases may move between versions
    GRADE_MAX = 4.0  # Jev grades on a 0-4 scale; normalized to [0, 1]
    DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
    ENDPOINT_ENV = "TYPESAFE_JEV_ENDPOINT"
    KEY_ENV = "TYPESAFE_API_KEY"

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        api_key: str | None = None,
        opener=None,
    ):
        self._endpoint = endpoint or os.environ.get(self.ENDPOINT_ENV) or self.DEFAULT_ENDPOINT
        self._api_key = api_key
        self._opener = opener

    def score(
        self, query: str, candidates: list[dict], *, deadline: float
    ) -> dict[str, float]:
        api_key = self._api_key or os.environ.get(self.KEY_ENV)
        if not api_key:
            raise RerankError("auth")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RerankError("timeout")
        payload = self._build_payload(query, candidates)

        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            if self._opener is not None:
                response = self._opener(request, timeout=remaining, deadline=deadline)
            else:
                response = urlopen_retry(
                    request, timeout=remaining, retries=0, deadline=deadline
                )
            with response:
                body = read_limited(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RerankError("auth") from None
            if exc.code == 429:
                raise RerankError("rate_limit") from None
            raise RerankError("unavailable") from None
        except (TimeoutError, FutureTimeoutError) as exc:
            raise RerankError("timeout") from exc
        except RerankError:
            raise
        except OSError as exc:
            raise RerankError("unavailable") from exc
        try:
            decoded = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise RerankError("invalid_response") from None
        return self._parse_response(decoded, candidates)

    def _build_payload(self, query: str, candidates: list[dict]) -> dict:
        """Unverified wire format: one independent scoring question per
        candidate.  The question ``id`` is wire bookkeeping and is not shown
        to the model, so each ``instructions`` explicitly names the single
        candidate it must grade (「仅评价候选 <id>」).
        """
        return {
            "model": self.MODEL_VERSION,
            "task": "rerank",
            "query": query,
            "questions": [
                {
                    "id": str(candidate["source_id"]),
                    "instructions": (
                        f"仅评价候选 {candidate['source_id']}: "
                        "grade only this candidate's relevance to the query "
                        "on a 0-4 scale."
                    ),
                    "document": {
                        key: candidate.get(key)
                        for key in ("url", "title", "content", "published_at")
                    },
                }
                for candidate in candidates
            ],
        }

    def _parse_response(
        self, decoded: Any, candidates: list[dict]
    ) -> dict[str, float]:
        """Unverified response shape: ``{"scores": [{"id": ..., "grade": 0-4}]}``.

        Defensive by contract: a missing id, an unknown id, a non-finite
        grade, or a grade outside 0-4 is an ``invalid_response`` failure.
        """
        expected = {str(candidate["source_id"]) for candidate in candidates}
        if not isinstance(decoded, dict) or not isinstance(decoded.get("scores"), list):
            raise RerankError("invalid_response")
        seen: set[str] = set()
        scores: dict[str, float] = {}
        for entry in decoded["scores"]:
            if not isinstance(entry, dict):
                raise RerankError("invalid_response")
            source_id = entry.get("id")
            grade = entry.get("grade")
            if not isinstance(source_id, str) or source_id not in expected or source_id in seen:
                raise RerankError("invalid_response")
            if (
                isinstance(grade, bool)
                or not isinstance(grade, (int, float))
                or not math.isfinite(grade)
                or not 0.0 <= grade <= self.GRADE_MAX
            ):
                raise RerankError("invalid_response")
            seen.add(source_id)
            scores[source_id] = float(grade) / self.GRADE_MAX
        if seen != expected:
            raise RerankError("invalid_response")
        return scores


# The single authoritative profile registry.  ``ranking.reranker_profile_id``
# is validated against it in core; the CLI/MCP surfaces read it from here, and
# the desktop editor's ``RERANKER_PROFILES`` lists the same ids.
RERANKER_PROFILES: dict[str, Any] = {
    DEFAULT_RERANKER_PROFILE: JevReranker,
}


def build_reranker(profile_id: str) -> Reranker:
    """Construct the adapter registered for ``profile_id``.

    Construction performs no I/O and reads no secret; adapters read their key
    lazily inside ``score``.  An unregistered id is a ``ConfigError``.
    """
    factory = RERANKER_PROFILES.get(profile_id)
    if factory is None:
        raise ConfigError(
            "ranking.reranker_profile_id must be one of: "
            + ", ".join(sorted(RERANKER_PROFILES))
        )
    return factory()

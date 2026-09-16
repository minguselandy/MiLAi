"""Fail-closed fixed-pool reranking with optional RankingStateView semantics."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

from milai.adapters.reranker import CrossEncoderReranker, RerankerExecution
from milai.domain.ranking_state_view import RankingStateViewV01
from milai.domain.requirement_state import canonical_sha256

StateViewMode = Literal["NONE", "CORRECT", "SHUFFLED"]


class StateAwareRerankerProtocolError(RuntimeError):
    """The bounded model response violated its fixed-pool contract."""


def fixed_candidate_pool_digest(candidates: list[dict[str, Any]]) -> str:
    """Bind candidate identity and baseline position without exposing content."""

    material: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        candidate_id = _candidate_id(candidate)
        if candidate_id in seen:
            raise ValueError("fixed candidate pool contains duplicate identity")
        seen.add(candidate_id)
        material.append(
            {
                "candidate_id": candidate_id,
                "source_ref": str(candidate.get("source_ref", "")),
                "content_hash": str(candidate.get("content_hash", "")),
                "baseline_rank": index + 1,
            }
        )
    return canonical_sha256(material)


class StateAwareCrossEncoderReranker:
    """Score one immutable pool, validate the full response, or keep baseline order."""

    def __init__(
        self,
        backend: CrossEncoderReranker,
        *,
        expected_identity: Mapping[str, object],
    ) -> None:
        self._backend = backend
        self._expected_identity = dict(expected_identity)

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        limit: int,
        pool_size: int,
        state_view: RankingStateViewV01 | None = None,
        state_mode: StateViewMode = "NONE",
    ) -> RerankerExecution:
        if not query or limit <= 0 or pool_size < limit or pool_size != len(candidates):
            raise ValueError("state-aware reranker requires one complete positive fixed pool")
        baseline = [dict(item) for item in candidates[:limit]]
        try:
            pool_digest = fixed_candidate_pool_digest(candidates)
            if state_mode == "NONE":
                if state_view is not None:
                    raise StateAwareRerankerProtocolError("query-only arm received state")
                model_query = query
            else:
                if state_view is None:
                    raise StateAwareRerankerProtocolError("state arm lacks a view")
                if state_view.candidate_pool_digest != pool_digest:
                    raise StateAwareRerankerProtocolError("stale candidate-pool binding")
                model_query = state_view.render(
                    query,
                    shuffled=state_mode == "SHUFFLED",
                )
            execution = self._backend.rerank(
                model_query,
                candidates,
                limit=pool_size,
                pool_size=pool_size,
            )
            self._validate_metadata(execution.metadata)
            ranked = self._validate_and_sort(execution.results, candidates)
            selected: list[dict[str, Any]] = []
            for item in ranked[:limit]:
                projected = dict(item)
                reranker = projected.get("reranker")
                if not isinstance(reranker, dict):
                    raise StateAwareRerankerProtocolError("candidate score metadata missing")
                projected["reranker"] = {
                    **reranker,
                    "state_mode": state_mode,
                    "view_digest": state_view.view_digest if state_view is not None else None,
                }
                selected.append(projected)
            return RerankerExecution(
                selected,
                {
                    **execution.metadata,
                    "state_mode": state_mode,
                    "view_digest": state_view.view_digest if state_view is not None else None,
                    "candidate_pool_digest": pool_digest,
                    "fallback_used": False,
                    "automatic_retries": 0,
                    "model_invocations": 1,
                },
            )
        except Exception as exc:
            reason = _fallback_reason(exc)
            return RerankerExecution(
                baseline,
                {
                    **self._expected_identity,
                    "state_mode": state_mode,
                    "view_digest": state_view.view_digest if state_view is not None else None,
                    "fallback_used": True,
                    "fallback_reason": reason,
                    "automatic_retries": 0,
                    "model_invocations": int(reason != "PRECALL_PROTOCOL_FAILURE"),
                },
            )

    def _validate_metadata(self, metadata: Mapping[str, object]) -> None:
        for field, expected in self._expected_identity.items():
            if metadata.get(field) != expected:
                raise StateAwareRerankerProtocolError(f"model identity mismatch: {field}")

    @staticmethod
    def _validate_and_sort(
        results: list[dict[str, Any]],
        baseline: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        baseline_ids = [_candidate_id(item) for item in baseline]
        result_ids = [_candidate_id(item) for item in results]
        if len(results) != len(baseline) or set(result_ids) != set(baseline_ids):
            raise StateAwareRerankerProtocolError("partial or foreign candidate response")
        if len(set(result_ids)) != len(result_ids):
            raise StateAwareRerankerProtocolError("duplicate candidate response")
        baseline_index = {candidate_id: index for index, candidate_id in enumerate(baseline_ids)}
        scores: dict[str, float] = {}
        for item in results:
            metadata = item.get("reranker")
            score = metadata.get("score") if isinstance(metadata, Mapping) else None
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise StateAwareRerankerProtocolError("candidate score missing")
            numeric = float(score)
            if not math.isfinite(numeric):
                raise StateAwareRerankerProtocolError("candidate score is non-finite")
            scores[_candidate_id(item)] = numeric
        return sorted(
            (dict(item) for item in results),
            key=lambda item: (-scores[_candidate_id(item)], baseline_index[_candidate_id(item)]),
        )


def _candidate_id(candidate: Mapping[str, Any]) -> str:
    for field in ("evidence_id", "candidate_id", "claim_version_id"):
        value = candidate.get(field)
        if isinstance(value, str) and value:
            return value
    raise ValueError("candidate has no stable identity")


def _fallback_reason(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "TIMEOUT"
    if isinstance(exc, StateAwareRerankerProtocolError):
        message = str(exc)
        if "stale candidate-pool" in message or "state arm" in message or "query-only" in message:
            return "PRECALL_PROTOCOL_FAILURE"
        if "identity mismatch" in message:
            return "IDENTITY_MISMATCH"
        if "non-finite" in message:
            return "NON_FINITE_SCORE"
        return "PARTIAL_OR_FOREIGN_BATCH"
    return "BACKEND_UNAVAILABLE"


__all__ = [
    "StateAwareCrossEncoderReranker",
    "StateAwareRerankerProtocolError",
    "StateViewMode",
    "fixed_candidate_pool_digest",
]

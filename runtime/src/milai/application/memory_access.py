from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from milai.domain.memory_resolve import MemoryResolveRequest

if TYPE_CHECKING:
    from milai.application.memory_resolve import MemoryQueryInterpretation

MemoryAccessIntent = Literal["POSSIBLE", "REQUIRED"]

# Compatibility ceiling for the pre-DG23 AcquisitionPlan ``context_tokens``
# field.  It is an internal deterministic-work ceiling, never a Reader or
# presentation cap.  All acquisition/decision executions receive the same
# value irrespective of MemoryResolveBudget.max_context_tokens.
ACQUISITION_DECISION_CONTEXT_CEILING = 32_000


@dataclass(frozen=True, slots=True)
class MemoryAccessPlan:
    """Runtime-owned structural budget for one task-free Memory read."""

    access_intent: MemoryAccessIntent
    candidate_cap: int
    deadline_ms: int
    context_token_budget: int
    reranker_candidate_cap: int
    hard_partitions: tuple[str, ...]
    vector_policy: Literal["SPARSE_INSUFFICIENCY_ONLY"] = "SPARSE_INSUFFICIENCY_ONLY"
    reranker_policy: Literal["CONDITIONAL_SMALL_SET"] = "CONDITIONAL_SMALL_SET"
    planner_version: str = "memory-access-plan-v1"


class MemoryAccessPlanner:
    """Choose fixed server-bounded search work without a model or Host Task state."""

    _POSSIBLE_CANDIDATE_CAP = 30
    _POSSIBLE_DEADLINE_MS = 250
    _POSSIBLE_CONTEXT_TOKENS = 768
    _REQUIRED_RERANKER_CAP = 20

    def plan(
        self,
        request: MemoryResolveRequest,
        interpretation: MemoryQueryInterpretation,
    ) -> MemoryAccessPlan:
        if interpretation.intent not in {"POSSIBLE", "REQUIRED"}:
            raise ValueError("MemoryAccessPlan requires a reachable Memory intent")
        possible = interpretation.intent == "POSSIBLE"
        access_intent: MemoryAccessIntent = "POSSIBLE" if possible else "REQUIRED"
        requested = request.budget
        complex_search = interpretation.retrieval_intent in {
            "HISTORY",
            "CONFLICT",
            "EXPLANATION",
        }
        candidate_floor = max(
            30 if complex_search else 12,
            requested.max_results * 3,
        )
        candidate_cap = min(
            requested.max_candidates,
            min(self._POSSIBLE_CANDIDATE_CAP, candidate_floor)
            if possible
            else candidate_floor,
        )
        deadline_ms = min(
            requested.max_latency_ms,
            self._POSSIBLE_DEADLINE_MS if possible else requested.max_latency_ms,
        )
        context_token_budget = min(
            requested.max_context_tokens,
            self._POSSIBLE_CONTEXT_TOKENS if possible else requested.max_context_tokens,
        )
        hard_partitions = ["tenant", "principal_scope", "project_scope", "valid_time"]
        if request.entities:
            hard_partitions.append("entity")
        if request.memory_types:
            hard_partitions.append("memory_type")
        return MemoryAccessPlan(
            access_intent=access_intent,
            candidate_cap=candidate_cap,
            deadline_ms=deadline_ms,
            context_token_budget=context_token_budget,
            reranker_candidate_cap=(
                0
                if possible
                else min(self._REQUIRED_RERANKER_CAP, candidate_cap)
            ),
            hard_partitions=tuple(hard_partitions),
        )

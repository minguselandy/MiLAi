from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from milai.application.memory_access import MemoryAccessPlan
from milai.application.query_planner import QueryPlanner
from milai.application.retrieval import (
    MatchedReplayInvariantError,
    RetrievalService,
)
from milai.application.sufficiency import decide_sufficiency
from milai.domain.retrieval import RetrievalRequest
from milai.domain.sufficiency import SufficiencyDecision
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import GatedBatch, ProjectionState


def _request() -> RetrievalRequest:
    return RetrievalRequest(
        route="L1",
        query="How much did I spend on each coffee mug for my coworkers?",
        memory_intent="HISTORY",
        consistency="CANONICAL_REQUIRED",
        limit=10,
    )


def _access_plan() -> MemoryAccessPlan:
    return MemoryAccessPlan(
        access_intent="REQUIRED",
        candidate_cap=30,
        deadline_ms=1_000,
        context_token_budget=2_048,
        reranker_candidate_cap=20,
        hard_partitions=("tenant", "principal_scope", "valid_time"),
    )


def _price() -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": "price-evidence",
        "subject_id": "fixture-user",
        "source_ref": "memory://session/36/turn/0",
        "content": "user: I spent $60 on coffee mugs for my coworkers.",
        "relevance_score": 1.0,
    }


def _count() -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": "count-evidence",
        "subject_id": "fixture-user",
        "source_ref": "memory://session/45/turn/0",
        "content": "user: I purchased 5 coffee mugs for my coworkers.",
        "relevance_score": 0.9,
    }


def test_exact_state_miss_uses_query_ir_requirement_identity() -> None:
    request = RetrievalRequest(
        route="L0",
        claim_id=UUID(int=1),
        consistency="CANONICAL_REQUIRED",
    )
    plan = QueryPlanner().plan(request)

    decision, reason = decide_sufficiency(
        request,
        plan,
        [],
        [],
        None,
        stage="FINAL",
    )

    assert decision.status == "UNSATISFIED"
    assert decision.missing_slots == ["EXACT_STATE"]
    assert reason == "NO_CANONICAL_RESULT"


class _EvidenceRepository:
    def __init__(self, evidence: list[dict[str, Any]]) -> None:
        self.evidence = evidence
        self.vector_calls = 0
        self.trace: Any | None = None
        self.batch = GatedBatch(
            ProjectionState(0, 0, 0, False, False),
            [],
            [],
        )

    def projection_state(self, *args: Any, **kwargs: Any) -> ProjectionState:
        return self.batch.projection_state

    def search_evidence(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.evidence)

    def exact_candidates(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def search_fts(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def search_vector(self, *args: Any, **kwargs: Any) -> list[Any]:
        self.vector_calls += 1
        return []

    def gate_and_hydrate(self, *args: Any, **kwargs: Any) -> GatedBatch:
        return self.batch

    def record_trace(self, _context: Any, trace: Any) -> UUID:
        self.trace = trace
        return UUID(int=17)


def test_q1_contract_cannot_encode_candidate_presence_as_completeness() -> None:
    with pytest.raises(ValidationError, match="candidate_count"):
        SufficiencyDecision.model_validate(
            {
                "status": "COMPLETE",
                "covered_slots": [],
                "missing_slots": [],
                "proof": {},
                "stop_reason": "REQUIREMENT_SATISFIED",
                "candidate_count": 1,
            }
        )


def test_q1_nonempty_candidates_do_not_complete_an_operator_query() -> None:
    request = _request()
    plan = QueryPlanner().plan(request)

    decision, reason = decide_sufficiency(
        request,
        plan,
        [{"kind": "EVIDENCE_OBSERVATION", "content": "coffee mugs"}],
        [],
        None,
        stage="FTS",
    )

    assert decision.status == "PARTIAL"
    assert decision.missing_slots == ["TOTAL_PRICE", "ITEM_COUNT"]
    assert reason == "OPERATOR_RESULT_INCOMPLETE"


@pytest.mark.parametrize(
    ("query", "missing_slot"),
    [
        (
            "How many babies were born to friends and family in the last few months?",
            "MATCHING_EVENTS_IN_RANGE",
        ),
        (
            "I mentioned cooking something a couple of days ago. What was it?",
            "TARGET_EVENT",
        ),
        (
            "Who did I meet first, Mark and Sarah or Tom?",
            "EVENT_1",
        ),
        (
            "I'm visiting Denver soon. Any suggestions on what to do there?",
            "PREFERENCE_SIGNAL_SET",
        ),
    ],
)
def test_q1_unexecuted_operator_cannot_fall_through_to_lookup_complete(
    query: str, missing_slot: str
) -> None:
    request = RetrievalRequest(
        route="L1",
        query=query,
        memory_intent="HISTORY",
        consistency="CANONICAL_REQUIRED",
    )
    plan = QueryPlanner().plan(request).model_copy(
        update={"operator": None, "operator_arguments": {}}
    )

    decision, reason = decide_sufficiency(
        request,
        plan,
        [{"kind": "EVIDENCE_OBSERVATION", "content": query}],
        [],
        None,
        stage="FTS",
    )

    assert decision.status == "PARTIAL"
    assert missing_slot in decision.missing_slots
    assert reason == "MEMORY_QUERY_IR_OPERATOR_UNEXECUTED"


def test_q1_single_evidence_lookup_is_candidate_until_decision_engine_binding() -> None:
    request = RetrievalRequest(
        route="L1",
        query="What game did I finally beat last weekend?",
        memory_intent="HISTORY",
        consistency="CANONICAL_REQUIRED",
    )
    plan = QueryPlanner().plan(request).model_copy(
        update={"operator": None, "operator_arguments": {}}
    )

    decision, reason = decide_sufficiency(
        request,
        plan,
        [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "content": "user: I finally beat the Dark Souls 3 DLC last weekend.",
            }
        ],
        [],
        None,
        stage="FTS",
    )

    assert decision.status == "PARTIAL"
    assert decision.missing_slots == ["LOOKUP_ANSWER"]
    assert reason == "EVIDENCE_LOOKUP_CANDIDATE_ONLY"


def test_ambiguous_text_with_access_plan_remains_fail_closed() -> None:
    request = RetrievalRequest(
        route="L1",
        query="Recall opaqueuniquetoken",
        consistency="CANONICAL_REQUIRED",
    )
    plan = QueryPlanner().plan(request, access_intent="REQUIRED")
    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.mode == "AMBIGUOUS"

    decision, reason = decide_sufficiency(
        request,
        plan,
        [{"kind": "CANONICAL_STATE", "claim_version_id": "version-1"}],
        [],
        None,
        stage="FINAL",
    )

    assert decision.status == "UNSATISFIED"
    assert decision.stop_reason == "QUERY_AMBIGUOUS"
    assert reason == "MEMORY_QUERY_IR_AMBIGUOUS"


def test_ambiguous_text_without_access_plan_remains_fail_closed() -> None:
    request = RetrievalRequest(
        route="L1",
        query="Recall opaqueuniquetoken",
        consistency="CANONICAL_REQUIRED",
    )
    plan = QueryPlanner().plan(request)

    decision, reason = decide_sufficiency(
        request,
        plan,
        [{"kind": "CANONICAL_STATE", "claim_version_id": "version-1"}],
        [],
        None,
        stage="FINAL",
    )

    assert decision.status == "UNSATISFIED"
    assert decision.stop_reason == "QUERY_AMBIGUOUS"
    assert reason == "MEMORY_QUERY_IR_AMBIGUOUS"


def test_action_safe_access_lookup_escalates_before_final_completion() -> None:
    request = RetrievalRequest(
        route="L1",
        query="What is the recorded value for opaqueuniquetoken?",
        required_authority="ACTION_SAFE",
        requested_scope={"project_ids": ["milai"]},
        consistency="CANONICAL_REQUIRED",
    )
    plan = QueryPlanner().plan(request, access_intent="REQUIRED")
    results = [{"kind": "CANONICAL_STATE", "claim_version_id": "version-1"}]

    early, early_reason = decide_sufficiency(
        request, plan, results, [], None, stage="FTS"
    )
    final, final_reason = decide_sufficiency(
        request, plan, results, [], None, stage="FINAL"
    )

    assert early.status == "PARTIAL"
    assert early_reason == "ACTION_SAFE_REQUIRES_FULL_PIPELINE"
    assert final.status == "COMPLETE"
    assert final_reason == "TOP_K_EPISODIC_LOOKUP_COMPLETE"


def test_q1_partial_composition_escalates_in_same_call_and_abstains() -> None:
    repository = _EvidenceRepository([_count()])
    execution = RetrievalService(repository).retrieve(  # type: ignore[arg-type]
        SessionContext(UUID(int=1), UUID(int=2)),
        _request(),
        "dg17-partial-escalation",
        access_plan=_access_plan(),
    )

    decisions = execution.body["progressive_l1"]["sufficiency_decisions"]
    assert repository.vector_calls == 1
    assert execution.body["derived_result"]["status"] == "PARTIAL"
    assert [item["evidence_id"] for item in execution.body["results"]] == [
        "count-evidence"
    ]
    assert execution.body["abstained"] is True
    assert execution.body["abstention_reason"] == "OPERATOR_REQUIRED_SLOT_MISSING"
    assert [item["stage"] for item in decisions] == ["FTS", "VECTOR", "FINAL"]
    assert all(item["decision"]["status"] == "PARTIAL" for item in decisions)
    terminal = execution.body["progressive_l1"]["terminal_sufficiency_decision"]
    assert terminal["status"] == "PARTIAL"
    assert execution.body["access_trace"]["sufficiency_decision"] == terminal
    assert repository.trace.execution_trace["sufficiency_decision"] == terminal


def test_q1_complete_composition_is_the_only_evidence_operator_early_stop() -> None:
    repository = _EvidenceRepository([_price(), _count()])
    execution = RetrievalService(repository).retrieve(  # type: ignore[arg-type]
        SessionContext(UUID(int=1), UUID(int=2)),
        _request(),
        "dg17-complete-stop",
        access_plan=_access_plan(),
    )

    assert repository.vector_calls == 0
    assert execution.body["abstained"] is False
    assert execution.body["derived_result"]["status"] == "COMPLETE"
    assert execution.body["derived_result"]["value"] == 12
    assert execution.body["progressive_l1"]["stop_stage"] == "EVIDENCE_FTS"
    terminal = execution.body["progressive_l1"]["terminal_sufficiency_decision"]
    assert terminal["status"] == "COMPLETE"
    assert terminal["stop_reason"] == "REQUIREMENT_SATISFIED"


def test_q1r_one_retrieval_captures_legacy_prefix_and_current_outcome() -> None:
    repository = _EvidenceRepository([_count()])
    execution = RetrievalService(repository).retrieve(  # type: ignore[arg-type]
        SessionContext(UUID(int=1), UUID(int=2)),
        _request(),
        "dg17-q1r-one-execution",
        access_plan=_access_plan(),
        capture_matched_replay=True,
    )

    replay = execution.matched_replay
    assert replay is not None
    assert repository.vector_calls == 1
    assert repository.trace is not None
    assert len(replay.evidence_snapshot_digest) == 64
    assert replay.evidence_snapshot["start_end_projection_identity_equal"] is True
    legacy = replay.policy_bodies["DG16_ANY_EVIDENCE_STOP"]
    current = replay.policy_bodies["DG17_QUERY_SPECIFIC_STOP"]
    assert legacy["abstained"] is False
    assert legacy["progressive_l1"]["stop_stage"] == "EVIDENCE_FTS"
    assert legacy["progressive_l1"]["sufficiency_reason"] == (
        "LEGACY_ANY_EVIDENCE_STOP"
    )
    assert legacy["progressive_l1"]["terminal_sufficiency_decision"]["status"] == (
        "PARTIAL"
    )
    assert current["abstained"] is True
    assert current["abstention_reason"] == "OPERATOR_REQUIRED_SLOT_MISSING"
    shared = replay.policy_metadata["DG16_ANY_EVIDENCE_STOP"]["shared_execution"]
    assert shared["retrieval_execution_count"] == 1
    assert replay.policy_metadata["DG16_ANY_EVIDENCE_STOP"]["fresh_retrieval_calls"] == 0
    assert replay.policy_metadata["DG17_QUERY_SPECIFIC_STOP"]["fresh_retrieval_calls"] == 1


class _DriftingEvidenceRepository(_EvidenceRepository):
    def __init__(self, evidence: list[dict[str, Any]]) -> None:
        super().__init__(evidence)
        self.gate_calls = 0

    def gate_and_hydrate(self, *args: Any, **kwargs: Any) -> GatedBatch:
        self.gate_calls += 1
        if self.gate_calls == 1:
            return self.batch
        return GatedBatch(
            ProjectionState(1, 1, 1, False, False, evidence_watermark=1),
            [],
            [],
        )


def test_q1r_snapshot_drift_fails_closed_without_a_paired_capture() -> None:
    repository = _DriftingEvidenceRepository([_count()])

    with pytest.raises(
        MatchedReplayInvariantError,
        match="projection state changed",
    ):
        RetrievalService(repository).retrieve(  # type: ignore[arg-type]
            SessionContext(UUID(int=1), UUID(int=2)),
            _request(),
            "dg17-q1r-drift",
            access_plan=_access_plan(),
            capture_matched_replay=True,
        )

    assert repository.gate_calls == 2
    assert repository.trace is None

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
from milai.domain.query_task_contract import ParseDisposition
from milai.domain.reader_evidence_plan import DecisionSnapshot
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
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": "36",
            "turn_id": "36:turn:0",
            "turn_ordinal": 0,
            "round_id": "36:round:0",
            "round_ordinal": 0,
            "previous_turn_id": None,
            "next_turn_id": None,
        },
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "relevance_score": 1.0,
    }


def _count() -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": "count-evidence",
        "subject_id": "fixture-user",
        "source_ref": "memory://session/45/turn/0",
        "content": "user: I purchased exactly 5 coffee mugs for my coworkers.",
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": "45",
            "turn_id": "45:turn:0",
            "turn_ordinal": 0,
            "round_id": "45:round:0",
            "round_ordinal": 0,
            "previous_turn_id": None,
            "next_turn_id": None,
        },
        "source_context_source": "STRUCTURED_TURN_METADATA",
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


def test_identifier_number_lookup_is_not_reinterpreted_as_unexecuted_count() -> None:
    request = RetrievalRequest(
        route="L1",
        query="What is the phone number of my dentist?",
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
                "content": "assistant: The recorded contact number is 555-0100.",
            }
        ],
        [],
        None,
        stage="FTS",
    )

    assert decision.status == "PARTIAL"
    assert decision.missing_slots == ["LOOKUP_ANSWER"]
    assert reason == "EVIDENCE_LOOKUP_CANDIDATE_ONLY"


def test_best_effort_text_with_access_plan_remains_non_complete() -> None:
    request = RetrievalRequest(
        route="L1",
        query="Recall opaqueuniquetoken",
        consistency="CANONICAL_REQUIRED",
    )
    plan = QueryPlanner().plan(request, access_intent="REQUIRED")
    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.mode == "EVIDENCE"
    assert plan.query_task_contract is not None
    assert (
        plan.query_task_contract.parse_disposition
        == ParseDisposition.BEST_EFFORT_RECALL
    )

    decision, reason = decide_sufficiency(
        request,
        plan,
        [{"kind": "CANONICAL_STATE", "claim_version_id": "version-1"}],
        [],
        None,
        stage="FINAL",
    )

    assert decision.status == "PARTIAL"
    assert decision.stop_reason == "QUERY_AMBIGUOUS"
    assert reason == "BEST_EFFORT_RECALL_NOT_COMPLETE"


def test_best_effort_text_without_access_plan_remains_non_complete() -> None:
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

    assert decision.status == "PARTIAL"
    assert decision.stop_reason == "QUERY_AMBIGUOUS"
    assert reason == "BEST_EFFORT_RECALL_NOT_COMPLETE"


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


def test_q1_raw_evidence_escalates_but_never_becomes_operator_input() -> None:
    repository = _EvidenceRepository([_count()])
    execution = RetrievalService(repository).retrieve(  # type: ignore[arg-type]
        SessionContext(UUID(int=1), UUID(int=2)),
        _request(),
        "dg17-partial-escalation",
        access_plan=_access_plan(),
    )

    decisions = execution.body["progressive_l1"]["sufficiency_decisions"]
    assert repository.vector_calls == 1
    assert execution.body["derived_result"]["status"] == "ABSTAINED"
    assert execution.body["derived_result"]["accepted_input_evidence_ids"] == []
    assert [item["evidence_id"] for item in execution.body["results"]] == [
        "count-evidence"
    ]
    assert execution.body["abstained"] is True
    assert execution.body["abstention_reason"] == "OPERATOR_REQUIRED_SLOT_MISSING"
    assert [item["stage"] for item in decisions] == ["FTS", "VECTOR", "FINAL"]
    assert all(item["decision"]["status"] == "UNSATISFIED" for item in decisions)
    terminal = execution.body["progressive_l1"]["terminal_sufficiency_decision"]
    assert terminal["status"] == "UNSATISFIED"
    assert execution.body["access_trace"]["sufficiency_decision"] == terminal
    assert repository.trace.execution_trace["sufficiency_decision"] == terminal


def test_q1_complete_looking_raw_prose_does_not_early_stop_or_compute() -> None:
    repository = _EvidenceRepository([_price(), _count()])
    execution = RetrievalService(repository).retrieve(  # type: ignore[arg-type]
        SessionContext(UUID(int=1), UUID(int=2)),
        _request(),
        "dg17-complete-stop",
        access_plan=_access_plan(),
    )

    assert repository.vector_calls == 1
    assert execution.body["abstained"] is True
    assert execution.body["derived_result"]["status"] == "ABSTAINED"
    assert "operand_authority" not in execution.body["derived_result"]
    assert execution.body["derived_result"]["accepted_input_evidence_ids"] == []
    assert execution.body["progressive_l1"]["stop_stage"] is None
    terminal = execution.body["progressive_l1"]["terminal_sufficiency_decision"]
    assert terminal["status"] == "UNSATISFIED"
    assert terminal["stop_reason"] == "SEARCH_SPACE_EXHAUSTED"
    snapshot = execution.decision_snapshot
    assert snapshot is not None
    assert snapshot.lean_recall_mode == "STRICT"
    assert snapshot.evidence_set.missing_requirement_ids == (
        "ITEM_COUNT",
        "TOTAL_PRICE",
    )
    assert snapshot.evidence_set.covered_requirement_ids == ()
    assert snapshot.evidence_set.items == ()


def test_audit_observer_receives_complete_snapshot_even_when_deferral_requested() -> None:
    class Observer:
        def __init__(self) -> None:
            self.snapshots: list[DecisionSnapshot] = []

        def capture_product_execution(self, **values: Any) -> None:
            snapshot = values["decision_snapshot"]
            assert isinstance(snapshot, DecisionSnapshot)
            assert len(snapshot.binding_digest) == 64
            self.snapshots.append(snapshot)

    observer = Observer()
    repository = _EvidenceRepository([_count()])
    execution = RetrievalService(
        repository, retrieval_audit_observer=observer,  # type: ignore[arg-type]
    ).retrieve(
        SessionContext(UUID(int=1), UUID(int=2)), _request(), "audit-full-snapshot",
        access_plan=_access_plan(), defer_decision_snapshot=True,
    )
    assert observer.snapshots == [execution.decision_snapshot]
    assert isinstance(execution.decision_snapshot, DecisionSnapshot)


@pytest.mark.parametrize("with_audit", [False, True])
def test_ordinary_request_defers_raw_diagnostics_only_without_audit(
    monkeypatch: pytest.MonkeyPatch, with_audit: bool,
) -> None:
    from milai.application.evidence_acquisition import (
        DeferredEvidenceAcquisitionExecution,
        EvidenceAcquisitionExecution,
        EvidenceAcquisitionExecutor,
    )
    from milai.application.prepared_evidence_spans import PreparedEvidenceSpans
    from milai.application.reader_evidence_plan import materialize_decision_snapshot

    captured = []
    original = EvidenceAcquisitionExecutor.compile_existing_results

    def compile_results(self: Any, **kwargs: Any) -> Any:
        value = original(self, **kwargs)
        captured.append(value)
        return value

    class Observer:
        def capture_product_execution(self, **values: Any) -> None:
            assert isinstance(values["acquisition_execution"], EvidenceAcquisitionExecution)
            assert isinstance(values["decision_snapshot"], DecisionSnapshot)

    request = _request().model_copy(update={"query": "Find notes about ceramic mugs."})
    expected = RetrievalService(_EvidenceRepository([_count()])).retrieve(
        SessionContext(UUID(int=1), UUID(int=2)), request, "ordinary-eager",
        access_plan=_access_plan(),
    )
    monkeypatch.setattr(EvidenceAcquisitionExecutor, "compile_existing_results", compile_results)
    actual = RetrievalService(
        _EvidenceRepository([_count()]),
        retrieval_audit_observer=Observer() if with_audit else None,
    ).retrieve(
        SessionContext(UUID(int=1), UUID(int=2)), request, "ordinary-deferred",
        access_plan=_access_plan(), defer_decision_snapshot=True,
    )
    assert captured
    for work in captured:
        if with_audit:
            assert isinstance(work, EvidenceAcquisitionExecution)
        else:
            assert isinstance(work, DeferredEvidenceAcquisitionExecution)
            assert work.semantics._values is None
            assert isinstance(work.spans, PreparedEvidenceSpans)
            assert work.spans._values is None
    assert actual.body["results"] == expected.body["results"]
    assert actual.decision_snapshot is not None and expected.decision_snapshot is not None
    assert materialize_decision_snapshot(actual.decision_snapshot) == expected.decision_snapshot


@pytest.mark.parametrize("defer_snapshot", [False, True])
def test_q1r_one_retrieval_captures_legacy_prefix_and_current_outcome(
    defer_snapshot: bool,
) -> None:
    repository = _EvidenceRepository([_count()])
    execution = RetrievalService(repository).retrieve(  # type: ignore[arg-type]
        SessionContext(UUID(int=1), UUID(int=2)),
        _request(),
        "dg17-q1r-one-execution",
        access_plan=_access_plan(),
        capture_matched_replay=True,
        defer_decision_snapshot=defer_snapshot,
    )

    replay = execution.matched_replay
    assert isinstance(execution.decision_snapshot, DecisionSnapshot)
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
        "UNSATISFIED"
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

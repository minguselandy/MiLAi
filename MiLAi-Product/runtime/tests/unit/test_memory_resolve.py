from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest

from milai.application.memory_context import ContextCompilation, MemoryContextCompiler
from milai.application.memory_resolve import (
    MemoryQueryInterpreter,
    MemoryResolveService,
    _access_outcome,
)
from milai.application.memory_state import MemoryStateViewService
from milai.application.retrieval import (
    MatchedRetrievalReplay,
    RetrievalExecution,
    RetrievalService,
)
from milai.domain import (
    CanonicalStateAddress,
    MemoryContext,
    MemoryResolveBudget,
    MemoryResolveRequest,
    MemoryStateGetRequest,
    RetrievalRequest,
    TaskContextHint,
)
from milai.domain.reader_evidence_plan import ReaderEvidencePolicy
from milai.persistence import SessionContext


@pytest.mark.parametrize(
    ("query", "intent", "requirement", "retrieval_intent"),
    [
        ("What is the current release status?", "REQUIRED", "EXACT", "CURRENT_STATE"),
        ("当前项目进行到哪里?", "REQUIRED", "EXACT", "CURRENT_STATE"),
        ("Recall 当前 database setting", "REQUIRED", "EXACT", "CURRENT_STATE"),
        ("Could this affect the release?", "REQUIRED", "SEARCH", None),
        ("Explain the previous decision", "REQUIRED", "SEARCH", "EXPLANATION"),
        ("Are there conflicting branches?", "REQUIRED", "SEARCH", "CONFLICT"),
    ],
)
def test_runtime_query_interpreter_is_task_free_and_language_aware(
    query: str,
    intent: str,
    requirement: str,
    retrieval_intent: str | None,
) -> None:
    result = MemoryQueryInterpreter().interpret(query)

    assert result.intent == intent
    assert result.requirement == requirement
    assert result.retrieval_intent == retrieval_intent
    assert result.interpreter_version == "runtime-query-interpreter-v2"


def test_runtime_query_interpreter_applies_invocation_floor_without_task_truth() -> None:
    interpreter = MemoryQueryInterpreter()

    explicit = interpreter.interpret("What is 17 plus 25?")
    automatic = interpreter.interpret(
        "What is 17 plus 25?", invocation_mode="PREFETCH_AUTO"
    )
    exact = interpreter.interpret(
        "What is 17 plus 25?",
        invocation_mode="PREFETCH_AUTO",
        exact_target=True,
    )

    assert (explicit.intent, explicit.requirement) == ("REQUIRED", "SEARCH")
    assert (automatic.intent, automatic.requirement) == ("NOT_NEEDED", "NONE")
    assert (exact.intent, exact.requirement) == ("REQUIRED", "EXACT")


class _Retrieval:
    def __init__(self, execution: RetrievalExecution) -> None:
        self.execution = execution
        self.requests: list[RetrievalRequest] = []
        self.options: list[dict[str, Any]] = []

    def retrieve(
        self,
        _context: SessionContext,
        request: RetrievalRequest,
        _request_id: str,
        **options: Any,
    ) -> RetrievalExecution:
        self.requests.append(request)
        self.options.append(options)
        return self.execution


class _StateViews:
    def __init__(self, execution: RetrievalExecution) -> None:
        self.execution = execution
        self.requests: list[MemoryStateGetRequest] = []

    def get(
        self,
        _context: SessionContext,
        request: MemoryStateGetRequest,
        _request_id: str,
    ) -> RetrievalExecution:
        self.requests.append(request)
        return self.execution


def _body(**overrides: object) -> dict[str, Any]:
    body: dict[str, Any] = {
        "results": [
            {
                "claim_id": "claim-1",
                "claim_version_id": "version-1",
                "evidence_ids": ["evidence-1"],
                "open_issue_ids": [],
            }
        ],
        "open_issue_ids": [],
        "consistency": "CANONICAL_REQUIRED",
        "snapshot": {"canonical_outbox_sequence": 9},
        "retrieval_trace_id": "trace-1",
        "degraded_components": [],
        "fallback_used": False,
        "fallback_reason": None,
        "abstained": False,
        "abstention_reason": None,
        "access_trace": {"retrieval_trace_id": "trace-1"},
    }
    body.update(overrides)
    return body


def test_resolve_uses_one_l1_retrieval_and_adapts_hit_without_task() -> None:
    retrieval = _Retrieval(RetrievalExecution(_body()))
    service = MemoryResolveService(cast(RetrievalService, retrieval))
    request = MemoryResolveRequest(
        query="What is the current release status?",
        requested_scope={"project_ids": ["milai"]},
        budget=MemoryResolveBudget(max_results=3),
    )

    execution = service.resolve(
        SessionContext(
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ),
        request,
        "request-1",
    )

    assert len(retrieval.requests) == 1
    underlying = retrieval.requests[0]
    assert underlying.route == "L1"
    assert underlying.memory_intent == "CURRENT_STATE"
    assert underlying.limit == 3
    access_plan = retrieval.options[0]["access_plan"]
    assert access_plan.access_intent == "REQUIRED"
    assert access_plan.candidate_cap == 60
    assert access_plan.deadline_ms == 500
    assert access_plan.context_token_budget == 2_500
    # Explicit reads spend the Host-declared pool instead of applying a hidden clamp.
    assert access_plan.reranker_candidate_cap == access_plan.candidate_cap == 60
    assert retrieval.options[0]["defer_decision_snapshot"] is True
    assert not hasattr(request, "task_id")
    assert execution.body["status"] == "HIT"
    assert execution.body["memory_intent"] == "REQUIRED"
    assert execution.body["requirement"] == "EXACT"
    assert execution.body["evidence_refs"] == ["evidence-1"]
    context = execution.body["memory_context"]
    receipt = execution.body["context_receipt"]
    assert context["authority_class"] == "MIXED"
    assert context["selected_evidence_ids"] == ["evidence-1"]
    assert receipt["authority_class"] == "MIXED"
    assert receipt["source_evidence_ids"] == ["evidence-1"]
    assert receipt["claim_versions"] == ["version-1"]
    assert receipt["receipt_mapping"] == [
        {
            "alias": "C1",
            "evidence_ids": ["evidence-1"],
            "source_turn_refs": [],
            "claim_versions": ["version-1"],
            "issue_revisions": [],
        }
    ]
    assert "task_enhancement" not in execution.body


def test_resolve_separates_source_snapshot_cutoff_from_query_reference_time() -> None:
    retrieval = _Retrieval(RetrievalExecution(_body()))
    service = MemoryResolveService(cast(RetrievalService, retrieval))
    reference = datetime(2023, 1, 13, 12, tzinfo=UTC)
    snapshot = datetime(2023, 1, 13, 23, 36, tzinfo=UTC)
    request = MemoryResolveRequest(
        query="What happened a week ago?",
        reference_time=reference,
    )

    service.resolve(
        SessionContext(
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ),
        request,
        "request-snapshot-separation",
        source_snapshot_as_of=snapshot,
    )

    underlying = retrieval.requests[0]
    assert underlying.as_of == snapshot
    assert underlying.system_as_of == snapshot
    assert underlying.reference_time == reference


def test_formation_replay_handoff_exposes_only_decision_evidence() -> None:
    interpretation = MemoryQueryInterpreter().interpret(
        "What is my current release status?"
    )
    body = _body(
        query_plan={
            "planner_version": "query-planner-v0.2+formation-semantic-replay-v0.2"
        },
        results=[
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "answer-support",
                "evidence_ids": ["answer-support"],
                "content": "The current release status is ready.",
            },
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "assistant-noise",
                "evidence_ids": ["assistant-noise"],
                "content": "Could the status be blocked?",
            },
        ],
    )
    snapshot = type(
        "Snapshot",
        (),
        {"accepted_evidence_ids": ("answer-support",)},
    )()

    outcome = _access_outcome(
        body,
        interpretation,
        decision_snapshot=cast(Any, snapshot),
        reader_evidence_policy=ReaderEvidencePolicy.DECISION_ACCEPTED_ONLY,
    )

    assert outcome["evidence_refs"] == ["answer-support"]
    assert [item["evidence_id"] for item in outcome["items"]] == ["answer-support"]
    assert outcome["_reader_evidence_boundary"] == "DECISION_ACCEPTED_ONLY"


def test_progressive_formation_handoff_separates_context_from_binding_evidence() -> None:
    interpretation = MemoryQueryInterpreter().interpret(
        "What is my current release status?"
    )
    body = _body(
        query_plan={
            "planner_version": "query-planner-v0.2+formation-semantic-replay-v0.2"
        },
        results=[
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "answer-support",
                "evidence_ids": ["answer-support"],
                "content": "The current release status is ready.",
            },
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "governed-context",
                "evidence_ids": ["governed-context"],
                "content": "The release review happened yesterday.",
            },
        ],
    )
    snapshot = type(
        "Snapshot",
        (),
        {"accepted_evidence_ids": ("answer-support",)},
    )()

    outcome = _access_outcome(
        body,
        interpretation,
        decision_snapshot=cast(Any, snapshot),
        reader_evidence_policy=ReaderEvidencePolicy.GOVERNANCE_ADMITTED_SOFT_RANKED,
    )

    assert [item["evidence_id"] for item in outcome["items"]] == [
        "answer-support",
        "governed-context",
    ]
    assert outcome["evidence_refs"] == ["answer-support", "governed-context"]
    assert outcome["accepted_binding_evidence_refs"] == ["answer-support"]
    assert outcome["_reader_evidence_boundary"] == (
        "GOVERNANCE_ADMITTED_SOFT_RANKED"
    )


def test_nonformation_handoff_preserves_frozen_result_projection() -> None:
    interpretation = MemoryQueryInterpreter().interpret(
        "What is my current release status?"
    )
    body = _body(
        query_plan={"planner_version": "query-planner-v0.2"},
        results=[
            {"evidence_ids": ["answer-support"]},
            {"evidence_ids": ["neighbor"]},
        ],
    )
    snapshot = type(
        "Snapshot",
        (),
        {"accepted_evidence_ids": ("answer-support",)},
    )()

    outcome = _access_outcome(
        body,
        interpretation,
        decision_snapshot=cast(Any, snapshot),
    )

    assert outcome["evidence_refs"] == ["answer-support", "neighbor"]
    assert len(outcome["items"]) == 2
    assert outcome["_reader_evidence_boundary"] == (
        "GOVERNANCE_ADMITTED_SOFT_RANKED"
    )


@pytest.mark.parametrize(
    ("reader_policy", "expected_boundary", "expect_internal_candidates"),
    [
        (
            ReaderEvidencePolicy.GOVERNANCE_ADMITTED_SOFT_RANKED,
            "GOVERNANCE_ADMITTED_SOFT_RANKED",
            True,
        ),
        (
            ReaderEvidencePolicy.DECISION_ACCEPTED_ONLY,
            "DECISION_ACCEPTED_ONLY",
            False,
        ),
    ],
)
def test_instance_preserving_candidates_obey_boundary_and_never_escape(
    reader_policy: ReaderEvidencePolicy,
    expected_boundary: str,
    expect_internal_candidates: bool,
) -> None:
    class _CapturingCompiler:
        def __init__(self) -> None:
            self.outcome: dict[str, Any] | None = None
            self.delegate = MemoryContextCompiler()

        def compile(
            self,
            request: MemoryResolveRequest,
            outcome: dict[str, Any],
            **kwargs: Any,
        ) -> ContextCompilation:
            self.outcome = dict(outcome)
            return self.delegate.compile(request, outcome, **kwargs)

    baseline = {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "evidence_id": "baseline-evidence",
        "evidence_ids": ["baseline-evidence"],
        "source_ref": "memory://session/alpha/turn/1",
        "subject_id": "alpha",
        "content": "user: Baseline evidence.",
    }
    expanded = {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "evidence_id": "expanded-evidence",
        "evidence_ids": ["expanded-evidence"],
        "source_ref": "memory://session/beta/turn/2",
        "subject_id": "beta",
        "content": "user: Expanded governed evidence.",
    }
    snapshot = type(
        "Snapshot",
        (),
        {"accepted_evidence_ids": ("baseline-evidence",)},
    )()
    retrieval = _Retrieval(
        RetrievalExecution(
            _body(
                results=[baseline],
                query_plan={
                    "planner_version": (
                        "query-planner-v0.2+formation-semantic-replay-v0.2"
                    )
                },
            ),
            decision_snapshot=cast(Any, snapshot),
            context_candidate_items=(baseline, expanded),
        )
    )
    compiler = _CapturingCompiler()
    service = MemoryResolveService(
        cast(RetrievalService, retrieval),
        context_compiler=cast(MemoryContextCompiler, compiler),
        reader_evidence_policy=reader_policy,
        instance_preserving_admission_v0_1_enabled=True,
    )

    execution = service.resolve(
        SessionContext(UUID(int=1), UUID(int=2)),
        MemoryResolveRequest(query="Recall the governed evidence"),
        "instance-preserving-boundary",
    )

    assert compiler.outcome is not None
    assert (
        "_instance_preserving_candidate_items" in compiler.outcome
    ) is expect_internal_candidates
    assert execution.body["reader_evidence_boundary"] == expected_boundary
    assert "_instance_preserving_candidate_items" not in execution.body
    assert "_acquired_candidate_items" not in execution.body


def test_q1r_resolve_matched_replay_compiles_two_contexts_from_one_retrieval() -> None:
    evidence_body = _body(
        results=[
            {
                "kind": "EVIDENCE_OBSERVATION",
                "canonical": False,
                "evidence_id": "evidence-1",
                "source_ref": "memory://session/alpha/turn/4",
                "subject_id": "alpha",
                "observed_at": "2026-08-27T00:00:00+00:00",
                "content": "user: The cobalt code is 47.",
                "relevance_score": 1.0,
            }
        ],
        progressive_l1={
            "terminal_sufficiency_decision": {
                "status": "COMPLETE",
                "covered_slots": ["LOOKUP_ANSWER"],
                "missing_slots": [],
                "proof": {},
                "stop_reason": "REQUIREMENT_SATISFIED",
            }
        },
    )
    replay = MatchedRetrievalReplay(
        schema_version="matched-retrieval-replay-v0.1",
        evidence_snapshot={
            "schema_version": "runtime-evidence-snapshot-v0.1",
            "projection_state": {"canonical_snapshot_outbox_sequence": 9},
            "start_end_projection_identity_equal": True,
            "capture_mode": "ONE_RETRIEVAL_EXECUTION_PREFIX_REPLAY",
        },
        evidence_snapshot_digest="a" * 64,
        policy_bodies={
            "DG16_ANY_EVIDENCE_STOP": evidence_body,
            "DG17_QUERY_SPECIFIC_STOP": evidence_body,
        },
        policy_metadata={
            "DG16_ANY_EVIDENCE_STOP": {"shared_execution": {"retrieval_execution_count": 1}},
            "DG17_QUERY_SPECIFIC_STOP": {"shared_execution": {"retrieval_execution_count": 1}},
        },
    )
    retrieval = _Retrieval(
        RetrievalExecution(evidence_body, matched_replay=replay)
    )
    service = MemoryResolveService(cast(RetrievalService, retrieval))

    result = service.resolve_matched_replay(
        SessionContext(
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ),
        MemoryResolveRequest(
            query="Recall the cobalt code",
            budget=MemoryResolveBudget(max_context_tokens=512),
        ),
        "request-q1r",
    )

    assert len(retrieval.requests) == 1
    assert retrieval.options == [
        {
            "context_budget": 512,
            "access_plan": retrieval.options[0]["access_plan"],
            "capture_matched_replay": True,
        }
    ]
    assert result.evidence_snapshot_digest == "a" * 64
    assert set(result.policy_executions) == {
        "DG16_ANY_EVIDENCE_STOP",
        "DG17_QUERY_SPECIFIC_STOP",
    }
    contexts = [
        execution.body["memory_context"]
        for execution in result.policy_executions.values()
    ]
    assert contexts[0]["text"] == contexts[1]["text"]
    assert contexts[0]["semantic_context_digest"] == (
        contexts[1]["semantic_context_digest"]
    )
    for execution in result.policy_executions.values():
        assert execution.body["context_receipt"]["receipt_mapping"][0]["alias"] == "E1"
        assert execution.body["context_receipt"]["source_evidence_ids"] == ["evidence-1"]


def test_resolve_returns_runtime_evidence_context_and_formal_receipt() -> None:
    retrieval = _Retrieval(
        RetrievalExecution(
            _body(
                results=[
                    {
                        "kind": "EVIDENCE_OBSERVATION",
                        "canonical": False,
                        "evidence_id": "evidence-1",
                        "source_ref": "memory://session/alpha/turn/4",
                        "subject_id": "alpha",
                        "observed_at": "2026-08-27T00:00:00+00:00",
                        "content": "user: The cobalt code is 47.",
                        "relevance_score": 1.0,
                    }
                ],
                progressive_l1={
                    "terminal_sufficiency_decision": {
                        "schema_version": "sufficiency-decision-v0.1",
                        "status": "COMPLETE",
                        "covered_slots": ["ANSWER"],
                        "missing_slots": [],
                        "proof": {},
                        "stop_reason": "REQUIREMENT_SATISFIED",
                    }
                },
            )
        )
    )
    execution = MemoryResolveService(cast(RetrievalService, retrieval)).resolve(
        SessionContext(UUID(int=1), UUID(int=2)),
        MemoryResolveRequest(
            query="Recall the cobalt code",
            budget=MemoryResolveBudget(max_context_tokens=512),
        ),
        "runtime-evidence-context",
    )

    context = execution.body["memory_context"]
    receipt = execution.body["context_receipt"]
    assert context["schema_version"] == "memory-context-v0.1"
    assert context["authority_class"] == "EVIDENCE_ONLY"
    assert "The cobalt code is 47." in context["text"]
    assert context["estimated_tokens"] <= 512
    assert receipt["schema_version"] == "context-receipt-v0.2"
    assert receipt["authority_class"] == "EVIDENCE_ONLY"
    assert receipt["source_evidence_ids"] == ["evidence-1"]
    assert receipt["canonical_mutation"] is False


def test_budget_infeasible_evidence_context_is_explicit_abstention() -> None:
    text = "[Memory Context]\nNo governed Memory evidence fits the available budget."

    class _BudgetInfeasibleCompiler:
        def compile(self, *_args: object, **_kwargs: object) -> ContextCompilation:
            return ContextCompilation(
                MemoryContext(
                    authority_class="CANONICAL_STATE",
                    text=text,
                    semantic_context_digest="a" * 64,
                    reader_context_digest=hashlib.sha256(text.encode()).hexdigest(),
                    token_budget=128,
                    estimated_tokens=24,
                    available_windows=1,
                    selected_windows=0,
                    context_truncated=True,
                    selected_evidence_ids=[],
                    selected_source_turn_refs=[],
                    claim_versions=[],
                    open_issue_ids=[],
                    windows=[],
                    compile_trace={
                        "reader_readiness": "BUDGET_INFEASIBLE",
                        "selected_unit_ids": [],
                        "selected_conditional_unit_ids": [],
                        "atomic_unit_truncation_count": 0,
                        "long_turn_split_count": 0,
                        "rank_first_prefix_violation_count": 0,
                    },
                ),
                None,
            )

    retrieval = _Retrieval(
        RetrievalExecution(
            _body(
                results=[
                    {
                        "kind": "EVIDENCE_OBSERVATION",
                        "canonical": False,
                        "evidence_id": "evidence-too-large",
                        "source_ref": "memory://session/large/turn/0",
                        "subject_id": "large",
                        "content": "one protected whole unit",
                    }
                ]
            )
        )
    )
    service = MemoryResolveService(
        cast(RetrievalService, retrieval),
        context_compiler=cast(MemoryContextCompiler, _BudgetInfeasibleCompiler()),
    )

    execution = service.resolve(
        SessionContext(UUID(int=1), UUID(int=2)),
        MemoryResolveRequest(
            query="Recall all required details",
            budget=MemoryResolveBudget(max_context_tokens=128),
        ),
        "budget-infeasible-evidence",
    )

    assert execution.body["status"] == "ABSTAINED"
    assert execution.body["abstention_reason"] == "CONTEXT_BUDGET_INFEASIBLE"
    assert execution.body["context_receipt"] is None
    assert execution.body["context_receipt_issue_reason"] == "EVIDENCE_CONTEXT_EMPTY"
    assert execution.body["memory_context"]["compile_trace"]["reader_readiness"] == (
        "BUDGET_INFEASIBLE"
    )


def test_resolve_propagates_explicit_question_reference_time() -> None:
    retrieval = _Retrieval(RetrievalExecution(_body()))
    service = MemoryResolveService(cast(RetrievalService, retrieval))
    reference_time = datetime(2023, 3, 27, 23, 35, tzinfo=UTC)

    service.resolve(
        SessionContext(UUID(int=1), UUID(int=2)),
        MemoryResolveRequest(
            query="Recall how many doctor's appointments I went to in March",
            reference_time=reference_time,
        ),
        "reference-time",
    )

    assert retrieval.requests[0].as_of == reference_time


def test_optional_task_context_only_narrows_and_cannot_change_authority() -> None:
    retrieval = _Retrieval(RetrievalExecution(_body()))
    service = MemoryResolveService(cast(RetrievalService, retrieval))
    request = MemoryResolveRequest(
        query="Recall the release state",
        requested_scope={"project_ids": ["milai", "other"]},
        required_authority="ACTION_SAFE",
        entities=["release-alpha", "release-beta"],
        memory_types=["PROJECT_STATE", "PERSONAL_FACT"],
        task_context=TaskContextHint(
            project_ids=["milai"],
            entities=["release-alpha"],
            memory_types=["PROJECT_STATE"],
            action_risk="HIGH",
        ),
    )

    execution = service.resolve(
        SessionContext(UUID(int=1), UUID(int=2)), request, "task-context-narrowing"
    )

    underlying = retrieval.requests[0]
    assert underlying.requested_scope == {"project_ids": ["milai"]}
    assert underlying.entities == ["release-alpha"]
    assert underlying.memory_types == ["PROJECT_STATE"]
    assert underlying.required_authority == "ACTION_SAFE"
    enhancement = execution.body["task_enhancement"]
    assert enhancement["applied"] is True
    assert enhancement["authority_unchanged"] is True
    assert enhancement["consistency_unchanged"] is True
    assert enhancement["action_risk_non_authoritative"] is True
    assert set(enhancement["effects"]) == {
        "PROJECT_SCOPE_NARROWING",
        "ENTITY_HARD_PARTITION",
        "MEMORY_TYPE_HARD_PARTITION",
        "ACTION_RISK_OBSERVED_NO_POLICY_EFFECT",
    }


@pytest.mark.parametrize(
    ("request_fields", "task_fields"),
    [
        ({"requested_scope": {"project_ids": ["milai"]}}, {"project_ids": ["other"]}),
        ({"entities": ["release-alpha"]}, {"entities": ["release-beta"]}),
        ({"memory_types": ["FACT"]}, {"memory_types": ["PREFERENCE"]}),
    ],
)
def test_task_context_conflicting_with_deployment_bound_hints_is_rejected(
    request_fields: dict[str, Any], task_fields: dict[str, Any]
) -> None:
    with pytest.raises(ValueError, match="conflicts with the deployment-bound request"):
        MemoryResolveRequest(
            query="Recall release state",
            **request_fields,
            task_context=TaskContextHint(**task_fields),
        )


def test_possible_access_plan_is_a_low_cost_server_bounded_probe() -> None:
    retrieval = _Retrieval(RetrievalExecution(_body(results=[], abstained=True)))
    service = MemoryResolveService(cast(RetrievalService, retrieval))

    service.resolve(
        SessionContext(UUID(int=1), UUID(int=2)),
        MemoryResolveRequest(
            query="Could this affect the release?",
            invocation_mode="PREFETCH_AUTO",
            budget=MemoryResolveBudget(
                max_results=3,
                max_candidates=120,
                max_context_tokens=8_000,
                max_latency_ms=2_000,
            ),
        ),
        "possible-bounded-probe",
    )

    access_plan = retrieval.options[0]["access_plan"]
    assert access_plan.access_intent == "POSSIBLE"
    assert access_plan.candidate_cap == 12
    assert access_plan.deadline_ms == 250
    assert access_plan.context_token_budget == 768
    assert access_plan.reranker_candidate_cap == 0


def test_explicit_read_honors_host_wide_budget_without_memory_keywords() -> None:
    retrieval = _Retrieval(RetrievalExecution(_body(results=[], abstained=True)))
    service = MemoryResolveService(cast(RetrievalService, retrieval))

    service.resolve(
        SessionContext(UUID(int=1), UUID(int=2)),
        MemoryResolveRequest(
            query="What speed is my new internet plan?",
            budget=MemoryResolveBudget(
                max_results=50,
                max_candidates=120,
                max_context_tokens=8_192,
                max_latency_ms=2_000,
            ),
        ),
        "explicit-wide-read",
    )

    access_plan = retrieval.options[0]["access_plan"]
    assert access_plan.access_intent == "REQUIRED"
    assert access_plan.candidate_cap == 120
    assert access_plan.deadline_ms == 2_000
    assert access_plan.context_token_budget == 8_192
    assert access_plan.reranker_candidate_cap == 120


def test_prefetch_not_needed_returns_typed_none_without_touching_retrieval() -> None:
    retrieval = _Retrieval(RetrievalExecution(_body()))
    service = MemoryResolveService(cast(RetrievalService, retrieval))

    execution = service.resolve(
        SessionContext(
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ),
        MemoryResolveRequest(
            query="What is 17 plus 25?",
            invocation_mode="PREFETCH_AUTO",
        ),
        "request-none",
    )

    assert retrieval.requests == []
    assert execution.body["status"] == "ABSENT"
    assert execution.body["memory_intent"] == "NOT_NEEDED"
    assert execution.body["requirement"] == "NONE"
    assert execution.body["availability"] == "AVAILABLE"
    assert execution.body["access_trace"]["planned_stage"] == "NONE"


def test_resolve_with_one_state_key_uses_exact_state_view_and_skips_l1() -> None:
    retrieval = _Retrieval(RetrievalExecution(_body()))
    state_views = _StateViews(
        RetrievalExecution(
            {
                "schema_version": "memory-state-view-v0.1",
                "status": "HIT",
                "items": [
                    {
                        "claim_id": "claim-1",
                        "claim_version_id": "version-1",
                        "evidence_ids": ["evidence-1"],
                    }
                ],
                "open_issue_ids": [],
                "evidence_refs": ["evidence-1"],
                "consistency": "CANONICAL_REQUIRED",
                "canonical_position": 9,
                "trace_id": "trace-1",
                "availability": "AVAILABLE",
                "abstention_reason": None,
                "access_trace": {
                    "planned_stage": "EXACT",
                    "structural_cost": {"embedding_calls": 0},
                },
                "resolution": {
                    "addressable": True,
                    "reachable": True,
                    "correctly_resolved": True,
                },
                "request_id": "request-1",
            }
        )
    )
    service = MemoryResolveService(
        cast(RetrievalService, retrieval),
        state_views=cast(MemoryStateViewService, state_views),
    )
    state_key = CanonicalStateAddress(
        subject="project-1",
        predicate="runtime.release.status",
        claim_type="FACT",
    )

    execution = service.resolve(
        SessionContext(
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ),
        MemoryResolveRequest(
            query="Read the current exact state",
            state_keys=[state_key],
            requested_scope={"project_ids": ["milai"]},
            required_authority="ACTION_SAFE",
        ),
        "request-1",
    )

    assert retrieval.requests == []
    assert len(state_views.requests) == 1
    assert state_views.requests[0].state_key == state_key
    assert execution.body["status"] == "HIT"
    assert execution.body["requirement"] == "EXACT"
    assert execution.body["state_view_schema_version"] == "memory-state-view-v0.1"
    assert execution.body["access_trace"]["planned_stage"] == "EXACT"


@pytest.mark.parametrize(
    ("overrides", "status", "availability"),
    [
        (
            {
                "results": [],
                "abstained": True,
                "abstention_reason": "NO_CANDIDATE",
            },
            "ABSENT",
            "AVAILABLE",
        ),
        (
            {
                "results": [],
                "abstained": True,
                "abstention_reason": "CANONICAL_GATE_REJECTED",
            },
            "ABSTAINED",
            "AVAILABLE",
        ),
        (
            {
                "results": [],
                "abstained": True,
                "abstention_reason": "ACCESS_DENIED",
            },
            "DENIED",
            "AVAILABLE",
        ),
        (
            {"open_issue_ids": ["issue-1"]},
            "CONTESTED",
            "DEGRADED",
        ),
        (
            {"degraded_components": ["vector"], "fallback_used": True},
            "PARTIAL",
            "DEGRADED",
        ),
        (
            {
                "results": [],
                "abstained": True,
                "abstention_reason": "CANONICAL_UNAVAILABLE",
                "degraded_components": ["canonical_database"],
                "snapshot": None,
                "retrieval_trace_id": None,
            },
            "UNAVAILABLE",
            "UNAVAILABLE",
        ),
    ],
)
def test_resolve_typed_outcomes_do_not_collapse(
    overrides: dict[str, object], status: str, availability: str
) -> None:
    retrieval = _Retrieval(
        RetrievalExecution(
            _body(**overrides),
            503 if status == "UNAVAILABLE" else 200,
        )
    )
    service = MemoryResolveService(cast(RetrievalService, retrieval))

    execution = service.resolve(
        SessionContext(
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ),
        MemoryResolveRequest(query="Recall the release state"),
        "request-1",
    )

    assert execution.body["status"] == status
    assert execution.body["availability"] == availability
    assert execution.status_code == (503 if status == "UNAVAILABLE" else 200)

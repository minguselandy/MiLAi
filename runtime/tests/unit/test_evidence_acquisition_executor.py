from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
)
from milai.application.evidence_acquisition import EvidenceAcquisitionExecutor
from milai.application.query_planner import QueryPlanner
from milai.domain import RetrievalRequest
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState

REFERENCE = datetime(2026, 8, 28, 8, tzinfo=UTC)
CONTEXT = SessionContext(UUID(int=1), UUID(int=2))


class _Repository:
    def __init__(self, *, answer: bool = True) -> None:
        self.answer = answer
        self.calls = 0

    def search_evidence(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
        self.calls += 1
        if not self.answer:
            return []
        return [
            {
                "evidence_id": "evidence-47",
                "source_ref": "memory://session/s-1/turn/0",
                "subject_id": "s-1",
                "observed_at": REFERENCE.isoformat(),
                "captured_at": REFERENCE.isoformat(),
                "content": "I paid $60 for 5 ceramic mugs.",
                "content_hash": "source-hash",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "revoked_at": None,
                "relevance_score": 1.0,
                "kind": "EVIDENCE_OBSERVATION",
            }
        ]

    def search_evidence_dense(self) -> None:
        pass

    def scan_evidence_range(self) -> None:
        pass

    def hydrate_evidence_adjacency(self) -> None:
        pass

    def exact_candidates(self) -> None:
        pass


class _RangeRepository(_Repository):
    def __init__(self, *, scan_status: str = "COMPLETE") -> None:
        super().__init__(answer=False)
        self.scan_status = scan_status

    def scan_evidence_range(self, *args: object, **kwargs: object) -> dict[str, object]:
        return {
            "status": self.scan_status,
            "scan_axis": "SOURCE_OBSERVED_TIME",
            "source_partition_closed": True,
            "projection_watermark_covered": self.scan_status == "COMPLETE",
            "projection_watermark": 91,
            "target_watermark": 91,
            "source_count": 1,
            "projected_count": 1,
            "returned_count": 1,
            "max_items": 2_000,
            "dead_letter_gap": False,
            "unreadable_evidence_count": 0,
            "items": [
                {
                    "evidence_id": "maya-birth",
                    "source_ref": "memory://session/s1/turn/0",
                    "subject_id": "s1",
                    "observed_at": "2023-01-06T09:00:00+00:00",
                    "captured_at": "2023-01-06T09:00:01+00:00",
                    "content": "My friend Maya welcomed a baby on January 5th.",
                    "speaker": "user",
                    "speaker_source": "STRUCTURED_TURN_METADATA",
                }
            ],
        }


def _inputs(repository: _Repository):  # type: ignore[no-untyped-def]
    query = "How much did I pay per ceramic mug?"
    request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request)
    acquisition_plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    policy = AcquisitionCapabilityPolicy()
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(),
        projection_state=ProjectionState(7, 7, 7, False, False, 7, False),
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
    )
    return request, query_plan, acquisition_plan, policy, capabilities


def test_product_and_shadow_use_identical_official_candidate_and_state_semantics() -> None:
    repository = _Repository()
    request, query_plan, acquisition_plan, policy, capabilities = _inputs(repository)
    executor = EvidenceAcquisitionExecutor(repository)
    product = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="PRODUCT",
        state_epoch=0,
    )
    shadow = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
    )
    assert product.executor_identity == shadow.executor_identity
    assert product.candidates == shadow.candidates
    assert product.bindings == shadow.bindings
    assert product.requirement_state == shadow.requirement_state
    assert product.sufficiency_decision == shadow.sufficiency_decision
    assert product.context_mutation_performed is False
    assert shadow.context_mutation_performed is False
    assert product.canonical_mutation is False


def test_sufficiency_fails_closed_when_requirement_binding_is_missing() -> None:
    repository = _Repository()
    outside_requested_window = datetime(2025, 1, 1, 8, tzinfo=UTC)
    repository.search_evidence = lambda *args, **kwargs: [  # type: ignore[method-assign]
        {
            "evidence_id": "evidence-game",
            "source_ref": "memory://session/s-1/turn/0",
            "subject_id": "s-1",
            "observed_at": outside_requested_window.isoformat(),
            "captured_at": outside_requested_window.isoformat(),
            "content": "I finally beat Cocoon.",
            "content_hash": "source-hash-game",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
            "revoked_at": None,
            "relevance_score": 1.0,
            "kind": "EVIDENCE_OBSERVATION",
        }
    ]
    query = "What game did I finally beat last weekend?"
    request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request)
    acquisition_plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    policy = AcquisitionCapabilityPolicy()
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(),
        projection_state=ProjectionState(7, 7, 7, False, False, 7, False),
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
        event_occurrence_range=(
            acquisition_plan.global_constraints.event_occurrence_range
        ),
    )

    execution = EvidenceAcquisitionExecutor(repository).execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="PRODUCT",
        state_epoch=0,
    )

    assert execution.requirement_state.missing_requirement_ids
    assert execution.sufficiency_decision.status != "COMPLETE"
    assert execution.sufficiency_decision.missing_slots == (
        execution.requirement_state.missing_requirement_ids
    )
    assert execution.sufficiency_reason == "ACQUISITION_INTERMEDIATE_DECISION_DEFERRED"


def test_extra_pass_recomputes_binding_state_but_defers_final_sufficiency() -> None:
    repository = _Repository(answer=False)
    request, query_plan, acquisition_plan, policy, capabilities = _inputs(repository)
    executor = EvidenceAcquisitionExecutor(repository)
    baseline = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
    )
    assert baseline.requirement_state.missing_requirement_ids
    actions = feasible_acquisition_actions(
        baseline.requirement_state,
        capabilities,
        policy,
        remaining_candidates=12,
    )
    action = next(item for item in actions if item.channel == "FTS_RAW")
    repository.answer = True
    recovered = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=1,
        action=action,
        current_requirement_state=baseline.requirement_state,
        existing_results=baseline.results,
    )
    assert recovered.candidates
    assert recovered.bindings
    assert recovered.requirement_state.state_epoch == 1
    assert recovered.requirement_state.satisfied_requirement_ids
    assert recovered.sufficiency_decision.status == "PARTIAL"
    assert recovered.sufficiency_reason == "ACQUISITION_INTERMEDIATE_DECISION_DEFERRED"
    assert recovered.context_mutation_performed is False


def test_bounded_scan_preserves_exact_repository_proof_for_requirement_state() -> None:
    repository = _RangeRepository()
    query = "How many babies were born to friends and family in the last few months?"
    request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope={"project_ids": ["milai"]},
        as_of=datetime(2023, 3, 27, 12, tzinfo=UTC),
        system_as_of=datetime(2023, 3, 27, 12, tzinfo=UTC),
    )
    event_plan = QueryPlanner().plan(request)
    query_ir = event_plan.memory_query_ir
    assert query_ir is not None
    temporal = query_ir.constraints.normalized_temporal
    assert temporal is not None
    source_temporal = temporal.model_copy(update={"time_axis": "SOURCE_OBSERVED_TIME"})
    source_ir = query_ir.model_copy(
        update={
            "constraints": query_ir.constraints.model_copy(
                update={"normalized_temporal": source_temporal}
            ),
            "requirements": [
                item.model_copy(update={"temporal_constraints": source_temporal})
                for item in query_ir.requirements
            ],
        }
    )
    query_plan = event_plan.model_copy(
        update={
            "memory_query_ir": source_ir,
            "operator_arguments": {
                **event_plan.operator_arguments,
                "time_axis": "SOURCE_OBSERVED_TIME",
            },
        }
    )
    acquisition_plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    policy = AcquisitionCapabilityPolicy()
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(),
        projection_state=ProjectionState(91, 91, 91, False, False, 91, False),
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
    )
    execution = EvidenceAcquisitionExecutor(repository).execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
    )

    proof = execution.bounded_range_scan_proof
    assert proof is not None
    assert proof.schema_version == "bounded-range-scan-proof-v0.2"
    assert proof.status == "PARTIAL"
    assert proof.closure_complete is False
    assert proof.query_closure.event_time_interval.basis == "SOURCE_OBSERVED_PROXY"
    assert proof.projection_closure.projection_watermark == 91
    assert proof.projection_closure.target_watermark == 91
    assert proof.event_set_closure.unresolved_event_count == 1
    assert execution.derived_result is not None
    assert execution.derived_result["completeness"]["projection_position"] == 91
    assert execution.sufficiency_decision.proof.projection_watermark == 91
    assert all(
        item.proof_status == "SATISFIED"
        for item in execution.requirement_state.requirements
    )

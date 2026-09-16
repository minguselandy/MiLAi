from __future__ import annotations

import pytest
from pydantic import ValidationError

from milai.application.decision_engine import _count_requires_range_proof
from milai.application.query_execution import derive_query_execution_plan_v01
from milai.domain.bound_operands import (
    BoundOperandV01,
    BoundValueV01,
    RoleIndexedBoundOperandsV01,
    build_role_indexed_bound_operands_v01,
)
from milai.domain.query_execution import CompletionMode, CountSemantics
from milai.domain.query_task_contract import (
    CollectionClosureBasis,
    CollectionContractV01,
    CollectionKind,
    EvidenceRole,
    EvidenceTopology,
    OutputContractV01,
    OutputShape,
    OutputValueType,
    ParseDisposition,
    ProofObligation,
    QueryOperation,
    QueryTaskContractV01,
    RequirementValueType,
    RetrievalHintsV01,
    TypedRequirementV01,
    ValueContractV01,
)
from milai.domain.semantic_query import (
    EvidenceRequirementV02,
    MemoryPlannerTrace,
    MemoryQueryIRV02,
    MemoryQueryStep,
    RequirementCardinalityV02,
)


def _bound_operand(
    *,
    interpretation_id: str,
    normalized_value: int,
) -> BoundOperandV01:
    return BoundOperandV01(
        requirement_id="r-members",
        role_key="members",
        evidence_role=EvidenceRole.COLLECTION_MEMBER,
        value=BoundValueV01(
            value_type=RequirementValueType.INTEGER,
            normalized_value=normalized_value,
            unit="item",
        ),
        binding_ref=f"binding:{interpretation_id}",
        interpretation_id=interpretation_id,
        span_id="span-shared",
        source_evidence_id="evidence-shared",
        source_turn_ref="memory://session/s-1/turn/4",
    )


def _scalar_count_contract() -> QueryTaskContractV01:
    return QueryTaskContractV01(
        parse_disposition=ParseDisposition.EXECUTABLE,
        operation=QueryOperation.COUNT,
        output=OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.INTEGER,
            unit="item",
        ),
        evidence_topology=EvidenceTopology.SINGLE_ITEM,
        requirements=(
            TypedRequirementV01(
                requirement_id="r-count-fact",
                role_key="count_value",
                evidence_role=EvidenceRole.ANSWER_VALUE,
                relation="has_count",
                value=ValueContractV01(value_type=RequirementValueType.INTEGER),
                collection=CollectionContractV01(kind=CollectionKind.SCALAR_FACT),
            ),
        ),
        proof_obligations=(
            ProofObligation.GROUNDED_RELATION,
            ProofObligation.ALL_REQUIRED_ROLES,
        ),
        retrieval_hints=(
            RetrievalHintsV01(
                requirement_id="r-count-fact",
                surface_terms=("bandwidth",),
            ),
        ),
        reason_code="DIRECT_SCALAR_COUNT_FACT",
    )


def _member_count_contract() -> QueryTaskContractV01:
    return QueryTaskContractV01(
        parse_disposition=ParseDisposition.EXECUTABLE,
        operation=QueryOperation.COUNT,
        output=OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.INTEGER,
            unit="event",
        ),
        evidence_topology=EvidenceTopology.MEMBER_SET,
        requirements=(
            TypedRequirementV01(
                requirement_id="r-event-members",
                role_key="event_members",
                evidence_role=EvidenceRole.COLLECTION_MEMBER,
                relation="attended",
                collection=CollectionContractV01(
                    kind=CollectionKind.MEMBER_SET,
                    minimum=0,
                    maximum=None,
                    distinct=True,
                    identity_key="event_identity",
                    closure_basis=CollectionClosureBasis.SOURCE_PARTITION,
                ),
            ),
        ),
        proof_obligations=(
            ProofObligation.ALL_REQUIRED_ROLES,
            ProofObligation.PARTITION_CLOSURE,
            ProofObligation.IDENTITY_DEDUP,
        ),
        reason_code="COUNT_DISTINCT_MEMBERS",
    )


def _legacy_count_ir(completeness: str) -> MemoryQueryIRV02:
    return MemoryQueryIRV02(
        mode="COMPOSE",
        answer_shape="SCALAR",
        requirements=[
            EvidenceRequirementV02(
                slot_id="COUNT_VALUE",
                interpretation_kind="QUANTITY",
                predicate_constraints=["integer_count"],
                value_type="NUMBER",
                cardinality=RequirementCardinalityV02(minimum=1, maximum=1),
            )
        ],
        steps=[
            MemoryQueryStep(
                kind="RETRIEVE",
                outputs=["COUNT_CANDIDATES"],
                constraints={"operator_family": "COUNT"},
            ),
            MemoryQueryStep(
                kind="BIND_SLOT",
                inputs=["COUNT_CANDIDATES"],
                outputs=["COUNT_VALUE"],
            ),
        ],
        completeness=completeness,  # type: ignore[arg-type]
        planner_trace=MemoryPlannerTrace(
            source="DETERMINISTIC",
            compiler_version="test-count-semantics-v0.1",
            auxiliary_model_calls=0,
            reason_code="TEST_COUNT_SEMANTICS",
        ),
    )


def test_role_index_keeps_distinct_values_from_one_evidence_record() -> None:
    first = _bound_operand(interpretation_id="i-first", normalized_value=1)
    second = _bound_operand(interpretation_id="i-second", normalized_value=2)

    index = build_role_indexed_bound_operands_v01([second, first])

    assert [item.value.normalized_value for item in index.for_role("members")] == [
        1,
        2,
    ]
    assert index.covered_role_keys == ("members",)
    assert index.missing_role_keys(("members", "range_proof")) == ("range_proof",)


def test_role_index_rejects_only_an_exact_semantic_duplicate() -> None:
    operand = _bound_operand(interpretation_id="i-first", normalized_value=1)

    with pytest.raises(ValidationError, match="unique semantic identities"):
        RoleIndexedBoundOperandsV01(operands=(operand, operand))


def test_scalar_count_plan_does_not_invent_member_set_proofs() -> None:
    contract = _scalar_count_contract()

    plan = derive_query_execution_plan_v01(contract)

    assert plan.source_contract_digest == contract.contract_digest
    assert plan.operator.count_semantics == CountSemantics.SCALAR_FACT
    assert plan.operator.operand_role_keys == ("count_value",)
    assert plan.completion.mode == CompletionMode.ALL_REQUIRED_ROLES
    assert ProofObligation.RANGE_CLOSURE not in plan.completion.proof_obligations
    assert ProofObligation.IDENTITY_DEDUP not in plan.completion.proof_obligations
    assert plan.acquisition.targets[0].retrieval_hints == contract.retrieval_hints[0]


def test_member_count_plan_preserves_declared_collection_closure() -> None:
    contract = _member_count_contract()

    plan = derive_query_execution_plan_v01(contract)

    assert plan.operator.count_semantics == CountSemantics.MEMBER_SET
    assert plan.completion.mode == CompletionMode.MEMBER_SET_CLOSED
    assert plan.completion.required_role_keys == ("event_members",)
    assert set(plan.completion.proof_obligations) == {
        ProofObligation.ALL_REQUIRED_ROLES,
        ProofObligation.PARTITION_CLOSURE,
        ProofObligation.IDENTITY_DEDUP,
    }


def test_legacy_decision_engine_distinguishes_scalar_and_member_count() -> None:
    scalar = _legacy_count_ir("ALL_REQUIRED_BINDINGS")
    members = _legacy_count_ir("ALL_MATCHES_IN_RANGE")

    assert _count_requires_range_proof(scalar, "COUNT_DISTINCT") is False
    assert _count_requires_range_proof(members, "COUNT_DISTINCT") is True
    assert _count_requires_range_proof(None, "TEMPORAL_COUNT_DISTINCT") is True


def test_execution_plan_is_query_text_independent_and_deterministic() -> None:
    contract = _member_count_contract()

    first = derive_query_execution_plan_v01(contract)
    second = derive_query_execution_plan_v01(contract)

    assert first == second
    assert "query" not in first.model_dump(mode="json")

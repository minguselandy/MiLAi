from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from milai.domain.query_task_contract import (
    CollectionClosureBasis,
    CollectionContractV01,
    CollectionKind,
    EvidenceRole,
    EvidenceSpeaker,
    EvidenceTopology,
    OutputContractV01,
    OutputShape,
    OutputValueType,
    ParseDisposition,
    ParticipantConstraintV01,
    ParticipantRole,
    ProofObligation,
    QueryOperation,
    QueryTaskContractV01,
    RequirementValueType,
    RetrievalHintsV01,
    SourceConstraintProvenance,
    SourceContractV01,
    SubjectContractV01,
    TemporalAxis,
    TemporalBoundary,
    TemporalContractV01,
    TemporalKind,
    TypedRequirementV01,
    ValueContractV01,
)


def _requirement(
    requirement_id: str = "answer",
    *,
    role_key: str = "answer",
    evidence_role: EvidenceRole = EvidenceRole.ANSWER_VALUE,
    collection: CollectionContractV01 | None = None,
    temporal: TemporalContractV01 | None = None,
    source: SourceContractV01 | None = None,
) -> TypedRequirementV01:
    return TypedRequirementV01(
        requirement_id=requirement_id,
        role_key=role_key,
        evidence_role=evidence_role,
        subject=SubjectContractV01(identity="user"),
        relation="internet_plan_speed",
        participants=(
            ParticipantConstraintV01(role=ParticipantRole.EXPERIENCER, identity="user"),
        ),
        value=ValueContractV01(value_type=RequirementValueType.TEXT),
        temporal=temporal or TemporalContractV01(),
        source=source or SourceContractV01(),
        collection=collection or CollectionContractV01(),
    )


def _lookup_contract(**overrides: object) -> QueryTaskContractV01:
    values: dict[str, object] = {
        "parse_disposition": ParseDisposition.EXECUTABLE,
        "operation": QueryOperation.LOOKUP,
        "output": OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.TEXT,
        ),
        "evidence_topology": EvidenceTopology.SINGLE_ITEM,
        "requirements": (_requirement(),),
        "proof_obligations": (ProofObligation.GROUNDED_RELATION,),
        "retrieval_hints": (
            RetrievalHintsV01(
                requirement_id="answer",
                phrases=("internet plan",),
                surface_terms=("speed",),
                language_tags=("en",),
            ),
        ),
        "reason_code": "DIRECT_RELATION_LOOKUP",
    }
    values.update(overrides)
    return QueryTaskContractV01.model_validate(values)


def test_lookup_contract_has_stable_canonical_identity() -> None:
    first = _lookup_contract()
    second = QueryTaskContractV01.model_validate_json(first.model_dump_json())

    assert first.canonical_json() == second.canonical_json()
    assert first.contract_digest == second.contract_digest
    assert len(first.contract_digest) == 64
    assert '"surface_terms":["speed"]' in first.canonical_json()


def test_semantic_participant_and_evidence_source_are_independent() -> None:
    assistant_source = SourceContractV01(
        preferred_speakers=(EvidenceSpeaker.ASSISTANT,),
        provenance=SourceConstraintProvenance.SEMANTIC_INTERPRETATION,
    )
    requirement = _requirement(source=assistant_source)

    assert requirement.participants[0].identity == "user"
    assert requirement.source.preferred_speakers == (EvidenceSpeaker.ASSISTANT,)


def test_hard_source_restriction_requires_explicit_query_provenance() -> None:
    with pytest.raises(ValidationError, match="explicit-query provenance"):
        SourceContractV01(
            allowed_speakers=(EvidenceSpeaker.ASSISTANT,),
            provenance=SourceConstraintProvenance.SEMANTIC_INTERPRETATION,
        )


def test_best_effort_recall_keeps_grounding_but_carries_no_strict_completion() -> None:
    contract = _lookup_contract(parse_disposition=ParseDisposition.BEST_EFFORT_RECALL)

    assert contract.proof_obligations == (ProofObligation.GROUNDED_RELATION,)

    with pytest.raises(ValidationError, match="without strict proof"):
        _lookup_contract(
            parse_disposition=ParseDisposition.BEST_EFFORT_RECALL,
            proof_obligations=(
                ProofObligation.GROUNDED_RELATION,
                ProofObligation.ALL_REQUIRED_ROLES,
            ),
        )


def test_unsupported_query_cannot_smuggle_executable_semantics() -> None:
    unsupported = QueryTaskContractV01(
        parse_disposition=ParseDisposition.UNSUPPORTED,
        reason_code="NO_SUPPORTED_INTERPRETATION",
    )

    assert unsupported.operation is None
    with pytest.raises(ValidationError, match="cannot carry executable semantics"):
        QueryTaskContractV01(
            parse_disposition=ParseDisposition.UNSUPPORTED,
            operation=QueryOperation.LOOKUP,
            reason_code="INVALID",
        )


def test_scalar_count_fact_does_not_require_range_closure() -> None:
    count_fact = _requirement(
        evidence_role=EvidenceRole.ANSWER_VALUE,
        collection=CollectionContractV01(kind=CollectionKind.SCALAR_FACT),
    )
    contract = QueryTaskContractV01(
        parse_disposition=ParseDisposition.EXECUTABLE,
        operation=QueryOperation.COUNT,
        output=OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.INTEGER,
        ),
        evidence_topology=EvidenceTopology.SINGLE_ITEM,
        requirements=(count_fact,),
        proof_obligations=(ProofObligation.GROUNDED_RELATION,),
        reason_code="STORED_SCALAR_COUNT",
    )

    assert ProofObligation.RANGE_CLOSURE not in contract.proof_obligations


def test_member_count_supports_zero_but_requires_dedup_and_universe_closure() -> None:
    member = _requirement(
        requirement_id="members",
        role_key="members",
        evidence_role=EvidenceRole.COLLECTION_MEMBER,
        collection=CollectionContractV01(
            kind=CollectionKind.MEMBER_SET,
            minimum=0,
            maximum=None,
            distinct=True,
            identity_key="event_identity",
            closure_basis=CollectionClosureBasis.QUERY_RANGE,
        ),
    )
    contract = QueryTaskContractV01(
        parse_disposition=ParseDisposition.EXECUTABLE,
        operation=QueryOperation.COUNT,
        output=OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.INTEGER,
        ),
        evidence_topology=EvidenceTopology.MEMBER_SET,
        requirements=(member,),
        proof_obligations=(
            ProofObligation.RANGE_CLOSURE,
            ProofObligation.IDENTITY_DEDUP,
        ),
        reason_code="COUNT_RANGE_MEMBERS",
    )

    assert contract.requirements[0].collection.minimum == 0

    with pytest.raises(ValidationError, match="identity/dedup proof"):
        QueryTaskContractV01(
            parse_disposition=ParseDisposition.EXECUTABLE,
            operation=QueryOperation.COUNT,
            output=contract.output,
            evidence_topology=EvidenceTopology.MEMBER_SET,
            requirements=(member,),
            proof_obligations=(ProofObligation.RANGE_CLOSURE,),
            reason_code="MISSING_DEDUP",
        )


def test_compare_requires_independent_operand_roles() -> None:
    left = _requirement(
        "left",
        role_key="left",
        evidence_role=EvidenceRole.LEFT_OPERAND,
    )
    right = _requirement(
        "right",
        role_key="right",
        evidence_role=EvidenceRole.RIGHT_OPERAND,
    )
    contract = QueryTaskContractV01(
        parse_disposition=ParseDisposition.EXECUTABLE,
        operation=QueryOperation.COMPARE,
        output=OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.TEXT,
        ),
        evidence_topology=EvidenceTopology.MULTI_OPERAND,
        requirements=(left, right),
        proof_obligations=(ProofObligation.ALL_REQUIRED_ROLES,),
        reason_code="COMPARE_TWO_OPERANDS",
    )

    assert [item.role_key for item in contract.requirements] == ["left", "right"]

    with pytest.raises(ValidationError, match="RIGHT_OPERAND"):
        QueryTaskContractV01(
            parse_disposition=ParseDisposition.EXECUTABLE,
            operation=QueryOperation.COMPARE,
            output=contract.output,
            evidence_topology=EvidenceTopology.MULTI_OPERAND,
            requirements=(left,),
            proof_obligations=(ProofObligation.ALL_REQUIRED_ROLES,),
            reason_code="MISSING_RIGHT",
        )


def test_temporal_range_and_relation_have_distinct_typed_shapes() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    end = datetime(2026, 8, 1, tzinfo=UTC)
    bounded = TemporalContractV01(
        kind=TemporalKind.RANGE,
        axis=TemporalAxis.EVENT_OCCURRENCE_TIME,
        start=start,
        end=end,
        boundary=TemporalBoundary.CLOSED_OPEN,
        timezone="America/New_York",
    )
    relation = TemporalContractV01(
        kind=TemporalKind.RELATION,
        axis=TemporalAxis.EVENT_OCCURRENCE_TIME,
        related_requirement_ids=("event-a", "event-b"),
    )

    assert bounded.start == start
    assert relation.related_requirement_ids == ("event-a", "event-b")

    with pytest.raises(ValidationError, match="timezone offset"):
        TemporalContractV01(
            kind=TemporalKind.RANGE,
            axis=TemporalAxis.EVENT_OCCURRENCE_TIME,
            start=datetime(2026, 7, 1),
            end=end,
            boundary=TemporalBoundary.CLOSED_OPEN,
        )


def test_contract_rejects_duplicate_requirements_and_orphan_hints() -> None:
    answer = _requirement()
    with pytest.raises(ValidationError, match="requirement identities must be unique"):
        _lookup_contract(requirements=(answer, answer))

    with pytest.raises(ValidationError, match="existing requirements"):
        _lookup_contract(
            retrieval_hints=(RetrievalHintsV01(requirement_id="unknown"),),
        )


def test_version_diff_requires_both_states_transition_and_chain_proof() -> None:
    requirements = (
        _requirement("old", role_key="old", evidence_role=EvidenceRole.PRIOR_STATE),
        _requirement("new", role_key="new", evidence_role=EvidenceRole.CURRENT_STATE),
        _requirement("change", role_key="change", evidence_role=EvidenceRole.TRANSITION),
    )
    contract = QueryTaskContractV01(
        parse_disposition=ParseDisposition.EXECUTABLE,
        operation=QueryOperation.VERSION_DIFF,
        output=OutputContractV01(
            shape=OutputShape.EXPLANATION,
            value_type=OutputValueType.EXPLANATION,
        ),
        evidence_topology=EvidenceTopology.VERSION_CHAIN,
        requirements=requirements,
        proof_obligations=(ProofObligation.VERSION_CHAIN,),
        reason_code="STATE_VERSION_DIFF",
    )

    assert contract.operation == QueryOperation.VERSION_DIFF


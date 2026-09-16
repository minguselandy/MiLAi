from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from milai.domain.acquisition_capability import FeasibleAcquisitionAction
from milai.domain.requirement_acquisition import (
    PlannedRequirementAcquisitionActionV01,
    RequirementAcquisitionAggregateBudgetV01,
    RequirementAcquisitionPlanLineageV01,
    RequirementAcquisitionPlanV01,
    RequirementCompleteRetrievalPolicyV01,
    TargetRequirementV01,
    build_requirement_acquisition_plan,
    default_requirement_complete_retrieval_policy,
    validate_requirement_acquisition_plan,
)
from milai.domain.requirement_state import (
    RequirementCardinalityState,
    RequirementDisposition,
    RequirementState,
    canonical_sha256,
)
from milai.domain.temporal_proof import (
    BoundedRangeAccessClosureV02,
    BoundedRangeDedupClosureV02,
    BoundedRangeEventSetClosureV02,
    BoundedRangeProjectionClosureV02,
    BoundedRangeQueryClosureV02,
    BoundedRangeScanClosureV02,
    BoundedRangeScanProofV02,
    BoundedRangeSnapshotClosureV02,
    EventTimeBasisV02,
    EventTimeIntervalV02,
    EventTimePrecisionV02,
    build_bounded_range_scan_proof_v02,
    build_event_identity_v01,
    build_event_time_interval_v02,
    classify_range_membership,
    deduplicate_event_identities,
    read_legacy_bounded_range_scan_proof_v01,
)
from milai.domain.typed_answer import (
    TypedAnswerContractV01,
    TypedAnswerLineageV01,
    build_typed_answer_decision_v01,
    validate_reader_answer_v01,
)

REFERENCE = datetime(2026, 8, 29, 12, tzinfo=UTC)


def _state(*, epoch: int = 0) -> RequirementState:
    disposition = RequirementDisposition(
        requirement_id="MATCHING_EVENTS_IN_RANGE",
        kind="RANGE_COMPLETENESS",
        status="COMPLETENESS_PROOF_MISSING",
        required_cardinality=RequirementCardinalityState(
            minimum=0,
            maximum=None,
            distinct=True,
        ),
        observed_cardinality=0,
        proof_status="MISSING",
    )
    material = {
        "schema_version": "requirement-state-v0.1",
        "query_ir_digest": "1" * 64,
        "acquisition_plan_digest": "2" * 64,
        "acquisition_capability_digest": "3" * 64,
        "candidate_snapshot_digest": "4" * 64,
        "binding_digest": "5" * 64,
        "sufficiency_decision_digest": "6" * 64,
        "sufficiency_policy_version": "test-v1",
        "state_epoch": epoch,
        "requirements": [disposition.model_dump(mode="json")],
        "lifetime": "MEMORY_RESOLVE",
        "canonical": False,
        "canonical_mutation": False,
    }
    return RequirementState.model_validate(
        {"state_digest": canonical_sha256(material), **material}
    )


def _feasible(state: RequirementState, *, cap: int = 8) -> FeasibleAcquisitionAction:
    material = {
        "schema_version": "feasible-acquisition-action-v0.1",
        "capability_id": "channel:TEMPORAL_EVENT",
        "capability_digest": state.acquisition_capability_digest,
        "target_requirement_id": "MATCHING_EVENTS_IN_RANGE",
        "requirement_state_digest": state.state_digest,
        "requirement_state_epoch": state.state_epoch,
        "policy_digest": "7" * 64,
        "channel": "TEMPORAL_EVENT",
        "bounded_cost": {
            "acquisition_passes": 1,
            "candidate_count": cap,
            "model_calls": 0,
        },
    }
    return FeasibleAcquisitionAction.model_validate(
        {"action_digest": canonical_sha256(material), **material}
    )


def _plan(
    state: RequirementState,
    feasible: FeasibleAcquisitionAction,
    *,
    candidate_cap: int | None = None,
) -> tuple[RequirementAcquisitionPlanV01, RequirementCompleteRetrievalPolicyV01]:
    policy = default_requirement_complete_retrieval_policy()
    lineage = RequirementAcquisitionPlanLineageV01(
        query_ir_digest=state.query_ir_digest,
        requirement_state_digest=state.state_digest,
        requirement_state_epoch=state.state_epoch,
        acquisition_capability_digest=state.acquisition_capability_digest,
        selection_policy_digest=policy.policy_digest,
        policy_digest=feasible.policy_digest,
        snapshot_identity="8" * 64,
        access_snapshot_identity="9" * 64,
    )
    cap = candidate_cap if candidate_cap is not None else feasible.bounded_cost["candidate_count"]
    action = PlannedRequirementAcquisitionActionV01(
        action_digest=feasible.action_digest,
        target_requirement_id=feasible.target_requirement_id,
        action_role="PROOF_CLOSURE",
        capability_id=feasible.capability_id,
        channel=feasible.channel,
        candidate_cap=cap,
        bounded_cost={
            "acquisition_passes": 1,
            "candidate_count": cap,
            "model_calls": 0,
        },
        reason_code="ALL_MATCHES_IN_RANGE_REQUIRES_PROOF",
    )
    target = TargetRequirementV01(
        requirement_id="MATCHING_EVENTS_IN_RANGE",
        kind="RANGE_COMPLETENESS",
        status="COMPLETENESS_PROOF_MISSING",
        missing_evidence_roles=["EVENT_OCCURRENCE"],
        proof_obligations=["ALL_MATCHES_IN_RANGE"],
    )
    aggregate = RequirementAcquisitionAggregateBudgetV01(
        max_repository_calls=2,
        planned_repository_calls=1,
        max_hydrated_candidates=120,
        planned_candidate_cap_sum=cap,
    )
    return (
        build_requirement_acquisition_plan(
            lineage=lineage,
            target_requirements=[target],
            actions=[action],
            aggregate_budget=aggregate,
        ),
        policy,
    )


def test_dg25_plan_accepts_one_fresh_exact_feasible_action() -> None:
    state = _state()
    feasible = _feasible(state)
    plan, policy = _plan(state, feasible)

    validation = validate_requirement_acquisition_plan(
        plan,
        requirement_state=state,
        feasible_actions=[feasible],
        policy=policy,
        current_snapshot_identity="8" * 64,
        current_access_snapshot_identity="9" * 64,
        baseline_candidate_caps={feasible.action_digest: 8},
    )

    assert validation.accepted is True
    assert validation.reason_codes == ["PLAN_FEASIBLE"]
    assert policy.default_enabled is False
    assert policy.model_calls == policy.automatic_retries == 0


def test_dg25_plan_rejects_stale_state_and_unregistered_action() -> None:
    state = _state()
    feasible = _feasible(state)
    plan, policy = _plan(state, feasible)
    fresh_state = _state(epoch=1)

    validation = validate_requirement_acquisition_plan(
        plan,
        requirement_state=fresh_state,
        feasible_actions=[],
        policy=policy,
        current_snapshot_identity="8" * 64,
        current_access_snapshot_identity="9" * 64,
    )

    assert validation.accepted is False
    assert "STALE_REQUIREMENT_STATE" in validation.reason_codes
    assert "UNREGISTERED_ACTION" in validation.reason_codes


def test_dg25_plan_requires_proof_action_and_exact_baseline_cap() -> None:
    state = _state()
    feasible = _feasible(state, cap=7)
    plan, policy = _plan(state, feasible)

    validation = validate_requirement_acquisition_plan(
        plan,
        requirement_state=state,
        feasible_actions=[feasible],
        policy=policy,
        current_snapshot_identity="8" * 64,
        current_access_snapshot_identity="9" * 64,
        baseline_candidate_caps={feasible.action_digest: 8},
    )
    assert validation.reason_codes == ["BASELINE_ACTION_CAP_CHANGED"]

    payload = plan.model_dump(mode="json", exclude={"plan_digest"})
    payload["actions"][0]["action_role"] = "EVIDENCE_DISCOVERY"
    payload["plan_digest"] = canonical_sha256(payload)
    with pytest.raises(ValidationError, match="requires a proof-closing action"):
        type(plan).model_validate(payload)


def _interval(
    start: datetime,
    end: datetime,
    *,
    basis: EventTimeBasisV02 = "EXPLICIT_CALENDAR",
    precision: EventTimePrecisionV02 = "DAY",
    anchor_evidence_ids: tuple[str, ...] = (),
    grounded_span_ids: tuple[str, ...] = (),
    ambiguity_reasons: tuple[str, ...] = (),
) -> EventTimeIntervalV02:
    return build_event_time_interval_v02(
        interval_start=start,
        interval_end_exclusive=end,
        timezone="UTC",
        precision=precision,
        basis=basis,
        anchor_evidence_ids=anchor_evidence_ids,
        grounded_span_ids=grounded_span_ids,
        ambiguity_reasons=ambiguity_reasons,
    )


def test_dg25_interval_membership_is_closed_open_and_never_guesses_overlap() -> None:
    query = _interval(REFERENCE, REFERENCE + timedelta(days=7), precision="WEEK")
    inside = _interval(REFERENCE + timedelta(days=1), REFERENCE + timedelta(days=2))
    outside = _interval(REFERENCE + timedelta(days=7), REFERENCE + timedelta(days=8))
    overlap = _interval(REFERENCE - timedelta(days=1), REFERENCE + timedelta(days=1))

    assert classify_range_membership(inside, query) == "IN_RANGE"
    assert classify_range_membership(outside, query) == "OUT_OF_RANGE"
    assert classify_range_membership(overlap, query) == "AMBIGUOUS_RANGE_MEMBERSHIP"
    assert classify_range_membership(None, query) == "EVENT_TIME_UNRESOLVED"


def test_dg25_event_identity_deduplicates_repeats_but_preserves_twins() -> None:
    interval = _interval(REFERENCE, REFERENCE + timedelta(days=1))
    first = build_event_identity_v01(
        event_type="BIRTH",
        actor_identity="aunt",
        object_or_participant_identity="ava",
        occurrence_interval_digest=interval.interval_digest,
        source_evidence_ids=["e-1"],
        identity_policy_version="event-id-v1",
    )
    repeat = build_event_identity_v01(
        event_type="BIRTH",
        actor_identity="aunt",
        object_or_participant_identity="ava",
        occurrence_interval_digest=interval.interval_digest,
        source_evidence_ids=["e-2"],
        identity_policy_version="event-id-v1",
        disposition="DUPLICATE_OF",
    )
    twin = build_event_identity_v01(
        event_type="BIRTH",
        actor_identity="aunt",
        object_or_participant_identity="lily",
        occurrence_interval_digest=interval.interval_digest,
        source_evidence_ids=["e-1"],
        identity_policy_version="event-id-v1",
    )

    dedup = deduplicate_event_identities([first, repeat, twin])

    assert dedup.dedup_complete is True
    assert len(dedup.distinct_event_identity_digests) == 2
    assert dedup.duplicate_groups[first.event_identity_digest] == ["e-1", "e-2"]


def _proof(
    *,
    proxy: bool = False,
    max_items_hit: bool = False,
) -> BoundedRangeScanProofV02:
    interval = _interval(
        REFERENCE,
        REFERENCE + timedelta(days=7),
        basis="SOURCE_OBSERVED_PROXY" if proxy else "EXPLICIT_CALENDAR",
        precision="WEEK",
        ambiguity_reasons=("EVENT_TIME_NOT_GROUNDED",) if proxy else (),
    )
    return build_bounded_range_scan_proof_v02(
        query_closure=BoundedRangeQueryClosureV02(
            query_ir_digest="1" * 64,
            requirement_state_digest="2" * 64,
            event_time_interval=interval,
            timezone="UTC",
        ),
        snapshot_closure=BoundedRangeSnapshotClosureV02(
            transaction_snapshot_identity="3" * 64,
            source_partition_snapshot_identity="4" * 64,
            access_snapshot_identity="5" * 64,
            revocation_snapshot_identity="6" * 64,
            snapshot_stable=True,
        ),
        scan_closure=BoundedRangeScanClosureV02(
            source_partition_closed=True,
            range_scan_complete=True,
            max_items=2_000,
            max_items_hit=max_items_hit,
            unreadable_source_count=0,
        ),
        projection_closure=BoundedRangeProjectionClosureV02(
            projection_version="temporal-v1",
            temporal_normalizer_version="normalizer-v2",
            target_watermark=10,
            projection_watermark=10,
            projection_watermark_covered=True,
            dead_letter_gap=False,
            unprojected_source_count=0,
            raw_fallback_closed=False,
        ),
        event_set_closure=BoundedRangeEventSetClosureV02(
            candidate_event_count=2,
            in_range_event_count=2,
            out_of_range_event_count=0,
            ambiguous_time_count=0,
            unresolved_event_count=0,
            event_identity_policy_version="event-id-v1",
        ),
        dedup_closure=BoundedRangeDedupClosureV02(
            dedup_policy_version="event-id-v1",
            duplicate_group_count=0,
            unresolved_duplicate_group_count=0,
            distinct_event_count=2,
            dedup_complete=True,
        ),
        access_closure=BoundedRangeAccessClosureV02(
            policy_digest="7" * 64,
            unreadable_evidence_count=0,
            access_snapshot_valid=True,
        ),
    )


def test_dg25_proof_complete_requires_every_closure_and_event_time_axis() -> None:
    assert _proof().status == "COMPLETE"
    assert _proof(max_items_hit=True).status == "PARTIAL"
    assert _proof(proxy=True).status == "PARTIAL"


def test_dg25_legacy_range_proof_remains_readable() -> None:
    legacy = read_legacy_bounded_range_scan_proof_v01(
        {
            "status": "PARTIAL",
            "scan_axis": "SOURCE_OBSERVED_TIME",
            "source_partition_closed": True,
            "projection_watermark_covered": False,
            "projection_watermark": 7,
            "target_watermark": 8,
            "source_count": 4,
            "projected_count": 3,
            "returned_count": 4,
            "max_items": 2_000,
            "dead_letter_gap": False,
            "unreadable_evidence_count": 0,
        }
    )
    assert legacy.scan_axis == "SOURCE_OBSERVED_TIME"
    assert legacy.status == "PARTIAL"


def _answer_lineage() -> TypedAnswerLineageV01:
    return TypedAnswerLineageV01(
        query_ir_digest="1" * 64,
        requirement_state_digest="2" * 64,
        sufficiency_decision_digest="3" * 64,
        operator_result_digest="4" * 64,
        proof_digest="5" * 64,
        evidence_set_digest="6" * 64,
    )


def test_dg25_deterministic_answer_cannot_be_delegated_to_reader() -> None:
    contract = TypedAnswerContractV01(
        answer_type="INTEGER",
        normalized_value=4,
        unit="events",
        allowed_surface_variants=["4", "four"],
        allowed_evidence_refs=["e-1"],
    )
    decision = build_typed_answer_decision_v01(
        lineage=_answer_lineage(),
        runtime_status="COMPLETE",
        answer_contract=contract,
        rendering_route="DETERMINISTIC_FORMATTER",
    )
    assert decision.rendering_route == "DETERMINISTIC_FORMATTER"
    with pytest.raises(ValidationError, match="cannot be delegated"):
        build_typed_answer_decision_v01(
            lineage=_answer_lineage(),
            runtime_status="COMPLETE",
            answer_contract=contract,
            rendering_route="CONSTRAINED_READER",
        )


def test_dg25_reader_conformance_rejects_value_unit_json_and_citation_drift() -> None:
    contract = TypedAnswerContractV01(
        answer_type="EXPLANATION",
        normalized_value="because of prior evidence",
        unit=None,
        allowed_evidence_refs=["e-1"],
    )
    decision = build_typed_answer_decision_v01(
        lineage=_answer_lineage(),
        runtime_status="COMPLETE",
        answer_contract=contract,
        rendering_route="CONSTRAINED_READER",
    )
    valid = {
        "normalized_value": "because of prior evidence",
        "unit": None,
        "asserts_complete": True,
        "evidence_refs": ["e-1"],
    }

    assert validate_reader_answer_v01(decision, valid).accepted is True
    assert (
        validate_reader_answer_v01(decision, {**valid, "normalized_value": "changed"}).reason_code
        == "READER_OPERATOR_VALUE_MISMATCH"
    )
    assert (
        validate_reader_answer_v01(decision, {**valid, "unit": "days"}).reason_code
        == "READER_OPERATOR_UNIT_MISMATCH"
    )
    assert (
        validate_reader_answer_v01(decision, {**valid, "evidence_refs": ["e-2"]}).reason_code
        == "READER_EVIDENCE_REF_OUTSIDE_SET"
    )
    assert validate_reader_answer_v01(decision, "not-json").reason_code == ("READER_INVALID_JSON")

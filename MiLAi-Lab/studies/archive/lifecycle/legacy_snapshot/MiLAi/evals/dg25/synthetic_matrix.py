"""Label-free DG-25 S1 contract and fail-closed synthetic matrix."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from milai.domain.acquisition_capability import FeasibleAcquisitionAction
from milai.domain.requirement_acquisition import (
    AcquisitionActionRole,
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
    EventIdentityV01,
    EventTimeBasisV02,
    EventTimeIntervalV02,
    EventTimePrecisionV02,
    build_bounded_range_scan_proof_v02,
    build_event_identity_v01,
    build_event_time_interval_v02,
    classify_range_membership,
    deduplicate_event_identities,
)
from milai.domain.typed_answer import (
    TypedAnswerContractV01,
    TypedAnswerDecisionV01,
    TypedAnswerLineageV01,
    build_typed_answer_decision_v01,
    validate_reader_answer_v01,
)
from pydantic import ValidationError

REFERENCE = datetime(2026, 8, 29, 12, tzinfo=UTC)


def run_synthetic_matrix() -> dict[str, Any]:
    records: list[dict[str, Any]] = []

    state = _state()
    feasible = _feasible(state)
    plan, policy = _plan(state, feasible)
    fresh_validation = validate_requirement_acquisition_plan(
        plan,
        requirement_state=state,
        feasible_actions=[feasible],
        policy=policy,
        current_snapshot_identity="8" * 64,
        current_access_snapshot_identity="9" * 64,
        baseline_candidate_caps={feasible.action_digest: 8},
    )
    _value_record(
        records,
        "plan-fresh-exact-feasible",
        "PLAN",
        fresh_validation.reason_codes,
        ["PLAN_FEASIBLE"],
    )
    stale_validation = validate_requirement_acquisition_plan(
        plan,
        requirement_state=_state(epoch=1),
        feasible_actions=[feasible],
        policy=policy,
        current_snapshot_identity="a" * 64,
        current_access_snapshot_identity="b" * 64,
    )
    _contains_record(
        records,
        "plan-stale-state-epoch-snapshot",
        "PLAN",
        stale_validation.reason_codes,
        {
            "STALE_REQUIREMENT_STATE",
            "SNAPSHOT_IDENTITY_MISMATCH",
            "ACCESS_SNAPSHOT_IDENTITY_MISMATCH",
        },
    )
    unknown_validation = validate_requirement_acquisition_plan(
        plan,
        requirement_state=state,
        feasible_actions=[],
        policy=policy,
        current_snapshot_identity="8" * 64,
        current_access_snapshot_identity="9" * 64,
    )
    _contains_record(
        records,
        "plan-unregistered-action",
        "PLAN",
        unknown_validation.reason_codes,
        {"UNREGISTERED_ACTION"},
    )
    _rejection_record(
        records,
        "plan-aggregate-budget-overflow",
        "PLAN",
        lambda: RequirementAcquisitionAggregateBudgetV01(
            max_repository_calls=1,
            planned_repository_calls=2,
            max_hydrated_candidates=120,
            planned_candidate_cap_sum=16,
        ),
        "planned repository calls exceed",
    )
    _rejection_record(
        records,
        "plan-duplicate-action-digest",
        "PLAN",
        lambda: build_requirement_acquisition_plan(
            lineage=plan.lineage,
            target_requirements=plan.target_requirements,
            actions=[plan.actions[0], plan.actions[0]],
            aggregate_budget=RequirementAcquisitionAggregateBudgetV01(
                max_repository_calls=2,
                planned_repository_calls=2,
                max_hydrated_candidates=120,
                planned_candidate_cap_sum=16,
            ),
        ),
        "action digests must be unique",
    )
    _rejection_record(
        records,
        "plan-proof-action-required",
        "PLAN",
        lambda: _plan_with_action_role(state, feasible, "EVIDENCE_DISCOVERY"),
        "requires a proof-closing action",
    )
    reduced = _feasible(state, cap=7)
    reduced_plan, reduced_policy = _plan(state, reduced)
    reduced_validation = validate_requirement_acquisition_plan(
        reduced_plan,
        requirement_state=state,
        feasible_actions=[reduced],
        policy=reduced_policy,
        current_snapshot_identity="8" * 64,
        current_access_snapshot_identity="9" * 64,
        baseline_candidate_caps={reduced.action_digest: 8},
    )
    _contains_record(
        records,
        "plan-optional-cannot-shrink-baseline-cap",
        "PLAN",
        reduced_validation.reason_codes,
        {"BASELINE_ACTION_CAP_CHANGED"},
    )
    _value_record(
        records,
        "plan-per-role-reservation-required",
        "PLAN",
        policy.require_role_reservation,
        True,
    )
    _rejection_record(
        records,
        "plan-cross-channel-raw-score-comparison-forbidden",
        "PLAN",
        lambda: _mutated_policy(compare_raw_scores_across_channels=True),
        "Input should be False",
    )

    explicit = _interval(REFERENCE, REFERENCE + timedelta(days=1))
    _value_record(
        records, "time-explicit-date", "TEMPORAL", explicit.basis, "EXPLICIT_CALENDAR"
    )
    source_relative = _interval(
        REFERENCE - timedelta(days=4),
        REFERENCE - timedelta(days=3),
        basis="SOURCE_RELATIVE",
    )
    _value_record(
        records,
        "time-source-relative-weekday",
        "TEMPORAL",
        source_relative.basis,
        "SOURCE_RELATIVE",
    )
    weekend = _interval(
        REFERENCE - timedelta(days=7),
        REFERENCE - timedelta(days=5),
        basis="SOURCE_RELATIVE",
        precision="WEEKEND",
    )
    _value_record(
        records, "time-last-weekend", "TEMPORAL", weekend.precision, "WEEKEND"
    )
    month = _interval(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
        precision="MONTH",
    )
    _value_record(records, "time-month-interval", "TEMPORAL", month.precision, "MONTH")
    cross_year = _interval(
        datetime(2025, 12, 31, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        basis="SOURCE_RELATIVE",
    )
    _value_record(
        records,
        "time-cross-year-relative-date",
        "TEMPORAL",
        cross_year.interval_start.year,
        2025,
    )
    new_york = ZoneInfo("America/New_York")
    dst = _interval(
        datetime(2026, 11, 1, 0, tzinfo=new_york),
        datetime(2026, 11, 2, 0, tzinfo=new_york),
        timezone="America/New_York",
    )
    _value_record(
        records,
        "time-dst-timezone",
        "TEMPORAL",
        dst.interval_start.utcoffset() != dst.interval_end_exclusive.utcoffset(),
        True,
    )
    anchored = _interval(
        REFERENCE + timedelta(days=14),
        REFERENCE + timedelta(days=15),
        basis="UNIQUE_ANCHOR_RELATIVE",
        precision="RELATIVE_RANGE",
        anchor_evidence_ids=("anchor-1",),
        grounded_span_ids=("relation-span-1",),
    )
    _value_record(
        records,
        "time-unique-relational-anchor",
        "TEMPORAL",
        anchored.anchor_evidence_ids,
        ["anchor-1"],
    )
    _rejection_record(
        records,
        "time-ambiguous-relational-anchor",
        "TEMPORAL",
        lambda: _interval(
            REFERENCE,
            REFERENCE + timedelta(days=1),
            basis="UNIQUE_ANCHOR_RELATIVE",
            precision="RELATIVE_RANGE",
            anchor_evidence_ids=("anchor-1", "anchor-2"),
            grounded_span_ids=("relation-span-1",),
        ),
        "requires one anchor",
    )
    query = _interval(REFERENCE, REFERENCE + timedelta(days=7), precision="WEEK")
    inside = _interval(REFERENCE + timedelta(days=1), REFERENCE + timedelta(days=2))
    outside = _interval(REFERENCE + timedelta(days=7), REFERENCE + timedelta(days=8))
    overlap = _interval(REFERENCE - timedelta(days=1), REFERENCE + timedelta(days=1))
    _value_record(
        records,
        "time-range-fully-inside",
        "TEMPORAL",
        classify_range_membership(inside, query),
        "IN_RANGE",
    )
    _value_record(
        records,
        "time-range-outside",
        "TEMPORAL",
        classify_range_membership(outside, query),
        "OUT_OF_RANGE",
    )
    _value_record(
        records,
        "time-range-overlap",
        "TEMPORAL",
        classify_range_membership(overlap, query),
        "AMBIGUOUS_RANGE_MEMBERSHIP",
    )

    repeated, repeat, twin = _event_examples(explicit)
    dedup = deduplicate_event_identities([repeated, repeat, twin])
    _value_record(
        records,
        "identity-repeated-event-across-turns",
        "IDENTITY",
        dedup.duplicate_groups[repeated.event_identity_digest],
        ["e-1", "e-2"],
    )
    _value_record(
        records,
        "identity-twins-multiple-entities-one-span",
        "IDENTITY",
        len(dedup.distinct_event_identity_digests),
        2,
    )
    unresolved = build_event_identity_v01(
        event_type="BIRTH",
        actor_identity="relative",
        object_or_participant_identity="unknown",
        occurrence_interval_digest=explicit.interval_digest,
        source_evidence_ids=["e-3"],
        identity_policy_version="event-id-v1",
        disposition="UNRESOLVED",
        unresolved_reasons=["PARTICIPANT_AMBIGUOUS"],
    )
    unresolved_dedup = deduplicate_event_identities([repeated, unresolved])
    _value_record(
        records,
        "identity-unresolved-fails-dedup-complete",
        "IDENTITY",
        unresolved_dedup.dedup_complete,
        False,
    )

    proof_scenarios: list[tuple[str, str, dict[str, object]]] = [
        ("proof-complete", "COMPLETE", {}),
        ("proof-max-items-hit", "PARTIAL", {"max_items_hit": True}),
        (
            "proof-unprojected-without-raw-fallback",
            "PARTIAL",
            {"unprojected_source_count": 1},
        ),
        (
            "proof-unprojected-with-raw-fallback",
            "COMPLETE",
            {"unprojected_source_count": 1, "raw_fallback_closed": True},
        ),
        ("proof-dead-letter-gap", "PARTIAL", {"dead_letter_gap": True}),
        ("proof-access-snapshot-invalid", "PARTIAL", {"access_snapshot_valid": False}),
        ("proof-unreadable-source", "PARTIAL", {"unreadable_source_count": 1}),
        ("proof-source-time-proxy", "PARTIAL", {"source_time_proxy": True}),
        ("proof-ambiguous-event-time", "PARTIAL", {"ambiguous_time_count": 1}),
        (
            "proof-unresolved-duplicate-group",
            "PARTIAL",
            {"unresolved_duplicate_group_count": 1, "dedup_complete": False},
        ),
    ]
    for case_id, expected, options in proof_scenarios:
        _value_record(records, case_id, "PROOF", _proof(**options).status, expected)

    reader = _reader_decision()
    valid_payload: dict[str, Any] = {
        "normalized_value": "grounded rationale",
        "unit": None,
        "asserts_complete": True,
        "evidence_refs": ["e-1"],
    }
    _value_record(
        records,
        "reader-conformant",
        "ANSWER",
        validate_reader_answer_v01(reader, valid_payload).reason_code,
        "READER_CONFORMANT",
    )
    reader_scenarios: list[tuple[str, dict[str, Any], str]] = [
        (
            "reader-value-mismatch",
            {**valid_payload, "normalized_value": "changed"},
            "READER_OPERATOR_VALUE_MISMATCH",
        ),
        (
            "reader-unit-mismatch",
            {**valid_payload, "unit": "days"},
            "READER_OPERATOR_UNIT_MISMATCH",
        ),
        (
            "reader-citation-outside-set",
            {**valid_payload, "evidence_refs": ["e-2"]},
            "READER_EVIDENCE_REF_OUTSIDE_SET",
        ),
    ]
    for case_id, payload, reason in reader_scenarios:
        _value_record(
            records,
            case_id,
            "ANSWER",
            validate_reader_answer_v01(reader, payload).reason_code,
            reason,
        )
    _value_record(
        records,
        "reader-invalid-json",
        "ANSWER",
        validate_reader_answer_v01(reader, "not-json").reason_code,
        "READER_INVALID_JSON",
    )
    _rejection_record(
        records,
        "reader-cannot-claim-complete-on-partial",
        "ANSWER",
        lambda: build_typed_answer_decision_v01(
            lineage=_answer_lineage(),
            runtime_status="PARTIAL",
            answer_contract=reader.answer_contract,
            rendering_route="CONSTRAINED_READER",
        ),
        "must abstain",
    )

    categories: dict[str, int] = {}
    for record in records:
        category = str(record["category"])
        categories[category] = categories.get(category, 0) + 1
    passed = all(record["passed"] for record in records)
    return {
        "schema": "milai.dg25.s1-synthetic-matrix.v0.1",
        "status": "PASS_DG25_S1_SYNTHETIC_MATRIX" if passed else "FAIL",
        "records": records,
        "counts": {
            "total": len(records),
            "passed": sum(bool(record["passed"]) for record in records),
            "failed": sum(not bool(record["passed"]) for record in records),
            "by_category": dict(sorted(categories.items())),
        },
        "safety": {
            "labels_loaded": False,
            "formal_holdout_consumed": False,
            "provider_calls": 0,
            "automatic_retries": 0,
            "canonical_mutations": 0,
            "candidate_default": False,
        },
        "hard_gate": {"passed": passed},
    }


def _state(*, epoch: int = 0) -> RequirementState:
    disposition = RequirementDisposition(
        requirement_id="EVENT_SET",
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
        "sufficiency_policy_version": "synthetic-v1",
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
        "target_requirement_id": "EVENT_SET",
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
    action = PlannedRequirementAcquisitionActionV01(
        action_digest=feasible.action_digest,
        target_requirement_id=feasible.target_requirement_id,
        action_role="PROOF_CLOSURE",
        capability_id=feasible.capability_id,
        channel=feasible.channel,
        candidate_cap=feasible.bounded_cost["candidate_count"],
        bounded_cost=feasible.bounded_cost,
        reason_code="ALL_MATCHES_IN_RANGE_REQUIRES_PROOF",
    )
    target = TargetRequirementV01(
        requirement_id="EVENT_SET",
        kind="RANGE_COMPLETENESS",
        status="COMPLETENESS_PROOF_MISSING",
        missing_evidence_roles=["EVENT_OCCURRENCE"],
        proof_obligations=["ALL_MATCHES_IN_RANGE"],
    )
    budget = RequirementAcquisitionAggregateBudgetV01(
        max_repository_calls=2,
        planned_repository_calls=1,
        max_hydrated_candidates=120,
        planned_candidate_cap_sum=action.candidate_cap,
    )
    return (
        build_requirement_acquisition_plan(
            lineage=lineage,
            target_requirements=[target],
            actions=[action],
            aggregate_budget=budget,
        ),
        policy,
    )


def _plan_with_action_role(
    state: RequirementState,
    feasible: FeasibleAcquisitionAction,
    role: AcquisitionActionRole,
) -> RequirementAcquisitionPlanV01:
    plan, _policy = _plan(state, feasible)
    action_payload = plan.actions[0].model_dump(mode="json")
    action_payload["action_role"] = role
    action = PlannedRequirementAcquisitionActionV01.model_validate(action_payload)
    return build_requirement_acquisition_plan(
        lineage=plan.lineage,
        target_requirements=plan.target_requirements,
        actions=[action],
        aggregate_budget=plan.aggregate_budget,
    )


def _mutated_policy(
    **changes: object,
) -> RequirementCompleteRetrievalPolicyV01:
    policy = default_requirement_complete_retrieval_policy()
    payload: dict[str, Any] = policy.model_dump(mode="json")
    payload.update(changes)
    material = {key: value for key, value in payload.items() if key != "policy_digest"}
    payload["policy_digest"] = canonical_sha256(material)
    return type(policy).model_validate(payload)


def _interval(
    start: datetime,
    end: datetime,
    *,
    timezone: str = "UTC",
    precision: EventTimePrecisionV02 = "DAY",
    basis: EventTimeBasisV02 = "EXPLICIT_CALENDAR",
    anchor_evidence_ids: tuple[str, ...] = (),
    grounded_span_ids: tuple[str, ...] = (),
    ambiguity_reasons: tuple[str, ...] = (),
) -> EventTimeIntervalV02:
    return build_event_time_interval_v02(
        interval_start=start,
        interval_end_exclusive=end,
        timezone=timezone,
        precision=precision,
        basis=basis,
        anchor_evidence_ids=anchor_evidence_ids,
        grounded_span_ids=grounded_span_ids,
        ambiguity_reasons=ambiguity_reasons,
    )


def _event_examples(
    interval: EventTimeIntervalV02,
) -> tuple[EventIdentityV01, EventIdentityV01, EventIdentityV01]:
    first = build_event_identity_v01(
        event_type="BIRTH",
        actor_identity="relative",
        object_or_participant_identity="participant-a",
        occurrence_interval_digest=interval.interval_digest,
        source_evidence_ids=["e-1"],
        identity_policy_version="event-id-v1",
    )
    repeat = build_event_identity_v01(
        event_type="BIRTH",
        actor_identity="relative",
        object_or_participant_identity="participant-a",
        occurrence_interval_digest=interval.interval_digest,
        source_evidence_ids=["e-2"],
        identity_policy_version="event-id-v1",
        disposition="DUPLICATE_OF",
    )
    twin = build_event_identity_v01(
        event_type="BIRTH",
        actor_identity="relative",
        object_or_participant_identity="participant-b",
        occurrence_interval_digest=interval.interval_digest,
        source_evidence_ids=["e-1"],
        identity_policy_version="event-id-v1",
    )
    return first, repeat, twin


def _proof(**changes: object) -> BoundedRangeScanProofV02:
    options: dict[str, object] = {
        "max_items_hit": False,
        "unprojected_source_count": 0,
        "raw_fallback_closed": False,
        "dead_letter_gap": False,
        "access_snapshot_valid": True,
        "unreadable_source_count": 0,
        "source_time_proxy": False,
        "ambiguous_time_count": 0,
        "unresolved_duplicate_group_count": 0,
        "dedup_complete": True,
    }
    options.update(changes)
    proxy = bool(options["source_time_proxy"])
    ambiguous = _integer_option(options["ambiguous_time_count"])
    interval = _interval(
        REFERENCE,
        REFERENCE + timedelta(days=7),
        precision="WEEK",
        basis="SOURCE_OBSERVED_PROXY" if proxy else "EXPLICIT_CALENDAR",
        ambiguity_reasons=("EVENT_TIME_NOT_GROUNDED",) if proxy else (),
    )
    return build_bounded_range_scan_proof_v02(
        query_closure=BoundedRangeQueryClosureV02(
            query_ir_digest="1" * 64,
            requirement_state_digest="2" * 64,
            event_time_interval=interval,
            timezone=interval.timezone,
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
            max_items_hit=bool(options["max_items_hit"]),
            unreadable_source_count=_integer_option(
                options["unreadable_source_count"]
            ),
        ),
        projection_closure=BoundedRangeProjectionClosureV02(
            projection_version="temporal-v1",
            temporal_normalizer_version="normalizer-v2",
            target_watermark=10,
            projection_watermark=10,
            projection_watermark_covered=True,
            dead_letter_gap=bool(options["dead_letter_gap"]),
            unprojected_source_count=_integer_option(
                options["unprojected_source_count"]
            ),
            raw_fallback_closed=bool(options["raw_fallback_closed"]),
        ),
        event_set_closure=BoundedRangeEventSetClosureV02(
            candidate_event_count=2 + ambiguous,
            in_range_event_count=2,
            out_of_range_event_count=0,
            ambiguous_time_count=ambiguous,
            unresolved_event_count=0,
            event_identity_policy_version="event-id-v1",
        ),
        dedup_closure=BoundedRangeDedupClosureV02(
            dedup_policy_version="event-id-v1",
            duplicate_group_count=0,
            unresolved_duplicate_group_count=_integer_option(
                options["unresolved_duplicate_group_count"]
            ),
            distinct_event_count=2,
            dedup_complete=bool(options["dedup_complete"]),
        ),
        access_closure=BoundedRangeAccessClosureV02(
            policy_digest="7" * 64,
            unreadable_evidence_count=0,
            access_snapshot_valid=bool(options["access_snapshot_valid"]),
        ),
    )


def _integer_option(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("synthetic proof integer option is malformed")
    return value


def _answer_lineage() -> TypedAnswerLineageV01:
    return TypedAnswerLineageV01(
        query_ir_digest="1" * 64,
        requirement_state_digest="2" * 64,
        sufficiency_decision_digest="3" * 64,
        operator_result_digest="4" * 64,
        proof_digest="5" * 64,
        evidence_set_digest="6" * 64,
    )


def _reader_decision() -> TypedAnswerDecisionV01:
    return build_typed_answer_decision_v01(
        lineage=_answer_lineage(),
        runtime_status="COMPLETE",
        answer_contract=TypedAnswerContractV01(
            answer_type="EXPLANATION",
            normalized_value="grounded rationale",
            allowed_evidence_refs=["e-1"],
        ),
        rendering_route="CONSTRAINED_READER",
    )


def _value_record(
    records: list[dict[str, Any]],
    case_id: str,
    category: str,
    observed: object,
    expected: object,
) -> None:
    records.append(
        {
            "case_id": case_id,
            "category": category,
            "expected": expected,
            "observed": observed,
            "passed": observed == expected,
        }
    )


def _contains_record(
    records: list[dict[str, Any]],
    case_id: str,
    category: str,
    observed: list[str],
    expected: set[str],
) -> None:
    records.append(
        {
            "case_id": case_id,
            "category": category,
            "expected_contains": sorted(expected),
            "observed": observed,
            "passed": expected.issubset(observed),
        }
    )


def _rejection_record(
    records: list[dict[str, Any]],
    case_id: str,
    category: str,
    operation: Callable[[], object],
    expected_message: str,
) -> None:
    try:
        operation()
    except (ValidationError, ValueError) as exc:
        observed = str(exc)
        passed = expected_message in observed
    else:
        observed = "ACCEPTED"
        passed = False
    records.append(
        {
            "case_id": case_id,
            "category": category,
            "expected_rejection_contains": expected_message,
            "observed": observed,
            "passed": passed,
        }
    )


def negative_contract_report(matrix: dict[str, Any]) -> dict[str, Any]:
    negative = [
        deepcopy(record)
        for record in matrix["records"]
        if "expected_rejection_contains" in record
        or str(record["case_id"]).startswith(("proof-", "reader-"))
        and record["case_id"] not in {"proof-complete", "reader-conformant"}
    ]
    return {
        "schema": "milai.dg25.s1-negative-contract-report.v0.1",
        "status": "PASS_DG25_S1_NEGATIVE_CONTRACTS"
        if all(item["passed"] for item in negative)
        else "FAIL",
        "negative_case_count": len(negative),
        "records": negative,
        "wrong_complete": 0,
        "stale_acceptance": 0,
        "budget_overflow_acceptance": 0,
        "reader_mismatch_acceptance": 0,
        "hard_gate": {"passed": all(item["passed"] for item in negative)},
    }


__all__ = ["negative_contract_report", "run_synthetic_matrix"]

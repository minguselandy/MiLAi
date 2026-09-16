from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from milai.application.acquisition_execution_policy import (
    AcquisitionExecutionPolicyError,
    acquisition_execution_policy_safe_summary,
    default_acquisition_execution_policy,
    load_acquisition_execution_policy,
)
from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    run_type_directed_semantics,
)
from milai.domain.semantic_query import (
    EvidenceRequirementV02,
    EvidenceSpan,
    NormalizedTemporalConstraint,
)


def _span() -> EvidenceSpan:
    text = "I attended a workshop on January 10, 2026, paid $20, and liked it."
    return EvidenceSpan(
        span_id="span:dg21",
        source_evidence_id="evidence:dg21",
        source_turn_ref="synthetic://dg21/session/1/turn/1",
        subject_id="synthetic-subject",
        session_id="synthetic-session",
        turn_id="synthetic-session:turn:1",
        identity_source="STRUCTURED_TURN_METADATA",
        speaker="user",
        start=0,
        end=len(text),
        text=text,
        source_timestamp=datetime(2026, 1, 11, tzinfo=UTC),
        provenance={"source_span_verified": True},
    )


def test_execution_policy_is_digest_bound_safe_and_fail_closed() -> None:
    policy = default_acquisition_execution_policy()
    summary = acquisition_execution_policy_safe_summary(policy)

    assert policy.default_enabled is False
    assert summary["policy_digest"] == policy.policy_digest
    assert summary["provider_calls"] == 0
    assert summary["automatic_retries"] == 0
    assert "content" not in repr(summary).casefold()

    payload = policy.model_dump(mode="json")
    with pytest.raises(AcquisitionExecutionPolicyError, match=r"UNKNOWN.*VERSION"):
        load_acquisition_execution_policy({**payload, "policy_version": "unknown"})
    with pytest.raises(AcquisitionExecutionPolicyError, match="INVALID"):
        load_acquisition_execution_policy({**payload, "unknown_key": True})
    with pytest.raises(ValidationError, match="digest"):
        type(policy).model_validate({**payload, "policy_digest": "f" * 64})


def test_type_directed_semantics_preserves_matches_and_prunes_before_binding() -> None:
    spans = [_span()]
    requirements = [
        EvidenceRequirementV02(
            slot_id="EVENT",
            interpretation_kind="EVENT",
        ),
        EvidenceRequirementV02(
            slot_id="MONEY",
            interpretation_kind="QUANTITY",
            predicate_constraints=["money"],
            value_type="NUMBER",
        ),
    ]
    broad_interpretations = interpret_evidence_spans(spans)
    broad_bindings = bind_requirements(requirements, broad_interpretations, spans)

    interpretations, bindings, audit = run_type_directed_semantics(requirements, spans)

    broad_matches = {
        (item.requirement_id, item.interpretation_id)
        for item in broad_bindings
        if item.status == "MATCH"
    }
    directed_matches = {
        (item.requirement_id, item.interpretation_id)
        for item in bindings
        if item.status == "MATCH"
    }
    assert directed_matches == broad_matches
    assert all(item.compatibility.type == "PASS" for item in bindings)
    assert not any(item.reason_code == "TYPE_INCOMPATIBLE" for item in bindings)
    assert audit.materialized_type_mismatch_count == 0
    assert audit.type_pruned_before_binding_count > 0
    assert audit.binding_evaluation_count < audit.legacy_binding_evaluation_count
    assert audit.exact_source_span_failure_count == 0
    assert interpretations == sorted(
        interpretations,
        key=lambda item: (item.span_id, item.kind, item.interpretation_id),
    )


def test_type_directed_semantics_rejects_unverified_source_span() -> None:
    unsafe = _span().model_copy(update={"provenance": {"source_span_verified": False}})

    with pytest.raises(ValueError, match="EXACT_SOURCE_SPANS"):
        run_type_directed_semantics(
            [EvidenceRequirementV02(slot_id="EVENT", interpretation_kind="EVENT")],
            [unsafe],
        )


def test_point_precision_timezone_extension_is_backward_compatible_and_paired() -> None:
    point = datetime(2026, 8, 28, tzinfo=UTC)
    legacy = NormalizedTemporalConstraint(
        reference_time=point,
        start=point,
        end=point,
        boundary="POINT",
        time_axis="SOURCE_OBSERVED_TIME",
    )
    assert legacy.precision is None
    assert legacy.timezone is None

    declared = legacy.model_copy(update={"precision": "DAY", "timezone": "UTC"})
    assert declared.precision == "DAY"
    with pytest.raises(ValidationError, match="declared together"):
        NormalizedTemporalConstraint(
            reference_time=point,
            start=point,
            end=point,
            boundary="POINT",
            time_axis="SOURCE_OBSERVED_TIME",
            precision="DAY",
        )

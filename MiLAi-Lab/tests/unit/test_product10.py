from __future__ import annotations

import pytest

from milai_lab.product10 import (
    InstanceGroup,
    distinct_instance_coverage,
    duplicate_instance_rate,
    first_loss,
    structural_capability_shapes,
    validate_label_case,
)


def _groups() -> tuple[InstanceGroup, ...]:
    return (
        InstanceGroup("g1", ("e1",), ("t1", "t1-repeat"), True),
        InstanceGroup("g2", ("e2",), ("t2",), True),
    )


def test_instance_metrics_preserve_distinct_groups_and_report_raw_counts() -> None:
    coverage = distinct_instance_coverage(
        _groups(), visible_evidence_ids=["e1"], visible_turn_refs=["t2"]
    )
    duplicate = duplicate_instance_rate(
        _groups(),
        visible_evidence_ids=["e1"],
        visible_turn_refs=["t1-repeat", "t2"],
    )

    assert coverage == {"numerator": 2, "denominator": 2, "value": 1.0}
    assert duplicate == {
        "numerator": 1,
        "denominator": 3,
        "value": 1 / 3,
        "empty_eligible_set": False,
    }


def test_first_loss_has_unique_precedence() -> None:
    group = _groups()[0]
    assert first_loss(
        group,
        raw_evidence_ids=["e1"],
        raw_turn_refs=[],
        post_identity_evidence_ids=[],
        post_identity_turn_refs=[],
        admitted_evidence_ids=[],
        admitted_turn_refs=[],
        rendered_evidence_ids=[],
        rendered_turn_refs=[],
    ) == "INSTANCE_DESTROYING_COLLAPSE"
    assert first_loss(
        group,
        raw_evidence_ids=["e1"],
        raw_turn_refs=[],
        post_identity_evidence_ids=["e1"],
        post_identity_turn_refs=[],
        admitted_evidence_ids=["e1"],
        admitted_turn_refs=[],
        rendered_evidence_ids=["e1"],
        rendered_turn_refs=[],
        host_used=False,
    ) == "VISIBLE_BUT_HOST_MISSED"


def test_rendered_adjacent_turn_is_covered_even_without_direct_raw_anchor() -> None:
    group = InstanceGroup(
        group_id="case:g1",
        acceptable_evidence_ids=(),
        acceptable_turn_refs=("turn-adjacent",),
        required_for_answer=True,
    )

    assert first_loss(
        group,
        raw_evidence_ids=(),
        raw_turn_refs=(),
        post_identity_evidence_ids=(),
        post_identity_turn_refs=(),
        admitted_evidence_ids=(),
        admitted_turn_refs=(),
        rendered_evidence_ids=("hydrating-anchor",),
        rendered_turn_refs=("turn-adjacent",),
    ) is None


def test_label_validation_rejects_cross_group_turn_alias() -> None:
    value = {
        "case_id": "case-1",
        "capability_shapes": ["ENUMERATION"],
        "instance_groups": [
            {
                "group_id": "g1",
                "acceptable_evidence_ids": [],
                "acceptable_turn_refs": ["turn-1"],
                "required_for_answer": True,
            },
            {
                "group_id": "g2",
                "acceptable_evidence_ids": [],
                "acceptable_turn_refs": ["turn-1"],
                "required_for_answer": True,
            },
        ],
    }
    with pytest.raises(ValueError, match="multiple groups"):
        validate_label_case(value)


def test_structural_shapes_keep_semantics_out_of_product_identity() -> None:
    shapes = structural_capability_shapes(
        question_type="multi-session",
        question="How many items were mentioned in total?",
        group_member_counts=[2, 1],
        reference_session_count=2,
        model_shapes=[],
    )
    assert set(shapes) == {
        "ENUMERATION",
        "COUNTING",
        "REPEATED_MENTION",
        "SAME_TYPE_DIFFERENT_INSTANCE",
        "CROSS_SESSION_AGGREGATION",
        "CONTINUATION",
    }

from __future__ import annotations

from copy import deepcopy

import pytest

from milai_lab.product11 import (
    CAPABILITY_SHAPES,
    InstanceGroup,
    canonical_sha256,
    classify_x0_opportunity,
    continuation_instance_gain,
    direct_acquisition_coverage,
    distinct_instance_coverage,
    duplicate_instance_rate,
    validate_human_seal,
    validate_source_fixture,
    validate_x0_opportunity_assignments,
)
from milai_lab.product11_human import (
    build_source_review_view,
    build_submission_rows,
    merge_independent_submissions,
    validate_independent_submission,
)


def _fixture() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for index in range(24):
        case_id = f"case-{index:02d}"
        cases.append(
            {
                "case_id": case_id,
                "question": f"What happened in {case_id}?",
                "capability_shapes": list(CAPABILITY_SHAPES),
                "intended_stratum": ("CONTINUATION", "INTRA_SOURCE", "CONTROL")[index % 3],
                "sessions": [
                    {
                        "source_id": f"source-{case_id}",
                        "session_id": f"session-{case_id}",
                        "turns": [
                            {
                                "turn_ref": f"p11://{case_id}/t0",
                                "text": f"Evidence for {case_id}",
                            },
                            {
                                "turn_ref": f"p11://{case_id}/t1",
                                "text": f"Second evidence for {case_id}",
                            },
                        ],
                    }
                ],
            }
        )
    return {
        "schema_version": "milai-product11-opened-dev-v0.1",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_source": False,
        "cases": cases,
    }


def _human_rows(fixture: dict[str, object]) -> list[dict[str, object]]:
    header: dict[str, object] = {
        "record_type": "manifest",
        "schema_version": "milai-product11-human-instance-groups-v0.1",
        "human_adjudication_status": "COMPLETE",
        "model_assisted_proxy": False,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "source_fixture_sha256": canonical_sha256(fixture),
    }
    rows = [header]
    cases = fixture["cases"]
    assert isinstance(cases, list)
    for index, raw_case in enumerate(cases):
        assert isinstance(raw_case, dict)
        case_id = str(raw_case["case_id"])
        rows.append(
            {
                "record_type": "case",
                "case_id": case_id,
                "capability_shapes": list(CAPABILITY_SHAPES),
                "instance_groups": [
                    {
                        "group_id": f"{case_id}:g1",
                        "acceptable_evidence_ids": [],
                        "acceptable_turn_refs": [f"p11://{case_id}/t0"],
                        "source_ids": [f"source-{case_id}"],
                        "session_ids": [f"session-{case_id}"],
                        "required_for_answer": True,
                    }
                ],
                "continuation_opportunity": index < 8,
                "intra_source_opportunity": 8 <= index < 16,
                "control_or_already_complete": index >= 16,
                "human_adjudication_status": "COMPLETE",
                "model_assisted_proxy": False,
                "annotator": {
                    "kind": "HUMAN",
                    "id": "annotator-a",
                    "signed_at": "2026-09-04T00:00:00Z",
                    "attestation": "I independently annotated this case.",
                },
                "reviewer": {
                    "kind": "HUMAN",
                    "id": "reviewer-b",
                    "signed_at": "2026-09-04T00:01:00Z",
                    "attestation": "I independently reviewed this case.",
                },
            }
        )
    return rows


def _groups() -> tuple[InstanceGroup, ...]:
    return (
        InstanceGroup("g1", ("e1",), ("t1", "t1-repeat"), ("s1",), ("x1",), True),
        InstanceGroup("g2", ("e2",), ("t2",), ("s1",), ("x1",), True),
    )


def _a0_traces() -> list[dict[str, object]]:
    traces: list[dict[str, object]] = []
    for index in range(24):
        case_id = f"case-{index:02d}"
        if index < 8:
            rendered: list[str] = []
            direct: list[str] = []
            raw = [f"p11://{case_id}/t0"]
        elif index < 16:
            rendered = [f"p11://{case_id}/t1"]
            direct = [f"p11://{case_id}/t1"]
            raw = list(direct)
        else:
            rendered = [f"p11://{case_id}/t0"]
            direct = list(rendered)
            raw = list(rendered)
        traces.append(
            {
                "schema_version": "milai-product11-x0-a0-case-trace-v0.1",
                "case_id": case_id,
                "status": "TRACE_COMPLETE",
                "source_snapshot_as_of": "2026-09-04T00:00:00Z",
                "invariants": {
                    "labels_loaded": False,
                    "label_fields_present": False,
                    "canonical_mutation": False,
                    "cross_namespace_source_count": 0,
                },
                "identity_sets": {
                    "rendered_evidence_ids": [],
                    "rendered_turn_refs": rendered,
                    "post_identity_evidence_ids": [],
                    "post_identity_turn_refs": direct,
                    "raw_evidence_ids": [],
                    "raw_turn_refs": raw,
                },
            }
        )
    return traces


def _complete_submission(
    rows: list[dict[str, object]], *, identity: str
) -> list[dict[str, object]]:
    completed = deepcopy(rows)
    completed[0]["human_review_status"] = "COMPLETE"
    completed[0]["human_attestation"] = {
        "kind": "HUMAN",
        "id": identity,
        "signed_at": "2026-09-04T00:00:00Z",
        "attestation": "I independently reviewed all 24 source-only cases.",
    }
    for row in completed[1:]:
        case_id = str(row["case_id"])
        row["human_review_status"] = "COMPLETE"
        row["instance_groups"] = [
            {
                "group_id": f"{case_id}:human-group",
                "acceptable_evidence_ids": [],
                "acceptable_turn_refs": [f"p11://{case_id}/t0"],
                "source_ids": [],
                "session_ids": [],
                "required_for_answer": True,
            }
        ]
    return completed


def test_product11_metrics_use_exact_group_coverage_and_na_duplicate_denominator() -> None:
    assert distinct_instance_coverage(
        _groups(), visible_evidence_ids=["e1"], visible_turn_refs=["t2"]
    ) == {"numerator": 2, "denominator": 2, "value": 1.0}
    assert direct_acquisition_coverage(
        _groups(), direct_evidence_ids=[], direct_turn_refs=["t1"]
    ) == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert (
        continuation_instance_gain(
            _groups(),
            call1_evidence_ids=["e1"],
            call1_turn_refs=[],
            call2_evidence_ids=["e2", "e2"],
            call2_turn_refs=[],
        )
        == 0.5
    )
    assert duplicate_instance_rate(_groups(), visible_evidence_ids=[], visible_turn_refs=[]) == {
        "numerator": 0,
        "denominator": 0,
        "value": None,
        "empty_eligible_set": True,
    }


def test_product11_source_fixture_is_nonformal_and_label_free() -> None:
    summary = validate_source_fixture(_fixture())
    assert summary["case_count"] == 24
    assert summary["intended_stratum_counts"] == {
        "CONTINUATION": 8,
        "CONTROL": 8,
        "INTRA_SOURCE": 8,
    }

    invalid = _fixture()
    invalid["formal_source"] = True
    with pytest.raises(ValueError, match="reject Formal"):
        validate_source_fixture(invalid)


def test_product11_human_seal_requires_distinct_humans_and_all_gates() -> None:
    fixture = _fixture()
    summary = validate_human_seal(fixture, _human_rows(fixture))
    assert summary["status"] == "PASS_PRODUCT11_X0_HUMAN_SEAL"
    assert summary["continuation_opportunity_count"] == 8
    assert summary["intra_source_opportunity_count"] == 8
    assert summary["control_or_already_complete_count"] == 8

    same_person = _human_rows(fixture)
    same_person[1]["reviewer"] = same_person[1]["annotator"]
    with pytest.raises(ValueError, match="not independent"):
        validate_human_seal(fixture, same_person)


def test_product11_human_seal_allows_source_overlap_but_rejects_turn_overlap() -> None:
    fixture = _fixture()
    rows = _human_rows(fixture)
    first = rows[1]
    groups = first["instance_groups"]
    assert isinstance(groups, list)
    groups.append(
        {
            "group_id": "case-00:g2",
            "acceptable_evidence_ids": [],
            "acceptable_turn_refs": ["p11://case-00/t1"],
            "source_ids": ["source-case-00"],
            "session_ids": ["session-case-00"],
            "required_for_answer": True,
        }
    )
    assert validate_human_seal(fixture, rows)["group_count"] == 25

    overlap = deepcopy(rows)
    overlap_groups = overlap[1]["instance_groups"]
    assert isinstance(overlap_groups, list)
    overlap_groups[1]["acceptable_turn_refs"] = ["p11://case-00/t0"]
    with pytest.raises(ValueError, match="cross-group turn overlap"):
        validate_human_seal(fixture, overlap)


def test_product11_model_candidate_cannot_be_sealed_as_human() -> None:
    fixture = _fixture()
    rows = _human_rows(fixture)
    rows[0]["human_adjudication_status"] = "PENDING"
    rows[0]["model_assisted_proxy"] = True
    with pytest.raises(ValueError, match="manifest is invalid"):
        validate_human_seal(fixture, rows)


def test_product11_x0_opportunity_uses_frontier_and_direct_anchor_separately() -> None:
    result = classify_x0_opportunity(
        _groups(),
        visible_evidence_ids=["e1"],
        visible_turn_refs=[],
        direct_evidence_ids=["e1"],
        direct_turn_refs=[],
        frontier_evidence_ids=["e2"],
        frontier_turn_refs=[],
        selected_coarse_source_ids=["s1"],
        selected_coarse_session_ids=[],
    )

    assert result == {
        "continuation_opportunity": True,
        "intra_source_opportunity": True,
        "control_or_already_complete": False,
    }


def test_product11_human_opportunity_flags_must_match_frozen_a0_trace() -> None:
    fixture = _fixture()
    rows = _human_rows(fixture)
    traces = _a0_traces()

    assert validate_x0_opportunity_assignments(fixture, rows, traces) == {
        "continuation_opportunity_count": 8,
        "intra_source_opportunity_count": 8,
        "control_or_already_complete_count": 8,
        "opportunity_assignments_match_a0_trace": True,
    }

    rows[1]["continuation_opportunity"] = False
    with pytest.raises(ValueError, match="disagrees with frozen A0 trace"):
        validate_x0_opportunity_assignments(fixture, rows, traces)


def test_product11_human_workflow_is_source_only_and_proposal_free() -> None:
    fixture = _fixture()
    rows = build_submission_rows(
        fixture,
        role="ANNOTATOR",
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
    )
    assert len(rows) == 25
    assert rows[0]["model_assisted_proxy"] is False
    assert all(row["instance_groups"] == [] for row in rows[1:])

    fixture["cases"][0]["sessions"][0]["turns"][1]["text"] = (
        "Index-only distractor 00; opaque body"
    )
    view = build_source_review_view(
        fixture,
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
        authoritative_packets=["full-source.json"],
    )
    assert view["contains_product_output"] is False
    assert view["contains_model_proposals"] is False
    assert view["compacted_distractor_turn_count"] == 1
    assert "identity_sets" not in str(view)


def test_product11_human_merge_derives_opportunities_after_exact_agreement() -> None:
    fixture = _fixture()
    annotator_template = build_submission_rows(
        fixture,
        role="ANNOTATOR",
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
    )
    reviewer_template = build_submission_rows(
        fixture,
        role="INDEPENDENT_REVIEWER",
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
    )
    result = merge_independent_submissions(
        fixture,
        _a0_traces(),
        _complete_submission(annotator_template, identity="human-a"),
        _complete_submission(reviewer_template, identity="human-b"),
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
    )

    assert result["status"] == "READY_FOR_X0_SEAL"
    assert result["continuation_opportunity_count"] == 8
    assert result["intra_source_opportunity_count"] == 8
    assert result["control_or_already_complete_count"] == 8
    assert result["adjudicated_rows"] is not None


def test_product11_human_merge_reports_conflict_without_adjudicating() -> None:
    fixture = _fixture()
    annotator = _complete_submission(
        build_submission_rows(
            fixture,
            role="ANNOTATOR",
            fixture_file_sha256="fixture-sha",
            a0_trace_sha256="trace-sha",
        ),
        identity="human-a",
    )
    reviewer = _complete_submission(
        build_submission_rows(
            fixture,
            role="INDEPENDENT_REVIEWER",
            fixture_file_sha256="fixture-sha",
            a0_trace_sha256="trace-sha",
        ),
        identity="human-b",
    )
    reviewer[1]["instance_groups"][0]["acceptable_turn_refs"] = ["p11://case-00/t1"]
    result = merge_independent_submissions(
        fixture,
        _a0_traces(),
        annotator,
        reviewer,
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
    )

    assert result["status"] == "BLOCKED_HUMAN_RECONCILIATION_REQUIRED"
    assert result["conflict_case_count"] == 1
    assert result["adjudicated_rows"] is None


def test_product11_one_human_can_validate_without_other_submission() -> None:
    fixture = _fixture()
    template = build_submission_rows(
        fixture,
        role="ANNOTATOR",
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
    )
    with pytest.raises(ValueError, match="manifest is invalid"):
        validate_independent_submission(
            fixture,
            template,
            expected_role="ANNOTATOR",
            fixture_file_sha256="fixture-sha",
            a0_trace_sha256="trace-sha",
        )

    result = validate_independent_submission(
        fixture,
        _complete_submission(template, identity="human-a"),
        expected_role="ANNOTATOR",
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
    )
    assert result["status"] == "READY_FOR_INDEPENDENT_MERGE"
    assert result["case_count"] == 24
    assert result["other_submission_accessed"] is False

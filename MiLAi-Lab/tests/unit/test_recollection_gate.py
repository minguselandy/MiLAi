from __future__ import annotations

from typing import Any

from milai_lab.recollection_gate import (
    admitted_dg28_groups,
    dg28_target_source_refs,
    evaluate_recollection_result,
)


def _result(
    *,
    accepted: list[str],
    candidates: list[dict[str, Any]],
    complete: bool = True,
) -> dict[str, Any]:
    return {
        "accepted_binding_evidence_refs": accepted,
        "sufficiency_decision": {"status": "COMPLETE" if complete else "UNSATISFIED"},
        "memory_context": {
            "compile_trace": {
                "canonical_mutation": False,
                "hidden_model_calls": 0,
                "raw_retrieval_trace": {"candidates": candidates},
                "admitted_evidence_trace": {
                    "selected_evidence_ids": accepted,
                    "whole_unit_admission": True,
                    "units": [
                        {
                            "kind": "REQUIRED_BINDING",
                            "evidence_ids": accepted,
                        }
                    ]
                    if accepted
                    else [],
                },
            }
        },
        "search_trace": {
            "acquisition_state": {
                "canonical_mutation": False,
                "residual_model_call_count": 0,
                "prior_action_digests": ["a" * 64],
            },
            "acquisition_probe_dispositions": [
                {"channel": "FTS_RAW", "status": "EXECUTED"}
            ],
            "semantic_audit": {"exact_source_span_failure_count": 0},
        },
    }


def _candidate(evidence_id: str, source_ref: str) -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "source_turn_ref": source_ref,
        "subject_id": "subject",
        "session_id": "session",
        "turn_id": "session:turn:0",
        "identity_source": "STRUCTURED_TURN_METADATA",
    }


def _identity(source_ref: str) -> dict[str, str]:
    return {
        "source_ref": source_ref,
        "subject_id": "subject",
        "session_id": "session",
        "turn_id": "session:turn:0",
    }


def test_recollection_result_separates_reference_integrity_and_binding_truth() -> None:
    candidates = [_candidate("true", "s2://true"), _candidate("false", "s2://false")]
    metrics = evaluate_recollection_result(
        _result(accepted=["true", "false"], candidates=candidates),
        identities={
            "true": _identity("s2://true"),
            "false": _identity("s2://false"),
        },
        true_evidence_ids=["true"],
        false_evidence_ids=["false"],
    )

    assert metrics.reference_integrity == 1.0
    assert metrics.binding_precision == 0.5
    assert metrics.false_accepted_count == 1
    assert metrics.evidence_set_binding_exactness == 1.0
    assert metrics.strict_wrong_complete_count == 0
    assert metrics.acquisition_phase_count == 1


def test_complete_without_true_binding_counts_as_wrong_complete() -> None:
    metrics = evaluate_recollection_result(
        _result(
            accepted=["false"],
            candidates=[_candidate("false", "s2://false")],
        ),
        identities={"false": _identity("s2://false")},
        true_evidence_ids=[],
        false_evidence_ids=["false"],
    )

    assert metrics.strict_wrong_complete_count == 1


def test_legacy_arm_uses_public_items_without_claiming_evidence_set_trace() -> None:
    result = _result(
        accepted=["true"],
        candidates=[_candidate("true", "s2://true")],
    )
    compile_trace = result["memory_context"]["compile_trace"]
    compile_trace.pop("raw_retrieval_trace")
    compile_trace.pop("admitted_evidence_trace")
    result["items"] = [
        {
            "evidence_id": "true",
            "acquisition_candidate": {
                "source_turn_ref": "s2://true",
                "subject_id": "subject",
                "session_id": "session",
                "turn_id": "session:turn:0",
                "identity_source": "STRUCTURED_TURN_METADATA",
            },
        }
    ]

    metrics = evaluate_recollection_result(
        result,
        identities={"true": _identity("s2://true")},
        true_evidence_ids=["true"],
        false_evidence_ids=[],
    )

    assert metrics.reference_integrity == 1.0
    assert metrics.evidence_set_binding_exactness == 0.0


def test_dg28_targets_resolve_and_score_duplicate_groups_independently() -> None:
    records = {
        "case-a": {
            "haystack_session_ids": ["session-a"],
        }
    }
    targets = [
        {
            "equivalence_group_id": "group-1",
            "acceptable_source_turn_ref": "case-a:s0:internal-session-a:t2",
        },
        {
            "equivalence_group_id": "group-2",
            "acceptable_source_turn_ref": "case-a:s0:internal-session-a:t2",
        },
    ]
    refs = dg28_target_source_refs(records, targets)
    source_ref = next(iter(refs.values()))
    result = _result(
        accepted=[],
        candidates=[_candidate("target", source_ref)],
        complete=False,
    )

    assert admitted_dg28_groups(result, refs) == ("group-1", "group-2")

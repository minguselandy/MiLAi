from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.build_dg25_s10_terminal import (
    DELIVERABLE_NAMES,
    ROOT,
    DG25TerminalError,
    derive_terminal_dispositions,
    validate_s4b_stop,
)


def test_current_sealed_s4b_stop_recomputes_without_registry_reopen() -> None:
    evidence = validate_s4b_stop(ROOT)

    assert evidence["registry_content_reopened"] is False
    assert evidence["policy_adopted"] is False
    assert evidence["metrics"] == {
        "arm_count": 16,
        "minimum_accepted_binding_precision": 2 / 3,
        "wrong_complete_sum_across_diagnostic_arms": 16,
        "wrong_complete_arm_count": 8,
        "wrong_complete_arms": [
            "R1",
            "R2",
            "R3",
            "R4",
            "R5_NO_SYNONYM_NORMALIZATION",
            "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION",
            "R_FINAL_DROP_ROLE_RESERVATION",
            "R_FINAL_DROP_SOFT_LEXICAL_FEATURES",
        ],
        "temporal_wrong_complete_sum": 0,
    }


def test_terminal_dispositions_preserve_failure_and_not_entered_lanes() -> None:
    evidence = validate_s4b_stop(ROOT)

    assert evidence["dispositions"] == {
        "overall": "FAIL_SAFETY_OR_REGRESSION",
        "retrieval": "FAIL_BINDING_PRECISION_OR_GOVERNANCE",
        "temporal": "PARKED_EVENT_TIME_OR_DEDUP_UNRESOLVED",
        "answer": "NOT_ENTERED_C1_FAILED",
        "efficiency": "NOT_ENTERED_CORRECTNESS_UNSEALED",
        "safety": "FAIL_SAFETY_OR_REGRESSION",
        "quality": "NOT_ENTERED_S9_DUE_S4B_STOP",
    }
    assert len(DELIVERABLE_NAMES) == 49


def test_terminal_rejects_reclassified_or_incomplete_stop() -> None:
    post_gate = deepcopy(validate_s4b_stop(ROOT)["post_gate"])
    post_gate["rules"] = [
        rule for rule in post_gate["rules"] if rule["id"] != "STOP_WRONG_COMPLETE"
    ]

    with pytest.raises(DG25TerminalError, match="failure set"):
        derive_terminal_dispositions(post_gate)

    post_gate = deepcopy(validate_s4b_stop(ROOT)["post_gate"])
    post_gate["passed"] = True
    post_gate["disposition"] = "PASS"
    with pytest.raises(DG25TerminalError, match="not authoritative"):
        derive_terminal_dispositions(post_gate)

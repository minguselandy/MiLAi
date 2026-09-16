from __future__ import annotations

import pytest
from scripts.build_dg23_s9_terminal import (
    EXPECTED_STATUS,
    DG23S9Error,
    derive_dispositions,
)


def test_dg23_s9_preserves_independent_pass_and_parked_lanes() -> None:
    dispositions = derive_dispositions(EXPECTED_STATUS)

    assert dispositions == {
        "context_decision": "PASS_BUDGET_INVARIANT_DECISION_AND_CONTEXT",
        "recall_binding": "PASS_DG22_RECALL_BINDING_NON_REGRESSION",
        "answer": "FAIL_CORRECT_CASE_REGRESSION",
        "reader_semantics": "PARKED_READER_SEMANTIC_NON_MONOTONICITY",
        "safety": "PASS_DG23_SAFETY",
        "quality": "PASS_DG23_QUALITY_POSTGRESQL_SECURITY_ARCHITECTURE",
        "overall": "PARKED_READER_SEMANTIC_NON_MONOTONICITY",
    }


def test_dg23_s9_rejects_missing_or_reclassified_stage_status() -> None:
    missing = dict(EXPECTED_STATUS)
    missing.pop("s7")
    with pytest.raises(DG23S9Error, match="denominator"):
        derive_dispositions(missing)

    reclassified = dict(EXPECTED_STATUS)
    reclassified["s7"] = "PASS_DG23_MATCHED_READER_ANSWER_CLOSURE"
    with pytest.raises(DG23S9Error, match="authoritative"):
        derive_dispositions(reclassified)

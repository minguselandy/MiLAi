from __future__ import annotations

import pytest
from scripts.build_dg22_s10_terminal import (
    EXPECTED_STATUS,
    DG22S10Error,
    derive_dispositions,
)


def test_s10_dispositions_preserve_independent_partial_and_failure_lanes() -> None:
    dispositions = derive_dispositions(EXPECTED_STATUS)

    assert dispositions == {
        "reader": "PASS_READER_CONFORMANCE",
        "recall_binding": "PASS_REQUIREMENT_COMPLETE_RECALL_PRECISION",
        "temporal": "PARTIAL_EVENT_POINT_ONLY_COUNT_UNRESOLVED",
        "answer": "FAIL_CORRECT_CASE_REGRESSION",
        "overall": "FAIL_SAFETY_OR_REGRESSION",
    }


def test_s10_rejects_missing_or_reclassified_stage_status() -> None:
    missing = dict(EXPECTED_STATUS)
    missing.pop("s6")
    with pytest.raises(DG22S10Error, match="denominator"):
        derive_dispositions(missing)

    reclassified = dict(EXPECTED_STATUS)
    reclassified["s8"] = "PARTIAL_MEDIATOR_PASS_ANSWER_GATE_MISS"
    with pytest.raises(DG22S10Error, match="authoritative"):
        derive_dispositions(reclassified)

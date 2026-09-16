"""A test count or one persistent lineage must never sign the testbed gate."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from seal_v0218_testbed import REQUIRED_REVIEW, requirements


def evidence():
    return {
        "status": "STRUCTURAL_VALIDATION_PASSED_PENDING_T5_SIGNOFF",
        "roots": 12,
        "coarse_families": 9,
        "boundary_rows": [{"status": "PASS"} for _ in range(12)],
        "variants": {"stable": 12, "superseded": 12, "unresolved": 12, "helpful": 2},
        "actual_both_lineages": ["schedule", "financial"],
        "A_self_note_valid_protocol": 2,
        "B_actual_both": 4,
    }, {
        "decision": "APPROVED_LIMITED_DISCOVERY",
        "review_kind": "DEVELOPER_SELF_REVIEW_NOT_INDEPENDENT_HUMAN",
        "accepted": sorted(REQUIRED_REVIEW),
        "whole_goal_complete": False,
        "unopened_C": 0,
    }


def test_limited_readiness_does_not_require_agent_error_or_whole_A_success():
    result, review = evidence()
    requirements(result, review)


@pytest.mark.parametrize(
    "gap", ["roots", "one_chain", "duplicate_chain", "canary", "review", "whole_goal", "C"]
)
def test_missing_gate_cannot_be_replaced_with_more_tests(gap):
    result, review = copy.deepcopy(evidence())
    result["unit_tests_passed"] = 100000
    if gap == "roots":
        result["roots"] = 8
    elif gap == "one_chain":
        result["actual_both_lineages"] = ["schedule"]
    elif gap == "duplicate_chain":
        result["actual_both_lineages"] = ["schedule", "schedule"]
    elif gap == "canary":
        result["boundary_rows"][0]["status"] = "FAIL"
    elif gap == "review":
        review["accepted"].remove("mixed_note_claims_separated")
    elif gap == "whole_goal":
        review["whole_goal_complete"] = True
    else:
        review["unopened_C"] = 4
    with pytest.raises(AssertionError):
        requirements(result, review)

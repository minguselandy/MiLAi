"""Missing reference proofs and incomplete readouts must not become semantic negatives."""

import pytest

from compile_collected_operation_feedback import compile_case, witness_relation


@pytest.mark.parametrize(
    "left,right,expected",
    [
        (True, True, "tie"),
        (True, False, "left"),
        (False, True, "right"),
        (False, False, "unknown"),
        (None, False, "unknown"),
        (True, None, "unknown"),
    ],
)
def test_witness_proxy_preserves_unknown(left, right, expected):
    assert witness_relation(left, right) == expected


def test_semantic_reviews_do_not_inherit_witness_labels_or_failed_answers():
    row = {
        "gold": {},
        "metadata": {},
        "state": {},
        "questions": {"next": {"criteria": {"a": "READ", "b": "HANDOFF"}}},
    }
    branches = [
        {
            "action": {"id": key},
            "reference_proof_complete": value,
            "readout_status": status,
            "readout": key,
        }
        for key, value, status in [("a", True, "FAILED"), ("b", False, "COMPLETED")]
    ]
    proxy = compile_case(row, branches)
    assert proxy["feedback"]["comparisons"][0]["delivery"] == "left"
    reviews = {
        "a": {"answer_status": "complete", "material_status": "sufficient"},
        "b": {"answer_status": "incomplete", "material_status": "sufficient"},
    }
    semantic = compile_case(row, branches, reviews)
    pair = semantic["feedback"]["comparisons"][0]
    assert pair["delivery"] == "tie" and pair["answer"] == "unknown"
    missing = compile_case(row, branches, {})
    assert missing["feedback"]["comparisons"][0]["delivery"] == "unknown"
    assert "feedback" not in row

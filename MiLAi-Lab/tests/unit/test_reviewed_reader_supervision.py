"""Alternative proofs and source uncertainty must not become false unique labels."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from reviewed_reader_supervision import relabel, reviewed_target


def test_any_complete_proof_suffices_without_reading_the_other_path():
    review = {"disposition": "supported", "complete_proofs": [[0, 1], [2]]}
    assert reviewed_target(review, [0, 1, 2], [2]) == (
        {"stop_sufficient": 1.0}, "reviewed_proof_complete")
    assert reviewed_target(review, [0, 1, 2], [0])[0] == {"open_p1": 0.5, "open_p2": 0.5}
    assert reviewed_target(review, [0, 1, 2], [0, 1])[0] == {"stop_sufficient": 1.0}


def test_already_satisfied_alternative_does_not_require_an_equivalent_extra_read():
    review = {"disposition": "supported", "complete_proofs": [[0, 1, 3], [0, 2, 3]]}
    assert reviewed_target(review, [0, 1, 2, 3], [0, 1])[0] == {"open_p3": 1.0}
    # Incomparable routes remain legal; this is not a shortest-length/cost policy.
    review["complete_proofs"] = [[0, 1], [2]]
    assert reviewed_target(review, [0, 1, 2], [])[0] == {
        "open_p0": 1 / 3, "open_p1": 1 / 3, "open_p2": 1 / 3}


def test_incomplete_pool_can_supply_a_partial_premise_before_exhaustion():
    review = {"disposition": "pool_insufficient", "complete_proofs": [],
              "useful_partial_evidence": [2]}
    assert reviewed_target(review, [2, 8], [])[0] == {"open_p0": 1.0}
    assert reviewed_target(review, [2, 8], [2])[0] == {"stop_exhausted": 1.0}


def test_reading_either_equivalent_partial_source_satisfies_that_premise():
    review = {"disposition": "pool_insufficient", "complete_proofs": [],
              "useful_partial_evidence": [1, 2, 3], "partial_evidence_groups": [[1, 2], [3]]}
    assert reviewed_target(review, [0, 1, 2, 3], [])[0] == {
        "open_p1": 0.25, "open_p2": 0.25, "open_p3": 0.5}
    assert reviewed_target(review, [0, 1, 2, 3], [1])[0] == {"open_p3": 1.0}
    assert reviewed_target(review, [0, 1, 2, 3], [2])[0] == {"open_p3": 1.0}
    assert reviewed_target(review, [0, 1, 2, 3], [2, 3])[0] == {"stop_exhausted": 1.0}


def test_ambiguity_and_missing_retrieved_proof_are_not_hard_negative_labels():
    assert reviewed_target({"disposition": "masked"}, [0], [0])[0] == {}
    assert reviewed_target({"disposition": "supported", "complete_proofs": [[0, 1]]},
                           [0, 2], [0])[0] == {}


def test_qualified_shorter_proof_masks_extra_read_without_claiming_certain_sufficiency():
    review = {"disposition": "supported", "complete_proofs": [[0, 1, 2]],
              "qualified_alternative_proofs": [[0, 1]]}
    assert reviewed_target(review, [0, 1, 2, 3], [0, 1]) == (
        {}, "masked_qualified_proof_complete")
    assert reviewed_target(review, [0, 1, 2, 3], [0, 1, 2]) == (
        {"stop_sufficient": 1.0}, "reviewed_proof_complete")
    assert reviewed_target(review, [0, 1, 2, 3], [0])[0] == {
        "open_p1": 0.5, "open_p2": 0.5}


def test_relabelling_preserves_visible_input_and_separates_dev_from_training():
    row = {"state": {"question": "visible question"}, "questions": {"next": "actions"},
           "gold": {"next": {"probabilities": {"open_p0": 1}}},
           "metadata": {"row": 8, "family": "f", "split": "dev", "event_id": "e",
                        "label_status": "old", "pool_source_indices": [2, 0],
                        "opened_source_indices": [2]}}
    original = copy.deepcopy(row)
    review = {"source_row": 8, "family": "f", "split": "dev", "review_id": "review",
              "disposition": "supported", "complete_proofs": [[2]],
              "rationale": "PRIVATE_EVALUATION_ONLY"}
    result, stats = relabel([row], [review], "dev")
    assert row == original
    assert result[0]["gold"]["next"]["probabilities"] == {"stop_sufficient": 1.0}
    assert result[0]["metadata"]["training_allowed"] is False
    assert stats["runtime_inputs_unchanged"] and stats["changed_states"] == 1
    assert "PRIVATE" not in str(result[0]["state"])
    with pytest.raises(ValueError, match="split or family"):
        relabel([row], [{**review, "family": "other"}], "dev")

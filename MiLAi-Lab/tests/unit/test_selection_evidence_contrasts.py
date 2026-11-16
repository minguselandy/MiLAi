"""Semantic changes must not be explained solely by different available actions."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from milai_lab.methods.bounded_evidence import selection_payload
from prepare_selection_evidence_contrasts import contrasts


@pytest.mark.parametrize("pool,answers", [([0, 1, 2], ("open_p0", "open_p1")),
                                        ([2, 0, 1], ("open_p1", "open_p2"))])
def test_same_actions_need_different_complements_when_observed_premise_changes(pool, answers):
    candidates = [{"id": f"p{i}", "title": f"doc{j}", "text": f"fact{j}"}
                  for i, j in enumerate(pool)]
    initial = {**selection_payload("question", [], candidates),
               "metadata": {"row": 7, "pool_source_indices": pool, "family": "f"}}
    review = {"source_row": 7, "disposition": "supported", "complete_proofs": [[0, 1]]}
    left, right = contrasts(initial, review)
    assert left["state"]["candidates"] == right["state"]["candidates"] == candidates
    assert left["questions"] == right["questions"]
    assert left["state"]["read_evidence"][0]["id"] == "observed0"
    assert right["state"]["read_evidence"][0]["id"] == "observed0"
    assert left["state"]["read_evidence"][0]["text"] == "fact1"
    assert right["state"]["read_evidence"][0]["text"] == "fact0"
    assert left["gold"]["next"]["probabilities"] == {answers[0]: 1.0}
    assert right["gold"]["next"]["probabilities"] == {answers[1]: 1.0}
    assert not left["metadata"]["training_allowed"]

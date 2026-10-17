"""Mixed-corpus inputs keep full bodies and real evidence changes without label leakage."""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from build_source_selection_states import derive, effective_reviews
from prepare_source_selection import project


def test_uuid_source_and_multiple_proofs_produce_shared_fixed_budget_inputs():
    source = {"question": "Which needed fact?", "answer": "PRIVATE_REFERENCE", "answerable": True,
              "paragraphs": [{"idx": i, "title": f"title {i}", "paragraph_text": f"fact {i}",
                              "is_supporting": i in (0, 1, 2, 3)} for i in range(10)]}
    record = {"source": source, "metadata": {"row": 5, "family": "f", "split": "dev",
              "dataset": "two_wiki", "question_id": "a-uuid-not-a-hop-number"}}
    review = {"source_row": 5, "review_id": "r5", "family": "f", "split": "dev",
              "disposition": "supported", "complete_proofs": [[0, 1, 2, 3], [4]],
              "qualified_alternative_proofs": [[0, 2]], "useful_partial_evidence": [0, 1, 2, 3, 4],
              "rationale": "PRIVATE_REVIEW"}
    rows = derive(record, review, 17)
    opened = {tuple(sorted(r["metadata"]["opened_source_indices"])) for r in rows}
    assert {(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3), (4,)} <= opened
    assert all(len(r["state"]["read_evidence"]) < 4 for r in rows)
    assert len(opened) == len(rows)
    exports, _ = project(rows, [review], "dev")
    for left, right in zip(exports["source"], exports["reference"], strict=True):
        payload = {k: left[k] for k in ("state", "questions")}
        assert payload == {k: right[k] for k in payload}
        assert "PRIVATE" not in str(payload)
        assert len(left["state"]["read_evidence"] + left["state"]["candidates"]) == 10
        assert all(action in left["questions"]["next"]["criteria"]
                   for action in left["gold"].get("next", {}).get("probabilities", {}))
        assert left["metadata"]["training_allowed"] is False


def test_projection_addendum_preserves_original_snapshot_and_answers():
    snapshot = {"cases": [{"source_row": 1, "complete_proofs": [[0]],
                            "disposition": "supported", "expected_answer": "primary"}]}
    original = copy.deepcopy(snapshot)
    addenda = {"cases": [{"source_row": 1, "additional_complete_proofs": [[0, 1]],
                           "alternative_answer": "historical alternative"}]}
    actual = effective_reviews(snapshot, addenda)
    assert snapshot == original
    assert actual["cases"][0]["complete_proofs"] == [[0], [0, 1]]
    assert actual["cases"][0]["expected_answer"] == "primary"

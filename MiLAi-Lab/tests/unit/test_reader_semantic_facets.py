"""Semantic variants preserve source identity and separate alternative proofs."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_reader_semantic_facets import facet_states


def test_alternative_proofs_keep_aliases_and_offline_targets_out_of_input():
    source = {"metadata": {"row": 4, "family": "f", "split": "train"},
              "source": {"paragraphs": [
                  {"idx": i, "title": f"Title {i}", "paragraph_text": f"Literal {i}"}
                  for i in (8, 2, 19)]}}
    facet = {"facet": "alternatives", "family": "f", "question": "Which place?",
             "pool_source_indices": [8, 2, 19], "opened_states": [[], [2], [8, 19]],
             "disposition": "supported", "complete_proofs": [[2], [8, 19]],
             "expected_answer": "SECRET"}
    rows = facet_states(source, facet)
    assert rows[0]["gold"]["next"]["probabilities"] == {
        "open_p0": 1/3, "open_p1": 1/3, "open_p2": 1/3}
    for row in rows[1:]:
        assert row["gold"]["next"]["probabilities"] == {"stop_sufficient": 1.0}
        assert "SECRET" not in str({k: row[k] for k in ("state", "questions")})
    assert rows[1]["state"]["read_evidence"][0] == {
        "id": "p1", "title": "Title 2", "text": "Literal 2"}
    assert [r["id"] for r in rows[1]["state"]["candidates"]] == ["p0", "p2"]
    source["metadata"]["split"] = "dev"
    with pytest.raises(ValueError, match="training family"):
        facet_states(source, facet)

"""Support identity must survive aliases and transitive relation-chain overlap."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from intake_two_wiki_selection import group_sources


def test_shared_entity_or_title_connects_families_transitively():
    def row(qid, entities, title):
        return {"_id": qid, "entity_ids": entities, "supporting_facts": [[title, 0]],
                "type": "compositional"}

    rows = [row("a", "Q1_Q2", "Alpha"), row("b", "Q2_Q3", "Different alias"),
            row("c", "Q9_Q10", "Different alias"), row("d", "Q11_Q12", "Independent")]
    families = group_sources(rows)
    assert [f["question_ids"] for f in families] == [["a", "b", "c"], ["d"]]
    assert families[0]["rows"] == [0, 1, 2]

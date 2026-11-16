"""New collection may not replay T0 groups or reveal native reference fields."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_host_intent_t1 import prepare_sources


def fixture():
    t0 = {"histories": [{"id": "old", "source_group": "old", "split": "train",
                         "sources": [], "requests": [{"id": "early", "content": "Task"}]}]}
    group = {"family": "new", "dataset": "two_wiki_author_train",
             "question_id": "question-1", "source_rows": [7]}
    allocation = {"new_sources": {"train": [], "dev": [group]}}
    reference = {"metadata": {"dataset": group["dataset"], "family": "new",
        "source_row": 7, "split": "dev"}, "source": {
            "id": "question-1", "question": "Public question", "answer": "offline-only",
            "answerable": True, "paragraphs": [{"idx": 0, "title": "Source",
                "paragraph_text": "Literal passage", "is_supporting": True}]}}
    return allocation, t0, [reference]


def test_new_collection_keeps_inherited_dev_and_public_t0_inputs():
    allocation, t0, references = fixture()
    new, full = prepare_sources(allocation, t0, references)
    assert full["histories"][:-1] == t0["histories"]
    assert len(new["histories"]) == 1
    history = new["histories"][0]
    assert history["split"] == "dev" and history["source_group"] == "new"
    request = history["requests"][0]
    assert request["sources"][0]["content"] == "Source\nLiteral passage"
    references[0]["source"]["answer"] = "different-hidden-label"
    references[0]["source"]["paragraphs"][0]["is_supporting"] = False
    assert prepare_sources(allocation, t0, references) == (new, full)


def test_existing_group_cannot_be_replayed_as_a_new_group():
    allocation, t0, references = fixture()
    allocation["new_sources"]["dev"][0]["family"] = "old"
    with pytest.raises(ValueError, match="repeat a closed T0"):
        prepare_sources(allocation, t0, references)

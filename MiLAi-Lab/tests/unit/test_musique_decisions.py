"""Missing complements, literal alternatives, and masked retrieval failures."""

import copy
from pathlib import Path

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    import prepare_musique_decisions

    return prepare_musique_decisions


def source():
    return {"id": "q", "question": "Who supplies the station?", "answerable": True,
            "answer": "offline answer", "question_decomposition": [{"id": 1}],
            "paragraphs": [
                {"title": "station", "paragraph_text": "First premise", "is_supporting": True},
                {"title": "supplier", "paragraph_text": "Second premise", "is_supporting": True},
                {"title": "noise", "paragraph_text": "Irrelevant", "is_supporting": False},
            ]}


def test_two_complements_are_useful_before_an_answer_is_possible(module):
    row = source()
    assert module.action_supervision(row, [0, 1, 2], []) == (
        {"open_p0": 0.5, "open_p1": 0.5}, "missing_complement")
    assert module.action_supervision(row, [0, 1, 2], [0]) == (
        {"open_p1": 1.0}, "missing_complement")
    assert module.action_supervision(row, [0, 1, 2], [0, 1]) == (
        {"stop_sufficient": 1.0}, "reference_proof_complete")


def test_answerable_retrieval_gap_is_masked_not_false_exhaustion(module):
    row = source()
    target, reason = module.action_supervision(row, [0, 2], [0])
    assert target == {}
    assert reason == "masked_retrieval_gap_or_unannotated_alternative"
    row["answerable"] = False
    assert module.action_supervision(row, [0, 2], [0]) == (
        {"stop_exhausted": 1.0}, "official_unanswerable_pool")


def test_equivalent_supports_share_mass_and_satisfy_the_same_requirement(module):
    row = source()
    row["paragraphs"].append({**row["paragraphs"][0], "is_supporting": False})
    assert module.action_supervision(row, [0, 1, 3], [1])[0] == {
        "open_p0": 0.5, "open_p2": 0.5}
    assert module.action_supervision(row, [0, 1, 3], [1, 3])[0] == {
        "stop_sufficient": 1.0}


def test_source_labels_cannot_change_retrieval_or_runtime_state(module):
    row = source()
    changed = copy.deepcopy(row)
    changed["answer"] = "hidden change"
    changed["question_decomposition"] = [{"id": 999, "answer": "hidden"}]
    for p in changed["paragraphs"]:
        p["is_supporting"] = not p["is_supporting"]
    assert module.ranked_pool(row, 2) == module.ranked_pool(changed, 2)
    metadata = {"row": 0, "family": "f0", "split": "train"}
    a = module.derive_states({"source": row, "metadata": metadata}, 2)[0]
    b = module.derive_states({"source": changed, "metadata": metadata}, 2)[0]
    assert a["state"] == b["state"]
    assert a["questions"] == b["questions"]
    assert "probabilities" in a["gold"]["next"]

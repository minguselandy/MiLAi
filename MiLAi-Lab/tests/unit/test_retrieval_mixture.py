"""Task mixing must preserve source boundaries and not confuse loss mass with draws."""
import copy
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from retrieval_mixture import (
    combine_components,
    event_weights,
    mixture_event_weights,
    project_mixed_row,
    score_mixed_predictions,
)


def example(identity, family, task="memory_operation", split="train", masked=False):
    question = "next" if task == "memory_operation" else "applicability"
    choices = ({"read": "READ", "handoff": "HANDOFF"} if task == "memory_operation"
               else {"satisfies": "yes", "does_not_satisfy": "no"})
    first = next(iter(choices))
    return {"state": {"task": {"request": "Literal request"}, "candidate": {"text": "Literal"}},
            "questions": {question: {"type": "choice", "criteria": choices}},
            "gold": {} if masked else {question: {"probabilities": {first: 1.0}}},
            "metadata": {"event_id": identity, "family": family, "row": identity,
                         "split": split, "label_status": "reviewed",
                         "action_kinds": {"read": "READ", "handoff": "HANDOFF"}}}


def test_composition_preserves_public_inputs_masks_and_pre_mask_ids():
    parts = [
        {"name": "operations", "task": "memory_operation", "loss_weight": 3,
         "rows": [example("a", "f"), example("b", "f", masked=True)]},
        {"name": "instructions", "task": "instruction_applicability", "loss_weight": 1,
         "rows": [example("c", "g", "instruction_applicability"),
                  example("d", "h", "instruction_applicability", "dev")]},
    ]
    original = copy.deepcopy(parts)
    data, masses = combine_components(parts)
    assert parts == original
    originals = {r["metadata"]["event_id"]: r for p in parts for r in p["rows"]}
    for row in [*data["train"], *data["dev"]]:
        source = originals[row["metadata"]["event_id"]]
        assert {k: row[k] for k in ("state", "questions", "gold")} == {
            k: source[k] for k in ("state", "questions", "gold")}
    assert [r["metadata"]["state_id"] for r in data["train"] if r["gold"]] == [0, 2]
    assert data["dev"][0]["metadata"]["state_id"] == 3
    assert masses == {"operations": 0.75, "instructions": 0.25}


def test_shared_source_family_cannot_cross_splits_even_across_tasks():
    parts = [{"name": "op", "task": "memory_operation", "loss_weight": 1,
              "rows": [example("a", "shared")]},
             {"name": "ir", "task": "instruction_applicability", "loss_weight": 1,
              "rows": [example("b", "shared", "instruction_applicability", "dev")]}]
    with pytest.raises(ValueError, match="crosses training and development"):
        combine_components(parts)


def test_duplicate_examples_are_not_extra_supervision():
    row = example("a", "f")
    with pytest.raises(ValueError, match="Duplicate task example"):
        combine_components([{"name": "op", "task": "memory_operation", "loss_weight": 1,
                             "rows": [row, row]}])


def test_loss_mass_is_component_then_family_then_event():
    rows = [{"metadata": {"family": family, "row": event, "component": component}}
            for component, family, event, copies in (
                ("op", "a", 0, 7), ("op", "a", 1, 2), ("op", "b", 2, 1),
                ("ir", "c", 3, 1), ("ir", "d", 4, 1)) for _ in range(copies)]
    weights = mixture_event_weights(rows, {"op": 3, "ir": 1})
    mass = defaultdict(float)
    for row, weight in zip(rows, weights, strict=True):
        m = row["metadata"]
        mass[m["component"], m["family"], m["row"]] += weight
    assert sum(weights) == pytest.approx(12)
    assert mass["op", "a", 0] == pytest.approx(2.25)
    assert mass["op", "a", 1] == pytest.approx(2.25)
    assert mass["op", "b", 2] == pytest.approx(4.5)
    assert mass["ir", "c", 3] == pytest.approx(1.5)
    assert mass["ir", "d", 4] == pytest.approx(1.5)
    assert mixture_event_weights(rows[:10], {"op": 1}) == event_weights(rows[:10])


def test_mixed_metrics_do_not_merge_applicability_and_operation_success():
    data, _ = combine_components([
        {"name": "op", "task": "memory_operation", "loss_weight": 1,
         "rows": [example("a", "a")]},
        {"name": "ir", "task": "instruction_applicability", "loss_weight": 1,
         "rows": [example("b", "b", "instruction_applicability")]},
    ])
    rows = data["train"]
    rows[0]["state"]["pending_candidates"] = [
        {"item_index": i, "kind": "original_source", "text": "Repeated source text. " * 50}
        for i in range(3)]
    assert "observation_encoding" in project_mixed_row(rows[0], "shared")["state"]
    assert project_mixed_row(rows[1], "mechanical") == rows[1]
    scores = score_mixed_predictions(rows, [{"choice": "read"}, {"choice": "does_not_satisfy"}])
    assert scores["by_task"]["memory_operation"]["counts"] == {"labelled": 1, "accepted": 1}
    assert scores["by_task"]["instruction_applicability"]["counts"] == {
        "labelled": 1, "correct": 0}
    assert set(scores) == {"by_task", "by_component", "scope"}

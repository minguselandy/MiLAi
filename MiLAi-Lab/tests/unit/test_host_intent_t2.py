"""Training-only source selection and exact reviewed-state aggregation."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import prepare_host_intent_t2
from milai_lab.methods.retrieval_supervision import annotate_decisions
from prepare_host_intent_t2 import aggregate, select_histories, source_registry


def row(family, identity, *, split="train", state_id=None):
    item = {
        "state": {"task": {"retrieval_request": {"query": "Which date?"}}},
        "questions": {"next": {"type": "choice", "criteria": {"read": "READ", "done": "HANDOFF"}}},
        "gold": {}, "metadata": {"family": family, "split": split, "event_id": identity,
                                "label_status": "unreviewed_masked", "collection_policy": "laya"}}
    if state_id is not None:
        item["metadata"].update(state_id=state_id, task="memory_operation",
                                component="operation_history")
        item["gold"] = {"next": {"probabilities": {"read": 1.0, "done": 0.0}}}
    return item


def test_selection_uses_groups_and_preserves_whole_histories_without_development():
    data = {"train": [row(f"train-{i}", str(i), state_id=i) for i in range(10)],
            "dev": [row("dev", "d", split="dev", state_id=10)]}
    fixture = {"histories": [
        {"id": family, "source_group": family, "split": split,
         "sources": [{"content": "Literal source"}],
         "requests": [{"id": "before", "content": "First"},
                      {"id": "after", "incoming_sources": [{"content": "Changed source"}]}]}
        for split in data for family in [r["metadata"]["family"] for r in data[split]]]}
    original = copy.deepcopy(fixture)
    public, selection = select_histories(fixture, source_registry(data), count=4, seed=0)
    assert selection["source_groups"] == 4
    assert selection["request_positions_per_interface"] == 8
    assert "dev" not in selection["selected_groups"]
    assert all(h in original["histories"] and h["split"] == "train" for h in public["histories"])
    assert select_histories({"histories": list(reversed(fixture["histories"]))},
                            source_registry(data), count=4, seed=0)[0] == public
    assert fixture == original
    fixture["histories"][-1]["split"] = "train"
    with pytest.raises(ValueError, match="inherited source split"):
        select_histories(fixture, source_registry(data), count=4, seed=0)


def test_aggregation_preserves_old_ids_dev_and_masks_and_matches_update_budget():
    data = {"train": [row("f", "old", state_id=10)],
            "dev": [row("dev", "dev", split="dev", state_id=20)]}
    raw = [row("f", "own-0"), row("f", "own-1")]
    reviews = [{"event_id": "own-0", "preferred_actions": ["read"], "basis": "source review"}]
    reviewed = annotate_decisions(raw, reviews)
    original = copy.deepcopy((data, raw, reviewed))
    result, report = aggregate(data, raw, reviewed, {"selected_groups": ["f"]},
                               collector_policy="laya")
    assert result["train"][:1] == data["train"] and result["dev"] == data["dev"]
    assert [r["metadata"]["state_id"] for r in result["train"]] == [10, 21, 22]
    assert result["train"][2]["gold"] == {}
    assert report["own_rows"] == 2 and report["own_labelled"] == 1
    assert report["effective_train_rows"] == 2 and report["optimizer_updates_each_arm"] == 1
    assert report["row_draws_each_arm"] == 16
    for actual, expected in zip(result["train"][1:], reviewed, strict=True):
        assert {k: actual[k] for k in ("state", "questions", "gold")} == {
            k: expected[k] for k in ("state", "questions", "gold")}
    assert (data, raw, reviewed) == original


@pytest.mark.parametrize("problem", ["dev", "outside", "duplicate", "changed", "teacher", "masked"])
def test_aggregation_requires_actual_selected_training_states_and_explicit_reviews(problem):
    data = {"train": [row("f", "old", state_id=0)],
            "dev": [row("dev", "d", split="dev", state_id=1)]}
    raw = [row("dev" if problem == "dev" else "outside" if problem == "outside" else "f",
               "old" if problem == "duplicate" else "new",
               split="dev" if problem == "dev" else "train")]
    if problem == "teacher":
        raw[0]["metadata"]["collection_policy"] = "rules"
    reviews = [] if problem == "masked" else [
        {"event_id": raw[0]["metadata"]["event_id"], "preferred_actions": ["read"]}]
    reviewed = annotate_decisions(raw, reviews)
    if problem == "changed":
        reviewed[0]["state"]["task"]["retrieval_request"]["query"] = "Changed input"
    with pytest.raises(ValueError):
        aggregate(data, raw, reviewed, {"selected_groups": ["f"]}, collector_policy="laya")


def test_cli_copies_common_files_and_only_appends_own_rows(tmp_path, monkeypatch):
    data = tmp_path / "old"
    data.mkdir()
    old = row("f", "old", state_id=0)
    dev = row("dev", "d", split="dev", state_id=1)
    (data / "train.jsonl").write_text(json.dumps(old))  # Valid final JSONL row without newline.
    (data / "dev.jsonl").write_text(json.dumps(dev) + "\n")
    (data / "mixture.json").write_text('{"operation_history":1.0}\n')
    raw = [row("f", "new")]
    reviewed = annotate_decisions(raw, [{"event_id": "new", "preferred_actions": ["read"]}])
    selection = tmp_path / "selection.json"
    selection.write_text('{"selected_groups":["f"]}')
    for name, rows in (("raw", raw), ("reviewed", reviewed)):
        (tmp_path / f"{name}.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in rows))
    output = tmp_path / "prepared"
    monkeypatch.setattr(sys, "argv", ["prepare_host_intent_t2", "aggregate", str(data),
        str(selection), str(tmp_path / "raw.jsonl"), str(tmp_path / "reviewed.jsonl"),
        str(output), "--source-version", "mechanical"])
    prepare_host_intent_t2.main()
    for name in ("train.jsonl", "dev.jsonl", "mixture.json"):
        assert (output / "continued-ce" / name).read_bytes() == (data / name).read_bytes()
    assert (output / "aggregate/dev.jsonl").read_bytes() == (data / "dev.jsonl").read_bytes()
    assert (output / "aggregate/mixture.json").read_bytes() == (data / "mixture.json").read_bytes()
    augmented = prepare_host_intent_t2.read_rows(output / "aggregate/train.jsonl")
    assert augmented[0] == old and len(augmented) == 2
    assert augmented[1]["metadata"]["state_id"] == 2
    assert augmented[1]["gold"] == reviewed[0]["gold"]

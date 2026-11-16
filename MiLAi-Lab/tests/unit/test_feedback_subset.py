"""Nested source curves keep the same original matched rows and exact Unicode JSONL bytes."""
import copy
import json
import sys

import pytest
from test_feedback_training_preparation import build, fixture

from prepare_feedback_subset import main, subset_pairs


def parent_pool():
    old, dev, feedback = fixture()
    feedback[0]["state"]["text"] = "First\u2028second\u2029third\u0085last"
    feedback[1]["metadata"]["family"] = "later-source"
    data, report = build(old, dev, feedback)
    return data, report


def test_subset_keeps_original_ids_pairs_ties_unknowns_and_explicit_common_update_budget():
    data, parent = parent_pool()
    before = copy.deepcopy((data, parent))
    indices, report = subset_pairs(data["feedback"], data["continued-ce"], parent,
                                    ["own-source", "missing-source"], 192)
    assert indices == [0, 2, 3, 5]
    assert report["groups_without_feedback"] == ["missing-source"]
    assert report["optimizer_updates"] == 192 and report["row_draws_each_arm"] == 3072
    assert report["feedback"]["answer"]["tie_pairs"] == 2
    assert report["feedback"]["delivery"]["unknown_pairs"] == 1
    assert report["shared_replay_event_ids"] == [
        parent["shared_replay_event_ids"][i] for i in (0, 2)]
    assert (data, parent) == before


def test_changed_parent_pairing_is_not_silently_matched_again():
    data, parent = parent_pool()
    data["continued-ce"][0], data["continued-ce"][1] = (
        data["continued-ce"][1], data["continued-ce"][0])
    with pytest.raises(ValueError, match="matching identities"):
        subset_pairs(data["feedback"], data["continued-ce"], parent, ["own-source"], 192)


def test_cli_preserves_physical_lines_and_dev_bytes_without_recompiling(tmp_path, monkeypatch):
    data, report = parent_pool()
    parent, output = tmp_path / "parent", tmp_path / "subset"
    parent.mkdir()
    for arm in ("feedback", "continued-ce"):
        folder = parent / arm
        folder.mkdir()
        (folder / "train.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data[arm]))
        (folder / "dev.jsonl").write_text(' {"dev": "unchanged Ω"}\n')
        (folder / "feedback-dev.jsonl").write_text('{"feedback-dev": "unchanged"}\n')
    (parent / "preparation.json").write_text(json.dumps(report))
    groups = tmp_path / "groups.json"
    groups.write_text(json.dumps({"selected_groups": ["own-source"]}))
    monkeypatch.setattr(sys, "argv", ["subset", str(parent), str(groups), str(output),
                                      "--optimizer-updates", "192"])
    main()
    for arm in ("feedback", "continued-ce"):
        with (parent / arm / "train.jsonl").open("rb") as stream:
            lines = list(stream)
        expected = b"".join(lines[i] for i in (0, 2, 3, 5))
        assert (output / arm / "train.jsonl").read_bytes() == expected
        for name in ("dev.jsonl", "feedback-dev.jsonl"):
            assert (output / arm / name).read_bytes() == (parent / arm / name).read_bytes()
    assert not json.loads((output / "preparation.json").read_text())["labels_recompiled"]

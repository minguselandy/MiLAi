"""Coverage controls repeat actual initial states, not post labels or fictional observations."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_quality_fit_audit import row

from feedback_coverage import compile_coverage_controls
from quality_feedback import quality_event_weights
from train_bounded_laya import training_stages


def fixture():
    rows = []
    for family in ("A", "B", "C"):
        for collector in ("rules", "laya"):
            for step in (0, 1):
                known = (family == "A" or (family == "B" and (
                    (collector, step) in {("rules", 0), ("laya", 1)}))
                    or (family == "C" and step == 0))
                identity = f"{family}/{collector}/{step}"
                value = row(identity, family, len(rows), unknown=not known)
                value["state"]["text"] = "Actual input " + identity
                value["metadata"].update(split="train", collection_policy=collector,
                    control_step=step, training_event=identity)
                rows.append(value)
    for index in range(12):
        value = row(f"old-{index}", "old", 100 + index, replay=True)
        value["metadata"].update(split="train", training_event=f"old-event-{index}")
        rows.append(value)
    return rows


def test_common_family_filter_keeps_collectors_unknown_states_and_original_objects():
    rows = fixture()
    before = copy.deepcopy(rows)
    result = compile_coverage_controls(rows)
    assert rows == before
    assert result["eligible_families"] == ["A", "B"]
    assert result["excluded_families"] == [{"family": "C",
        "all_collector_stage_slots_present": True, "has_known_target_initial": True,
        "has_known_target_post": False}]
    assert result["collectors"] == ["rules", "laya"]
    assert result["counts"]["initial_only"]["unique_feedback_states"] == 4
    assert result["counts"]["initial_post"]["unique_feedback_states"] == 8
    assert result["counts"]["initial_only"]["actual_stage_counts"] == {"initial": 8}
    assert result["counts"]["initial_post"]["actual_stage_counts"] == {"initial": 4, "post": 4}
    for slot in result["mapping"]:
        for arm in ("initial_only", "initial_post"):
            assert result["arms"][arm][slot["position"]] == rows[slot[arm + "_source_index"]]
    assert result["arms"]["initial_only"][8:] == result["arms"]["initial_post"][8:] == rows[12:20]


def test_duplicate_initials_do_not_create_new_identity_or_loss_mass():
    result = compile_coverage_controls(fixture())
    replay_weights = []
    for arm in result["arms"].values():
        weights = quality_event_weights(arm, "answer", "quality-direction", .25)
        assert sum(weights[:8]) / len(arm) == pytest.approx(.8)
        assert sum(weights[8:]) / len(arm) == pytest.approx(.2)
        for family in ("A", "B"):
            assert sum(w for r, w in zip(arm[:8], weights[:8], strict=True)
                       if r["metadata"]["family"] == family) / len(arm) == pytest.approx(.4)
        replay_weights.append(weights[8:])
    assert replay_weights[0] == replay_weights[1]
    initial = result["arms"]["initial_only"][:8]
    assert initial[0] == initial[1]
    assert initial[0]["metadata"]["event_id"] == initial[1]["metadata"]["event_id"]
    assert initial[0]["metadata"]["state_id"] == initial[1]["metadata"]["state_id"]
    assert any(weight == 0 for weight in quality_event_weights(
        result["arms"]["initial_only"], "answer", "quality-direction", .25)[:8])


def test_draw_indices_and_exact_replay_sequence_match_across_controls():
    result = compile_coverage_controls(fixture())
    arms = result["arms"]
    stages = training_stages(len(arms["initial_only"]), 1, 0, 7, [2, 4, 7])
    draws = [(data_pass, i) for _, windows in stages for window in windows
             for data_pass, i in window]
    assert len(draws) == 112
    replay = []
    for arm in arms.values():
        replay.append([(data_pass, arm[i]) for data_pass, i in draws if "feedback" not in arm[i]])
    assert replay[0] == replay[1]


def test_missing_actual_slot_is_reported_instead_of_fabricated():
    rows = fixture()
    rows = [r for r in rows if r["metadata"]["event_id"] != "A/laya/1"]
    result = compile_coverage_controls(rows)
    assert result["eligible_families"] == ["B"]
    excluded = next(r for r in result["excluded_families"] if r["family"] == "A")
    assert excluded["all_collector_stage_slots_present"] is False


@pytest.mark.parametrize("change", ["dev", "duplicate", "extra_post", "replay_short"])
def test_invalid_original_pool_cannot_be_silently_repaired(change):
    rows = fixture()
    if change == "dev":
        rows[0]["metadata"]["split"] = "dev"
    elif change == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif change == "extra_post":
        extra = copy.deepcopy(rows[1])
        extra["metadata"].update(event_id="extra-post", state_id=99, control_step=2)
        rows.append(extra)
    else:
        rows = rows[:13]
    with pytest.raises(ValueError):
        compile_coverage_controls(rows)


def test_cli_keeps_development_bytes_and_source_identity(tmp_path):
    source, output = tmp_path / "source", tmp_path / "controls"
    source.mkdir()
    rows = fixture()
    (source / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for name in ("dev.jsonl", "feedback-dev.jsonl"):
        (source / name).write_text('{"uninspected_dev":"原文\u2028保留"}\n')
    originals = {p.name: p.read_bytes() for p in source.iterdir()}
    root = Path(__file__).resolve().parents[2]
    subprocess.run(  # noqa: S603 -- fixed repository CLI, synthetic test-owned input
        [sys.executable, str(root / "tools/prepare_feedback_coverage_controls.py"),
         str(source), str(output)], env={**os.environ, "PYTHONPATH":
            str(root / "src") + ":" + str(root / "tools")}, check=True, capture_output=True)
    for arm in ("initial_only", "initial_post"):
        for name in ("dev.jsonl", "feedback-dev.jsonl"):
            assert (output / arm / name).read_bytes() == originals[name]
    assert originals == {p.name: p.read_bytes() for p in source.iterdir()}

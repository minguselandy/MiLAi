"""Captured preprocessing consumes budget; prior interventions preserve saved models."""
import copy
import json
import re
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

import native_qa_control as native
from milai_lab.datasets.hotpot_memory import export_question
from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel
from milai_lab.methods.small_memory_policy import PolicyScores


class Capacity:
    def __init__(self, config=None):
        self.tokenizer = lambda text, **kwargs: {"offset_mapping": [
            (m.start(), m.end()) for m in re.finditer(r"\S+", text)]}

    def text_tokens(self, text):
        return len(text.split())

    def check(self, messages):
        return {}


def source_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "HostCapacity", Capacity)
    history, _ = export_question({"id": "two-facts", "question": "Which two facts?",
        "answer": "both", "type": "bridge", "level": "hard",
        "context": {"title": ["One", "Two"],
                    "sentences": [["First actual fact."], ["Second actual fact."]]},
        "supporting_facts": {"title": ["One", "Two"], "sent_id": [0, 0]}},
        "train", ordinal=0)
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "sources.json").write_text(json.dumps({"histories": [history]}))
    config = tmp_path / "reader.json"
    config.write_text(json.dumps({"entrypoints": {"functional": {
        "host": {"base_url": "http://unused.invalid/v1", "model": "test", "max_tokens": 64},
        "system_prompt": "Answer from the supplied sources.",
        "capacity": {"enable_thinking": False}}}}))
    return history, SimpleNamespace(reader_config=config, sources=sources, roots=1,
        output=tmp_path / "common", reuse_banks=None, initial_states_from=None,
        initial_policy="rules4", methods=["rules4"], checkpoint=[], historical_checkpoint=[],
        cosine_backbone=None, device="cpu", material_tokens=2048, control_steps=3,
        evidence_units=True, evidence_context_turn_radius=1, source_directory_only=True,
        profile_retrieval=False, teacher_continuation_steps=None)


def test_actual_after_lookup_restore_keeps_consumed_step_and_remaining_budget(
    tmp_path, monkeypatch,
):
    history, args = source_fixture(tmp_path, monkeypatch)
    native.prepare_packets(args)
    common = args.output
    snapshots = [json.loads(x) for x in (common / "banks" / history["id"] /
        "question-rules4-checkpoints.jsonl").read_text().splitlines()]
    assert snapshots[1]["decision"]["step"] == 1
    args = copy.copy(args)
    args.output = tmp_path / "after-lookup"
    args.reuse_banks = args.initial_states_from = common
    args.initial_decision_index = 1
    native.prepare_packets(args)
    run = json.loads((args.output / "run.json").read_text())
    assert run["initial_decision_index"] == 1 and run["captured_prefix_steps_consumed"]
    assert run["captured_prefix_steps_by_task"] == {history["id"] + "/question": 1}
    actual = json.loads((args.output / "trajectories.json").read_text())[0]["trace"]["trace"]
    assert [e["step"] for e in actual] == [0, 1, 2]
    assert actual[0]["inherited_prefix"] is True
    assert actual[0]["selection_mode"] == "captured_common_prefix"
    assert actual[1]["before"] == snapshots[1]["decision"]["before"]
    assert actual[1]["actions"] == snapshots[1]["decision"]["actions"]
    assert [e["before"]["budget"]["remaining_control_steps"] for e in actual] == [3, 2, 1]
    assert run["Reader_calls"] == 0


@pytest.mark.parametrize("mutation", [
    "task", "query", "last_result", "prefix_steps", "prefix_task",
])
def test_mismatched_task_or_prefix_is_rejected(tmp_path, monkeypatch, mutation):
    history, args = source_fixture(tmp_path, monkeypatch)
    native.prepare_packets(args)
    path = args.output / "banks" / history["id"] / "question-rules4-checkpoints.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    if mutation == "task":
        rows[1]["event_id"] = "another-task"
    elif mutation == "query":
        rows[1]["decision"]["before"]["task"]["request"] = "another-question"
    elif mutation == "last_result":
        rows[1]["decision"]["before"]["last_result"] = None
    else:
        trajectory = args.output / "trajectories.json"
        value = json.loads(trajectory.read_text())
        if mutation == "prefix_steps":
            value[0]["trace"]["trace"][0]["step"] = 1
        else:
            value[0]["trace"]["trace"][0]["before"]["task"]["request"] = "other"
        trajectory.write_text(json.dumps(value))
    path.write_text("".join(json.dumps(x) + "\n" for x in rows))
    with pytest.raises(ValueError, match=r"another task|prefix"):
        native.captured_control_start(args.output, history["id"], "question",
            history["id"] + "/question", history["requests"][0]["query"], decision_index=1)


def test_zero_prior_override_is_inference_only_and_saved_config_is_unchanged(
    tmp_path, monkeypatch,
):
    import torch

    _, args = source_fixture(tmp_path, monkeypatch)
    config = SmallControlConfig("frozen_mlp", "unused", prior_policy="fixed_context",
                                prior_menu_order="bound_parameters_v2")
    checkpoint = tmp_path / "saved"
    checkpoint.mkdir()
    saved = json.dumps(asdict(config))
    (checkpoint / "config.json").write_text(saved)
    loaded = []

    class Model:
        def __init__(self):
            self.config = config
            self.counters = {"forwards": 0}

        def score(self, online):
            self.counters["forwards"] += 1
            ids = [a["id"] for a in online["actions"]]
            raw = torch.tensor([float(a["kind"] == "READ") for a in online["actions"]])
            return PolicyScores(ids, SmallControlModel.with_prior(self, raw, online).tolist())

    def load(*args, **kwargs):
        model = Model()
        loaded.append(model)
        return model

    monkeypatch.setattr(native.SmallControlModel, "load", load)
    args.methods = []
    args.checkpoint = [("learner", checkpoint)]
    args.inference_prior_margin = 0.0
    native.prepare_packets(args)
    recorded = json.loads((args.output / "run.json").read_text())["inference_prior_overrides"]
    assert recorded["learner"]["stored_config"]["prior_margin"] == 1
    assert recorded["learner"]["effective_config"]["prior_margin"] == 0
    assert recorded["learner"]["weights_changed"] is False
    assert loaded[0].config.prior_margin == 0 and config.prior_margin == 1
    assert (checkpoint / "config.json").read_text() == saved


@pytest.mark.parametrize("margin", [-1, float("nan"), float("inf"), True])
def test_invalid_prior_override_fails_before_any_output(tmp_path, margin):
    args = SimpleNamespace(initial_states_from=None, checkpoint=[("model", Path("unused"))],
                           inference_prior_margin=margin, output=tmp_path / "output")
    with pytest.raises(ValueError, match="finite nonnegative"):
        native.prepare_packets(args)
    assert not args.output.exists()


def test_nonzero_initial_index_needs_snapshot_and_zero_budget_default_is_preserved(
    tmp_path, monkeypatch,
):
    _, args = source_fixture(tmp_path, monkeypatch)
    args.initial_decision_index = 1
    with pytest.raises(ValueError, match="captured common prefix"):
        native.prepare_packets(args)
    assert not args.output.exists()
    args.initial_decision_index = 0
    args.control_steps = 0
    native.prepare_packets(args)
    assert not json.loads((args.output / "trajectories.json").read_text())[0]["trace"]["trace"]


def test_consumed_prefix_cannot_receive_a_new_full_control_budget(tmp_path, monkeypatch):
    _, args = source_fixture(tmp_path, monkeypatch)
    native.prepare_packets(args)
    common = args.output
    args = copy.copy(args)
    args.output = tmp_path / "no-remaining-budget"
    args.reuse_banks = args.initial_states_from = common
    args.initial_decision_index = 1
    args.control_steps = 1
    with pytest.raises(ValueError, match="no policy control budget"):
        native.prepare_packets(args)
    run = json.loads((args.output / "run.json").read_text())
    assert run["status"] == "FAILED" and run["Reader_calls"] == 0

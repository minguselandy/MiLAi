"""Complete executable arguments survive native option clipping in an explicit condition."""
import copy
import json
from dataclasses import asdict
from itertools import permutations

import pytest
from test_operation_input_diagnostics import tokenizer

from audit_action_encoding import option_encoding
from audit_request_text import check_projection
from milai_lab.memory.literal_projection import expand_observation_state
from milai_lab.methods.laya_memory_policy import (
    ACTION_BINDING_INSTRUCTIONS,
    GenerativeMemoryPolicy,
    LayaMemoryPolicy,
    operation_payload,
    payload_actions,
    project_operation_payload,
)
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from retrieval_mixture import project_mixed_row


def inputs(w4=False):
    literal = 'Original source: "quoted" Ω😀 {braces}; no fabricated clocks. '
    state = MemoryControlState(
        task={"retrieval_request": {"query": "alpha", "read_goal": {"required_points": ["beta"]}}},
        new_events=[{"source_ref": f"source-{i}", "content": literal} for i in range(3)])
    if w4:
        state.observed_materials, state.observed_evidence = [], []
    actions = [MemoryAction("alpha", "REFRESH_VIEW", 'target {a} "b" ', {
        "sources": [f"literal-source-{i}" for i in range(40)],
        "tail": {"table": {"literal": [None, False, 0, 0.0, "delta"]}}}),
        MemoryAction("beta", "SEARCH", "", {"query": "gamma " * 80 + "delta"}),
        MemoryAction("gamma", "HANDOFF", "Reader")]
    event = {"before": state.project(), "actions": [asdict(a) for a in actions]}
    row = decision_example(event, {"family": "offline", "event_id": "case/0",
                                   "task": "memory_operation"})
    row["gold"] = {"next": {"probabilities": {"alpha": 0.7, "beta": 0.3}}}
    return state, actions, event, row


@pytest.mark.parametrize("projection", ["shared_actions", "shared_actions_request_text"])
@pytest.mark.parametrize("w4", [False, True])
def test_export_live_generation_and_repeated_projection_keep_exact_bindings(projection, w4):
    state, actions, event, row = inputs(w4)
    before = copy.deepcopy(row)
    training = project_mixed_row(row, projection)
    expected = {key: training[key] for key in ("state", "questions")}
    exported = decision_example(event, row["metadata"], projection=projection)
    assert expected == {key: exported[key] for key in ("state", "questions")}
    assert operation_payload(state, actions, projection) == expected
    assert project_operation_payload(training, projection) == training
    assert payload_actions(training) == actions
    assert training["gold"] == before["gold"] and training["metadata"] == before["metadata"]
    assert row == before
    assert training["questions"]["next"]["instructions"].count(ACTION_BINDING_INSTRUCTIONS) == 1
    restored = expand_observation_state(training["state"])
    assert restored.pop("action_bindings") == [asdict(a) for a in actions]
    assert ("observed_materials" in restored) is w4
    if projection.endswith("request_text"):
        check_projection(row, training, "shared_actions")
    else:
        assert restored == state.project()
    seen = []
    assert LayaMemoryPolicy(lambda p: seen.append(p) or {"choice": "alpha"},
                            projection).choose(state, actions) == "alpha"
    assert seen == [expected]
    calls = []
    assert GenerativeMemoryPolicy(lambda phase, messages, schema:
        calls.append(messages) or {"choice": "beta"}, projection).choose(state, actions) == "beta"
    wire = json.loads(calls[0][-1]["content"])
    assert wire == json.loads(json.dumps(expected))
    assert json.dumps(expand_observation_state(wire["state"])["action_bindings"],
                      sort_keys=True) == json.dumps([asdict(a) for a in actions], sort_keys=True)


def test_previously_shared_legacy_export_matches_live_projection_without_reinterpreting_literals():
    state, actions, _, row = inputs()
    legacy = project_operation_payload(row, "shared")
    assert "action_bindings" not in legacy["state"]
    assert legacy["questions"] == row["questions"]
    assert expand_observation_state(legacy["state"]) == state.project()
    projected = project_operation_payload(legacy, "shared_actions")
    assert {key: projected[key] for key in ("state", "questions")} == operation_payload(
        state, actions, "shared_actions")
    assert projected["questions"]["next"]["criteria"] == {a.id: a.kind for a in actions}


def test_native_cap_is_observed_and_complete_table_survives_every_option_order():
    pytest.importorskip("laya.common")
    from laya.common import build_sequence
    from laya.train import to_internal

    _, actions, _, row = inputs()
    tok = tokenizer()
    legacy = option_encoding(row, tok)
    assert legacy["capped_options"] == 2
    assert not legacy["literal_complete_action_table_present"]
    complete = option_encoding(row, tok, "shared_actions")
    assert complete["literal_complete_action_table_present"] and complete["capped_options"] == 0
    assert complete["sequence_stats"]["state_tokens_dropped"] == 0
    assert complete["sequence_stats"]["head_tokens_dropped"] == 0
    payload = project_operation_payload(row, "shared_actions")
    for order in permutations(range(len(actions))):
        _, markers, options, stats = build_sequence(tok, payload["state"],
            to_internal("next", payload["questions"]["next"]), max_len=12288, head_max_len=2048,
            option_order=list(order), return_stats=True, return_truncation_stats=True)
        assert len(markers) == options["options_distinct"] == len(actions)
        assert stats["state_tokens_dropped"] == 0

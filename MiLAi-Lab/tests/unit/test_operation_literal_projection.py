import copy
import json
import sys
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from milai_lab.memory.literal_projection import (
    expand_observation_state,
    project_observation_state,
)
from milai_lab.methods.laya_memory_policy import (
    GenerativeMemoryPolicy,
    LayaMemoryPolicy,
    operation_payload,
)
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.runners.memory_control import memory_policy


def observations():
    text = 'A literal report including {"meta": 0}; unknown dates remain unknown. '
    return MemoryControlState(
        task={"request": "Which report is current?", "fresh_observations": [
            {"content": text, "role": "user"}, {"content": text, "role": "assistant"}]},
        new_events=[{"source_ref": f"distinct-source-identity-{i}",
            "role": "user" if i % 2 else "assistant", "content": text,
            "reported_at": None, "captured_at": f"2032-07-02T09:00:0{i}+08:00",
            "delivery": "controller observation only; not Reader evidence"} for i in range(6)],
        visible_evidence=[{"label": "e0", "kind": "original_source", "evidence": [
            {"source": f"s{i}", "role": "user" if i % 2 else "assistant", "content": text,
             "reported_at": None, "captured_at": f"2032-07-02T09:00:0{i}+08:00"}
            for i in range(6)]}],
        last_result={"ok": True, "scope": {"columns": ["literal"], "shared": {},
                                            "rows": [["not an encoded object"]]}},
        pending_candidates=[{"item_index": i, "date": "2032-07-02T09:00:00+08:00",
                             "navigation_only": True} for i in range(3)],
    )


def test_literal_sharing_restores_exact_roles_clocks_identity_order_and_opaque_text():
    state = observations().project()
    original = copy.deepcopy(state)
    projected = project_observation_state(state)
    wire = json.loads(json.dumps(projected))
    assert wire["observation_encoding"]["format"] == "literal_tables_v1"
    assert '"table":' in json.dumps(wire)
    assert wire["task"] == state["task"]
    assert wire["last_result"]["scope"] == state["last_result"]["scope"]
    assert expand_observation_state(wire) == state == original
    assert project_observation_state(wire) == wire
    assert len(json.dumps(projected)) < len(json.dumps(state))


def test_missing_fields_stay_distinct_from_explicit_nulls_and_literal_table_shapes():
    state = observations().project()
    state["new_events"][0].pop("reported_at")
    # A producer's ordinary object can have the same shape as the wire table.
    state["budget"]["literal"] = {"columns": ["value"], "shared": {}, "rows": [[1], [2]]}
    state["budget"]["producer_object"] = {"table": {"columns": [], "shared": {}, "rows": []}}
    projected = json.loads(json.dumps(project_observation_state(state)))
    assert expand_observation_state(projected) == state
    assert "reported_at" not in expand_observation_state(projected)["new_events"][0]


def test_shared_rows_keep_json_boolean_integer_and_float_values_distinct():
    state = observations().project()
    state["budget"]["observations"] = [
        {"nested": {"value": value}, "description": "An equal description across typed values."}
        for value in (False, 0, 0.0, True, 1, 1.0)]
    restored = expand_observation_state(json.loads(json.dumps(project_observation_state(state))))
    assert json.dumps(restored, sort_keys=True) == json.dumps(state, sort_keys=True)


def test_shared_export_native_and_generation_use_identical_information_without_gold():
    state = observations()
    actions = [MemoryAction("s", "SEARCH", "original task"), MemoryAction("h", "HANDOFF", "Reader")]
    expected = operation_payload(state, actions, "shared")
    row = decision_example({"before": state.project(), "actions": [asdict(a) for a in actions]},
                           {"family": "OFFLINE_ONLY"}, projection="shared")
    assert {key: row[key] for key in ("state", "questions")} == expected
    assert row["gold"] == {} and "OFFLINE_ONLY" not in json.dumps(expected)
    seen = []
    native = LayaMemoryPolicy(lambda p: seen.append(p) or {"choice": "h"}, "shared")
    assert native.choose(state, actions) == "h" and seen == [expected]

    def generate(stage, messages, schema):
        assert stage == "memory_control"
        seen.append(json.loads(messages[-1]["content"]))
        return {"choice": "h"}

    assert GenerativeMemoryPolicy(generate, "shared").choose(state, actions) == "h"
    assert seen[-1] == json.loads(json.dumps(expected))


@pytest.mark.parametrize("projection", ["full", "mechanical", "shared"])
def test_host_factory_projects_inside_metered_native_call(monkeypatch, projection):
    seen, charged = [], []

    class Model:
        def __init__(self, *args):
            self.counters = {"forwards": 0}

        def predict(self, payload):
            seen.append(payload)
            self.counters["forwards"] += 1
            return {"choice": "h"}

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Model)
    policy = memory_policy({"policy": "laya", "checkpoint": "test", "state_projection": projection},
        SimpleNamespace(record_compute=lambda phase, values: charged.append((phase, values))),
        call=lambda *_: {}, admit=lambda: None, record=lambda _: None)
    state = observations()
    actions = [MemoryAction("h", "HANDOFF", "Reader"), MemoryAction("s", "SEARCH", "request")]
    assert policy.choose(state, actions) == "h"
    assert seen == [operation_payload(state, actions, projection)]
    assert charged[-1][0] == "dynamic_memory_laya" and charged[-1][1]["forwards"] == 1

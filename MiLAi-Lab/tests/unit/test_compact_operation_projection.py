"""A new JSON serialization condition keeps values and old inputs intact."""
import copy
import json

import pytest
from test_complete_action_projection import inputs
from test_operation_curve_analysis import row
from test_retrieval_mixture import example

from analyze_operation_curve import operation_diagnostics
from milai_lab.memory.literal_projection import (
    compact_observation_state,
    expand_observation_state,
)
from milai_lab.methods.laya_memory_policy import payload_actions, project_operation_payload
from operation_input_diagnostics import recorded_inputs, serialized_strings
from retrieval_mixture import project_applicability_row, project_mixed_row


@pytest.mark.parametrize("text_request", [False, True])
def test_compact_condition_changes_only_syntax_whitespace_not_literals_or_action_head(text_request):
    _, actions, _, source = inputs(True)
    source["state"]["task"]["opaque"] = {
        " ": [False, 0, 0.0, True, 1, 1.0, None, {}, []],
        "quoted": '  preserve\t\n  Ω😀 "quoted" {"meta":0} <mask>  ',
        "missing_is_distinct_from_null": {"present": None}}
    original = copy.deepcopy(source)
    suffix = "_request_text" if text_request else ""
    shared = project_operation_payload(source, "shared_actions" + suffix)
    compact = project_operation_payload(source, "compact_actions" + suffix)
    assert isinstance(compact["state"], str)
    assert compact["state"] == json.dumps(shared["state"], ensure_ascii=False,
                                        separators=(",", ":"))
    assert json.dumps(json.loads(compact["state"]), ensure_ascii=False) == json.dumps(
        shared["state"], ensure_ascii=False)
    assert {k: v for k, v in compact.items() if k != "state"} == {
        k: v for k, v in shared.items() if k != "state"}
    assert payload_actions(compact) == actions
    assert expand_observation_state(compact["state"]) == expand_observation_state(shared["state"])
    assert source == original
    assert project_operation_payload(source, "shared_actions" + suffix) == shared
    wire, spans = serialized_strings(compact["state"], "<mask>")
    assert wire == compact["state"].replace("<mask>", " ")
    for span in spans:
        assert wire[span["start"]:span["end"]] == json.dumps(
            span["text"], ensure_ascii=False)[1:-1].replace("<mask>", " ")
    if not text_request:
        restored, restored_actions = recorded_inputs(compact)
        assert restored.project() == {k: v for k, v in source["state"].items()
                                      if k != "action_bindings"}
        assert restored_actions == actions


@pytest.mark.parametrize("projection", ["compact_actions", "compact_actions_request_text"])
def test_auxiliary_training_and_evaluation_use_same_input_condition_and_masks(projection):
    source = example("source", "family", "instruction_applicability", masked=True)
    source["metadata"]["task"] = "instruction_applicability"
    original = copy.deepcopy(source)
    projected = project_applicability_row(source, projection)
    assert project_mixed_row(source, projection) == projected
    assert project_applicability_row(projected, projection) == projected
    assert isinstance(projected["state"], str)
    assert projected["gold"] == {} and projected["metadata"] == original["metadata"]
    assert source == original


def test_curve_diagnostics_can_read_compact_rows_without_changing_scores():
    rows = [row("state", "family", "dev", 0), row("masked", "family", "dev", 1, False)]
    compact = [{**r, "state": compact_observation_state(r["state"])} for r in rows]
    predictions = [{"choice": "read"}, {}]
    lengths = [{"sequence_tokens": 100}, {"sequence_tokens": 200}]
    assert operation_diagnostics(compact, predictions, lengths, {}) == operation_diagnostics(
        rows, predictions, lengths, {})

"""Real origin formats preserve common continuation, partial labels and terminal reuse."""

import copy
import json

import pytest

from feedback_outcomes import observed_outcome, reached_outcomes
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from prepare_retrieval_feedback import compile_reached_feedback
from quality_feedback import answer_first_counts, outcome, validate_quality_pool
from retrieval_feedback import RESOURCE_FIELDS


def captured(tmp_path, remaining=4, *, initial=False):
    capture = tmp_path / "capture"
    actions = [
        {"id": "read", "kind": "READ", "target": "source", "parameters": {"index": 0}},
        {"id": "search", "kind": "SEARCH", "target": "request", "parameters": {"limit": 16}},
        {"id": "stop", "kind": "HANDOFF", "target": "opened", "parameters": {}},
        {"id": "unexamined", "kind": "REFRESH_VIEW", "target": "view", "parameters": {}},
    ]
    before = MemoryControlState(
        task={"request": "both facts"}, budget={"remaining_control_steps": remaining}
    ).project()
    call = {
        "schema": "frozen_retrieval_call_v2" if initial else "frozen_retrieval_decision_v1",
        "call_id": "call",
        "bank": "bank",
        "public_message": {"content": "both facts", "message_id": "q"},
        "initial_observation": before,
        "initial_actions": actions,
        "host_prefix_trace": "trace.jsonl",
        "request": {"query": "both facts"},
    }
    if not initial:
        call.update(control_step=1, control_checkpoint="control.json")
    write_json(capture / "call.json", call)
    (capture / "before").mkdir()
    (capture / "before/trace.jsonl").write_text('{"event":"original_prefix"}\n')
    raw = decision_example(
        {"before": before, "actions": actions},
        {"path": str(capture), "event_id": "event", "split": "train", "family": "paper", "row": 0},
    )
    return capture, raw


def reader(folder, call, packet, status, schema):
    wire = {
        "model": "fixed",
        "messages": [
            {"role": "system", "content": "fixed instructions"},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": "both facts",
                        "retrieval_request": call["request"],
                        "memory": packet,
                    }
                ),
            },
        ],
    }
    write_json(
        folder / "readout.json", {"status": status, "answer": "A first answer, never repaired."}
    )
    write_json(
        folder / "frame.json", {"schema": schema, "call_id": call["call_id"], "request": wire}
    )
    write_json(folder / "request.json", wire)


def branch(tmp_path, capture, action_id, *, steps=2, reads=4, status="COMPLETED"):
    call = read_json(capture / "call.json")
    start = call.get("control_step", 0)
    (action,) = [a for a in call["initial_actions"] if a["id"] == action_id]
    policy = {"policy": "fixed_context", "reads": reads}
    intervention = {"first_action": action, "continuation_steps": steps}
    case = tmp_path / action_id
    events = [
        {
            "event": "memory_control_step",
            "phase": "decision_output",
            "step": start,
            "before": call["initial_observation"],
            "actions": call["initial_actions"],
            "selected": action_id,
            "selection_mode": "intervention_first_action",
            "retrieval_call_id": "call",
        }
    ]
    if action["kind"] != "HANDOFF":
        for offset in range(
            1, min(call["initial_observation"]["budget"]["remaining_control_steps"], steps + 2)
        ):
            next_action = {
                "id": f"next-{offset}",
                "kind": "READ",
                "target": "next source",
                "parameters": {"index": offset, "expand_context": True},
            }
            stop = call["initial_actions"][2]
            state = copy.deepcopy(call["initial_observation"])
            state["budget"]["remaining_control_steps"] -= offset
            events.append(
                {
                    "event": "memory_control_step",
                    "phase": "decision_output",
                    "step": start + offset,
                    "before": state,
                    "actions": [next_action, stop],
                    "selected": next_action["id"] if offset <= steps else stop["id"],
                    "selection_mode": "policy" if offset <= steps else "intervention_handoff",
                    "retrieval_call_id": "call",
                }
            )
    packet = {
        "evidence": [{"content": action_id + " literal material"}],
        "termination_reason": "budget_exhausted",
    }
    result = {
        "status": "COMPLETED",
        "bank": "bank",
        **call["public_message"],
        "retrieval_result": packet,
        "frozen_initial_observation_and_actions_equal": True,
        "frozen_request_and_allowance_equal": True,
        "frozen_start_step": start,
        "messages": [{"type": "tool", "tool_call_id": "call", "content": json.dumps(packet)}],
    }
    write_json(
        case / "replay.json",
        {
            "captured_call": str(capture),
            "source_version": "frozen",
            "status": "COMPLETED",
            "policy": policy,
            "intervention": intervention,
            **(
                {"prefix_operations_reexecuted": 0, "restored_control_step": start}
                if "control_checkpoint" in call
                else {}
            ),
            "result": result,
        },
    )
    (case / "runtime").mkdir()
    prefix = (capture / "before/trace.jsonl").read_text()
    (case / "runtime/trace.jsonl").write_text(
        prefix + "".join(json.dumps(e) + "\n" for e in events)
    )
    reader(case / "host-readout", call, packet, status, "given_request_branch_host_readout_v1")
    return {
        "kind": "same_before_first_action",
        "case": str(case),
        "readout": str(case / "host-readout/readout.json"),
        "policy": policy,
        "intervention": intervention,
        "source_version": "frozen",
    }


def collected_terminal(tmp_path, capture):
    call = read_json(capture / "call.json")
    packet = {
        "evidence": [{"content": "original collected material"}],
        "termination_reason": "budget_exhausted",
    }
    result = {
        "status": "COMPLETED",
        "bank": "bank",
        **call["public_message"],
        "retrieval_result": packet,
    }
    result_path = tmp_path / "original-result.json"
    write_json(result_path, result)
    call.update(
        source_root=str(tmp_path),
        host_result_path=result_path.name,
        original_result=packet,
        control_events=[
            {
                "phase": "decision_output",
                "step": 1,
                "selected": "read",
                "before": call["initial_observation"],
                "actions": call["initial_actions"],
            }
        ],
    )
    write_json(capture / "call.json", call)
    reader(tmp_path / "original-reader", call, packet, "COMPLETED", "given_request_host_readout_v1")
    return {
        "kind": "closed_collector_last_decision",
        "call": str(capture / "call.json"),
        "result": str(result_path),
        "readout": str(tmp_path / "original-reader/readout.json"),
    }


def test_first_plus_two_choices_and_bounded_handoff_are_actual_not_two_total(tmp_path):
    capture, _ = captured(tmp_path)
    origin = branch(tmp_path, capture, "read")
    outcome = observed_outcome(capture, origin)
    assert outcome["action"]["parameters"] == {"index": 0}
    assert outcome["origin"] == origin and outcome["readout_status"] == "COMPLETED"
    trace = (tmp_path / "read/runtime/trace.jsonl").read_text().splitlines()
    assert len(trace) == 5  # Preserved prefix + first + two ordinary choices + HANDOFF.


def test_initial_call_has_no_post_state_prefix_counter_but_must_start_at_zero(tmp_path):
    capture, _ = captured(tmp_path, initial=True)
    origin = branch(tmp_path, capture, "read")
    path = tmp_path / "read/replay.json"
    replay = read_json(path)
    assert "prefix_operations_reexecuted" not in replay
    assert observed_outcome(capture, origin)["action"]["id"] == "read"
    replay["result"]["frozen_start_step"] = 1
    write_json(path, replay)
    with pytest.raises(ValueError, match="initial control boundary"):
        observed_outcome(capture, origin)


def test_post_state_missing_prefix_counter_is_not_treated_as_initial(tmp_path):
    capture, _ = captured(tmp_path)
    origin = branch(tmp_path, capture, "read")
    path = tmp_path / "read/replay.json"
    replay = read_json(path)
    del replay["prefix_operations_reexecuted"]
    write_json(path, replay)
    with pytest.raises(KeyError, match="prefix_operations_reexecuted"):
        observed_outcome(capture, origin)


@pytest.mark.parametrize("changed", ["parameters", "prefix", "suffix", "slots", "frame"])
def test_changed_executed_binding_or_continuation_cannot_receive_labels(tmp_path, changed):
    capture, _ = captured(tmp_path)
    origin = branch(tmp_path, capture, "read")
    case = tmp_path / "read"
    trace = case / "runtime/trace.jsonl"
    if changed == "parameters":
        origin["intervention"]["first_action"]["parameters"]["index"] = 7
        replay = read_json(case / "replay.json")
        replay["intervention"] = copy.deepcopy(origin["intervention"])
        write_json(case / "replay.json", replay)
    elif changed == "prefix":
        trace.write_text("changed\n" + trace.read_text())
    elif changed == "suffix":
        lines = trace.read_text().splitlines()
        event = json.loads(lines[2])
        event["selection_mode"] = "intervention_first_action"
        lines[2] = json.dumps(event)
        trace.write_text("\n".join(lines) + "\n")
    elif changed == "slots":
        call = read_json(capture / "call.json")
        call["initial_observation"]["budget"]["remaining_control_steps"] = 3
        write_json(capture / "call.json", call)
    else:
        frame = read_json(case / "host-readout/frame.json")
        frame["request"]["model"] = "different"
        write_json(case / "host-readout/frame.json", frame)
    with pytest.raises(ValueError):
        observed_outcome(capture, origin)


def test_different_common_continuation_is_not_the_same_comparison(tmp_path):
    capture, _ = captured(tmp_path)
    left = branch(tmp_path, capture, "read", reads=4)
    right = branch(tmp_path, capture, "search", reads=3)
    with pytest.raises(ValueError, match="common declared continuation"):
        reached_outcomes(capture, {"read": left, "search": right})


@pytest.mark.parametrize("remaining", [1, 2])
def test_collector_reuse_only_when_no_ordinary_continuation_slot_exists(tmp_path, remaining):
    capture, _ = captured(tmp_path, remaining)
    original = collected_terminal(tmp_path, capture)
    other = branch(tmp_path, capture, "search")
    origins = {"read": original, "search": other}
    if remaining == 1:
        outcomes = reached_outcomes(capture, origins)
        assert outcomes["read"]["origin"] == original
        assert not (capture / "replay.json").exists()
    else:
        with pytest.raises(ValueError, match="terminal single-slot READ"):
            reached_outcomes(capture, origins)


def test_three_outcomes_keep_partial_feedback_ties_and_unexamined_options(tmp_path):
    capture, raw = captured(tmp_path, 1)
    origins = {
        "read": branch(tmp_path, capture, "read", status="FAILED"),
        "search": branch(tmp_path, capture, "search"),
        "stop": branch(tmp_path, capture, "stop"),
    }
    order = {"left": dict.fromkeys(RESOURCE_FIELDS, 0), "right": dict.fromkeys(RESOURCE_FIELDS, 1)}
    review = {
        "event_id": "event",
        "capture": str(capture),
        "reviewer": "test source author",
        "outcomes": origins,
        "comparisons": [
            {
                "left": "read",
                "right": "search",
                "basis": {
                    "quality_before_resource_tiebreak": {"answer": "unknown", "delivery": "right"},
                    "resource_order": copy.deepcopy(order),
                },
            },
            {
                "left": "search",
                "right": "stop",
                "basis": {
                    "quality_before_resource_tiebreak": {"answer": "tie", "delivery": "left"},
                    "resource_order": copy.deepcopy(order),
                },
            },
        ],
    }
    untouched = copy.deepcopy(raw)
    (row,) = compile_reached_feedback([raw], [review])
    assert raw == untouched and all(row[k] == raw[k] for k in ("state", "questions", "gold"))
    assert row["feedback"]["outcomes"] == origins
    assert row["feedback"]["comparisons"][1]["answer"] == "left"  # Legacy cost view only.
    assert outcome(row["feedback"]["comparisons"][1], "answer", "quality-tie") == "tie"
    assert "unexamined" in row["questions"]["next"]["criteria"]
    validate_quality_pool([row])
    assert answer_first_counts([row])["components"]["delivery_auxiliary"]["pairs"] == 1
    review["comparisons"][0]["basis"]["quality_before_resource_tiebreak"]["answer"] = "right"
    with pytest.raises(ValueError, match="incomplete final answer"):
        compile_reached_feedback([raw], [review])

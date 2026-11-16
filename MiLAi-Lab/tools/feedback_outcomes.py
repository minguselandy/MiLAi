"""Read real collected and replayed decisions without synthetic replay wrappers."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    MemoryAction,
    MemoryControlState,
)
from summarize_handoff_comparison import completed_tool


def validate_control_boundary(call: dict[str, Any], replay: dict[str, Any]) -> None:
    """Initial calls have no executed prefix; post states must restore their exact prefix."""
    if "control_checkpoint" in call:
        if (replay["prefix_operations_reexecuted"] != 0
                or replay["restored_control_step"] != call["control_step"]):
            raise ValueError("Post-state replay changed its executed control boundary")
    elif (call["schema"] != "frozen_retrieval_call_v2" or call.get("control_step", 0) != 0
          or replay["result"]["frozen_start_step"] != 0):
        raise ValueError("Initial replay requires the actual initial control boundary")


def first_action_tool(capture: Path, origin: dict[str, Any]) -> dict[str, Any]:
    """Bind one actual first action followed by the declared fixed-context continuation."""
    case = Path(origin["case"])
    call = read_json(capture / "call.json")
    replay = read_json(case / "replay.json")
    result = replay["result"]
    validate_control_boundary(call, replay)
    policy, intervention = origin["policy"], origin["intervention"]
    if (Path(replay["captured_call"]).resolve() != capture.resolve()
            or replay["policy"] != policy or replay["intervention"] != intervention
            or replay["source_version"] != origin["source_version"]
            or policy != {"policy": "fixed_context", "reads": policy["reads"]}
            or replay["status"] != "COMPLETED" or result["status"] != "COMPLETED"
            or not result["frozen_initial_observation_and_actions_equal"]
            or not result["frozen_request_and_allowance_equal"]):
        raise ValueError("First-action outcome differs from its declared restored condition")
    relative = Path(call["host_prefix_trace"])
    prefix = (capture / "before" / relative).read_bytes()
    with (case / "runtime" / relative).open("rb") as stream:
        if stream.read(len(prefix)) != prefix:
            raise ValueError("First-action trace changed the captured prefix")
        events = [json.loads(line) for line in stream if line.strip()]
    decisions = [event for event in events if event.get("event") == "memory_control_step"
                 and event.get("phase") == "decision_output"]
    continuation = intervention["continuation_steps"]
    remaining = call["initial_observation"]["budget"]["remaining_control_steps"]
    start = call.get("control_step", 0)
    if (not 1 <= len(decisions) <= min(remaining, continuation + 2)
            or [event["step"] for event in decisions] != list(
                range(start, start + len(decisions)))):
        raise ValueError("First-action continuation exceeds its declared actual slots")
    first = decisions[0]
    if (first["before"] != call["initial_observation"]
            or first["actions"] != call["initial_actions"]
            or first["retrieval_call_id"] != call["call_id"]
            or first["selection_mode"] != "intervention_first_action"):
        raise ValueError("First-action trace does not start at the complete captured decision")
    action, = [a for a in first["actions"] if a["id"] == first["selected"]]
    if action != intervention["first_action"]:
        raise ValueError("Executed first action has different complete parameters")
    controller = FixedContextMemoryPolicy(reads=policy["reads"])
    for offset, event in enumerate(decisions):
        selected, = [a for a in event["actions"] if a["id"] == event["selected"]]
        if selected["kind"] == "HANDOFF" and offset != len(decisions) - 1:
            raise ValueError("A continuation cannot continue after HANDOFF")
        if offset == 0:
            continue
        actions = [MemoryAction(**a) for a in event["actions"]]
        if offset <= continuation:
            forced = len(actions) == 1
            choice = actions[0].id if forced else controller.choose(
                MemoryControlState(**event["before"]), actions)
            mode = "only_available_action" if forced else "policy"
            if event["selected"] != choice or event["selection_mode"] != mode:
                raise ValueError("Actual suffix differs from the declared common continuation")
        elif (offset != continuation + 1 or selected["kind"] != "HANDOFF"
              or event["selection_mode"] != "intervention_handoff"):
            raise ValueError("Only the bounded HANDOFF can follow the continuation")
    receipt, = [message for message in result["messages"]
                if message.get("type") == "tool" and message.get("tool_call_id") == call["call_id"]]
    packet = json.loads(receipt["content"])
    if packet != result["retrieval_result"]:
        raise ValueError("First-action Tool receipt differs from the returned packet")
    return {"action": action, "packet": packet, "result": result}


def observed_outcome(capture: Path, origin: dict[str, Any]) -> dict[str, Any]:
    call = read_json(capture / "call.json")
    if origin["kind"] == "closed_collector_last_decision":
        if Path(origin["call"]).resolve() != (capture / "call.json").resolve():
            raise ValueError("Collected outcome belongs to a different before state")
        initial = Path(call["initial_capture"]) if "initial_capture" in call else capture
        parent = read_json(initial / "call.json")
        decisions = [e for e in parent["control_events"] if e["phase"] == "decision_output"]
        last = decisions[-1]
        if (last["step"] != call.get("control_step", 0)
                or last["before"] != call["initial_observation"]
                or last["actions"] != call["initial_actions"]):
            raise ValueError("A collected final outcome cannot label an earlier decision")
        action, = [a for a in last["actions"] if a["id"] == last["selected"]]
        result_path = Path(call["source_root"]) / call["host_result_path"]
        if Path(origin["result"]).resolve() != result_path.resolve():
            raise ValueError("Collected result is not the actual captured message result")
        result = read_json(result_path)
        if result["status"] != "COMPLETED" or result["retrieval_result"] != call["original_result"]:
            raise ValueError("Collected Tool outcome differs from the closed capture")
        packet = result["retrieval_result"]
        expected_schema = "given_request_host_readout_v1"
    elif origin["kind"] == "new_same_before_raw_delivery":
        case = Path(origin["case"])
        replay = read_json(case / "replay.json")
        tool = completed_tool(case, capture, replay["policy"], replay["source_version"])
        action, packet = tool["action"], tool["packet"]
        result = replay["result"]
        expected_schema = "given_request_branch_host_readout_v1"
    elif origin["kind"] == "same_before_first_action":
        tool = first_action_tool(capture, origin)
        action, packet, result = tool["action"], tool["packet"], tool["result"]
        expected_schema = "given_request_branch_host_readout_v1"
    else:
        raise ValueError("Unknown actual outcome origin")
    if result["bank"] != call["bank"] or any(
            result[key] != value for key, value in call["public_message"].items()):
        raise ValueError("Outcome changed the captured public request")
    readout_path = Path(origin["readout"])
    readout = read_json(readout_path)
    frame = read_json(readout_path.parent / "frame.json")
    if frame["schema"] != expected_schema or frame["call_id"] != call["call_id"]:
        raise ValueError("Readout is not the declared actual supplied-request outcome")
    if readout["status"] not in {"COMPLETED", "FAILED"}:
        raise ValueError("Feedback requires a closed first readout attempt")
    wire = read_json(readout_path.parent / "request.json")
    if origin["kind"] == "same_before_first_action" and frame["request"] != wire:
        raise ValueError("First-action Reader frame differs from the actual wire")
    body = json.loads(wire["messages"][1]["content"])
    if body["memory"] != packet or body["retrieval_request"] != call["request"]:
        raise ValueError("Readout did not receive the actual packet and original request")
    return {"action": action, "packet": packet, "wire": wire,
            "tool_status": result["status"], "readout_status": readout["status"],
            "origin": copy.deepcopy(origin)}


def paired_outcomes(capture: Path, origins: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """All changes in the fixed reader input must be consequences in the actual packet."""
    outcomes = {key: observed_outcome(capture, origin) for key, origin in origins.items()}
    normalized = []
    for key, outcome in outcomes.items():
        if outcome["action"]["id"] != key:
            raise ValueError("Outcome is attached to a different complete action binding")
        wire = copy.deepcopy(outcome["wire"])
        body = json.loads(wire["messages"][1]["content"])
        body["memory"] = None
        wire["messages"][1]["content"] = body
        normalized.append(wire)
    if any(wire != normalized[0] for wire in normalized):
        raise ValueError("Paired readers differ outside the actual delivered packet")
    return outcomes


def reached_outcomes(capture: Path, origins: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Common declared continuation, with only a terminal READ reused from a collector."""
    if (not 2 <= len(origins) <= 3 or any(origin["kind"] not in {
            "same_before_first_action", "closed_collector_last_decision"}
            for origin in origins.values())):
        raise ValueError("Reached-state comparisons need two or three actual decision outcomes")
    interventions = [origin for origin in origins.values()
                     if origin["kind"] == "same_before_first_action"]
    if not interventions or any(
            origin["policy"] != interventions[0]["policy"]
            or origin["intervention"]["continuation_steps"] !=
            interventions[0]["intervention"]["continuation_steps"] for origin in interventions):
        raise ValueError("Reached-state outcomes require one common declared continuation")
    outcomes = paired_outcomes(capture, origins)
    call = read_json(capture / "call.json")
    for key, origin in origins.items():
        if origin["kind"] == "closed_collector_last_decision" and (
                call["initial_observation"]["budget"]["remaining_control_steps"] != 1
                or outcomes[key]["action"]["kind"] != "READ"
                or outcomes[key]["packet"].get("termination_reason") != "budget_exhausted"):
            raise ValueError("Collector reuse requires an equivalent terminal single-slot READ")
    return outcomes

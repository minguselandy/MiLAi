"""Explicit conditional Host framing for a controlled fresh request after actual delivery."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json
from milai_lab.runners.frozen_host_readout import readout_batch


def public_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in m.items() if k not in {"reasoning", "reasoning_content"}}
            for m in messages]


def append_fresh_request(wire: dict[str, Any], call: dict[str, Any]) -> dict[str, Any]:
    """Append a controlled call to public input, never to the generated answer."""
    request = copy.deepcopy(wire)
    request["messages"] = public_messages(request["messages"])
    mode = call["host"]["tool_mode"]
    if mode == "native":
        assistant = {"role": "assistant", "content": None, "tool_calls": [{
            "id": call["call_id"], "type": "function", "function": {
                "name": "milai_retrieve",
                "arguments": json.dumps(call["request"], ensure_ascii=False)}}]}
    elif mode == "json_action":
        assistant = {"role": "assistant", "content": json.dumps({"calls": [{
            "name": "milai_retrieve", "arguments": call["request"]}]}, ensure_ascii=False)}
    else:
        raise ValueError("Unknown Host tool protocol")
    request["messages"].extend([assistant, {"role": "tool", "name": "milai_retrieve",
        "tool_call_id": call["call_id"], "content": ""}])
    readout_batch(request, mode)
    return request


def prepare_controlled_readout(preparation: dict[str, Any], captured: Path) -> dict[str, Any]:
    """Keep the completed invocation's actual final input and append the declared request.

    The appended assistant call is an experimental intervention, not an actual
    autonomous Host choice. No original final answer enters the readout input.
    The target ToolMessage is a reserved placeholder; run_readout substitutes an
    actual branch receipt before any dispatch through the existing budget owner.
    """
    closed_root = Path(preparation["closed_capture"])
    closed = read_json(closed_root / "closed.json")
    original = read_json(Path(preparation["source_call"]) / "call.json")
    call = read_json(captured / "call.json")
    if (preparation["status"] != "FRESH_RAW_KNOWN_BUDGET_REQUESTS_PREPARED_NOT_EXECUTED"
            or closed["final_context_status"] != "BOUND_TO_COMPLETED_FINAL_GENERATION"
            or closed["source_version"] != call["source_version"]
            or closed["public_message"] != original["public_message"]
            or call["bank"] != closed["bank"] or call["host_request_generated"]
            or call["public_message"]["message_id"] != preparation["public_message"]["message_id"]):
        raise ValueError("Controlled readout requires this fresh call and bound closed input")
    condition, = [c for c in preparation["conditions"] if c["request"] == call["request"]]
    boundary = closed["pre_final_snapshot"]
    before_final = closed_root / boundary["snapshot"]
    if (boundary["status"] != "CAPTURED_BEFORE_FINAL_RESPONSE_PERSISTENCE"
            or boundary["output_message_id"] != closed["final_context"]["output_message_id"]
            or before_final.resolve() != Path(preparation["source_snapshot"]).resolve()):
        raise ValueError("Controlled readout changed the prepared pre-final snapshot")
    context = closed["final_context"]
    matches = []
    for line in (before_final / original["host_prefix_trace"]).read_text().splitlines():
        event = json.loads(line)
        wire = event.get("request", {})
        if public_messages(wire.get("messages", [])) == context["messages"]:
            matches.append(wire)
    if not matches or any(wire != matches[0] for wire in matches[1:]):
        raise ValueError("Final provider context does not identify one literal request payload")
    mode = call["host"]["tool_mode"]
    if mode != original["host"]["tool_mode"]:
        raise ValueError("Fresh readout changed the actual Host tool protocol")
    if mode == "native" and matches[0]["tools"] != context["tools"]:
        raise ValueError("Closed final tool catalog differs from its actual wire")
    request = append_fresh_request(matches[0], call)
    batch = readout_batch(request, mode)
    return {"schema": "frozen_host_readout_v1", "status": "READY",
        "frame_origin": "CONTROLLED_FRESH_REQUEST_AFTER_CLOSED_ACTUAL_DELIVERY",
        "captured_call": str(captured.resolve()), "call_id": call["call_id"], "tool_mode": mode,
        "closed_capture": str(closed_root.resolve()), "arm": condition["arm"],
        "starting_bank_boundary": preparation["source_snapshot_boundary"],
        "original_final_source_ref_absent_from_starting_bank": preparation[
            "original_final_source_ref_absent_from_starting_bank"],
        "request": request, "target_message_index": len(request["messages"]) - 1,
        "batch_call_ids": batch, "source_final_request": matches[0],
        "source_final_output_message_id": context["output_message_id"],
        "original_answer_loaded_as_input": False, "host_request_generated": False,
        "target_content_is_placeholder": True,
        "scope": "Controlled fresh retrieval request appended to the actual completed Host "
        "invocation's final provider input, before its original answer. Existing visible history "
        "and all original receipts are fixed. Only the fresh branch receipt is substituted; "
        "one conditional final answer, no further tools. This is not an original autonomous "
        "Host frame or proof of stopping/request behavior. Raw-known refs are a visible subset; "
        "the Host retains its complete recorded input, including any sibling receipts."}

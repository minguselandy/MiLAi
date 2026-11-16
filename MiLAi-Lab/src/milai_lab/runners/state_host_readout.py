"""One actual post-tool STATE Host input with one retrieval receipt substituted."""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.functional_state import canonical
from milai_lab.providers.chat_bridge import VLLMChatModel
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.runners.frozen_host_readout import (
    readout_answer,
    readout_batch,
    substitute_receipt,
)
from milai_lab.runners.state_bench_adapter import learning_envelope


def prepare_state_readout(captured: Path) -> dict[str, Any]:
    """Locate the first actual Host wire after this original completed tool batch.

    STATE assigns transcript-index/call-index IDs when rendering the next input.
    The within-batch retrieval ordinal disambiguates even identical queries.
    No original answer or evaluator-only domain snapshot is used as an input.
    """
    call = read_json(captured / "call.json")
    if call["schema"] not in {
            "state_dynamic_retrieval_call_v1", "state_dynamic_retrieval_decision_v1"}:
        raise ValueError("STATE readout requires an actual dynamic STATE capture")
    frame: dict[str, Any] = {"schema": "state_frozen_host_readout_v1",
        "captured_call": str(captured.resolve()), "retrieval_call_id": call["call_id"],
        "scope": "One final Host answer after replacing one actual retrieval receipt. "
            "Other original batch receipts fixed; no business execution, simulated future user "
            "or autonomous task success is inferred.", "original_answer_loaded_as_input": False}
    public = call.get("host_frame")
    if public is None or not public.get("host_request_generated"):
        return {**frame, "status": "NO_HOST_REQUEST_ORIGIN"}
    if "original_result" not in call:
        return {**frame, "status": "NO_ORIGINAL_TOOL_RECEIPT"}
    root = Path(call["source_root"])
    run = read_json(root / "run.json")
    if run["status"] not in {"FAILED", "COMPLETED_RESEARCH_TRAJECTORY"}:
        raise ValueError("STATE readout requires the original task run to be closed")
    frame.update(original_task_status=run["status"],
                 tool_mode=call["settings"]["host"]["tool_mode"])
    prefix_file = captured / "before/provider-trace-prefix.jsonl"
    if not prefix_file.is_file():
        return {**frame, "status": "NO_CAPTURED_TRACE_PREFIX"}
    requests = public["response"]["tool_calls"]
    indices = [i for i, request in enumerate(requests) if request["name"] == "retrieve_learnings"]
    ordinal = call["retrieval_ordinal"] - public["memory_calls_before"]
    if not 1 <= ordinal <= len(indices):
        raise ValueError("STATE readout retrieval ordinal is outside the actual Host batch")
    index = indices[ordinal - 1]
    arguments = requests[index]["arguments"]
    for name in ("query", "read_goal"):
        if arguments.get(name) != call["request"].get(name):
            raise ValueError("STATE captured Host arguments differ from the actual retrieval")
    ids = [f"state-{len(public['conversation'])}-{i}" for i in range(len(requests))]
    frame.update(call_id=ids[index], original_batch_requests=copy.deepcopy(requests),
                 target_batch_index=index)
    prefix = prefix_file.read_bytes()
    with Path(call["trace_path"]).open("rb") as stream:
        if stream.read(len(prefix)) != prefix:
            raise ValueError("STATE original trace prefix changed")
        for offset, line in enumerate(stream):
            event = json.loads(line)
            if (event.get("event") not in {"vllm_request", "vllm_response", "vllm_error"}
                    or event.get("path") != "chat/completions"):
                continue
            request = event["request"]
            positions = [i for i, message in enumerate(request["messages"])
                if message["role"] == "tool" and message.get("tool_call_id") == frame["call_id"]]
            if not positions:
                continue
            if len(positions) != 1 or readout_batch(request, frame["tool_mode"]) != ids:
                raise ValueError("STATE post-tool wire lacks the complete original batch")
            assistant = next(message for message in reversed(request["messages"])
                             if message["role"] == "assistant")
            actual_requests = ([{"name": item["function"]["name"],
                "arguments": json.loads(item["function"]["arguments"])}
                for item in assistant["tool_calls"]] if frame["tool_mode"] == "native"
                else json.loads(assistant["content"])["calls"])
            if actual_requests != requests:
                raise ValueError("STATE post-tool bindings differ from the original Host batch")
            position, = positions
            receipt = request["messages"][position]
            if json.loads(receipt["content"]) != learning_envelope(call["original_result"]):
                raise ValueError("STATE original Host receipt differs from the captured packet")
            return {**frame, "status": "READY", "request": copy.deepcopy(request),
                "target_message_index": position, "batch_call_ids": ids,
                "trace_event_after_prefix": offset, "original_wire_event": event["event"],
                "original_post_tool_http_status": event.get("http_status")}
    return {**frame, "status": "NO_POST_TOOL_HOST_INPUT"}


def state_readout_request(frame: dict[str, Any], replay: dict[str, Any]) -> dict[str, Any]:
    """Substitute the actual branch envelope and restrict output to a final answer."""
    if (replay["status"] != "COMPLETED"
            or replay["call_id"] != frame["retrieval_call_id"]
            or replay["captured_call"] != frame["captured_call"]):
        raise ValueError("STATE readout requires the completed branch from this exact capture")
    if replay["envelope"] != learning_envelope(replay["packet"]):
        raise ValueError("STATE replay envelope differs from its actual packet")
    return substitute_receipt(frame, {"type": "tool", "tool_call_id": frame["call_id"],
                                      "content": canonical(replay["envelope"])})


def run_state_readout(
    frame: dict[str, Any], replay: dict[str, Any], output: Path, *,
    host: VLLMChatModel, source_version: str,
) -> dict[str, Any]:
    """Use the branch's existing client, ledger and remaining per-turn generation gate."""
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {"status": "RUNNING", "source_version": source_version,
        "automatic_retry": False, "domain_tools_executed": 0, "scope": frame["scope"],
        "generation_calls_before": host.calls_in_message, "actual_http_attempts": 0}

    def dispatched(event: dict[str, Any]) -> None:
        if event["event"] == "vllm_request":
            report["actual_http_attempts"] += 1

    try:
        write_json(output / "frame.json", frame)
        if frame["status"] != "READY":
            report.update(status="NOT_EXECUTED", reason=frame["status"])
            return report
        request = state_readout_request(frame, replay)
        write_json(output / "request.json", request)
        host.reserve_external_request("state_frozen_host_readout")
        response = host.client.native_post("chat/completions", request, on_event=dispatched)
        write_json(output / "response.json", response)
        report.update(status="COMPLETED",
                      answer=readout_answer(response, frame["tool_mode"], request))
        return report
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        if isinstance(error, CapacityExceeded):
            report["capacity_rejection"] = error.receipt
        raise
    finally:
        report.update(generation_calls_after=host.calls_in_message,
            wall_seconds=time.perf_counter() - started,
            cpu_seconds_nested=time.process_time() - cpu,
            accounting="Host HTTP uses the original branch client/ledger. Readout CPU is nested "
                       "in the branch driver; no separate compute charge.")
        write_json(output / "readout.json", report)

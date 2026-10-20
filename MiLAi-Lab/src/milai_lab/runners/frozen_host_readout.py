"""One fixed Host readout after substituting an actual frozen tool receipt."""
from __future__ import annotations

import copy
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jsonschema import validate  # type: ignore[import-untyped]

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunLimits, Trace, entry_budget, http_budget_scope
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity
from milai_lab.providers.contextual_vllm import VLLMConfig
from milai_lab.providers.functional_queue import FunctionalQueue
from milai_lab.providers.generation_admission import DurableGenerationAdmission


def _batch(request: dict[str, Any], mode: str) -> list[str]:
    messages = request["messages"]
    index = max(i for i, item in enumerate(messages) if item["role"] == "assistant")
    response = messages[index]
    receipts = [item["tool_call_id"] for item in messages[index + 1:] if item["role"] == "tool"]
    if mode == "native":
        expected = [item["id"] for item in response["tool_calls"]]
        if sorted(expected) != sorted(receipts):
            raise ValueError("FROZEN_READOUT_INCOMPLETE_NATIVE_BATCH")
    else:
        calls = json.loads(response["content"])["calls"]
        if len(calls) != len(receipts):
            raise ValueError("FROZEN_READOUT_INCOMPLETE_JSON_BATCH")
    return receipts


def prepare_readout(captured: Path) -> dict[str, Any]:
    """Use the first actual post-tool Host input, without feeding the original answer.

    A single target receipt is substituted. Other receipts in the same complete
    batch are common observed context, so this measures a conditional per-call
    effect rather than an autonomous counterfactual conversation.
    """
    call = read_json(captured / "call.json")
    frame: dict[str, Any] = {
        "schema": "frozen_host_readout_v1", "captured_call": str(captured),
        "call_id": call["call_id"], "tool_mode": call["host"]["tool_mode"],
        "scope": "One target receipt intervention; other actual batch receipts fixed. "
                 "One final Host answer, no further retrieval or business execution.",
    }
    if not call["host_request_generated"]:
        return {**frame, "status": "NO_HOST_REQUEST_ORIGIN"}
    original = Path(call["source_root"]) / call["host_result_path"]
    if not original.is_file():
        raise ValueError("FROZEN_READOUT_ORIGINAL_HOST_NOT_CLOSED")
    frame["original_host_status"] = read_json(original)["status"]
    relative = Path(call["host_prefix_trace"])
    prefix = (captured / "before" / relative).read_bytes()
    trace = Path(call["source_root"]) / relative
    with trace.open("rb") as stream:
        if stream.read(len(prefix)) != prefix:
            raise ValueError("FROZEN_READOUT_TRACE_PREFIX_CHANGED")
        for offset, line in enumerate(stream):
            event = json.loads(line)
            request = event.get("request", {})
            messages = request.get("messages", [])
            positions = [i for i, item in enumerate(messages)
                         if item["role"] == "tool" and item.get("tool_call_id") == call["call_id"]]
            if not positions:
                continue
            if len(positions) != 1:
                raise ValueError("FROZEN_READOUT_AMBIGUOUS_RECEIPT")
            batch = _batch(request, frame["tool_mode"])
            if call["call_id"] not in batch:
                raise ValueError("FROZEN_READOUT_TARGET_NOT_IN_LATEST_BATCH")
            position, = positions
            if ("original_result" in call
                    and json.loads(messages[position]["content"]) != call["original_result"]):
                raise ValueError("FROZEN_READOUT_ORIGINAL_TOOL_PACKET_CHANGED")
            return {**frame, "status": "READY", "request": copy.deepcopy(request),
                "target_message_index": position, "batch_call_ids": batch,
                "original_event": event["event"],
                "trace_event_after_prefix": offset,
                "original_answer_loaded_as_input": False}
    return {**frame, "status": "NO_POST_TOOL_HOST_INPUT"}


def substitute_receipt(frame: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """Keep the recorded prompt/catalog/sampling; change receipt and final-only choice."""
    if frame["status"] != "READY":
        raise ValueError("FROZEN_READOUT_CONTEXT_UNAVAILABLE")
    if receipt["type"] != "tool" or receipt["tool_call_id"] != frame["call_id"]:
        raise ValueError("FROZEN_READOUT_RECEIPT_IDENTITY_CHANGED")
    request: dict[str, Any] = copy.deepcopy(frame["request"])
    request["messages"][frame["target_message_index"]]["content"] = receipt["content"]
    if frame["tool_mode"] == "native":
        request["tool_choice"] = "none"
    else:
        schema = request["response_format"]["json_schema"]["schema"]
        if "oneOf" in schema:
            final, = [branch for branch in schema["oneOf"]
                      if "answer" in branch.get("properties", {})]
            request["response_format"]["json_schema"]["schema"] = final
        elif set(schema["properties"]) != {"answer"}:
            raise ValueError("FROZEN_READOUT_FINAL_SCHEMA_UNAVAILABLE")
    return request


def readout_answer(response: dict[str, Any], mode: str, request: dict[str, Any]) -> str:
    """Validate a single final response without truncation repair or another model call."""
    choices = response["choices"]
    if len(choices) != 1 or choices[0]["finish_reason"] != "stop":
        raise IncompleteChatResponse("FROZEN_READOUT_INCOMPLETE_FINAL_RESPONSE")
    message = choices[0]["message"]
    if message["role"] != "assistant" or message.get("tool_calls"):
        raise IncompleteChatResponse("FROZEN_READOUT_EXPECTED_FINAL_ANSWER")
    content = message["content"]
    if not isinstance(content, str):
        raise IncompleteChatResponse("FROZEN_READOUT_TEXT_REQUIRED")
    if mode == "json_action":
        answer = json.loads(content)
        validate(answer, request["response_format"]["json_schema"]["schema"])
        return str(answer["answer"])
    return content


def run_readout(
    captured: Path, replay: Path, output: Path, frame: dict[str, Any], *, source_version: str,
) -> dict[str, Any]:
    """Meter one readout through the original HTTP owner, queue and remaining call gate."""
    from milai_lab.runners import functional

    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {
        "status": "RUNNING", "source_version": source_version,
        "captured_call": str(captured), "replay": str(replay),
        "automatic_retry": False, "actual_http_attempts": 0,
        "http_attempt_scope": "Native dispatch attempts, not provider acknowledgements.",
        "scope": frame["scope"], "cpu_ledger_recorded": False,
        "http_accounting": "Original continuous ledger, no separate budget.",
    }
    trace = Trace(output / "trace.jsonl", "frozen_host_readout")

    def dispatched(event: dict[str, Any]) -> None:
        if event["event"] == "vllm_request":
            report["actual_http_attempts"] += 1
            trace(event)

    budget = None
    try:
        write_json(output / "frame.json", frame)
        if frame["status"] != "READY":
            report.update(status="NOT_EXECUTED", reason=frame["status"])
            return report
        result = read_json(replay / "replay.json")["result"]
        receipts = [row for row in result.get("messages", [])
                    if row.get("type") == "tool" and row.get("tool_call_id") == frame["call_id"]]
        if not receipts:
            report.update(status="NOT_EXECUTED", reason="NO_ACTUAL_TOOL_RECEIPT",
                          tool_status=result["status"])
            return report
        receipt, = receipts
        # This is the actual returned ToolMessage, including structured error packets.
        if json.loads(receipt["content"]) != result["retrieval_result"]:
            raise ValueError("FROZEN_READOUT_RECEIPT_AND_RESULT_DIFFER")
        wire = substitute_receipt(frame, receipt)
        write_json(output / "request.json", wire)
        call = read_json(captured / "call.json")
        runtime = replay / "runtime"
        freeze = functional.frozen(runtime)
        settings = freeze["config"]
        bank_root = runtime / Path(call["source_bank_root"]).relative_to(call["source_root"])
        limits = RunLimits(**freeze["budget_before"]["limits"])
        configs = [asdict(VLLMConfig(**settings["host"]))]
        if "embedding" in settings:
            configs.append(asdict(VLLMConfig(**settings["embedding"])))
        with http_budget_scope(settings, limits, client_configs=configs):
            budget = entry_budget(limits, Path(settings["budget_path"]))
            report["budget_before"] = copy.deepcopy(budget.state)
            binding = call["binding"]
            host = VLLMConfig(**settings["host"])
            admission = DurableGenerationAdmission(
                bank_root / "message-admission.json", binding["message_id"],
                {"owner": binding["owner"], "bank": binding["bank"], "session": binding["session"],
                 "request_ref": binding["source_ref"],
                 "request_revision": binding["source_revision"],
                 "config_version": binding["config_version"]},
                asdict(host), settings["max_calls_per_message"], "resume", 0)
            report["generation_calls_before"] = admission.count
            admission.reserve(
                asdict(host), settings["max_calls_per_message"], "frozen_host_readout")
            report["generation_calls_after"] = admission.count
            client = functional.FunctionalVLLMClient(
                host, emit=trace, budget=budget, capacity=HostCapacity(settings["capacity"]))
            with client:
                client.queue = FunctionalQueue(runtime / "queue-admission.json",
                                               **settings["queue_limits"])
                response = client.native_post("chat/completions", wire, on_event=dispatched)
                write_json(output / "response.json", response)
                report.update(status="COMPLETED",
                    answer=readout_answer(response, frame["tool_mode"], wire))
        return report
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        if isinstance(error, CapacityExceeded):
            report["capacity_rejection"] = error.receipt
        raise
    finally:
        report.update(wall_seconds=time.perf_counter() - started,
            cpu_seconds=time.process_time() - cpu,
            usage=trace.usage)
        if budget is not None:
            report["budget_after"] = copy.deepcopy(budget.state)
        write_json(output / "readout.json", report)

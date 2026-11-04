"""One nonpersistent answer from an actual explicitly supplied retrieval request.

This is a conditional mechanism measurement, not an autonomous Host conversation
or a reconstructed historical Host frame. Only the task and returned packet enter
the answer input; the readout does not become a Source for later requests.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import Trace
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.providers.contextual_vllm import VLLMConfig
from milai_lab.runners.frozen_host_readout import execute_readout_request

ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
                 "required": ["answer"], "additionalProperties": False}


def validate_given_readout_request(request: dict[str, Any]) -> None:
    """A fresh packet-only reader cannot stand in for a Host with prior evidence."""
    if RetrievalRequest.model_validate(request).task_context.known_evidence_refs:
        raise ValueError("GIVEN_READOUT_CANNOT_RECONSTRUCT_PRIOR_HOST_KNOWLEDGE")


def given_readout_frame(
    call: dict[str, Any], result: dict[str, Any], settings: dict[str, Any],
    *, replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use only a completed supplied-request receipt and its explicit public task."""
    public = call["public_message"]
    transport = "programmatic_given_request" if replay is None else "frozen_actual_tool_call"
    if (call["host_request_generated"] or result.get("host_request_generated") is not False
            or result.get("request_transport") != transport
            or "given_retrieval_request" not in public):
        raise ValueError("GIVEN_READOUT_REQUIRES_SUPPLIED_REQUEST")
    validate_given_readout_request(call["request"])
    if (result["bank"] != call["bank"]
            or any(result[key] != value for key, value in public.items())
            or RetrievalRequest.model_validate(public["given_retrieval_request"])
            != RetrievalRequest.model_validate(call["request"])):
        raise ValueError("GIVEN_READOUT_PUBLIC_REQUEST_CHANGED")
    if replay is not None and (replay["result"] != result or (result["status"] == "COMPLETED"
            and (not result["frozen_initial_observation_and_actions_equal"]
                 or not result["frozen_request_and_allowance_equal"]))):
        raise ValueError("GIVEN_BRANCH_READOUT_REQUIRES_SAME_ACTUAL_BEFORE")
    frame: dict[str, Any] = {
        "schema": "given_request_host_readout_v1", "status": "NOT_EXECUTED",
        "call_id": call["call_id"], "host_request_generated": False,
        "original_answer_loaded_as_input": False, "answer_persisted_as_source": False,
        "scope": "One conditional answer from the public task and actual returned packet. "
                 "No prior Host conversation, hidden Store, source inventory or new retrieval. "
                 "The program supplies the retrieval request; this is not autonomous tool use.",
    }
    if replay is not None:
        frame.update(schema="given_request_branch_host_readout_v1",
            original_call_status=call["status"],
            scope="One conditional answer from the same supplied public task and this actual "
                  "branch's returned packet. No original answer, hidden Store, prior Host "
                  "conversation or extra retrieval. This is not autonomous Host evaluation.")
    tool_completed = (call["status"] == "ORIGINAL_COMPLETED" if replay is None else
                      replay["status"] == "COMPLETED")
    if not tool_completed or result["status"] != "COMPLETED":
        return {**frame, "reason": "GIVEN_RETRIEVAL_NOT_COMPLETED"}
    receipt, = [message for message in result["messages"]
                if message["type"] == "tool" and message["tool_call_id"] == call["call_id"]]
    packet = json.loads(receipt["content"])
    if (packet != result["retrieval_result"]
            or (replay is None and packet != call["original_result"])):
        raise ValueError("GIVEN_READOUT_RETURNED_PACKET_CHANGED")
    host = VLLMConfig(**settings["host"])
    public_time = {key: public[key] for key in (
        "occurred_at", "query_time", "calendar_context", "query_calendar_context") if key in public}
    request = {
        "model": host.model, "temperature": host.temperature, "max_tokens": host.max_tokens,
        # The frozen settings have already been validated. Actual dispatch still
        # constructs HostCapacity and checks the whole wire; no tokenizer load
        # is needed merely to copy this flag and its defined default.
        "chat_template_kwargs": {"enable_thinking": settings["capacity"].get(
            "enable_thinking", False)},
        "messages": [{"role": "system", "content": settings["system_prompt"]},
            {"role": "user", "content": json.dumps({
                "request": public["content"], "retrieval_request": call["request"],
                "memory": packet,
                **({"public_request_time": public_time} if public_time else {})},
                ensure_ascii=False)}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "answer", "schema": copy.deepcopy(ANSWER_SCHEMA)}},
    }
    return {**frame, "status": "READY", "request": request}


def run_given_readout(captured: Path, output: Path, *, source_version: str,
                      replay_case: Path | None = None) -> dict[str, Any]:
    """Read out the just-closed Tool result before the sequence admits later arrivals."""
    from milai_lab.runners.functional import _visibility_replay, frozen

    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {
        "status": "RUNNING", "source_version": source_version, "captured_call": str(captured),
        "automatic_retry": False, "actual_http_attempts": 0,
        "http_attempt_scope": "Native dispatch attempts, not provider acknowledgements.",
        "host_request_generated": False, "answer_persisted_as_source": False,
        "cpu_ledger_recorded": False,
        "http_accounting": "Actual bank's original ledger, queue and remaining message allowance.",
        **({"replay": str(replay_case), "readout_origin": "actual_same_before_branch"}
           if replay_case is not None else {}),
    }
    trace = Trace(output / "trace.jsonl", "given_request_host_readout")
    try:
        call = read_json(captured / "call.json")
        replay = read_json(replay_case / "replay.json") if replay_case is not None else None
        if replay is not None and (Path(replay["captured_call"]).resolve() != captured.resolve()
                                   or replay["source_version"] != source_version):
            raise ValueError("GIVEN_BRANCH_READOUT_CAPTURE_CHANGED")
        runtime = replay_case / "runtime" if replay_case is not None else Path(call["source_root"])
        freeze = frozen(runtime)
        if (call["source_version"]["git_commit"] != source_version
                or freeze["source_version"] != call["source_version"]):
            raise ValueError("GIVEN_READOUT_SOURCE_VERSION_CHANGED")
        result_path = (replay_case / "replay.json" if replay_case is not None
                       else runtime / call["host_result_path"])
        result = replay["result"] if replay is not None else read_json(result_path)
        bank = runtime / Path(call["source_bank_root"]).relative_to(call["source_root"])
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = MemoryService(store, tuple(call["binding"]["bank"]),
                call["binding"]["owner"], bank / "memory.lock", functional_contract="functional_v1")
            blocked = _visibility_replay(service, result, session=call["binding"]["session"],
                                         message_id=call["public_message"]["message_id"])
        if blocked is not None:
            report.update(status="NOT_EXECUTED", reason="GIVEN_READOUT_VISIBILITY_REVOKED",
                          visibility_receipt=blocked)
            return report
        frame = given_readout_frame(call, result, freeze["config"], replay=replay)
        report.update(scope=frame["scope"], **{
            "original_result" if replay is None else "branch_result": str(result_path)})
        write_json(output / "frame.json", frame)
        if frame["status"] != "READY":
            report.update(status="NOT_EXECUTED", reason=frame["reason"])
            return report
        write_json(output / "request.json", frame["request"])
        execute_readout_request(runtime, call, frame["request"], output, report, trace,
                                answer_mode="json_action")
        return report
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        if isinstance(error, CapacityExceeded):
            report["capacity_rejection"] = error.receipt
        raise
    finally:
        report.update(wall_seconds=time.perf_counter() - started,
                      cpu_seconds=time.process_time() - cpu, usage=trace.usage)
        write_json(output / "readout.json", report)

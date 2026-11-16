"""Execute an actual STATE retrieval capture in an isolated Store copy."""
from __future__ import annotations

import copy
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import Trace
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.memory_control import FirstActionIntervention, MemoryAction
from milai_lab.runners.state_bench_adapter import learning_envelope


def replay_state_retrieval(
    captured: Path, output: Path, *, source_version: str,
    build_memory: Callable[
        [MemoryService, Callable[[dict[str, Any]], None]], IntentRetrievalMemory],
    intervention: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep actual request/allowance/bindings; optionally force one captured action.

    The caller supplies the declared policy, tokenizer and existing metered model
    clients. This executor never opens a budget, regenerates a Host request or
    executes domain tools. Its CPU measurement is nested in the caller's cost.
    """
    call = read_json(captured / "call.json")
    if call["schema"] not in {
            "state_dynamic_retrieval_call_v1", "state_dynamic_retrieval_decision_v1"}:
        raise ValueError("STATE replay requires an actual dynamic STATE capture")
    if call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}:
        raise ValueError("Original STATE collection must be closed before comparison")
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    trace = Trace(output / "trace.jsonl", "state_retrieval_replay")
    report: dict[str, Any] = {"status": "RUNNING", "source_version": source_version,
        "captured_call": str(captured.resolve()), "call_id": call["call_id"],
        "intervention": copy.deepcopy(intervention), "automatic_retry": False,
        "host_request_regenerated": False, "domain_tools_executed": 0,
        "frozen_request_and_allowance_equal": False,
        "frozen_initial_observation_and_actions_equal": None,
        "scope": "Actual frozen STATE tool execution; no Host answer or task-quality label. "
                 "Original prefix remains logical usage, not newly executed work."}
    write_json(output / "replay.json", report)
    first_seen = False

    def observe(event: dict[str, Any]) -> None:
        nonlocal first_seen
        if event["phase"] == "start":
            for field in ("request", "binding", "read_allowance"):
                if event[field] != call[field]:
                    raise ValueError(f"STATE_REPLAY_{field.upper()}_CHANGED")
            report["frozen_request_and_allowance_equal"] = True
        elif event["phase"] == "decision_input" and not first_seen:
            if (event["before"] != call["initial_observation"]
                    or event["actions"] != call["initial_actions"]):
                raise ValueError("STATE_REPLAY_INITIAL_DECISION_CHANGED")
            first_seen = True
            report["frozen_initial_observation_and_actions_equal"] = True

    try:
        if intervention is not None:
            if intervention["first_action"] not in (call["initial_actions"] or []):
                raise ValueError("STATE branch action is not a captured complete binding")
            if (type(intervention["continuation_steps"]) is not int
                    or intervention["continuation_steps"] < 0):
                raise ValueError("STATE branch continuation_steps must be nonnegative")
        runtime = output / "runtime"
        runtime.mkdir()
        for name in ("memory.sqlite", "domain.json"):
            shutil.copyfile(captured / "before" / name, runtime / name)
        checkpoint = (read_json(captured / call["control_checkpoint"])
                      if "control_checkpoint" in call else None)
        with TransactionalSqliteStore.from_conn_string(str(runtime / "memory.sqlite")) as store:
            settings = call["store"]
            service = MemoryService(store, tuple(settings["namespace"]), settings["owner"],
                runtime / "memory.lock", functional_contract=settings["functional_contract"],
                memory_profile=settings["memory_profile"],
                memory_ranking=settings["memory_ranking"])
            bound = call["binding"]
            service.bind_public_turn(bound["session"], bound["message_id"], bound["source_ref"],
                                     config_version=bound["config_version"], phase="resume")
            memory = build_memory(service, trace)
            memory.return_envelope = learning_envelope
            memory.replay_admission_policy = call["admission_policy"]
            memory.replay_initial_observation = call["initial_observation"]
            memory.replay_control_checkpoint = checkpoint
            memory.retrieval_observer = observe
            if intervention is not None:
                memory.control_intervention = FirstActionIntervention(
                    MemoryAction(**intervention["first_action"]),
                    intervention["continuation_steps"])
            report.update(restored_control_step=checkpoint["step"] if checkpoint else 0,
                          prefix_operations_reexecuted=0)
            packet = memory.retrieve(call["runnable_config"], call["call_id"],
                                     RetrievalRequest.model_validate(call["request"]))
            if call["initial_observation"] is not None and not first_seen:
                raise ValueError("STATE_REPLAY_ORIGINAL_DECISION_NOT_REACHED")
            report.update(status="COMPLETED", packet=packet, envelope=learning_envelope(packet),
                complete_return_tokens=memory.return_tokens(packet),
                read_allowance_after=memory.read_allowance(call["runnable_config"]))
            write_json(output / "packet.json", packet)
            return report
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report.update(wall_seconds=time.perf_counter() - started,
            cpu_seconds_nested=time.process_time() - cpu,
            accounting="Nested executor CPU; caller separates already billed model CPU. "
                       "No ledger opened or written by this executor.")
        write_json(output / "replay.json", report)

"""Prepare explicit current-version F1 inputs from a closed post-operation capture.

Original observations and outcomes remain in the source capture. This prepares a
new presentation of the same acquired materials, not another collection outcome.
The ordinary replay executor still checks the complete prepared observation/menu.
"""
from __future__ import annotations

import copy
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, NoReturn

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.functional_state import canonical, reference_key
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.intent_retrieval import delivery_packet_fits
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.source_observations import SourceObservationBudget
from milai_lab.providers.contextual_capacity import HostCapacity


def _no_acquisition(*args: Any, **kwargs: Any) -> NoReturn:
    raise RuntimeError("F1 input preparation cannot acquire or generate material")


def prepare_handoff_call(captured: Path, output: Path, *, source_version: str) -> dict[str, Any]:
    """Copy before; reproject only delivery fields and regenerate the legal menu.

    Preparation does not execute a policy, return a receipt, create known evidence,
    change the read allowance, or write the shared model ledger. Its CPU cost is
    reported for the caller's next idle settlement.
    """
    started, cpu = time.perf_counter(), time.process_time()
    call = read_json(captured / "call.json")
    if (call["schema"] != "frozen_retrieval_decision_v1"
            or call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}):
        raise ValueError("F1 preparation requires a closed actual post-operation capture")
    checkpoint = read_json(captured / call["control_checkpoint"])
    if checkpoint["state"] != call["initial_observation"]:
        raise ValueError("Captured checkpoint and original observation differ")
    output.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {"status": "PREPARING", "source_capture": str(captured.resolve()),
        "source_version": source_version, "model_calls": 0, "operations_executed": 0,
        "ledger_recorded": False,
        "scope": "Explicit new delivery projection/menu on the same actual post-state; "
                 "not a new original outcome or evidence-sufficiency label."}
    try:
        before = output / "before"
        shutil.copytree(captured / "before", before)
        settings = read_json(before / "input-freeze.json")["config"]
        control = settings["memory_control"]
        if not control.get("delivery_selection"):
            raise ValueError("F1 comparison requires the captured delivery-selection executor")
        capacity = HostCapacity(settings["capacity"])
        request = RetrievalRequest.model_validate(call["request"])
        configured_steps = control.get("max_control_steps", 8)
        steps = min(configured_steps, request.limits.max_control_steps
                    if request.limits.max_control_steps is not None else configured_steps)
        limit = min(settings["ordinary_material_tokens"], request.limits.max_return_tokens
                    or settings["ordinary_material_tokens"])
        key = "retrieval:" + reference_key([call["binding"]["session"],
                                            call["binding"]["message_id"], call["call_id"]])
        state = MemoryControlState(**copy.deepcopy(checkpoint["state"]))
        known = checkpoint["operations"]["known_materials"]

        def fits(items: dict[int, dict[str, Any]]) -> bool:
            return delivery_packet_fits(key, items, steps=steps, known_count=len(known),
                return_limit=limit, return_tokens=lambda packet: capacity.text_tokens(
                    canonical(packet)))

        bank = before / Path(call["source_bank_root"]).relative_to(call["source_root"])
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = MemoryService(store, tuple(call["binding"]["bank"]),
                call["binding"]["owner"], bank / "memory.lock", functional_contract="functional_v1",
                memory_profile=settings.get("memory_profile", "ordinary"),
                memory_ranking=settings.get("memory_ranking", "dense"))
            observation_tokens = control.get("source_observation_tokens")
            operations = EvidenceOperations(service, state, load_pool=_no_acquisition,
                search_pool=_no_acquisition, refresh_call=_no_acquisition, fits=_no_acquisition,
                fits_materials=fits, known_materials=known,
                search_batch_sizes=tuple(dict.fromkeys(
                    min(n, settings.get("source_top_k", 20)) for n in (8, 16))),
                view_capacity=control.get("view_capacity", 1),
                view_policy=control.get("view_policy", "incremental"),
                view_builder=control.get("view_builder", "generated"),
                internal_views=control.get("internal_views", True),
                source_observation=SourceObservationBudget(observation_tokens, capacity.text_tokens)
                    if observation_tokens is not None else None,
                delivery_selection=True, checkpoint=checkpoint["operations"])
            operations._deliver(state)
            state.budget.update(remaining_control_steps=steps - checkpoint["step"],
                reader_capacity_reserved=True,
                acquisition_reads_remaining=call["read_allowance"]["reads_remaining"])
            actions = operations.actions(state)
            if not call["read_allowance"]["reads_remaining"]:
                actions = [action for action in actions if action.kind == "HANDOFF"]
            if canonical(operations.checkpoint()) != canonical(checkpoint["operations"]):
                raise ValueError("Current preparation changed captured executor materials/state")
        projected = state.project()
        # All current semantic inputs outside delivery projection must remain literal.
        delivery_fields = {"visible_evidence", "observed_materials", "observed_evidence",
                           "retrieved_scopes"}
        changed = {name for name in projected.keys() | checkpoint["state"].keys()
                   if projected.get(name) != checkpoint["state"].get(name)}
        if changed - delivery_fields:
            raise ValueError("F1 preparation changed request, history, allowance or navigation")
        report.update(status="PREPARED_NOT_EXECUTED", changed_observation_fields=sorted(changed),
            original_actions=call["initial_actions"], current_actions=[asdict(a) for a in actions],
            original_observation=call["initial_observation"], current_observation=projected,
            prefix_operations_reexecuted=0, executor_materials_serialized_equal=True,
            known_evidence_unchanged=projected["task"] == checkpoint["state"]["task"],
            max_return_tokens=limit, read_allowance=call["read_allowance"])
        projection = {key: report[key] for key in ("source_capture", "source_version", "scope",
            "changed_observation_fields", "executor_materials_serialized_equal")}
        prepared = {**copy.deepcopy(call), "schema": "handoff_comparison_decision_v1",
            "initial_observation": projected, "initial_actions": report["current_actions"],
            "control_checkpoint": "control.json", "comparison_projection": projection,
            "scope": "Original call status/outcome retained for provenance; current F1 input "
                     "prepared but not executed. See preparation.json for literal input changes."}
        write_json(output / "control.json", {**checkpoint, "state": projected})
        write_json(output / "call.json", prepared)
        return report
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report.update(cpu_seconds_pending=time.process_time() - cpu,
                      wall_seconds=time.perf_counter() - started)
        write_json(output / "preparation.json", report)

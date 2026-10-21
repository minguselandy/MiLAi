"""Capture and execute a real retrieval call from its original Store and allowance."""
from __future__ import annotations

import copy
import shutil
import sqlite3
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def copy_call_root(root: Path, bank_root: Path, destination: Path) -> None:
    """Copy one active bank, using SQLite online backups rather than raw WAL files.

    The caller serializes tool execution and holds the service lock. Other banks
    are not part of this request. The original ledger stays an external path in
    input-freeze.json, never a forked budget for the experiment.
    """
    destination.mkdir(parents=True, exist_ok=False)
    for path in root.iterdir():
        if path.is_file():
            shutil.copy2(path, destination / path.name)
    target_bank = destination / bank_root.relative_to(root)
    shutil.copytree(bank_root, target_bank,
        ignore=shutil.ignore_patterns("*.sqlite", "*.sqlite-wal", "*.sqlite-shm"))
    for database in bank_root.rglob("*.sqlite"):
        target = target_bank / database.relative_to(bank_root)
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(target) as saved:
                source.backup(saved)


class RetrievalRecorder:
    """Keep every actual call, including failed and zero-decision calls."""

    def __init__(
        self, directory: Path, root: Path, bank_root: Path,
        context: Callable[[], dict[str, Any]], snapshot: Callable[[Path], None],
        *, capture_control_steps: bool = False,
    ) -> None:
        self.directory, self.root, self.bank_root = directory, root, bank_root
        self.context, self.snapshot = context, snapshot
        self.capture_control_steps = capture_control_steps
        self.calls: dict[str, tuple[Path, dict[str, Any]]] = {}
        self.steps: dict[str, list[tuple[Path, dict[str, Any]]]] = {}

    def __call__(self, event: dict[str, Any]) -> None:
        call_id, phase = event["call_id"], event["phase"]
        if phase == "start":
            case = self.directory / str(uuid.uuid4())
            case.mkdir(parents=True, exist_ok=False)
            row = {"schema": "frozen_retrieval_call_v2", "status": "CAPTURING",
                **copy.deepcopy(self.context()), **copy.deepcopy(event),
                "source_root": str(self.root), "source_bank_root": str(self.bank_root),
                "captured_epoch": time.time(),
                "initial_observation": None, "initial_actions": None,
                "scope": "Actual literal Host call and pre-call state; "
                         "later trajectories may differ."}
            self.calls[call_id] = (case, row)
            self.steps[call_id] = []
            write_json(case / "call.json", row)
            wall, cpu = time.perf_counter(), time.process_time()
            try:
                self.snapshot(case / "before")
                row["status"] = "CAPTURED"
            except BaseException as error:
                row.update(status="CAPTURE_FAILED", error_type=type(error).__name__,
                           error=str(error))
                raise
            finally:
                row["capture_compute"] = {"wall_seconds": time.perf_counter() - wall,
                    "cpu_seconds": time.process_time() - cpu, "ledger_recorded": False,
                    "scope": "Nested collection overhead; do not double count driver CPU."}
                write_json(case / "call.json", row)
            return
        case, row = self.calls[call_id]
        if phase == "decision_input":
            if row["initial_observation"] is None:
                row.update(initial_observation=event["before"], initial_actions=event["actions"])
            elif not self.capture_control_steps:
                return
            if self.capture_control_steps and event["step"] > 0:
                step_case = case / "steps" / f"step-{event['step']:04d}"
                step_case.mkdir(parents=True, exist_ok=False)
                step = {**copy.deepcopy(row), **copy.deepcopy(self.context()),
                    "schema": "frozen_retrieval_decision_v1", "control_step": event["step"],
                    "captured_epoch": time.time(), "read_allowance": event["read_allowance"],
                    "initial_observation": event["before"], "initial_actions": event["actions"],
                    "control_checkpoint": "control.json", "status": "CAPTURING",
                    "initial_capture": str(case.resolve()),
                    "scope": "Actual post-operation decision and complete executor/Store state; "
                             "prefix operations are not reexecuted."}
                write_json(step_case / "control.json", event["control_checkpoint"])
                wall, cpu = time.perf_counter(), time.process_time()
                try:
                    self.snapshot(step_case / "before")
                    step["status"] = "CAPTURED"
                except BaseException as error:
                    step.update(status="CAPTURE_FAILED", error_type=type(error).__name__,
                                error=str(error))
                    raise
                finally:
                    step["capture_compute"] = {"wall_seconds": time.perf_counter() - wall,
                        "cpu_seconds": time.process_time() - cpu, "ledger_recorded": False,
                        "scope": "Nested snapshot overhead, not additional model work."}
                    write_json(step_case / "call.json", step)
                self.steps[call_id].append((step_case, step))
        elif phase == "completed":
            row.update(status="ORIGINAL_COMPLETED", original_result=event["result"],
                       served_from_cache=event["served_from_cache"])
        elif phase == "failed":
            row.update(status="ORIGINAL_FAILED", error_type=event["error_type"],
                       error=event["error"])
        if phase in {"completed", "failed"}:
            for step_case, step in self.steps[call_id]:
                step.update(status=row["status"])
                for name in ("original_result", "served_from_cache", "error_type", "error"):
                    if name in row:
                        step[name] = copy.deepcopy(row[name])
                write_json(step_case / "call.json", step)
        write_json(case / "call.json", row)


def replay_call(
    captured: Path, output: Path, policy: dict[str, Any], *, source_version: str,
    models: dict[tuple[Any, ...], Any] | None = None,
    intervention: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One new arm from the retained before, reusing the original public-message identity.

    No answer generation or automatic retry is added. This is the tool component
    of E2; the fixed Host downstream comparison is a separate required step.
    """
    from milai_lab.runners.functional import message

    call = read_json(captured / "call.json")
    if call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}:
        raise ValueError("Frozen call collection must be closed before comparison")
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    run: dict[str, Any] = {
        "status": "RUNNING", "captured_call": str(captured), "source_version": source_version,
        "policy": policy, "automatic_retry": False, "host_request_regenerated": False,
        "scope": "Frozen actual request tool execution; no downstream Host score.",
        **({"intervention": copy.deepcopy(intervention)} if intervention is not None else {}),
    }
    write_json(output / "replay.json", run)
    entry_budget = None
    try:
        if "control_checkpoint" in call:
            call["execution_checkpoint"] = read_json(captured / call["control_checkpoint"])
            prefix = call["execution_checkpoint"]["prefix_trace"]
            run.update(restored_control_step=call["execution_checkpoint"]["step"],
                prefix_operations_reexecuted=0,
                restored_prefix_usage={"control_steps": len(prefix),
                    "operations": sum("result" in event for event in prefix),
                    "read_operations": sum(any(action["id"] == event["selected"]
                        and action["kind"] == "READ" for action in event["actions"])
                        for event in prefix)},
                accounting_scope="Returned packet usage includes the logical original prefix. "
                    "Replay timing/ledger deltas measure only this new execution; "
                    "original prefix/model costs remain in the source collection.")
        if intervention is not None:
            if intervention["first_action"] not in (call["initial_actions"] or []):
                raise ValueError("Intervention first action is not a captured legal action")
            call = {**call, "intervention": copy.deepcopy(intervention)}
        root = output / "runtime"
        shutil.copytree(captured / "before", root)
        settings = read_json(root / "input-freeze.json")["config"]
        entry_budget = read_json(Path(settings["budget_path"]))
        result = message(root, bank=call["bank"], **call["public_message"],
            replay_retrieval=call, control_policy_override=policy, control_models=models,
            resume=True)
        run.update(status=result["status"], result=result)
        return result
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        elapsed = time.process_time() - cpu
        run.update(wall_seconds=time.perf_counter() - started, cpu_seconds_nested=elapsed)
        if entry_budget is not None:
            after = read_json(Path(settings["budget_path"]))
            charged = sum(value.get("cpu_seconds", 0) - entry_budget.get("compute", {}).get(
                name, {}).get("cpu_seconds", 0) for name, value in after.get("compute", {}).items())
            run.update(ledger_compute_cpu_seconds_nested=charged,
                       cpu_seconds_not_yet_recorded=elapsed - charged,
                       budget_before=entry_budget, budget_after=after)
        write_json(output / "replay.json", run)

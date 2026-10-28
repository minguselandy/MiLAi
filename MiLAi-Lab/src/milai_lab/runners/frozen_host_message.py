"""First-Host-decision snapshots and complete autonomous presentation branches."""
from __future__ import annotations

import copy
import json
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.providers.request_pipeline import ResponseEvent, ResponseHook
from milai_lab.runners.host_evidence_presentation import PRESENTATION


def memory_store_values(service: MemoryService) -> list[dict[str, Any]]:
    """Read the complete bank namespace, including Sources, views and admission values.

    Use the Store's non-semantic enumeration, without issuing read handles or
    touching access metadata through MemoryService.read/export_snapshot.
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = service.store.search(service.namespace, limit=1000, offset=offset)
        rows.extend({"namespace": list(item.namespace), "key": item.key, "value": item.value}
                    for item in page)
        if len(page) < 1000:
            break
        offset += len(page)
    return sorted(rows, key=lambda row: (row["namespace"], row["key"]))


def captured_bank_values(snapshot: Path, root: Path, bank: Path,
                         row: dict[str, Any]) -> list[dict[str, Any]]:
    from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore

    public_source, = [item for item in row["ready_state"]["memory_store_values"]
        if item["namespace"][-1] == "v13_1_sources"
        and item["key"] == row["ready_state"]["public_source_ref"]]
    copied_bank = snapshot / bank.relative_to(root)
    with SqliteStore.from_conn_string(str(copied_bank / "memory.sqlite")) as store:
        service = MemoryService(store, tuple(public_source["namespace"][:-1]),
            row["public_message"]["owner"], copied_bank / "memory.lock",
            functional_contract="functional_v1")
        return memory_store_values(service)


class HostMessageRecorder:
    """Capture before graph input/model dispatch, then record the actual first context.

    The collection's ordinary result file proves closure; this recorder does not
    turn a failed/interrupted original message into a completed outcome.
    """

    def __init__(self, directory: Path, root: Path, bank_root: Path,
                 metadata: dict[str, Any], snapshot: Callable[[Path], None]) -> None:
        self.directory, self.root, self.bank_root = directory, root, bank_root
        self.metadata, self.snapshot = metadata, snapshot
        self.path: Path | None = None
        self.row: dict[str, Any] = {}

    def ready(self, state: dict[str, Any]) -> None:
        self.path = self.directory / str(uuid.uuid4())
        self.path.mkdir(parents=True, exist_ok=False)
        self.row = {"schema": "frozen_host_message_v1", "status": "CAPTURING",
            **copy.deepcopy(self.metadata), "source_root": str(self.root.resolve()),
            "source_bank_root": str(self.bank_root.resolve()), "ready_state": copy.deepcopy(state),
            "initial_baseline_context": None, "initial_tool_catalog": None,
            "delivered_model_requests": [],
            "captured_epoch": time.time(),
            "scope": "Same actual public message before its first Host model dispatch. "
                     "Source imports/history are common preparation, not reexecuted tools. "
                     "Memory/world audits stay outside model input."}
        write_json(self.path / "host.json", self.row)
        started, cpu = time.perf_counter(), time.process_time()
        try:
            self.snapshot(self.path / "before")
            self.row["status"] = "CAPTURED_PRE_HOST"
        except BaseException as error:
            self.row.update(status="CAPTURE_FAILED", error_type=type(error).__name__,
                            error=str(error))
            raise
        finally:
            self.row["capture_compute"] = {"wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu, "ledger_recorded": False,
                "scope": "Nested original message/driver CPU, not additional model work."}
            write_json(self.path / "host.json", self.row)

    def context(self, messages: list[Any]) -> None:
        if self.path is not None and self.row["initial_baseline_context"] is None:
            self.row["initial_baseline_context"] = [m.model_dump(mode="json") for m in messages]
            write_json(self.path / "host.json", self.row)

    def catalog(self, tools: list[dict[str, Any]]) -> None:
        if self.path is not None and self.row["initial_tool_catalog"] is None:
            self.row["initial_tool_catalog"] = copy.deepcopy(tools)
            write_json(self.path / "host.json", self.row)

    def delivered(self, event: ResponseEvent) -> None:
        if self.path is None:
            return
        self.row["delivered_model_requests"].append({
            "schema": "provider_request_content_v1", "output_message_id": event.message_id,
            "messages": [{key: copy.deepcopy(value) for key, value in message.items()
                          if key not in {"reasoning", "reasoning_content"}}
                         for message in event.request.messages],
            "tools": copy.deepcopy(event.request.tools),
            "scope": "Request content associated with a decoded provider response; "
                     "provider reasoning fields are omitted. Not a correctness judgment."})
        write_json(self.path / "host.json", self.row)
        if event.message is not None and not event.message.tool_calls:
            self.capture_final_input_bank(event)

    def capture_final_input_bank(self, event: ResponseEvent) -> None:
        """Snapshot after the provider input was delivered, before its answer becomes a Source.

        Optional recording failure is retained without changing the actual decoded
        response. Only the eventual closed invocation may certify this boundary.
        """
        assert self.path is not None
        started, wall = time.process_time(), time.perf_counter()
        name = f"final-input-{len(self.row['delivered_model_requests']):04d}"
        report: dict[str, Any] = {"status": "CAPTURING", "snapshot": name,
            "inventory": name + "-store.json", "output_message_id": event.message_id}
        self.row["delivered_model_requests"][-1]["pre_final_snapshot"] = report
        write_json(self.path / "host.json", self.row)
        try:
            self.snapshot(self.path / name)
            values = captured_bank_values(self.path / name, self.root, self.bank_root, self.row)
            write_json(self.path / report["inventory"], {"memory_store_values": values})
            report["status"] = "CAPTURED_BEFORE_FINAL_RESPONSE_PERSISTENCE"
        except Exception as error:
            report.update(status="FAILED_RETAINED", error_type=type(error).__name__,
                          error=str(error))
        finally:
            report["capture_compute"] = {"cpu_seconds_nested": time.process_time() - started,
                "wall_seconds_nested": time.perf_counter() - wall, "ledger_recorded": False,
                "scope": "Inside original invocation/collector; do not add this CPU again."}
            write_json(self.path / "host.json", self.row)


class HostResponseRecorder:
    """Observe the existing decoded-response hook without changing request or response."""

    def __init__(self, recorder: HostMessageRecorder, inner: ResponseHook | None) -> None:
        self.recorder, self.inner = recorder, inner

    def on_response(self, event: ResponseEvent) -> None:
        if self.inner is not None:
            self.inner.on_response(event)
        if event.stage == "decoded_message":
            self.recorder.delivered(event)


def capture_closed_host_message(captured: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Retain the bank at this closed invocation before later messages change it.

    A final provider request is associated only with a completed final Host
    generation and its unique decoded message identity. Ambiguous or failed cases
    remain recorded without certifying a context or evidence sufficiency.
    """
    from milai_lab.runners.frozen_retrieval import copy_call_root

    started = time.process_time()
    wall = time.perf_counter()
    row = read_json(captured / "host.json")
    if (row["schema"] != "frozen_host_message_v1" or row["status"] != "CAPTURED_PRE_HOST"
            or result["status"] in {"RUNNING", "PENDING", "UNKNOWN"}
            or result["bank"] != row["bank"]
            or any(result[k] != v for k, v in row["public_message"].items())):
        raise ValueError("Closed snapshot requires this exact returned public invocation")
    root, bank = Path(row["source_root"]), Path(row["source_bank_root"])
    original = read_json(root / row["host_result_path"])
    if json.dumps(original, ensure_ascii=False) != json.dumps(result, ensure_ascii=False):
        raise ValueError("Returned message differs from its persisted actual attempt")
    if read_json(root / "input-freeze.json")["source_version"] != row["source_version"]:
        raise ValueError("Closed snapshot requires the captured implementation")
    after = captured / "after"
    copy_call_root(root, bank, after)
    values = captured_bank_values(after, root, bank, row)
    messages = result.get("messages", [])
    final_generation = (result["status"] == "COMPLETED" and bool(messages)
        and messages[-1]["type"] == "ai" and not messages[-1].get("tool_calls")
        and "failure_delivery" not in result)
    deliveries = row["delivered_model_requests"]
    matches = ([i for i, delivery in enumerate(deliveries)
                if delivery["output_message_id"] == messages[-1]["id"]]
               if final_generation else [])
    bound = final_generation and len(matches) == 1
    report = {"schema": "closed_host_message_v1", "status": "CLOSED_INVOCATION_SNAPSHOTTED",
        "source_capture": str(captured.resolve()), "source_version": row["source_version"],
        "bank": row["bank"], "public_message": row["public_message"],
        "message_status": result["status"], "generation_calls": result["generation_calls"],
        "result_path": row["host_result_path"], "snapshot": "after",
        "public_source_ref": row["ready_state"]["public_source_ref"],
        "memory_store_values": values, "delivered_request_candidates": matches,
        "final_context_status": "BOUND_TO_COMPLETED_FINAL_GENERATION" if bound else
            "NOT_BOUND_TO_A_COMPLETED_FINAL_GENERATION",
        "final_context": copy.deepcopy(deliveries[matches[0]]) if bound else None,
        "pre_final_snapshot": (copy.deepcopy(deliveries[matches[0]].get("pre_final_snapshot"))
                               if bound else None),
        "scope": "Exact post-invocation Store/Saver and provider-request content bound by "
                 "decoded final response identity; provider reasoning omitted. No replay, "
                 "known-reference creation, semantic witness label or Host-success grade. "
                 "Earlier receipts, current visibility and Source slices still require audit.",
        "capture_compute": {"cpu_seconds_nested": time.process_time() - started,
            "wall_seconds_nested": time.perf_counter() - wall, "ledger_recorded": False,
            "scope": "Collection-driver CPU includes this snapshot; do not add it again."}}
    write_json(captured / "closed.json", report)
    return report


def replay_host_message(
    captured: Path, output: Path, presentation: str, *, source_version: str,
    models: dict[tuple[Any, ...], Any] | None = None,
) -> dict[str, Any]:
    """One full Host/tools/answer branch from a real pre-Host snapshot; never retry.

    Only the presentation is overridden. Source imports, prior delivered messages,
    per-message admission and read allowance are restored by the ordinary runner.
    The original ledger is shared; global consumed cost is never rolled back.
    """
    from milai_lab.runners.functional import message

    row = read_json(captured / "host.json")
    if (row["schema"] != "frozen_host_message_v1" or row["status"] != "CAPTURED_PRE_HOST"
            or row["initial_baseline_context"] is None or row["initial_tool_catalog"] is None):
        raise ValueError("Host comparison requires a pre-Host snapshot and first model context")
    original = read_json(Path(row["source_root"]) / row["host_result_path"])
    if original["status"] in {"RUNNING", "PENDING", "UNKNOWN"}:
        raise ValueError("Close the original public message before branching")
    if source_version != row["source_version"]["git_commit"]:
        raise ValueError("Host comparison requires the captured implementation version")
    if presentation not in {"current", PRESENTATION}:
        raise ValueError("Unknown Host presentation arm")
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {"status": "RUNNING", "captured_host": str(captured),
        "source_version": source_version, "presentation": presentation,
        "original_message_status": original["status"], "automatic_retry": False,
        "prefix_model_or_tool_operations_reexecuted": None,
        "scope": "Full autonomous Host continuation from common pre-first-model state; "
                 "read/answer behavior is newly executed, not a forced final-only readout."}
    write_json(output / "replay.json", report)
    entry_budget = None
    try:
        runtime = output / "runtime"
        shutil.copytree(captured / "before", runtime)
        settings = read_json(runtime / "input-freeze.json")["config"]
        entry_budget = read_json(Path(settings["budget_path"]))
        result = message(runtime, bank=row["bank"], **row["public_message"],
            replay_host_message=row, host_presentation_override=presentation,
            control_models=models, resume=True)
        report.update(status=result["status"], result=result)
        if result.get("frozen_pre_host_state_equal"):
            report["prefix_model_or_tool_operations_reexecuted"] = 0
        if result["status"] == "COMPLETED" and not all(result.get(key) for key in (
                "frozen_pre_host_state_equal", "frozen_host_baseline_context_equal",
                "frozen_host_tool_catalog_equal")):
            raise ValueError("Completed Host branch did not verify the common first decision")
        return result
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        elapsed = time.process_time() - cpu
        report.update(cpu_seconds_nested=elapsed, wall_seconds=time.perf_counter() - started)
        if entry_budget is not None:
            after = read_json(Path(settings["budget_path"]))
            charged = sum(value.get("cpu_seconds", 0) - entry_budget.get("compute", {}).get(
                name, {}).get("cpu_seconds", 0) for name, value in after.get("compute", {}).items())
            report.update(ledger_compute_cpu_seconds_nested=charged,
                cpu_seconds_not_yet_recorded=elapsed - charged,
                budget_before=entry_budget, budget_after=after)
        write_json(output / "replay.json", report)

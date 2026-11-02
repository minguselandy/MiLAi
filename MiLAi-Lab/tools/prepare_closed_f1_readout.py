"""Bind a fresh controlled readout to an actual closed standalone F1 delivery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import read_json, read_jsonl
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import open_evidence_packs, project_packs
from milai_lab.runners.frozen_host_readout import readout_batch
from prepare_known_budget_readout import append_fresh_request

BOUNDARY = (
    "CLOSED_F1_TOOL_BANK_AFTER_NONPERSISTENT_READOUT_WITH_DECLARED_RUNTIME_METADATA_TRANSITION"
)


def resolved_known_input(preparation: dict[str, Any], call: dict[str, Any]) -> list[dict[str, Any]]:
    """Reopen exact delivered raw refs; no acquisition, generation, or Store mutation."""
    refs = call["request"]["task_context"]["known_evidence_refs"]
    inventory = preparation["source_store_values"]
    snapshots = {row["key"]: row["value"] for row in inventory
                 if row["namespace"] == [*call["binding"]["bank"], "v13_5_functional"]}
    materials = []
    for ref in refs:
        stored = snapshots[ref["snapshot_id"]]
        if (stored["status"] != "completed" or ref["collection"] != "materials"
                or ref["item_index"] not in stored["delivered_indices"]):
            raise ValueError("Known ref was not actually delivered")
        material = stored["materials"][ref["item_index"]]
        if material["kind"] != "original_source":
            raise ValueError("This boundary requires raw known evidence")
        materials.append(material)
    bank = Path(preparation["source_snapshot"]) / preparation["source_bank_relative"]
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(store, tuple(call["binding"]["bank"]),
            call["binding"]["owner"], bank / "memory.lock", functional_contract="functional_v1")
        opened = open_evidence_packs(service, materials)
    return project_packs(opened, list(range(len(opened))))


def prepare_closed_f1_readout(
    preparation: dict[str, Any], execution: Path, captured: Path,
) -> dict[str, Any]:
    """Keep the actual prior wire and add the reached fresh call, without its old answer.

    A standalone F1 readout does not persist an assistant Source. Its closed Tool
    bank is therefore a distinct legitimate starting boundary, not a normal Host
    pre-final snapshot. Initial and post-operation captures retain that distinction.
    """
    if (preparation["status"] != "FRESH_RAW_KNOWN_BUDGET_REQUESTS_PREPARED_NOT_EXECUTED"
            or preparation["source_snapshot_boundary"] != BOUNDARY):
        raise ValueError("Requires the explicitly declared closed F1 boundary")
    run = read_json(execution / "run.json")
    call = read_json(captured / "call.json")
    source = Path(call.get("comparison_projection", {}).get("source_capture", captured)).resolve()
    actual = read_json(source / "call.json")
    initial_path = Path(actual.get("initial_capture", source)).resolve()
    initial = read_json(initial_path / "call.json")
    if (run["status"] != "COMPLETED" or not run["exact_starting_bank_values"]
            or Path(run["source_snapshot"]).resolve()
            != Path(preparation["source_snapshot"]).resolve()
            or run["source_snapshot_boundary"] != BOUNDARY
            or [Path(p).resolve() for p in run["call_captures"]] != [initial_path.resolve()]
            or (source != initial_path and not source.is_relative_to(initial_path / "steps"))):
        raise ValueError("Readout requires the actual closed fresh execution and its capture")
    condition, = [c for c in preparation["conditions"] if c["arm"] == run["arm"]]
    original = read_json(Path(preparation["source_call"]) / "call.json")
    public = {k: v for k, v in preparation["public_message"].items() if k != "bank"}
    public["given_retrieval_request"] = condition["request"]
    for record in (initial, actual, call):
        if (record["status"] != "ORIGINAL_COMPLETED" or record["host_request_generated"]
                or record["source_version"] != preparation["source_version"]
                or record["public_message"] != public
                or record["bank"] != preparation["public_message"]["bank"]
                or record["request"] != condition["request"]
                or record["call_id"] != initial["call_id"]
                or record["host"]["tool_mode"] != original["host"]["tool_mode"]):
            raise ValueError("Fresh call identity, request, or runtime changed")
    audit = read_json(Path(preparation["anchor_audit"]))
    if (audit["actual_provider_request"] != preparation["source_provider_request"]
            or audit["source_readout"] != preparation["source_f1_readout"]
            or audit["source_call"] != preparation["source_call"]
            or condition["request"]["task_context"]["known_evidence_refs"]
            != audit["actual_known_raw_refs"]
            or audit["generated_answer_read_for_input_or_written_to_Store"]):
        raise ValueError("Fresh known input differs from the audited actual delivery")
    readout = read_json(Path(preparation["source_f1_readout"]))
    if readout["status"] != "COMPLETED":
        raise ValueError("Anchor standalone readout did not complete")
    known = resolved_known_input(preparation, initial)
    if not known or any(r["initial_observation"]["task"]["known_evidence"] != known
                        for r in (initial, actual, call)):
        raise ValueError("Actual resolved known input differs from the delivered raw evidence")
    wire = read_json(Path(preparation["source_provider_request"]))
    event, = [e for e in read_jsonl(Path(preparation["source_f1_readout"]).with_name("trace.jsonl"))
              if e["event"] == "vllm_response"]
    if (event["request"] != wire or json.loads(event["response_text"])["id"]
            != preparation["source_provider_output_message_id"]):
        raise ValueError("Anchor input differs from its actual provider exchange")
    request = append_fresh_request(wire, call)
    mode = call["host"]["tool_mode"]
    return {"schema": "frozen_host_readout_v1", "status": "READY",
        "frame_origin": "CONTROLLED_FRESH_REQUEST_AFTER_CLOSED_ACTUAL_DELIVERY",
        "captured_call": str(captured.resolve()), "call_id": call["call_id"], "tool_mode": mode,
        "arm": condition["arm"], "starting_bank_boundary": BOUNDARY,
        "anchor_audit": preparation["anchor_audit"], "fresh_execution": str(execution.resolve()),
        "actual_initial_capture": str(initial_path.resolve()), "resolved_raw_known_equal": True,
        "request": request, "target_message_index": len(request["messages"]) - 1,
        "batch_call_ids": readout_batch(request, mode),
        "source_final_request": wire,
        "source_final_output_message_id": preparation["source_provider_output_message_id"],
        "original_answer_loaded_as_input": False, "host_request_generated": False,
        "target_content_is_placeholder": True,
        "scope": "Controlled request appended to the actual standalone F1 provider input. "
        "The prior public history and receipts remain fixed; the original final answer is "
        "excluded. Only a real fresh branch receipt is substituted for one final readout. "
        "This is an after-F1 Tool-bank boundary, not normal Host pre_final, an autonomous "
        "request, a complete Host knowledge claim, or evidence of learned stopping."}

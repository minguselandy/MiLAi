"""Prepare explicit fresh return-budget requests from actual closed, raw-source evidence."""

from __future__ import annotations

import argparse
import copy
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from audit_host_witnesses import audit_visible_witnesses, covers
from milai_lab.analysis.retrieval_prefixes import select_call_prefixes
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.functional_state import body_text
from milai_lab.memory.retrieval_request import RetrievalRequest


def prepare_pair(
    closed_capture: Path, record: dict[str, Any], *, message_id: str, low: int, high: int
) -> dict[str, Any]:
    """Use the first actual call and its second new-Source READ, without outcome replacement.

    Known input here is explicitly the visible raw-material subset, not a claim
    that the Host knows nothing else. Preparation executes no tool or model.
    """
    report: dict[str, Any] = {
        "status": "INELIGIBLE_RETAINED",
        "family": record["family"],
        "collector": record["collector"],
        "closed_capture": str(closed_capture.resolve()),
        "conditions": [],
        "new_model_or_tool_calls": 0,
        "scope": "Controlled fresh retrieval requests, not autonomous Host decisions, "
        "new reached states, quality labels or complete Host knowledge.",
    }
    if record["status"] != "FIRST_ACTUAL_CALL_RETAINED":
        return {**report, "reason": "no_unique_first_actual_call"}
    selected = record["selection"]
    source_call = Path(selected["capture"])
    original = read_json(source_call / "call.json")
    if select_call_prefixes(source_call) != selected:
        raise ValueError("Prefix selection no longer matches the recorded first call")
    second = selected["slots"]["second_read"]
    if original["status"] != "ORIGINAL_COMPLETED" or second is None:
        return {**report, "reason": "first_call_not_closed_with_two_new_source_reads"}
    closed = read_json(closed_capture / "closed.json")
    host = read_json(closed_capture / "host.json")
    after = closed_capture / closed["snapshot"]
    result = read_json(after / closed["result_path"])
    if (
        closed["bank"] != original["bank"]
        or closed["public_message"] != original["public_message"]
        or closed["source_version"] != original["source_version"]
        or host["source_root"] != str(Path(original["source_root"]).resolve())
    ):
        raise ValueError("Closed Host state belongs to a different primary public invocation")
    if (
        closed["message_status"] != "COMPLETED"
        or closed["final_context_status"] != "BOUND_TO_COMPLETED_FINAL_GENERATION"
    ):
        return {**report, "reason": "no_bound_completed_final_host_input"}
    boundary = closed.get("pre_final_snapshot")
    if boundary is None or boundary["status"] != "CAPTURED_BEFORE_FINAL_RESPONSE_PERSISTENCE":
        return {**report, "reason": "no_actual_pre_final_response_bank_snapshot"}
    if boundary["output_message_id"] != closed["final_context"]["output_message_id"]:
        raise ValueError("Pre-final bank snapshot belongs to a different provider response")
    source_snapshot = closed_capture / boundary["snapshot"]
    settings = read_json(after / "input-freeze.json")["config"]
    if not 0 < low < high <= settings["ordinary_material_tokens"]:
        raise ValueError("Fresh return limits must be positive, ordered and within the native cap")
    if message_id == original["public_message"]["message_id"]:
        raise ValueError("The paired request must have a fresh public message identity")
    bank = after / Path(host["source_bank_root"]).relative_to(host["source_root"])
    public = original["public_message"]
    for path in bank.glob("*-input.json"):
        previous = read_json(path)
        if (previous["owner"], previous["session"], previous["message_id"]) == (
            public["owner"],
            public["session"],
            message_id,
        ):
            raise ValueError("The fresh message identity already has a retained invocation")
    inventory = read_json(closed_capture / boundary["inventory"])["memory_store_values"]
    if (result["status"] != "COMPLETED" or result["messages"][-1]["type"] != "ai"
            or result["messages"][-1]["id"] != boundary["output_message_id"]
            or result["messages"][-1].get("tool_calls") or "failure_delivery" in result):
        raise ValueError("Pre-final snapshot is not bound to this completed final generation")
    final_source = result.get("final_capture", {}).get("source_ref")
    if final_source is not None and any(
            row["namespace"][-1] == "v13_1_sources" and row["key"] == final_source
            for row in inventory):
        raise ValueError("Pre-final snapshot already contains the original generated final Source")
    (public_source,) = [
        x
        for x in inventory
        if x["key"] == closed["public_source_ref"] and x["namespace"][-1] == "v13_1_sources"
    ]
    namespace = public_source["namespace"][:-1]
    sources = {
        x["key"]: x["value"] for x in inventory if x["namespace"] == [*namespace, "v13_1_sources"]
    }
    snapshots = {
        x["key"]: x["value"]
        for x in inventory
        if x["namespace"] == [*namespace, "v13_5_functional"]
    }
    visible_items = []
    for message in closed["final_context"]["messages"]:
        if message["role"] == "tool" and message.get("name") == "milai_retrieve":
            packet = json.loads(message["content"])
            if packet["schema"] == "milai_retrieval_result_v1":
                visible_items.extend(packet["evidence"])
    refs, evidence = [], []
    coverage: dict[tuple[str, int], list[list[int]]] = defaultdict(list)
    for item in original["original_result"]["evidence"]:
        if item["kind"] != "original_source" or item not in visible_items:
            continue
        ref = item["ref"]
        saved = snapshots[ref["snapshot_id"]]
        if (
            saved["schema"] != "milai_retrieval_snapshot_v1"
            or saved["status"] != "completed"
            or ref["collection"] != "materials"
            or ref["item_index"] not in saved["delivered_indices"]
        ):
            raise ValueError("Visible original material is not in its completed delivery snapshot")
        material = saved["materials"][ref["item_index"]]
        if material["kind"] != "original_source":
            raise ValueError("Visible original material changed kind in its stored snapshot")
        turns = json.loads(material["text"])
        if not turns:
            continue
        ranges = [
            {
                "source_ref": t["source_ref"],
                "source_revision": t.get("source_revision", 1),
                "start": t["range"][0],
                "end": t["range"][1],
            }
            for t in turns
        ]
        if ranges != material["source_ranges"]:
            raise ValueError("Known raw material ranges differ from its actual delivered text")
        witnesses = [
            {
                "identity": [
                    sources[t["source_ref"]][k] for k in ("session", "capture_key", "role")
                ],
                "content": body_text(sources[t["source_ref"]]),
                "range": t["range"],
            }
            for t in turns
        ]
        proof = audit_visible_witnesses(
            closed["bank"], closed["public_message"], inventory, closed["public_source_ref"],
            [{**m, "type": m["role"]} for m in closed["final_context"]["messages"]],
            {"bank": closed["bank"], "request_id": public["message_id"], "witnesses": witnesses},
        )
        if not proof["all_declared_raw_slices_visible"]:
            continue
        if ref not in refs:
            refs.append(copy.deepcopy(ref))
            evidence.append({"reference": copy.deepcopy(ref), "witnesses": proof["witnesses"]})
        for turn in turns:
            coverage[turn["source_ref"], turn.get("source_revision", 1)].append(turn["range"])
    required = [
        span
        for acquisition in second["acquisition_steps"]
        for span in acquisition["new_source_intervals"]
    ]
    covered = [
        covers(coverage[span["source_ref"], span["source_revision"]], [span["start"], span["end"]])
        for span in required
    ]
    report.update(
        source_call=str(source_call),
        required_acquired_ranges=required,
        acquired_range_covered=covered,
        known_raw_materials=evidence,
    )
    if not refs or not all(covered):
        return {**report, "reason": "two_read_acquisition_not_fully_visible_as_raw_material"}
    request = copy.deepcopy(original["request"])
    request.setdefault("task_context", {})["known_evidence_refs"] = refs
    request.setdefault("limits", {})
    conditions = []
    for name, budget in [("baseline", high), ("limited", low)]:
        variant = copy.deepcopy(request)
        variant["limits"]["max_return_tokens"] = budget
        conditions.append(
            {"arm": name, "request": RetrievalRequest.model_validate(variant).project()}
        )
    return {
        **report,
        "status": "FRESH_RAW_KNOWN_BUDGET_REQUESTS_PREPARED_NOT_EXECUTED",
        "source_version": closed["source_version"],
        "source_snapshot": str(source_snapshot.resolve()),
        "source_snapshot_boundary": "ACTUAL_INPUT_DELIVERED_BEFORE_ORIGINAL_FINAL_SOURCE_CAPTURE",
        "source_snapshot_output_message_id": boundary["output_message_id"],
        "original_final_source_ref_absent_from_starting_bank": final_source,
        "source_bank_relative": str(bank.relative_to(after)),
        "source_public_source_ref": closed["public_source_ref"],
        "source_store_values": inventory,
        "original_ledger": settings["budget_path"],
        "public_message": {
            "bank": closed["bank"],
            "owner": public["owner"],
            "session": public["session"],
            "message_id": message_id,
            "content": public["content"],
            "workflow": public["workflow"],
            "incoming_sources": [],
        },
        "conditions": conditions,
        "original_request_retained": original["request"],
        "complete_Host_knowledge_claim": False,
        "state_accounting": "Two fresh initial states if executed; do not append both to the "
        "existing three selected slots. Training-slot allocation and actual readouts remain "
        "separate prerequisites. Original READ2 remains provenance, never silently relabelled.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path)
    parser.add_argument("closed_capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--family", required=True)
    parser.add_argument("--collector", default="rules")
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--low", type=int, default=1024)
    parser.add_argument("--high", type=int, default=2048)
    args = parser.parse_args()
    (record,) = [
        r
        for r in read_json(args.selection)["records"]
        if r["family"] == args.family and r["collector"] == args.collector
    ]
    started = time.process_time()
    report = prepare_pair(
        args.closed_capture, record, message_id=args.message_id, low=args.low, high=args.high
    )
    report.update(
        cpu_seconds_pending=time.process_time() - started,
        ledger_recorded=False,
        model_calls=0,
        no_sha_validation=True,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "preparation.json", report)
    print(report["status"], args.family)


if __name__ == "__main__":
    main()

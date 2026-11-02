"""Audit declared Source slices in the actual visible pre-Host tool receipts.

This is evaluator-side evidence coverage, not a semantic oracle or a model input.
Store presence, source bindings and a prior assistant answer do not establish delivery.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.functional_state import body_text
from milai_lab.methods.evidence_reading import project_pack
from milai_lab.methods.intent_retrieval import retrieval_packet


def covers(intervals: list[list[int]], requested: list[int]) -> bool:
    end = requested[0]
    for left, right in sorted(intervals):
        if left > end:
            break
        end = max(end, right)
    return end >= requested[1]


def audit_witnesses(capture: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    if (capture["schema"] != "frozen_host_message_v1"
            or capture["status"] != "CAPTURED_PRE_HOST"
            or capture["initial_baseline_context"] is None):
        raise ValueError("Witness audit requires the actual pre-Host visible context")
    return audit_visible_witnesses(capture["bank"], capture["public_message"],
        capture["ready_state"]["memory_store_values"], capture["ready_state"]["public_source_ref"],
        capture["initial_baseline_context"], case)


def audit_visible_witnesses(
    bank_name: str, public: dict[str, Any], rows: list[dict[str, Any]], public_source_ref: str,
    messages: list[dict[str, Any]], case: dict[str, Any],
) -> dict[str, Any]:
    """Bind explicit visible Tool bodies to this snapshot's actual material and Source records."""
    if bank_name != case["bank"] or public["message_id"] != case["request_id"]:
        raise ValueError("Witness definition does not name this actual request")
    public_row, = [row for row in rows
                   if row["namespace"][-1] == "v13_1_sources"
                   and row["key"] == public_source_ref]
    bank = public_row["namespace"][:-1]
    if public_row["value"]["owner"] != public["owner"]:
        raise ValueError("Captured public Source owner changed")
    sources = {row["key"]: row["value"] for row in rows
               if row["namespace"] == [*bank, "v13_1_sources"]}
    state = {row["key"]: row["value"] for row in rows
             if row["namespace"] == [*bank, "v13_5_functional"]}
    hidden = set(state["visibility"]["sources"]) if "visibility" in state else set()
    delivered: dict[tuple[str, int], list[dict[str, Any]]] = {}
    views, issues = [], []
    for message_index, message in enumerate(messages):
        if message["type"] != "tool" or message.get("name") != "milai_retrieve":
            continue
        try:
            packet = json.loads(message["content"])
        except json.JSONDecodeError:
            issues.append({"message_index": message_index, "reason": "unstructured_tool_receipt"})
            continue
        if not isinstance(packet, dict) or packet.get("schema") != "milai_retrieval_result_v1":
            continue
        reconstructed: dict[str, tuple[dict[str, Any], dict[str, tuple[str, int]]]] = {}
        for item in packet["evidence"]:
            reference = item["ref"]
            key, position = reference["snapshot_id"], reference["item_index"]
            saved = state.get(key)
            if (reference["collection"] != "materials" or saved is None
                    or saved.get("schema") != "milai_retrieval_snapshot_v1"
                    or saved["status"] != "completed"
                    or position not in saved["delivered_indices"]):
                issues.append({"message_index": message_index, "reference": reference,
                               "reason": "reference_not_in_actual_delivered_snapshot"})
                continue
            if key not in reconstructed:
                positions = saved["delivered_indices"]
                materials = [saved["materials"][p] for p in positions]
                indices = [saved["indices"][p] for p in positions]
                expected = retrieval_packet(key, materials, indices, positions, saved["reason"],
                    saved["usage"],
                    ok=saved.get("ok", saved["reason"] != "operation_outcome_unknown"))
                aliases: dict[tuple[str, int], str] = {}
                for material, index in zip(materials, indices, strict=True):
                    if "evidence" not in project_pack(material, index):
                        continue
                    turns = (json.loads(material["text"]) if material["kind"] == "original_source"
                             else material.get("support_turns", []))
                    for turn in turns:
                        identity = (turn["source_ref"], turn.get("source_revision", 1))
                        aliases.setdefault(identity, f"s{len(aliases)}")
                reconstructed[key] = expected, {
                    alias: identity for identity, alias in aliases.items()}
            expected, aliases_by_name = reconstructed[key]
            matched = next((value for value in expected["evidence"]
                            if value["ref"] == reference and value["kind"] == item["kind"]), None)
            if matched is None:
                issues.append({"message_index": message_index, "reference": reference,
                               "reason": "returned_item_binding_changed"})
                continue
            if item["kind"] != "original_source":
                views.append({"message_index": message_index, "reference": reference,
                              "kind": item["kind"], "status": "SEMANTIC_REVIEW_REQUIRED"})
            if (item.get("body_delivered") is False
                    or item.get("visibility", "visible") != "visible"):
                continue
            for body in item.get("evidence", []):
                if body not in matched.get("evidence", []):
                    issues.append({"message_index": message_index, "reference": reference,
                                   "reason": "visible_body_differs_from_recorded_delivery"})
                    continue
                identity = aliases_by_name[body["source"]]
                ref, revision = identity
                event = sources[ref]
                left, right = body["range"]
                if (ref in hidden or event.get("source_revision", 1) != revision
                        or event["owner"] != public["owner"] or body["role"] != event["role"]
                        or body.get("reported_at") != event.get(
                            "occurred_at", event.get("timestamp"))
                        or body.get("captured_at") != event.get("observed_at")
                        or any(body.get(k) != event.get(k)
                               for k in ("origin", "capture_context", "calendar_context"))
                        or not 0 <= left <= right <= len(body_text(event))
                        or body["content"] != body_text(event)[left:right]):
                    issues.append({"message_index": message_index, "reference": reference,
                        "source_ref": ref, "reason": "source_slice_not_currently_verified"})
                    continue
                delivered.setdefault(identity, []).append({"range": [left, right],
                    "message_index": message_index, "material_reference": reference})
    witnesses = []
    for witness in case["witnesses"]:
        matches = [event for event in sources.values() if [
            event["session"], event["capture_key"], event["role"]] == witness["identity"]]
        if len(matches) > 1:
            raise ValueError("Source witness identity is ambiguous")
        record: dict[str, Any] = {"identity": witness["identity"],
            "source_present": bool(matches), "raw_slice_visible": False, "deliveries": []}
        if matches:
            event, = matches
            if body_text(event) != witness["content"]:
                raise ValueError("Source witness content differs from its declared before")
            span = witness.get("range", [0, len(witness["content"])])
            if not 0 <= span[0] < span[1] <= len(witness["content"]):
                raise ValueError("Declared witness range is not inside its literal source")
            deliveries = delivered.get((event["event_id"], event.get("source_revision", 1)), [])
            record.update(source_ref=event["event_id"], requested_range=span,
                raw_slice_visible=covers([d["range"] for d in deliveries], span),
                deliveries=deliveries)
        witnesses.append(record)
    if not witnesses:
        raise ValueError("Declare nonempty source witnesses before condition review")
    complete = all(row["raw_slice_visible"] for row in witnesses)
    return {"status": "DECLARED_RAW_WITNESSES_VISIBLE" if complete else "WITNESS_REVIEW_REQUIRED",
        "bank": bank_name, "request_id": public["message_id"], "witnesses": witnesses,
        "all_declared_raw_slices_visible": complete, "other_materials_requiring_review": views,
        "receipt_issues": issues, "target_answer_or_original_outcome_read": False,
        "Store_presence_counted_as_knowledge": False,
        "scope": "Literal declared Source-slice coverage in actual visible tool bodies. "
                 "No new read, inferred fact, success grade or action label. Incomplete raw "
                 "coverage may still be sufficient through a reviewed View or smaller witness; "
                 "absence of this certificate is not evidence of task failure."}


def audit_closed_witnesses(closed: dict[str, Any], result: dict[str, Any],
                           case: dict[str, Any]) -> dict[str, Any]:
    """Use the completed final provider input and the post-message snapshot, never a later bank."""
    if (closed["schema"] != "closed_host_message_v1"
            or closed["status"] != "CLOSED_INVOCATION_SNAPSHOTTED"
            or result["status"] != closed["message_status"]
            or result["bank"] != closed["bank"]
            or any(result[k] != v for k, v in closed["public_message"].items())
            or case["bank"] != closed["bank"]
            or case["request_id"] != closed["public_message"]["message_id"]):
        raise ValueError("Closed witness audit requires the same actual invocation and case")
    if (closed["message_status"] != "COMPLETED"
            or closed["final_context_status"] != "BOUND_TO_COMPLETED_FINAL_GENERATION"):
        return {"status": "NO_COMPLETED_FINAL_CONTEXT", "bank": closed["bank"],
            "request_id": case["request_id"], "all_declared_raw_slices_visible": None,
            "witnesses": None, "scope": "Missing final context is unknown coverage, not failure "
                "or an action label. The original failed/ambiguous invocation remains recorded."}
    context = closed["final_context"]
    final = result["messages"][-1]
    if (context["schema"] != "provider_request_content_v1" or final["type"] != "ai"
            or final.get("tool_calls") or context["output_message_id"] != final["id"]
            or "failure_delivery" in result):
        raise ValueError("Final provider input is not bound to this completed model response")
    # Native and JSON-action transports retain role/name/content for Tool messages.
    messages = [{**m, "type": m["role"]} for m in context["messages"]]
    report = audit_visible_witnesses(closed["bank"], closed["public_message"],
        closed["memory_store_values"], closed["public_source_ref"], messages, case)
    report.pop("target_answer_or_original_outcome_read")
    report.update(context_scope="actual_completed_final_provider_request",
        execution_closure_checked=True, answer_text_used_for_judgment=False,
        provider_reasoning_used=False, final_message_id=final["id"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("witness_specification", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--case", required=True)
    parser.add_argument("--closed", action="store_true",
                        help="Audit the bound final provider input and closed after snapshot")
    args = parser.parse_args()
    started = time.process_time()
    case, = [case for case in read_json(args.witness_specification)["cases"]
             if case["case_id"] == args.case]
    if args.closed:
        closed = read_json(args.capture / "closed.json")
        result = audit_closed_witnesses(closed,
            read_json(args.capture / closed["snapshot"] / closed["result_path"]), case)
    else:
        result = audit_witnesses(read_json(args.capture / "host.json"), case)
    result.update(cpu_seconds_pending=time.process_time() - started, ledger_recorded=False,
                  model_calls=0)
    if args.output.exists():
        raise ValueError("Keep the prior witness audit; use a new output for a revised review")
    write_json(args.output, result)
    print(result["status"], args.case)


if __name__ == "__main__":
    main()

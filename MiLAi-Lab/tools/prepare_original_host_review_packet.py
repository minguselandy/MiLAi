"""Bind a closed original Host arm to source dialogue cuts and actual final inputs."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json
from summarize_original_feedback_host import final_provider_input


def source_texts(node: Any) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        if isinstance(node.get("content"), str) and "role" in node:
            yield node["role"], node["content"]
        for value in node.values():
            yield from source_texts(value)
    elif isinstance(node, list):
        for value in node:
            yield from source_texts(value)


def prepare(
    dispatch: dict[str, Any], summary: dict[str, Any], rubrics: dict[str, Any], arm_id: str,
) -> dict[str, Any]:
    arm, = [a for a in summary["arms"] if a["arm_id"] == arm_id]
    if arm["status"] in {"RUNNING", "NOT_EXECUTED"}:
        raise ValueError("Review packets require a closed actual arm")
    if summary["planned_positions"] != dispatch["planned_positions"]:
        raise ValueError("Keep the complete original Host cohort denominator")
    fixture = read_json(Path(dispatch["study"]["histories"]))
    criteria = {(r["history"], r["request"]): r for r in rubrics["cases"]}
    selected = [r for r in summary["positions"] if r["arm_id"] == arm_id]
    positions = {(r["history"], r["request"]): r for r in selected}
    if len(positions) != len(selected) or len(selected) != dispatch["study"]["positions_per_arm"]:
        raise ValueError("Keep every declared position exactly once")
    packets = []
    for history in fixture["histories"]:
        available = list(history["sources"])
        for request in history["requests"]:
            available.extend(request.get("incoming_sources", []))
            criterion = criteria[history["id"], request["id"]]
            cut = tuple(criterion["through"])
            sample = read_json(Path(criterion["source_file"]))
            expected, cut_found = [], False
            for segment in sorted(sample["conversations"], key=lambda s: s["segment_index"]):
                number = segment["segment_index"]
                for i, turn in enumerate(segment["dialogue"], 1):
                    if (number, i) == cut:
                        cut_found = turn["role"] == "user"
                    if (number, i) <= cut:
                        expected.append({"session_id": f"source-session-{number}",
                            "event_key": f"s{number}t{i}", "role": turn["role"],
                            "content": turn["content"], "occurred_at": None})
            identities = [[s["session_id"], s["event_key"], s["role"]] for s in available]
            if (not cut_found or available != expected
                    or identities != criterion["available_source_identities"]
                    or request["content"] != criterion["query"]):
                raise ValueError(
                    "Declared public query/source prefix differs from reviewed dialogue"
                )
            position = positions[history["id"], request["id"]]
            path = Path(position["result_path"]) if position["result_path"] else None
            boundary, messages = position["final_host_input"], None
            if path is not None:
                result = read_json(path)
                if (result["status"] != position["result_status"]
                        or result.get("final_answer") != position["answer"]):
                    raise ValueError("Actual result changed after the mechanical summary")
                boundary, messages = final_provider_input(path, result)
                if boundary != position["final_host_input"]:
                    raise ValueError("Actual final-input binding changed")
            receipts = ([m for m in messages if m["role"] == "tool"
                         and m.get("name") == "milai_retrieve"] if messages is not None else None)
            raw = [value for receipt in receipts or []
                   for value in source_texts(json.loads(receipt["content"]))]
            refs = {tuple(ref) for group in criterion["support_sets"] for ref in group}
            witnesses = []
            for source in available:
                identity = source["session_id"], source["event_key"], source["role"]
                if identity in refs:
                    witnesses.append({"identity": list(identity), "content": source["content"],
                        "whole_body_role_visible_in_receipts": any(
                            role == source["role"] and source["content"] in content
                            for role, content in raw) if receipts is not None else None})
            coverage = {tuple(w["identity"]): w["whole_body_role_visible_in_receipts"]
                        for w in witnesses}
            packets.append({"arm_id": arm_id, "history": history["id"],
                "request": request["id"], "query": request["content"],
                "result_path": str(path) if path else None, "execution": position["execution"],
                "status": position["result_status"], "answer": position["answer"],
                "current_tool_attempts": position["tool_attempts"], "source_criterion": criterion,
                "full_declared_prefix_literal_equal_to_source_dialogue_cut": True,
                "oracle_annotations_used": False, "witnesses": witnesses,
                "whole_support_set_visible": any(all(coverage[tuple(ref)] for ref in group)
                    for group in criterion["support_sets"]) if receipts is not None else None,
                "final_host_input": boundary, "visible_tool_receipts": receipts,
                "visible_prefetch_receipts": position["visible_prefetch_receipts"],
                "actual_final_provider_messages": messages})
    return {"status": "CLOSED_ORIGINAL_HOST_ARM_SOURCE_AND_FINAL_INPUT_PACKETS_BOUND",
        "arm_id": arm_id, "positions": packets, "planned_arm_positions": len(packets),
        "full_cohort_positions": dispatch["planned_positions"], "model_calls": 0,
        "ledger_recorded": False, "no_sha_validation": True,
        "scope": "Only source conversations through declared cuts are used; oracle annotations "
            "are excluded. Final inputs bind by actual response ID. Whole-body flags establish "
            "text/role visibility, not automatic semantic sufficiency or necessity. Missing and "
            "unexecuted results stay unknown; planned prefixes are not actual model exposure. "
            "This packet supplies no answer or delivery grades."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispatch", type=Path)
    parser.add_argument("summary", type=Path)
    parser.add_argument("rubrics", type=Path)
    parser.add_argument("arm_id")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    report = prepare(read_json(args.dispatch), read_json(args.summary),
                     read_json(args.rubrics), args.arm_id)
    report["cpu_seconds_nested"] = time.process_time() - started
    with args.output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(report["status"], args.arm_id, report["planned_arm_positions"])


if __name__ == "__main__":
    main()

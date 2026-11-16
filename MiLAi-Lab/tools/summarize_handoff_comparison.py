"""Verify actual F1 delivery pairs and conditional Host readouts, without outcome labels."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl
from milai_lab.runners.frozen_host_readout import readout_answer, substitute_receipt


def completed_tool(
    case: Path,
    capture: Path,
    policy: dict[str, Any],
    version: str,
) -> dict[str, Any]:
    replay = read_json(case / "replay.json")
    call = read_json(capture / "call.json")
    result = replay["result"]
    if (
        Path(replay["captured_call"]).resolve() != capture.resolve()
        or replay["source_version"] != version
        or replay["policy"] != policy
        or policy["routing"] != "handoff_only"
        or replay["status"] != "COMPLETED"
        or result["status"] != "COMPLETED"
        or replay["prefix_operations_reexecuted"] != 0
        or not result["frozen_initial_observation_and_actions_equal"]
        or not result["frozen_request_and_allowance_equal"]
    ):
        raise ValueError("Completed F1 tool differs from its declared restored condition")
    relative = Path(call["host_prefix_trace"])
    if not relative.name.endswith(f"-trace-{result['attempt']}.jsonl"):
        raise ValueError("F1 replay trace attempt differs from the captured invocation")
    prefix = (capture / "before" / relative).read_bytes()
    trace = case / "runtime" / relative
    with trace.open("rb") as stream:
        if stream.read(len(prefix)) != prefix:
            raise ValueError("F1 current trace no longer starts with its captured prefix")
        # Iterate physical JSONL lines; Unicode line separators inside content are data.
        events: list[dict[str, Any]] = [json.loads(line) for line in stream if line.strip()]
    inputs = [i for i, event in enumerate(events)
              if event.get("event") == "handoff_comparison_input"]
    if len(inputs) != 1:
        raise ValueError("One actual F1 policy input is required")
    index, = inputs
    actual = events[index]
    actions = [a for a in call["initial_actions"] if a["kind"] == "HANDOFF"]
    if actual["state"] != call["initial_observation"] or actual["actions"] != actions:
        raise ValueError("F1 state or ordered HANDOFF menu changed")
    tail = events[index + 1 :]
    selections = [e for e in tail if e.get("event") == "handoff_comparison_selection"]
    decisions = [
        e
        for e in events
        if e.get("event") == "memory_control_step" and e.get("phase") == "decision_output"
    ]
    if len(selections) != 1 or len(decisions) != 1:
        raise ValueError("F1 must execute exactly one delivery decision")
    selected = selections[0]["selected"]
    (action,) = [a for a in actions if a["id"] == selected]
    (executed,) = [a for a in decisions[0]["actions"] if a["id"] == decisions[0]["selected"]]
    if (executed != action or executed["kind"] != "HANDOFF"
            or decisions[0]["retrieval_call_id"] != call["call_id"]):
        raise ValueError("F1 executed a different action or an acquisition")
    (receipt,) = [
        m
        for m in result["messages"]
        if m.get("type") == "tool" and m.get("tool_call_id") == call["call_id"]
    ]
    packet = json.loads(receipt["content"])
    if packet != result["retrieval_result"]:
        raise ValueError("Actual tool receipt differs from the saved delivery")
    return {
        "trace": str(trace),
        "preserved_prefix_bytes": len(prefix),
        "current_request_trace_suffix_only": True,
        "action": action,
        "receipt": receipt,
        "packet": packet,
        "selection_mode": selections[0]["selection_mode"],
        "prefix_operations_reexecuted": 0,
        "new_decisions": 1,
        "actual_state_and_ordered_menu_equal": True,
    }


def conditional_readout(
    case: Path,
    capture: Path,
    frame: dict[str, Any],
    tool: dict[str, Any],
    version: str,
) -> dict[str, Any]:
    root = case / "host-readout"
    report = read_json(root / "readout.json")
    if (
        Path(report["captured_call"]).resolve() != capture.resolve()
        or report["source_version"] != version
        or read_json(root / "frame.json") != frame
    ):
        raise ValueError("F1 readout changed its original frame or capture")
    wire = None
    if (root / "request.json").exists():
        wire = read_json(root / "request.json")
        if wire != substitute_receipt(frame, tool["receipt"]):
            raise ValueError("F1 readout changed more than target receipt and final-only schema")
    answer = None
    if report["status"] == "COMPLETED":
        response = read_json(root / "response.json")
        responses = [
            e for e in read_jsonl(root / "trace.jsonl") if e.get("event") == "vllm_response"
        ]
        if (
            wire is None
            or len(responses) != 1
            or responses[0]["request"] != wire
            or json.loads(responses[0]["response_text"]) != response
            or report["actual_http_attempts"] != 1
        ):
            raise ValueError("Completed F1 answer lacks its actual provider request/response")
        answer = readout_answer(response, frame["tool_mode"], wire)
        if answer != report["answer"]:
            raise ValueError("Saved F1 answer differs from the actual provider response")
    elif report.get("answer") is not None:
        raise ValueError("Incomplete F1 readout cannot supply a completed answer")
    return {
        "status": report["status"],
        "answer": answer,
        "request": wire,
        "actual_http_attempts": report["actual_http_attempts"],
        "result_path": str(root / "readout.json"),
        "error": report.get("error", report.get("reason")),
        "actual_completed_provider_input_bound": report["status"] == "COMPLETED",
    }


def summarize(dispatch: dict[str, Any]) -> dict[str, Any]:
    root = Path(dispatch["output"])
    driver = read_json(root / "driver.json")
    proc = Path("/proc", str(driver["pid"]), "cmdline")
    if proc.exists() and str(root).encode() in proc.read_bytes().split(b"\0"):
        raise ValueError("Wait for the actual F1 worker to close")
    if driver["status"] == "RUNNING":
        raise ValueError("Unclosed F1 worker requires an interruption audit")
    policies = read_json(Path(dispatch["argv"][dispatch["argv"].index(str(root)) - 1]))
    cohort = read_json(root / "cohort.json")
    if (
        cohort["policies"] != policies
        or driver["source_version"] != dispatch["source_version"]
        or not driver["host_readout"]
        or driver["automatic_retry"]
    ):
        raise ValueError("F1 native recipe or readout protocol changed")
    call_indices = {str(Path(c["capture"]).resolve()): i for i, c in enumerate(cohort["calls"])}
    pairs = dispatch["pairs"]
    if (
        len(call_indices) != len(cohort["calls"])
        or set(call_indices) != {str(Path(p["capture"]).resolve()) for p in pairs}
        or set(cohort["selected_capture_indices"]) != set(call_indices.values())
    ):
        raise ValueError("F1 capture denominator changed")
    by_name = {p["name"]: (i, p) for i, p in enumerate(policies)}
    if len(by_name) != len(policies) or set(by_name) != {a for p in pairs for a in p["arm_names"]}:
        raise ValueError("F1 declared branch denominator changed")
    positions, comparisons = [], []
    for pair in pairs:
        capture = Path(pair["capture"])
        index = call_indices[str(capture.resolve())]
        frame = read_json(Path(pair["readout_frame"]))
        native_frame = root / "readout-frames" / f"{index:05d}.json"
        if native_frame.exists() and read_json(native_frame) != frame:
            raise ValueError("Native F1 frame differs from its pre-execution binding")
        members = []
        for name in pair["arm_names"]:
            arm_index, recipe = by_name[name]
            if recipe["capture"] != capture.name:
                raise ValueError("F1 recipe points to another capture")
            case = root / f"arm-{arm_index:02d}" / f"call-{index:05d}"
            row: dict[str, Any] = {
                "family": pair["family"],
                "condition": pair["condition"],
                "arm_name": name,
                "policy": recipe["policy"]["policy"],
                "case": str(case),
                "execution": "NOT_EXECUTED",
                "tool_status": None,
                "tool": None,
                "readout": None,
                "semantic_grade": "unknown",
                "delivery_grade": "unknown",
            }
            if (case / "replay.json").exists():
                replay = read_json(case / "replay.json")
                row.update(execution="RESULT_RETAINED", tool_status=replay["status"])
                if replay["status"] == "COMPLETED":
                    if not native_frame.exists():
                        raise ValueError("Completed F1 branch has no native frame binding")
                    row["tool"] = completed_tool(
                        case, capture, recipe["policy"], dispatch["source_version"]
                    )
                    if (case / "host-readout/readout.json").exists():
                        row["readout"] = conditional_readout(
                            case, capture, frame, row["tool"], dispatch["source_version"]
                        )
            elif case.exists() or driver.get("active", {}).get("path") == str(case):
                row["execution"] = "ENTERED_WITHOUT_CLOSED_RESULT"
            positions.append(row)
            members.append(row)
        left, right = members
        both_tools = all(m["tool"] is not None for m in members)
        both_requests = all(
            m["readout"] is not None and m["readout"]["request"] is not None for m in members
        )
        comparisons.append(
            {
                "family": pair["family"],
                "condition": pair["condition"],
                "arm_names": pair["arm_names"],
                "matched_completed_tools": both_tools,
                "actual_packets_equal": left["tool"]["packet"] == right["tool"]["packet"]
                if both_tools
                else None,
                "actual_readout_requests_equal": left["readout"]["request"]
                == right["readout"]["request"]
                if both_requests
                else None,
                "quality_comparison": "unreviewed",
            }
        )
    if len(positions) != dispatch["planned_branches"] or driver["planned_positions"] != len(
        positions
    ):
        raise ValueError("F1 planned branch count changed")
    return {
        "status": "F1_ACTUAL_BRANCH_CONTRACTS_RECONCILED_SEMANTIC_REVIEW_PENDING",
        "native_status": driver["status"],
        "planned_positions": len(positions),
        "families": len({p["family"] for p in pairs}),
        "conditions": len(pairs),
        "execution_counts": dict(Counter(r["execution"] for r in positions)),
        "positions": positions,
        "comparisons": comparisons,
        "model_calls": 0,
        "no_sha_validation": True,
        "scope": "Actual F1 state, menu, action, packet and conditional provider input are bound. "
        "Prefix reads are historical; no new acquisition is accepted for completed pairs. "
        "All planned positions remain, including failures and unexecuted branches. "
        "Answer text is not a semantic grade. Equal delivered packets/requests identify "
        "conditions where answer variation alone cannot establish policy benefit. "
        "Fixed sibling receipts remain; not autonomous stopping or full task success.",
        "cost_scope": "This reader does not settle or sum nested replay/readout/driver CPU. "
        "Actual native ledger boundaries and whole-child accounting remain separate.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispatch", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    report = summarize(read_json(args.dispatch))
    report.update(cpu_seconds_pending=time.process_time() - started, ledger_recorded=False)
    with args.output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(report["status"], report["planned_positions"])


if __name__ == "__main__":
    main()

"""Bind the prospective raw-current tie arm to its fixed states and original controls."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from current_raw_packet_tie import PROFILE
from milai_lab.harness.artifact_io import read_json, read_jsonl
from milai_lab.runners.frozen_host_readout import substitute_receipt
from summarize_handoff_comparison import completed_tool, conditional_readout


def bind_failed_response(case: Path, readout: dict[str, Any]) -> None:
    """Keep an incomplete provider response as evidence, never as a completed answer."""
    root = case / "host-readout"
    response_path = root / "response.json"
    trace_path = root / "trace.jsonl"
    responses = ([e for e in read_jsonl(trace_path) if e.get("event") == "vllm_response"]
                 if trace_path.exists() else [])
    if response_path.exists() or responses:
        if (not response_path.exists() or len(responses) != 1
                or responses[0]["request"] != readout["request"]
                or json.loads(responses[0]["response_text"]) != read_json(response_path)
                or readout["actual_http_attempts"] != 1):
            raise ValueError("Incomplete response is not bound to its actual request/trace")
        readout["incomplete_provider_response_bound"] = True
    else:
        readout["incomplete_provider_response_bound"] = False


def summarize(dispatch: dict[str, Any]) -> dict[str, Any]:
    root = Path(dispatch["output"])
    pairs = dispatch["pairs"]
    version = dispatch["base_runtime_source_version"]
    driver = read_json(root / "driver.json")
    wrapper = read_json(Path(dispatch["wrapper_receipt"]))
    proc = Path("/proc", str(driver["pid"]), "cmdline")
    if ((proc.exists() and str(root).encode() in proc.read_bytes().split(b"\0"))
            or driver["status"] == "RUNNING" or wrapper["status"] == "RUNNING"):
        raise ValueError("Wait for the actual third-arm worker to close")
    policies = read_json(Path(wrapper["recipes"]))
    cohort = read_json(root / "cohort.json")
    if (dispatch["method_profile"] != PROFILE or wrapper["profile"] != PROFILE
            or not wrapper["selector_restored"] or wrapper["intervention_used"]
            or wrapper["automatic_retry"] or driver["automatic_retry"]
            or not driver["host_readout"] or driver["source_version"] != version
            or wrapper["argv"] != dispatch["argv"][4:]
            or cohort["policies"] != policies):
        raise ValueError("Third-arm policy wrapper or native recipe changed")
    captures = {str(Path(c["capture"]).resolve()): i for i, c in enumerate(cohort["calls"])}
    by_name = {p["name"]: (i, p) for i, p in enumerate(policies)}
    if (len(captures) != len(cohort["calls"])
            or set(captures) != {str(Path(p["capture"]).resolve()) for p in pairs}
            or set(cohort["selected_capture_indices"]) != set(captures.values())
            or len(by_name) != len(policies)
            or set(by_name) != {p["arm_name"] for p in pairs}
            or len(pairs) != dispatch["states"]
            or len(pairs) != dispatch["planned_branches"]
            or len(pairs) != driver["planned_positions"]
            or len({p["family"] for p in pairs}) != dispatch["families"]
            or sum(p["changed_choice"] for p in pairs) != dispatch["predeclared_changed_choices"]):
        raise ValueError("Third-arm state or branch denominator changed")
    positions: list[dict[str, Any]] = []
    matched_calls: list[int] = []
    for pair in pairs:
        capture = Path(pair["capture"])
        index = captures[str(capture.resolve())]
        arm, recipe = by_name[pair["arm_name"]]
        if (recipe["capture"] != capture.name or recipe["policy"]["policy"] != "rules"
                or recipe["policy"]["routing"] != "handoff_only" or "intervention" in recipe):
            raise ValueError("Third arm requires ordinary rules/HANDOFF for its declared capture")
        call = read_json(capture / "call.json")
        actions = [a for a in call["initial_actions"] if a["kind"] == "HANDOFF"]
        matches = [i for i, recorded in enumerate(wrapper["policy_calls"])
                   if recorded["state"] == call["initial_observation"]
                   and recorded["actions"] == actions]
        if len(matches) > 1:
            raise ValueError("Repeated selector calls for one fixed state")
        if matches:
            recorded = wrapper["policy_calls"][matches[0]]
            if ({k: v for k, v in recorded.items() if k not in {"state", "actions"}}
                    != pair["selector_check"]):
                raise ValueError("Actual selector differs from its predeclared choice")
            matched_calls.extend(matches)
        case = root / f"arm-{arm:02d}" / f"call-{index:05d}"
        row: dict[str, Any] = {
            "family": pair["family"], "condition": pair["condition"],
            "arm_name": pair["arm_name"], "case": str(case),
            "execution": "NOT_EXECUTED", "tool_status": None, "tool": None,
            "readout": None, "changed_choice": pair["changed_choice"],
            "selector_call_bound": bool(matches), "actual_packets_equal_to_rule": None,
            "actual_readout_requests_equal_to_rule": None,
            "semantic_grade": "unknown", "delivery_grade": "unknown",
        }
        if (case / "replay.json").exists():
            replay = read_json(case / "replay.json")
            row.update(execution="RESULT_RETAINED", tool_status=replay["status"])
            if replay["status"] == "COMPLETED":
                frame = read_json(Path(pair["readout_frame"]))
                if read_json(root / "readout-frames" / f"{index:05d}.json") != frame:
                    raise ValueError("Third-arm Host frame changed")
                tool = completed_tool(case, capture, recipe["policy"], version)
                row["tool"] = tool
                if (tool["action"] != pair["predeclared_variant_action"]
                        or tool["selection_mode"] != "policy"
                        or tool["packet"]["termination_reason"] != "policy_handoff"
                        or (pair["changed_choice"] and not matches)):
                    raise ValueError("Third-arm executed action or termination changed")
                old_case = Path(pair["original_rule_case"])
                old_replay = read_json(old_case / "replay.json")
                old_tool = completed_tool(old_case, capture, recipe["policy"],
                                          old_replay["source_version"])
                if old_tool["action"] != pair["original_rule_action"]:
                    raise ValueError("Original rule action changed")
                old_wire = read_json(old_case / "host-readout/request.json")
                if old_wire != substitute_receipt(frame, old_tool["receipt"]):
                    raise ValueError("Third-arm frame differs from original control input")
                row["actual_packets_equal_to_rule"] = tool["packet"] == old_tool["packet"]
                if (case / "host-readout/readout.json").exists():
                    readout = conditional_readout(case, capture, frame, tool, version)
                    if readout["status"] != "COMPLETED":
                        bind_failed_response(case, readout)
                    row["readout"] = readout
                    if readout["request"] is not None:
                        row["actual_readout_requests_equal_to_rule"] = (
                            readout["request"] == old_wire
                        )
                if not pair["changed_choice"] and (
                    not row["actual_packets_equal_to_rule"]
                    or row["actual_readout_requests_equal_to_rule"] is False
                ):
                    raise ValueError("Unchanged action changed its packet or Host input")
        elif case.exists() or driver.get("active", {}).get("path") == str(case):
            row["execution"] = "ENTERED_WITHOUT_CLOSED_RESULT"
        positions.append(row)
    if sorted(matched_calls) != list(range(len(wrapper["policy_calls"]))):
        raise ValueError("Selector receipt includes an unbound or ambiguous state")
    return {
        "status": "THIRD_ARM_ACTUAL_CONTRACTS_RECONCILED_SEMANTIC_REVIEW_PENDING",
        "native_status": driver["status"], "wrapper_status": wrapper["status"],
        "planned_positions": len(positions), "families": dispatch["families"],
        "predeclared_changed_choices": dispatch["predeclared_changed_choices"],
        "execution_counts": dict(Counter(r["execution"] for r in positions)),
        "positions": positions, "model_calls": 0, "no_sha_validation": True,
        "scope": "Actual state/menu/action/receipt/provider input are bound to the frozen "
            "third-arm declaration and original rules control. Failed and unexecuted positions "
            "remain unknown. Equal-input answer variation is not a policy benefit. "
            "This audit supplies no semantic grades or default-policy adoption.",
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

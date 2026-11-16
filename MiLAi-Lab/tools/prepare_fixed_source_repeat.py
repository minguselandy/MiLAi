"""Prepare a preselected second Reader invocation from unchanged actual first inputs."""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


def prepare(prepared: Path, firsts: Path, sampling: dict) -> tuple[list[dict], list[dict], dict]:
    original = read_json(prepared / "run.json")
    first_run = read_json(firsts / "run.json")
    if (original["status"] != "COMPLETED" or original.get("actual_only") is not True
            or original.get("source_split") not in {"dev", "test"}
            or first_run["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}
            or Path(first_run["prepared"]).resolve() != prepared.resolve()):
        raise ValueError("Require closed evaluation firsts bound to actual endpoint preparation")
    all_cases, all_rows = read_json(prepared / "cases.json"), read_jsonl(prepared / "states.jsonl")
    if [c["family"] for c in all_cases] != sampling["source_order"]:
        raise ValueError("Original endpoint panel differs from the frozen source order")
    selection = sampling["second_Host_readout"]
    indices = selection["indices_zero_based"]
    if (len(indices) != selection["sources"] or len(set(indices)) != len(indices)
            or any(not 0 <= i < len(all_cases) for i in indices)
            or [all_cases[i]["family"] for i in indices] != selection["source_groups"]):
        raise ValueError("Repeated, missing or changed preselected source positions")
    paths = read_json(firsts / "readout-paths.json")
    cases, rows, provenance = [], [], []
    for index in indices:
        case = copy.deepcopy(all_cases[index])
        if len(case["branches"]) != 1:
            raise ValueError("Repeat only the one actual terminal packet")
        row = all_rows[case["state_index"]]
        if row["metadata"]["event_id"] != case["event_id"]:
            raise ValueError("Actual state pointer changed")
        branch = case["branches"][0]
        first_paths = {paths[p][case["case_key"]] for p in branch["policies"]}
        if len(first_paths) != 1:
            raise ValueError("Actual first binding has ambiguous Reader outcomes")
        first_path = Path(first_paths.pop())
        first = read_json(first_path)
        if (first["event_id"] != case["event_id"] or first["family"] != case["family"]
                or first["action"] != branch["action"]
                or read_json(Path(first["request"])) != branch["readout_request"]):
            raise ValueError("First actual request/action differs from the repeat input")
        # Remap the compiler pointer only; the original state stays unchanged.
        case["state_index"] = len(rows)
        cases.append(case)
        rows.append(copy.deepcopy(row))
        provenance.append({"original_case_index": index, "event_id": case["event_id"],
            "family": case["family"], "original_first": str(first_path.resolve()),
            "original_status": first["status"], "actual_action": branch["action"],
            "full_model_settings_messages_wire_equal": True})
    return cases, rows, {"original_preparation": str(prepared.resolve()),
        "original_firsts": str(firsts.resolve()), "bindings": provenance}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("firsts", type=Path)
    parser.add_argument("sampling", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    cases, rows, provenance = prepare(args.prepared, args.firsts, read_json(args.sampling))
    original = read_json(args.prepared / "run.json")
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "cases.json", cases)
    with (args.output / "states.jsonl").open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "first-provenance.json", provenance)
    run = {**original, "status": "COMPLETED", "families": len(cases),
        "selected_states": len(cases), "packets": len(cases),
        "forced_budget_handoff_states": sum(c.get("forced_budget_handoff", False) for c in cases),
        "repeat_preparation": True, "sampling": str(args.sampling.resolve()),
        "original_preparation": str(args.prepared.resolve()),
        "original_firsts": str(args.firsts.resolve()), "training_labels_allowed": False,
        "selection": "Predeclared source identities, including failed first Reader outcomes",
        "readout_scope": "One second Reader invocation on the same actual terminal packet. "
                         "Controller not rerun; original first outcome never replaced.",
        "scope": "Only compiler state_index pointers are remapped for the selected rows. "
                 "Full original request/model/settings/messages remain unchanged. This prepares "
                 "new calls; it does not reuse first responses or select best-of-two.",
        "new_native_executions": 0, "new_controller_executions": 0, "Host_calls": 0,
        "no_sha_validation": True, "compute": {"cpu_seconds": time.process_time() - cpu,
                                               "wall_seconds": time.perf_counter() - started}}
    write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()

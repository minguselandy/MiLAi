"""Bind first-call families to actual pre-final banks and reserve four slots before execution."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from allocate_known_budget_prefixes import allocate_record
from milai_lab.harness.artifact_io import read_json, write_json
from prepare_known_budget_requests import prepare_pair


def prepare_collection(
    selection: dict[str, Any], output: Path, *, low: int, high: int, runtime_python: str,
) -> dict[str, Any]:
    """Prepare all declared families once; missing/ambiguous Host captures keep their cells."""
    if selection["status"] != "PRIMARY_PREFIX_INVENTORY_CREATED;NO_BRANCH_QUALITY_LABELS":
        raise ValueError("Fresh preparation requires the actual primary prefix inventory")
    records = selection["records"]
    if len({r["family"] for r in records}) != len(records):
        raise ValueError("The maximum of four states applies per family, not per collector")
    output.mkdir(parents=True, exist_ok=False)
    started = time.process_time()
    collection = Path(selection["collection"])
    hosts = [(p.parent, read_json(p)) for p in collection.glob("frozen-host-messages/*/host.json")]
    allocated, preparations, jobs = [], {}, []
    outputs: dict[str, dict[str, str]] = {}
    for index, record in enumerate(records):
        matches = []
        if record["status"] == "FIRST_ACTUAL_CALL_RETAINED":
            call = read_json(Path(record["selection"]["capture"]) / "call.json")
            matches = [p for p, h in hosts if h["bank"] == call["bank"]
                and h["public_message"] == call["public_message"]
                and Path(h["source_root"]).resolve() == Path(call["source_root"]).resolve()]
        if len(matches) == 1 and (matches[0] / "closed.json").is_file():
            preparation = prepare_pair(matches[0], record,
                message_id="known-budget-v2-" + record["primary_public_position"],
                low=low, high=high)
        else:
            preparation = {"status": "INELIGIBLE_RETAINED", "family": record["family"],
                "collector": record["collector"], "conditions": [],
                "reason": "no_unique_closed_Host_capture_for_first_actual_call",
                "matched_host_captures": [str(p) for p in matches], "new_model_or_tool_calls": 0}
        preparation_path = output / "preparations" / f"{index:03d}.json"
        write_json(preparation_path, preparation)
        preparations[record["family"]] = str(preparation_path.resolve())
        allocated.append(allocate_record(record, preparation))
        outputs[record["family"]] = {}
        for condition in preparation["conditions"]:
            arm = condition["arm"]
            destination = output / "fresh-requests" / f"{index:03d}" / arm
            outputs[record["family"]][arm] = str(destination.resolve())
            jobs.append({"family": record["family"], "arm": arm,
                "argv": [runtime_python, str(Path(__file__).with_name(
                    "run_known_budget_request.py").resolve()), str(preparation_path.resolve()),
                    str(destination.resolve()), "--arm", arm],
                "automatic_retry": False, "status": "NOT_EXECUTED"})
    write_json(output / "preparation-map.json", preparations)
    write_json(output / "arm-output-map.json", outputs)
    write_json(output / "allocation.json", {"schema": "known_budget_prefix_allocation_v1",
        "status": "FOUR_SLOT_ALLOCATION_FIXED_BEFORE_FRESH_EXECUTION",
        "collection": str(collection.resolve()), "records": allocated,
        "maximum_states_per_family": 4, "model_calls": 0})
    report = {"status": "FRESH_CONDITIONS_AND_FOUR_SLOT_ALLOCATION_PREPARED_NOT_EXECUTED",
        "collection": str(collection.resolve()), "family_units": len(records),
        "fresh_pair_eligible": sum(r["fresh_pair_admitted"] for r in allocated),
        "jobs": jobs, "execution": "Root serializes every real model job; no automatic dispatch "
        "or retries. Reserved cells survive failure or absence. Resolve only after attempts close.",
        "maximum_states_per_family": 4, "low": low, "high": high,
        "actual_fresh_requests": 0, "actual_Host_readouts": 0, "quality_labels": [],
        "model_calls": 0, "ledger_recorded": False,
        "cpu_seconds_pending": time.process_time() - started, "no_sha_validation": True}
    write_json(output / "dispatch.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--low", type=int, default=1024)
    parser.add_argument("--high", type=int, default=2048)
    parser.add_argument("--runtime-python", default=sys.executable)
    args = parser.parse_args()
    report = prepare_collection(read_json(args.selection), args.output, low=args.low,
                                high=args.high, runtime_python=args.runtime_python)
    print(report["status"])


if __name__ == "__main__":
    main()

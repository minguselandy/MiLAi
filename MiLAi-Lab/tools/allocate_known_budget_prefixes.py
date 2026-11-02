"""Reserve four states before fresh requests run, then bind only actual reached captures."""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json
from run_known_budget_request import compare_initial_conditions


def allocate_record(record: dict[str, Any], preparation: dict[str, Any]) -> dict[str, Any]:
    """Eligibility precedes arm outcomes; the second READ is provenance for fresh slots."""
    if any(record[k] != preparation[k] for k in ("family", "collector")):
        raise ValueError("Fresh preparation belongs to a different primary family/collector")
    eligible = preparation["status"] == "FRESH_RAW_KNOWN_BUDGET_REQUESTS_PREPARED_NOT_EXECUTED"
    selection = record["selection"]
    if eligible and (
        selection["capture"] != preparation["source_call"]
        or selection["slots"]["second_read"] is None
        or [c["arm"] for c in preparation["conditions"]] != ["baseline", "limited"]
    ):
        raise ValueError("Fresh slots require the declared first-call two-READ preparation")
    roles = (["initial", "first_read", "fresh_known_baseline", "fresh_known_limited"]
             if eligible else ["initial", "first_read", "second_read", "condition_unavailable"])
    slots = []
    for index, role in enumerate(roles):
        fresh = role.startswith("fresh_known_")
        reached = (selection["slots"].get(role) if selection is not None and not fresh else None)
        slots.append({"slot": index + 1, "role": role,
            "origin": "fresh_request" if fresh else "original_call",
            "arm": role.removeprefix("fresh_known_") if fresh else None,
            "status": "RESERVED_NOT_EXECUTED" if fresh else "REACHED" if reached else "MISSING",
            "capture": reached["capture"] if reached else None,
            "control_step": reached["control_step"] if reached else None})
    return {"family": record["family"], "collector": record["collector"],
        "source_record": copy.deepcopy(record), "preparation": copy.deepcopy(preparation),
        "fresh_pair_admitted": eligible, "slots": slots,
        "second_read_provenance_only": (copy.deepcopy(selection["slots"]["second_read"])
                                         if eligible else None)}


def resolve_record(allocation: dict[str, Any], outputs: dict[str, Path]) -> dict[str, Any]:
    """Retain failed/missing arms in their reserved cells, never replacing them with READ2."""
    result = copy.deepcopy(allocation)
    preparation = result["preparation"]
    if set(outputs) != ({"baseline", "limited"} if result["fresh_pair_admitted"] else set()):
        raise ValueError("Arm paths must follow the pre-execution allocation")
    for slot in result["slots"]:
        if slot["origin"] != "fresh_request":
            continue
        arm = slot["arm"]
        output = outputs[arm].resolve()
        slot["run"] = str(output)
        if not (output / "run.json").exists():
            slot["status"] = "NOT_EXECUTED"
            continue
        run = read_json(output / "run.json")
        condition, = [c for c in preparation["conditions"] if c["arm"] == arm]
        if any(run[k] != value for k, value in {
            "arm": arm, "family": allocation["family"], "request": condition["request"],
            "source_snapshot": preparation["source_snapshot"],
        }.items()):
            raise ValueError("Executed arm differs from its reserved fresh condition")
        if run["status"] == "RUNNING":
            raise ValueError("Close actual fresh attempts before resolving training slots")
        slot["run_status"] = run["status"]
        captures = run["call_captures"]
        if len(captures) != 1:
            slot.update(status="NO_UNIQUE_ACTUAL_CALL", actual_call_count=len(captures))
            continue
        path = Path(captures[0]).resolve()
        call = read_json(path / "call.json")
        public = preparation["public_message"]
        if (path.parent != output / "frozen-retrieval-calls"
                or Path(call["source_root"]).resolve() != output / "runtime"
                or call["source_version"] != preparation["source_version"]
                or call["bank"] != public["bank"]
                or any(call["public_message"][k] != public[k] for k in
                       ("owner", "session", "message_id", "content", "workflow"))
                or call["request"] != condition["request"] or call["host_request_generated"]):
            raise ValueError("Fresh capture identity differs from its actual reserved invocation")
        slot["actual_call_status"] = call["status"]
        slot["actual_capture"] = str(path)
        if (call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}
                or call["initial_observation"] is None):
            slot["status"] = "NO_CLOSED_INITIAL_STATE"
            continue
        slot.update(status="REACHED", capture=str(path), control_step=0)
    if result["fresh_pair_admitted"] and all((p / "run.json").exists() for p in outputs.values()):
        result["pair_comparison"] = compare_initial_conditions(preparation, outputs)
    else:
        result["pair_comparison"] = None
    result["quality_labels"] = []
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Original prefix selection or fixed allocation")
    parser.add_argument("mapping", type=Path,
                        help="Family -> preparation path or two arm directories")
    parser.add_argument("output", type=Path)
    parser.add_argument("--resolve", action="store_true")
    args = parser.parse_args()
    started = time.process_time()
    source, mapping = read_json(args.input), read_json(args.mapping)
    if {r["family"] for r in source["records"]} != set(mapping):
        raise ValueError("Every declared family must retain an allocation, including missing cases")
    if args.resolve:
        if source["status"] != "FOUR_SLOT_ALLOCATION_FIXED_BEFORE_FRESH_EXECUTION":
            raise ValueError("Resolve the pre-execution allocation, not an outcome-selected cohort")
        records = [resolve_record(r, {k: Path(v) for k, v in mapping[r["family"]].items()})
                   for r in source["records"]]
        status = "FOUR_SLOT_ALLOCATION_RESOLVED_NO_QUALITY_LABELS"
    else:
        if source["status"] != "PRIMARY_PREFIX_INVENTORY_CREATED;NO_BRANCH_QUALITY_LABELS":
            raise ValueError("Allocate from the actual first-call prefix inventory")
        records = [allocate_record(r, read_json(Path(mapping[r["family"]])))
                   for r in source["records"]]
        status = "FOUR_SLOT_ALLOCATION_FIXED_BEFORE_FRESH_EXECUTION"
    report = {"schema": "known_budget_prefix_allocation_v1", "status": status,
        "input": str(args.input.resolve()), "collection": source["collection"],
        "records": records, "maximum_states_per_family": 4,
        "scope": "Fresh baseline/limited initial states replace the third/fourth training slots. "
        "Original READ2 is eligibility/provenance only for admitted pairs. Failed/missing fresh "
        "arms retain reserved cells; no later success or READ2 backfill. Fresh states follow "
        "actual delivery and are not old in-call READ2 checkpoints or autonomous Host choices.",
        "model_calls": 0, "ledger_recorded": False,
        "cpu_seconds_pending": time.process_time() - started, "no_sha_validation": True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(status)


if __name__ == "__main__":
    main()

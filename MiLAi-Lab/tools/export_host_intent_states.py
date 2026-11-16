"""Export actual closed Host decision inputs, masked until source-grounded annotation."""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.memory_control_learning import decision_example


def state_source_groups(runs: list[tuple[Path, dict[str, Any]]]) -> dict[str, str]:
    """Conservatively join supplied runs sharing native task/history identities.

    This is an export-local join over recorded identities, not a new role ledger
    or proof of independent content. Original native split roles stay unchanged.
    """
    components: list[set[str]] = []
    identities = {}
    for root, run in runs:
        selection = run["source_selection"]
        members = {f"STATE:{selection['domain']}:{identity}" for identity in [
            selection["task_id"], *selection["memory_trajectory_ids"]]}
        identities[str(root.resolve())] = members
        connected = [group for group in components if group & members]
        components = [group for group in components if not group & members]
        components.append(set().union(members, *connected))
    groups = {}
    for root_key, members in identities.items():
        component = next(group for group in components if group & members)
        groups[root_key] = "|".join(sorted(component))
    return groups


def export_state_states(root: Path, run: dict[str, Any], family: str) -> list[dict[str, Any]]:
    """Keep every actual decision from a closed dynamic STATE run, including failures."""
    if run["status"] not in {"COMPLETED_RESEARCH_TRAJECTORY", "FAILED"}:
        raise ValueError("STATE decision export requires a closed task run")
    if run["memory_protocol"] != "dynamic":
        raise ValueError("This STATE exporter requires the recorded dynamic protocol")
    captures = {}
    for path in (root / "retrieval-snapshots").glob("**/call.json"):
        call = read_json(path)
        captures[call["call_id"], call.get("control_step", 0)] = (path.parent, call)
    trace = root / "trace.jsonl"
    rows: list[dict[str, Any]] = []
    by_decision: dict[tuple[str, int], dict[str, Any]] = {}
    observed_inputs: dict[tuple[str, int], dict[str, Any]] = {}
    for event in read_jsonl(trace):
        if event.get("event") != "memory_control_step":
            continue
        key = (event["retrieval_call_id"], event["step"])
        if event["phase"] in {"decision_output", "operation_result"}:
            if any(json.dumps(event[field], ensure_ascii=False) != json.dumps(
                    observed_inputs[key][field], ensure_ascii=False)
                    for field in ("before", "actions")):
                raise ValueError("STATE decision output/result differs from its actual input")
        if event["phase"] == "decision_input":
            if key in by_decision:
                raise ValueError("Repeated STATE decision identity in the actual trace")
            metadata = {"family": family, "split": run["split"], "native_split": run["split"],
                "row": len(rows), "state_id": len(rows),
                "event_id": f"{root.resolve()}/{key[0]}/{key[1]}",
                "training_event": f"{root.resolve()}/{key[0]}", "task": "memory_operation",
                "component": "STATE_actual_decisions", "interface": "rich",
                "collection_policy": run["memory_policy"], "source_version": run["source_version"],
                "result_path": str((root / "run.json").resolve()),
                "trace_path": str(trace.resolve()),
                "task_status": run["status"], "task_error": run.get("error"),
                "native_task_id": run["task_id"], "decision_step": key[1],
                "source_selection": copy.deepcopy(run["source_selection"]),
                "decision_status": "selection_not_returned", "actual_bindings": {
                    name: copy.deepcopy(event[name]) for name in (
                        "candidate_materials", "opened_materials", "known_materials",
                        "observed_materials") if name in event}}
            if key in captures:
                path, call = captures[key]
                if (event["before"] != call["initial_observation"]
                        or event["actions"] != call["initial_actions"]):
                    raise ValueError("STATE trace and actual decision capture differ")
                metadata.update(capture=str(path.resolve()), capture_status=call["status"])
            row = decision_example(event, metadata)
            rows.append(row)
            by_decision[key] = row
            observed_inputs[key] = event
        elif event["phase"] == "decision_output":
            metadata = by_decision[key]["metadata"]
            action = next(a for a in event["actions"] if a["id"] == event["selected"])
            metadata.update(selected_action=copy.deepcopy(action),
                selection_mode=event["selection_mode"], decision_status=(
                    "plain_handoff" if action["kind"] == "HANDOFF" and not action["parameters"]
                    else "selected_without_operation_result"))
        elif event["phase"] == "operation_result":
            by_decision[key]["metadata"].update(decision_status="operation_returned",
                operation_result=copy.deepcopy(event["result"]))
    return rows


def export_states(
    root: Path, *, driver: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Export one caller-selected closed-position snapshot, including live runs."""
    if driver is None:
        driver = read_json(root / "driver.json")
    histories = {h["id"]: h for h in read_json(root / "fixture.json")["histories"]}
    rows: list[dict[str, Any]] = []
    results_by_profile: dict[str, dict[tuple[str, str], tuple[Path, dict[str, Any]]]] = {}
    for position in driver["completed"]:
        history = histories[position["history"]]
        request = next(r for r in history["requests"] if r["id"] == position["request"])
        profile = position.get("profile", position["policy"])
        bank = (history["id"] if history.get("continuous") and not request.get("independent") else
                history["id"] + "-" + position["request"])
        if profile not in results_by_profile:
            indexed = {}
            for path in (root / profile / "banks").glob("*/*-result.json"):
                result = read_json(path)
                indexed[result["bank"], result["message_id"]] = (path, result)
            results_by_profile[profile] = indexed
        indexed = results_by_profile[profile]
        result_key = (bank, position["request"])
        path, result = indexed[result_key if result_key in indexed else (bank, "request")]
        trace = next(path.parent.glob(path.name.replace("-result.json", "-trace-*.jsonl")))
        for event in read_jsonl(trace):
            if (event.get("event") != "memory_control_step"
                    or event.get("phase") != "decision_input"):
                continue
            key = [profile, history["id"], position["request"],
                   event["retrieval_call_id"], str(event["step"])]
            metadata = {"family": history["source_group"], "split": history["split"],
                "row": len(rows), "event_id": "/".join(key),
                "training_event": "/".join(key[:3]), "interface": position.get("interface", "rich"),
                "collection_policy": position["policy"], "source_version": driver["source_version"],
                "result_path": str(path), "trace_path": str(trace),
                "task_status": result["status"], "actual_bindings": {key: event[key] for key in (
                    "candidate_materials", "opened_materials", "known_materials",
                    "observed_materials") if key in event}}
            rows.append(decision_example(event, metadata))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--protocol", choices=("functional", "state_dynamic"),
                        default="functional")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.protocol == "state_dynamic":
        snapshots = [(run, read_json(run / "run.json")) for run in args.runs]
        families = state_source_groups(snapshots)
        rows = [row for run, result in snapshots
                for row in export_state_states(run, result, families[str(run.resolve())])]
        for i, row in enumerate(rows):
            row["metadata"]["state_id"] = i
        for family in set(families.values()):
            if len({row["metadata"]["split"] for row in rows
                    if row["metadata"]["family"] == family}) > 1:
                raise ValueError("Connected STATE source identities cross declared output splits")
        call_inventory = []
        for run, _ in snapshots:
            for path in (run / "retrieval-snapshots").glob("*/call.json"):
                call = read_json(path)
                call_inventory.append({"run": str(run), "capture": str(path.parent),
                    "call_id": call["call_id"], "status": call["status"],
                    "has_decision": call["initial_observation"] is not None})
        write_json(args.output / "call-inventory.json", call_inventory)
    else:
        snapshots = [(run, read_json(run / "driver.json")) for run in args.runs]
        rows = [row for run, driver in snapshots for row in export_states(run, driver=driver)]
    write_json(args.output / "closed-positions.json", {"runs": [
        {"run": str(run), "driver": driver} for run, driver in snapshots]})
    keys = [row["metadata"]["event_id"] for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate source decisions; name collection policies/profiles explicitly")
    for split in sorted({"train", "dev", *(row["metadata"]["split"] for row in rows)}):
        with (args.output / f"{split}.jsonl").open("w") as stream:
            for row in rows:
                if row["metadata"]["split"] == split:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"status": "ACTUAL_STATES_EXPORTED_ALL_LABELS_MASKED",
        "runs": list(map(str, args.runs)),
        "states": len(rows), "labelled": 0,
        "protocol": args.protocol,
        "closed_host_positions": (len(snapshots) if args.protocol == "state_dynamic"
                                  else sum(len(driver["completed"]) for _, driver in snapshots)),
        "positions_with_states": len({row["metadata"]["training_event"] for row in rows}),
        "splits": dict(Counter(row["metadata"]["split"] for row in rows)),
        "interfaces": dict(Counter(row["metadata"]["interface"] for row in rows)),
        "families": len({row["metadata"]["family"] for row in rows}),
        **({"decision_statuses": dict(Counter(row["metadata"]["decision_status"] for row in rows)),
            "registered_source_groups": len(set(families.values())),
            "source_group_membership": families,
            "captured_calls": len(call_inventory),
            "calls_without_decisions": sum(not call["has_decision"] for call in call_inventory),
            "source_group_scope": "Connected native task/history identities in supplied runs; "
                "not a new independent-family or global content-disjointness claim."}
           if args.protocol == "state_dynamic" else {}),
        "projection": "live operation_payload via decision_example; actual bindings outside state",
        "annotation": "No teacher action, operation availability or final answer becomes gold."}
    write_json(args.output / "export.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()

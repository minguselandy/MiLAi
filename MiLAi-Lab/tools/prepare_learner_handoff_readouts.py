"""Read out already executed terminal HANDOFF alternatives from real learner trajectories."""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState, RulesMemoryPolicy
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import given_packet_request


def bind_terminal(
    row: dict[str, Any],
    branch: dict[str, Any],
    event: dict[str, Any],
    request: dict[str, Any],
    settings: dict[str, Any],
    token_count: Any,
    state_index: int,
) -> dict[str, Any]:
    """Retain the original full online menu; supervise only actually executed HANDOFF choices."""
    expected = decision_example(event, {})
    if (
        row["state"] != expected["state"]
        or row["questions"] != expected["questions"]
        or event["before"] != branch["before"]
        or row["metadata"]["event_id"] != branch["event_id"]
        or [a["id"] for a in event["actions"]] != list(row["questions"]["next"]["criteria"])
    ):
        raise ValueError("Collected terminal alternatives must match the actual full-menu state")
    offered = [MemoryAction(**a) for a in branch["actions"]]
    choices = {
        "collector_actual": event["selected"],
        "rules": RulesMemoryPolicy(reads=4).choose(
            MemoryControlState(**copy.deepcopy(branch["before"])), offered
        ),
    }
    alternatives = [
        b["action"]["id"] for b in branch["results"] if b["action"]["id"] not in choices.values()
    ]
    if len(alternatives) > 1:
        raise ValueError("The collection protocol allows at most one coverage alternative")
    if alternatives:
        choices["coverage"] = alternatives[0]
    if set(choices.values()) != {b["action"]["id"] for b in branch["results"]}:
        raise ValueError("Nominated terminal alternatives differ from actual executed packets")
    case = {
        "family": branch["family"],
        "event_id": branch["event_id"],
        "case_key": branch["event_id"],
        "request_id": request["id"],
        "state_index": state_index,
        "before": branch["before"],
        "actions": event["actions"],
        "choices": choices,
        "branches": [],
        "known_evidence_refs": [],
        "forced_budget_handoff": event.get("forced_budget_handoff", False),
        "prefix_reexecuted_for_reconstruction": False,
    }
    for actual in branch["results"]:
        if actual["action"] not in event["actions"] or actual["action"]["kind"] != "HANDOFF":
            raise ValueError("Actual HANDOFF binding is absent from the original full menu")
        case["branches"].append(
            {
                "policies": [p for p, key in choices.items() if key == actual["action"]["id"]],
                "action": actual["action"],
                "execution_result": actual["result"],
                "packet": actual["packet"],
                "body_tokens": token_count(json.dumps(actual["packet"], ensure_ascii=False)),
                "reference_proof_complete": actual["reference_proof_complete"],
                "delivered_native_sources": actual["delivered_native_sources"],
                "readout_request": given_packet_request(
                    {
                        "content": request["content"],
                        "query_time": branch["before"]["task"]["query_time"],
                        "calendar_context": branch["before"]["task"]["calendar_context"],
                    },
                    branch["before"]["task"]["retrieval_request"],
                    actual["packet"],
                    settings,
                ),
            }
        )
    return case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--families", type=int, default=64)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    original = read_json(args.collection / "run.json")
    if args.offset + args.families > original["completed_families"]:
        raise ValueError("Select only closed source-family prefixes")
    histories = read_json(args.collection / "sources.json")["histories"]
    histories = histories[args.offset : args.offset + args.families]
    if any(h["split"] != "train" or len(h["requests"]) != 1 for h in histories):
        raise ValueError("This first I2 slice uses one native question per TRAIN source family")
    families = {h["source_group"]: h for h in histories}
    selected = []
    with (args.collection / "branches.jsonl").open() as stream:
        for line in stream:
            branch = json.loads(line)
            if branch["family"] in families:
                selected.append(branch)
                if len(selected) == len(histories):
                    break
    if [b["family"] for b in selected] != list(families):
        raise ValueError(
            "Requested families do not have the complete declared terminal alternatives"
        )
    selected_ids = {b["event_id"] for b in selected}
    rows = {}
    with (args.collection / "states.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            if row["metadata"]["event_id"] in selected_ids:
                rows[row["metadata"]["event_id"]] = row
                if len(rows) == len(selected_ids):
                    break
    settings = read_json(Path(original["config"]))["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    cases = []
    for index, branch in enumerate(selected):
        history = families[branch["family"]]
        request = history["requests"][0]
        events = read_jsonl(
            args.collection / "banks" / history["id"] / f"{request['id']}-operations.jsonl"
        )
        cases.append(
            bind_terminal(
                rows[branch["event_id"]],
                branch,
                events[-1],
                request,
                settings,
                capacity.text_tokens,
                index,
            )
        )
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "cases.json", cases)
    with (args.output / "states.jsonl").open("w") as stream:
        for branch in selected:
            stream.write(json.dumps(rows[branch["event_id"]], ensure_ascii=False) + "\n")
    write_json(
        args.output / "run.json",
        {
            "status": "COMPLETED",
            "collection": str(args.collection.resolve()),
            "config": original["config"],
            "collector_checkpoint": original["collector_checkpoint"],
            "families": len(cases),
            "selected_states": len(cases),
            "packets": sum(len(c["branches"]) for c in cases),
            "forced_budget_handoff_states": sum(c["forced_budget_handoff"] for c in cases),
            "selection": "Every first native question terminal state in fixed source order; no "
            "outcome filtering. Budget-forced actual delivery is explicitly identified.",
            "continuation_policy": "none: actual terminal HANDOFF alternatives",
            "continuation_steps": 0,
            "terminal_handoff": "nominated_binding",
            "new_native_executions": 0,
            "Host_calls": 0,
            "no_sha_validation": True,
            "scope": "Actual same-pool packets already executed during learner collection. "
            "Original complete online menus remain in training inputs. Prefix costs belong to the "
            "collector, not charged again. Conditional empty-K readouts, not autonomous Host.",
            "compute": {
                "cpu_seconds": time.process_time() - cpu,
                "wall_seconds": time.perf_counter() - started,
            },
        },
    )


if __name__ == "__main__":
    main()

"""Execute frozen full-menu scorer nominations for conditional delivery on actual acquired pools."""

from __future__ import annotations

import argparse
import copy
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from collect_qasper_operation_states import complete, covered_sources, reference_proofs
from collected_handoff import replay_collected_prefix
from feedback_choices import full_menu_choice
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.methods.laya_memory_policy import project_operation_payload
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState, RulesMemoryPolicy
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import given_packet_request


def nominations(
    branch: dict[str, Any], prediction: dict[str, Any], full_actions: list[dict[str, Any]]
) -> dict[str, Any]:
    full = full_menu_choice(full_actions, prediction["logits"])
    if full != prediction["choice"]:
        raise ValueError("Recorded full-menu prediction differs from its actual logits")
    handoffs = [MemoryAction(**a) for a in branch["actions"]]
    if any(a.kind != "HANDOFF" for a in handoffs):
        raise ValueError("Conditional delivery candidates must be actual HANDOFF bindings")
    conditional = max(handoffs, key=lambda a: prediction["logits"][a.id]).id
    return {
        "full_argmax": full,
        "conditional_only": True,
        "choices": {
            "frozen_conditional": conditional,
            "rules": RulesMemoryPolicy(reads=4).choose(
                MemoryControlState(**copy.deepcopy(branch["before"])), handoffs
            ),
            "fixed_current": next(a.id for a in handoffs if not a.parameters),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("scores", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    scored = read_json(args.scores / "run.json")
    if scored["status"] != "COMPLETED" or scored["completed_states"] != scored["planned_states"]:
        raise ValueError("Finish the complete frozen scorer matrix before packet execution")
    rows = read_jsonl(Path(scored["data"]))
    raw = {b["event_id"]: b for b in read_jsonl(args.collection / "branches.jsonl")}
    if {r["metadata"]["event_id"] for r in rows} != set(raw):
        raise ValueError("Use every declared terminal state, without label/score filtering")
    collected = read_json(args.collection / "run.json")
    settings = read_json(Path(collected["config"]))["entrypoints"]["functional"]
    histories = {
        h["source_group"]: h for h in read_json(args.collection / "sources.json")["histories"]
    }
    controls = {
        (c["source_group"], c["request_id"]): c for c in read_jsonl(Path(collected["controls"]))
    }
    capacity = HostCapacity(settings["capacity"])
    args.output.mkdir(parents=True, exist_ok=False)
    run = {
        "status": "RUNNING",
        "collection": str(args.collection.resolve()),
        "config": collected["config"],
        "scores": str(args.scores.resolve()),
        "families": len(histories),
        "states": len(rows),
        "new_packets_executed": 0,
        "reused_tool_packets": 0,
        "packets": 0,
        "no_sha_validation": True,
        "Host_calls": 0,
        "new_model_calls": 0,
        "continuation_policy": "none: nominated HANDOFF in actual acquired pool",
        "continuation_steps": 0,
        "terminal_handoff": "nominated_binding",
        "scope": "Conditional best HANDOFF from full-menu logits; full argmax remains separate. "
        "All source-order states retained. No autonomous stop or held-out success claim.",
    }
    cases, choice_counts = [], Counter()
    try:
        for index, row in enumerate(rows):
            branch = raw[row["metadata"]["event_id"]]
            history = histories[branch["family"]]
            request_id = branch["event_id"].rsplit("/", 2)[1]
            request = next(q for q in history["requests"] if q["id"] == request_id)
            event = read_jsonl(
                args.collection / "banks" / history["id"] / f"{request_id}-operations.jsonl"
            )[-1]
            actual_row = decision_example(event, {})
            if (
                branch["before"] != event["before"]
                or branch["actions"] != [a for a in event["actions"] if a["kind"] == "HANDOFF"]
                or any(row[k] != actual_row[k] for k in ("state", "questions"))
            ):
                raise ValueError("Scored row does not belong to this exact acquired pool and menu")
            projected = project_operation_payload(row, scored["operation_state"])
            if {k: projected[k] for k in ("state", "questions")} != read_json(
                args.scores / "calls" / str(index) / "input.json"
            ):
                raise ValueError(
                    "Saved scorer input changed the complete original observation/menu"
                )
            prediction = read_json(args.scores / "calls" / str(index) / "output.json")
            nomination = nominations(branch, prediction, event["actions"])
            choices = nomination["choices"]
            case = {
                "family": branch["family"],
                "event_id": branch["event_id"],
                "case_key": branch["event_id"],
                "request_id": request_id,
                "state_index": index,
                "before": branch["before"],
                "actions": event["actions"],
                **nomination,
                "known_evidence_refs": [],
                "branches": [],
            }
            executed = {b["action"]["id"]: copy.deepcopy(b) for b in branch["results"]}
            missing = [key for key in dict.fromkeys(choices.values()) if key not in executed]
            if missing:
                source_map = read_json(
                    args.collection / "banks" / history["id"] / "source-map.json"
                )
                proofs = reference_proofs(controls[branch["family"], request_id])
                with replay_collected_prefix(
                    args.collection, history, branch, settings, capacity
                ) as (operations, state):
                    saved = operations.checkpoint()
                    observation = (
                        operations.source_pages.budget if operations.source_pages else None
                    )
                    for key in missing:
                        operations.restore_checkpoint(saved, observation)
                        state = MemoryControlState(**copy.deepcopy(branch["before"]))
                        action = next(
                            MemoryAction(**a) for a in branch["actions"] if a["id"] == key
                        )
                        result = (
                            operations.execute(action, state) if action.parameters else {"ok": True}
                        )
                        packet = controlled_reader_packet(
                            operations.reader_evidence(), "collection"
                        )
                        coverage = covered_sources(
                            list(operations.opened.values()),
                            source_map["mapping"],
                            source_map["source_lengths"],
                        )
                        executed[key] = {
                            "action": asdict(action),
                            "result": result,
                            "packet": packet,
                            "reference_proof_complete": complete(proofs, coverage)
                            if proofs
                            else None,
                            "delivered_native_sources": sorted(coverage),
                        }
                        run["new_packets_executed"] += 1
            for key in dict.fromkeys(choices.values()):
                actual = executed[key]
                run["reused_tool_packets"] += key not in missing
                case["branches"].append(
                    {
                        "policies": [p for p, selected in choices.items() if selected == key],
                        "action": actual["action"],
                        "execution_result": actual["result"],
                        "packet": actual["packet"],
                        "reference_proof_complete": actual["reference_proof_complete"],
                        "delivered_native_sources": actual["delivered_native_sources"],
                        "body_tokens": capacity.text_tokens(
                            json.dumps(actual["packet"], ensure_ascii=False)
                        ),
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
                        "new_tool_execution": key in missing,
                    }
                )
            choice_counts["full_argmax_is_handoff"] += prediction["choice"] in {
                a["id"] for a in branch["actions"]
            }
            choice_counts["conditional_equals_current"] += (
                choices["frozen_conditional"] == choices["fixed_current"]
            )
            cases.append(case)
            run["packets"] += len(case["branches"])
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        write_json(args.output / "cases.json", cases)
        with (args.output / "states.jsonl").open("w") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        run.update(
            choice_counts=dict(choice_counts),
            compute={
                "cpu_seconds": time.process_time() - cpu,
                "wall_seconds": time.perf_counter() - started,
            },
        )
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()

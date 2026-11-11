"""Execute bounded comparisons at actual frozen-learner states in original Source banks."""

from __future__ import annotations

import argparse
import copy
import json
import random
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from collect_qasper_operation_states import complete, covered_sources, reference_proofs
from collected_handoff import replay_collected_prefix
from feedback_choices import coverage_alternative, full_menu_choice, parameter_stratum
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.methods.memory_control import (
    FirstActionIntervention,
    FixedContextMemoryPolicy,
    MemoryAction,
    MemoryControlState,
    RulesMemoryPolicy,
    run_memory_control,
)
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import given_packet_request


def continuation_policy(name: str) -> Any:
    return {"rules": RulesMemoryPolicy, "fixed_context": FixedContextMemoryPolicy}[name](reads=4)


def baseline(event: dict[str, Any], policy_name: str = "rules") -> str:
    return continuation_policy(policy_name).choose(
        MemoryControlState(**copy.deepcopy(event["before"])),
        [MemoryAction(**a) for a in event["actions"]],
    )


def select_events(
    events: list[dict[str, Any]], family_index: int, policy_name: str = "rules"
) -> list[dict[str, Any]]:
    """Initial plus one real post state, without consulting native labels or branch results."""
    initial = [e for e in events if e["step"] == 0]
    if len(initial) != 1:
        raise ValueError("This collection requires exactly one native request per family")
    post = [e for e in events if e["step"] > 0 and not e.get("forced_budget_handoff")]
    disagreement = [e for e in post if e["prediction"]["choice"] != baseline(e, policy_name)]
    if family_index % 2 and disagreement:
        return [initial[0], disagreement[0]]
    if post:
        return [initial[0], random.Random(family_index).choice(post)]  # noqa: S311
    return initial


def nominate(
    event: dict[str, Any], coverage: Counter[str], seed: int, policy_name: str = "rules"
) -> dict[str, str]:
    choices = {
        "learner": full_menu_choice(event["actions"], event["prediction"]["logits"]),
        policy_name: baseline(event, policy_name),
    }
    chosen = [a for a in event["actions"] if a["id"] in choices.values()]
    for action in chosen:
        coverage[parameter_stratum(action)] += 1
    alternate = coverage_alternative(
        {"initial_observation": event["before"], "initial_actions": event["actions"]},
        chosen,
        coverage,
        seed,
    )
    if alternate is not None:
        choices["coverage"] = alternate["id"]
        coverage[parameter_stratum(alternate)] += 1
    return choices


def execute_branch(
    operations: Any,
    before: dict[str, Any],
    action: MemoryAction,
    step: int,
    continuation_steps: int,
    terminal_handoff: str = "rules",
    policy_name: str = "rules",
) -> dict[str, Any]:
    """Keep the finite allowance; let the shared policy select acquired material at the boundary."""
    state = MemoryControlState(**copy.deepcopy(before))
    remaining = before["budget"]["remaining_control_steps"]
    policy = continuation_policy(policy_name)

    class TerminalPolicy:
        def choose(self, current: MemoryControlState, actions: list[MemoryAction]) -> str:
            elapsed = remaining - current.budget["remaining_control_steps"]
            offered = (
                [a for a in actions if a.kind == "HANDOFF"]
                if elapsed > continuation_steps
                else actions
            )
            terminal = RulesMemoryPolicy(reads=4) if terminal_handoff == "rules" else policy
            return (terminal if elapsed > continuation_steps else policy).choose(current, offered)

    if terminal_handoff not in {"current", "rules", "policy"}:
        raise ValueError("Declare current-packet or shared-policy terminal HANDOFF")
    result = run_memory_control(
        state,
        TerminalPolicy() if terminal_handoff != "current" else policy,
        operations,
        max_steps=step + remaining,
        start_step=step,
        # In rules mode the wrapper enforces the short boundary with a legal HANDOFF
        # choice. Do not let the legacy intervention discard observation-only material.
        intervention=FirstActionIntervention(
            action, remaining if terminal_handoff != "current" else continuation_steps
        ),
    )
    first = result["trace"][0]
    if first["before"] != before or first["selected"] != action.id:
        raise ValueError("Branch changed the actual before or nominated binding")
    result["terminal_handoff"] = terminal_handoff
    result["continuation_policy"] = policy_name
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--families", type=int, required=True)
    parser.add_argument("--split", choices=("train", "dev"), default="train")
    parser.add_argument("--continuation-steps", type=int, default=2)
    parser.add_argument(
        "--continuation-policy",
        choices=("rules", "fixed_context"),
        default="rules",
        help="Declared baseline nomination and shared continuation policy",
    )
    parser.add_argument(
        "--terminal-handoff",
        choices=("current", "rules", "policy"),
        default="rules",
        help="Shared policy selects among actual HANDOFF bindings at the short boundary",
    )
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    collection_run = read_json(args.collection / "run.json")
    if (
        collection_run.get("collector_checkpoint") is None
        or args.offset + args.families > collection_run["completed_families"]
    ):
        raise ValueError("Select only a closed family prefix from the actual learner collection")
    histories = read_json(args.collection / "sources.json")["histories"]
    histories = histories[args.offset : args.offset + args.families]
    if any(h["split"] != args.split or len(h["requests"]) != 1 for h in histories):
        raise ValueError("Feedback requires one original request per declared source-role family")
    settings = read_json(Path(collection_run["config"]))["entrypoints"]["functional"]
    controls = {
        (c["source_group"], c["request_id"]): c
        for c in read_jsonl(Path(collection_run["controls"]))
    }
    capacity = HostCapacity(settings["capacity"])
    args.output.mkdir(parents=True, exist_ok=False)
    run = {
        "status": "RUNNING",
        "collection": str(args.collection.resolve()),
        "config": collection_run["config"],
        "collector_checkpoint": collection_run["collector_checkpoint"],
        "families": len(histories),
        "split": args.split,
        "selected_states": 0,
        "comparison_states": 0,
        "packets": 0,
        "continuation_policy": type(continuation_policy(args.continuation_policy)).__name__
        + "(reads=4)",
        "nomination_baseline": args.continuation_policy,
        "continuation_steps": args.continuation_steps,
        "terminal_handoff": args.terminal_handoff,
        "selection": "Initial plus one actual non-forced post state; even family positions seeded "
        "uniform; odd positions use earliest learner/baseline disagreement, else uniform. "
        "Missing posts remain missing; no outcome/native-label selection.",
        "no_sha_validation": True,
        "Host_calls": 0,
        "automatic_retry": False,
        "scope": "Actual same-before full bindings and bounded ordinary continuation. "
        "Reference witness is an offline proxy; no Host success labels generated here.",
    }
    cases, rows, cells = [], [], []
    coverage: Counter[str] = Counter()
    try:
        for family_index, history in enumerate(histories, args.offset):
            root = args.collection / "banks" / history["id"]
            request = history["requests"][0]
            events = read_jsonl(root / f"{request['id']}-operations.jsonl")
            selected = select_events(events, family_index, args.continuation_policy)
            cells.append(
                {
                    "family": history["source_group"],
                    "actual_states": len(events),
                    "selected_steps": [e["step"] for e in selected],
                    "missing_post": len(selected) < 2,
                }
            )
            for event in selected:
                event_id = f"{history['source_group']}/{request['id']}/step-{event['step']}"
                choices = nominate(event, coverage, len(rows), args.continuation_policy)
                row = decision_example(
                    event,
                    {
                        "family": history["source_group"],
                        "split": history["split"],
                        "row": len(rows),
                        "state_id": len(rows),
                        "event_id": event_id,
                        "training_event": request["id"],
                        "task": "memory_operation",
                        "collector": "frozen_learner",
                    },
                )
                rows.append(row)
                case = {
                    "family": history["source_group"],
                    "event_id": event_id,
                    "case_key": event_id,
                    "request_id": request["id"],
                    "step": event["step"],
                    "choices": choices,
                    "branches": [],
                    "state_index": len(rows) - 1,
                    "before": event["before"],
                    "actions": event["actions"],
                    "known_evidence_refs": [],
                    "prefix_reexecuted_for_reconstruction": True,
                }
                # Singleton states retain coverage, but do not manufacture a quality tie.
                if len(set(choices.values())) < 2:
                    case["status"] = "SINGLETON_NOT_EXECUTED"
                    cases.append(case)
                    continue
                phase_wall, phase_cpu = time.perf_counter(), time.process_time()
                source_map = read_json(root / "source-map.json")
                proofs = reference_proofs(controls[history["source_group"], request["id"]])
                with replay_collected_prefix(
                    args.collection, history, case, settings, capacity, target_step=event["step"]
                ) as (operations, state):
                    saved = operations.checkpoint()
                    observation = (
                        operations.source_pages.budget if operations.source_pages else None
                    )
                    for key in dict.fromkeys(choices.values()):
                        operations.restore_checkpoint(saved, observation)
                        action = next(MemoryAction(**a) for a in event["actions"] if a["id"] == key)
                        result = execute_branch(
                            operations,
                            event["before"],
                            action,
                            event["step"],
                            args.continuation_steps,
                            args.terminal_handoff,
                            args.continuation_policy,
                        )
                        packet = controlled_reader_packet(
                            operations.reader_evidence(), "collection"
                        )
                        last = result["trace"][-1]
                        last_action = next(
                            a for a in last["actions"] if a["id"] == last["selected"]
                        )
                        ok = result["reason"] != "operation_outcome_unknown" and not (
                            last_action["kind"] == "HANDOFF"
                            and not last.get("result", {"ok": True})["ok"]
                        )
                        covered = covered_sources(
                            list(operations.opened.values()),
                            source_map["mapping"],
                            source_map["source_lengths"],
                        )
                        case["branches"].append(
                            {
                                "policies": [p for p, choice in choices.items() if choice == key],
                                "action": asdict(action),
                                "continuation": result,
                                "execution_result": {"ok": ok, "status": result["reason"]},
                                "packet": packet,
                                "body_tokens": capacity.text_tokens(
                                    json.dumps(packet, ensure_ascii=False)
                                ),
                                "delivered_native_sources": sorted(covered),
                                "reference_proof_complete": complete(proofs, covered)
                                if proofs
                                else None,
                                "readout_request": given_packet_request(
                                    {
                                        "content": request["content"],
                                        "query_time": state.task["query_time"],
                                        "calendar_context": state.task["calendar_context"],
                                    },
                                    state.task["retrieval_request"],
                                    packet,
                                    settings,
                                ),
                            }
                        )
                case.update(
                    status="COMPLETED",
                    reconstruction_and_branch_cpu_seconds=time.process_time() - phase_cpu,
                    reconstruction_and_branch_wall_seconds=time.perf_counter() - phase_wall,
                )
                cases.append(case)
                run.update(
                    selected_states=len(rows),
                    comparison_states=sum(bool(c["branches"]) for c in cases),
                    packets=sum(len(c["branches"]) for c in cases),
                )
                write_json(args.output / "run.json", run)
                write_json(args.output / "cases.json", [c for c in cases if c["branches"]])
                print(
                    json.dumps(
                        {k: run[k] for k in ("selected_states", "comparison_states", "packets")}
                    ),
                    flush=True,
                )
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        run.update(
            selected_states=len(rows),
            compute={
                "cpu_seconds": time.process_time() - cpu,
                "wall_seconds": time.perf_counter() - started,
            },
        )
        write_json(args.output / "run.json", run)
        write_json(args.output / "cases.json", [c for c in cases if c["branches"]])
        write_json(
            args.output / "coverage.json",
            {
                "cells": cells,
                "parameters": dict(coverage),
                "singletons": [c for c in cases if not c["branches"]],
            },
        )
        with (args.output / "states.jsonl").open("w") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

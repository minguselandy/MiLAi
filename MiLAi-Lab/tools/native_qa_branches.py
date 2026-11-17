"""Actual native QA branches from captured before/executor state, with fixed continuation."""
from __future__ import annotations

import copy
import json
import os
import random
import time
from dataclasses import asdict
from typing import Any

from langgraph.store.sqlite import SqliteStore  # type: ignore[import-not-found]

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.small_control_model import SmallControlModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import given_packet_request, separate_answer_fields
from native_qa_control import actual_packet, environment
from prepare_collected_operation_feedback import QueryOnceContextPolicy, execute_branch
from small_control_branches import copy_source_bank


def collect(args: Any) -> None:
    import torch  # type: ignore[import-not-found]

    torch.set_num_threads(4)
    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    parent = read_json(args.collection / "run.json")
    if parent["status"] != "COMPLETED":
        raise ValueError("Capture full actual trajectories before branching")
    settings = read_json(args.reader_config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    histories = read_json(args.sources / "sources.json")["histories"][:args.roots]
    if not histories or any(h["split"] != "train" for h in histories):
        raise ValueError("Feedback branches require declared TRAIN roots")
    model = SmallControlModel.load(args.checkpoint, device=args.device)
    rng = random.Random(args.seed)  # noqa: S311 -- prospective source/state/action sampling
    cases: list[dict[str, Any]] = []
    selected_states: list[dict[str, Any]] = []
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "collection": str(args.collection), "config": str(args.reader_config),
        "sources": str(args.sources), "checkpoint": str(args.checkpoint),
        "device": args.device, "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "planned_roots": len(histories), "closed_roots": 0, "Reader_calls": 0,
        "horizons": args.horizons, "continuation_policy": "query_once_context(reads4)",
        "terminal_handoff": "current", "seed": args.seed, "sha_validation": False,
        "collection_policy": getattr(args, "collection_policy", "query_once4"),
        "state_sampling": getattr(args, "state_sampling", "initial_and_post"),
        "material_formation": parent.get("material_formation", "token_ranges_v1"),
        "source_directory_only": parent.get("source_directory_only", False),
        "scope": "Same actual before, complete legal menu and remaining budget. Independent "
                 "SQLite read-only branch copies; no native labels used for sampling/decisions."}
    write_json(args.output / "run.json", run)
    try:
        for ordinal, history in enumerate(histories):
            bank = args.collection / "banks" / history["id"]
            mapping = read_json(bank / "source-map.json")
            for request in history["requests"]:
                path = bank / (f"{request['id']}-"
                    f"{getattr(args, 'collection_policy', 'query_once4')}-checkpoints.jsonl")
                captured = read_jsonl(path)
                initial = next(x for x in captured if x["decision"]["step"] == 0)
                post = [x for x in captured if x["decision"]["step"] > 0
                        and x["decision"]["before"].get("observed_materials")]
                sampling = getattr(args, "state_sampling", "initial_and_post")
                if sampling == "last_observed":
                    if not post:
                        raise ValueError("Declared last-observed sampling needs an actual state")
                    chosen = [post[-1]]
                else:
                    chosen = [initial]
                    if post:
                        chosen.append(rng.choice(post) if ordinal % 2 == 0 else post[-1])
                for saved in chosen:
                    event = saved["decision"]
                    before = event["before"]
                    actions = [MemoryAction(**a) for a in event["actions"]]
                    scored = model.score({"observation": before, "actions": event["actions"]})
                    current = scored.action_ids[max(range(len(scored.scores)),
                                                    key=scored.scores.__getitem__)]
                    fixed = QueryOnceContextPolicy(reads=4).choose(
                        MemoryControlState(**copy.deepcopy(before)), actions)
                    stop = next(a.id for a in actions if a.kind == "HANDOFF" and not a.parameters)
                    nominees = [("immediate_stop", stop), ("query_once4", fixed),
                                ("current_model", current)]
                    remaining = [a for a in actions if a.id not in {key for _, key in nominees}]
                    if sampling == "last_observed":
                        # Acquire genuinely new material, rather than sampling another
                        # delivery subset. Availability and bindings come from the executor.
                        remaining = [a for a in remaining if a.kind == "READ"
                            and not a.parameters.get("observe_only")
                            and not a.parameters.get("history_directory")
                            and "source_observation_cursor" not in a.parameters]
                    if remaining:
                        nominees.append(("random_alternative", rng.choice(remaining).id))
                    unique: list[MemoryAction] = []
                    methods: dict[str, list[str]] = {}
                    for name, key in nominees:
                        action = next(a for a in actions if a.id == key)
                        prior = next((a for a in unique if (a.kind,a.target,a.parameters) == (
                            action.kind,action.target,action.parameters)), None)
                        if prior is None:
                            unique.append(action)
                            methods[action.id] = []
                            prior = action
                        methods[prior.id].append(name)
                    state_number = len(selected_states)
                    selected_states.append({"family": history["source_group"],
                        "event_id": saved["event_id"], "step": event["step"],
                        "source_sampling": "fixed_prefix_of_declared_TRAIN_export",
                        "state_sampling": sampling,
                        "before": before, "actions": event["actions"],
                        "nominations": nominees, "model_scores": asdict(scored)})
                    for horizon in args.horizons:
                        event_id = saved["event_id"] + f"/step-{event['step']}/h{horizon}"
                        case = {"family": history["source_group"], "event_id": event_id,
                            "case_key": event_id, "request_id": request["id"],
                            "horizon": horizon, "state_index": state_number,
                            "before": before, "actions": event["actions"],
                            "choices": {name: a.id for a in unique for name in methods[a.id]},
                            "branches": []}
                        if sampling == "last_observed":
                            case["response_event_id"] = saved["event_id"]
                        for bi, action in enumerate(unique):
                            destination = args.output / f"state-{state_number:03d}-h{horizon}-b{bi}"
                            copy_source_bank(bank / "memory.sqlite", destination)
                            connection = str(destination / "memory.sqlite")
                            with SqliteStore.from_conn_string(connection) as store:
                                service = MemoryService(store,
                                    ("small-control-native",history["id"],"author"), "author",
                                    destination / "lock", functional_contract="functional_v1")
                                state = MemoryControlState(**copy.deepcopy(before))
                                state, operations = environment(service, request, capacity,
                                    args.material_tokens, state=state,
                                    checkpoint=saved["executor_checkpoint"],
                                    evidence_units=parent.get("material_formation") ==
                                        "whole_paragraph_v1_R2_whole_turn_R3",
                                    source_directory_only=parent.get(
                                        "source_directory_only", False))
                                restored_actions = [asdict(a) for a in operations.actions(state)]
                                if (state.project() != before
                                        or restored_actions != event["actions"]):
                                    raise ValueError("Actual replay before/menu differs")
                                branch_tick, branch_cpu = time.perf_counter(), time.process_time()
                                result = execute_branch(operations, before, action, event["step"],
                                    horizon, terminal_handoff="current",
                                    policy_name="query_once_context")
                                packet, delivered = actual_packet(operations, mapping)
                                wire = separate_answer_fields(given_packet_request({
                                    "content": request["content"], "query_time": "2026-11-17",
                                    "calendar_context": "Asia/Shanghai"},
                                    request["retrieval_request"], packet, settings))
                                capacity.check(wire["messages"])
                                measured = {"local_action_to_request_wall_seconds":
                                    time.perf_counter() - branch_tick,
                                    "local_action_to_request_cpu_seconds":
                                    time.process_time() - branch_cpu,
                                    "scope": "Execute actual first action/continuation, package "
                                        "and capacity check; excludes branch bank copy, "
                                        "nomination encoder and Reader. Overlaps trace phases."}
                                case["branches"].append({"action": asdict(action),
                                    "policies": methods[action.id], "packet": packet,
                                    "actual_delivered_source_ranges": delivered,
                                    "readout_request": wire, "continuation": result,
                                    "measured_costs": measured,
                                    "body_tokens": capacity.text_tokens(json.dumps(packet)),
                                    "condition_provenance": {"role": "ACTUAL_TRAIN_BRANCH",
                                        "horizon": horizon, "before_step": event["step"],
                                        "state_index": state_number},
                                    "execution_result": {"ok": result["reason"] !=
                                        "operation_outcome_unknown", "status": result["reason"]}})
                        cases.append(case)
            run["closed_roots"] = ordinal + 1
            write_json(args.output / "cases.json", cases)
            write_json(args.output / "selected-states.json", selected_states)
            write_json(args.output / "run.json", run)
            print(json.dumps({"closed_roots": ordinal+1, "states": len(selected_states),
                              "branches": sum(len(c["branches"]) for c in cases)}), flush=True)
        run["status"] = "COMPLETED"
    except Exception as error:
        run.update(status="FAILED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        run.update(wall_seconds=time.perf_counter()-tick, cpu_seconds=time.process_time()-cpu,
            model_counters=model.counters, compute_ledger_status="pending_idle_settlement")
        write_json(args.output / "run.json", run)

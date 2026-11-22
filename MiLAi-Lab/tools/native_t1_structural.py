"""Finite full-menu structural supervision on actual native Source transitions."""
from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore  # type: ignore[import-not-found]

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState, run_memory_control
from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel
from milai_lab.methods.small_memory_policy import EncoderCosineMemoryPolicy
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.scorers.reference_qa import reference_coverage
from native_qa_control import actual_packet, environment, material_packet
from prepare_collected_operation_feedback import execute_branch
from small_control_branches import copy_source_bank


def structural_supervision(actions: list[dict[str, Any]], outcomes: list[dict[str, Any]],
                           acquired_before: dict[str, Any]) -> dict[str, Any]:
    """Complete delivery, then actual acquisition progress, with measured operation ties."""
    ids = [action["id"] for action in actions]
    if [row["action"]["id"] for row in outcomes] != ids:
        raise ValueError("Structural outcomes must bind the entire actual offered menu")
    comparable, ranks = [], {}
    for row in outcomes:
        key = row["action"]["id"]
        delivered, acquired = row["delivered_coverage"], row["acquired_coverage"]
        if (row["reason"] == "operation_outcome_unknown" or delivered["covered"] is None
                or acquired["covered"] is None or acquired_before["covered"] is None):
            continue
        comparable.append(key)
        if delivered["complete"]:
            rank = (2, delivered["covered"], -row["nonterminal_operations"])
        elif (row["action"]["kind"] != "HANDOFF"
              and acquired["covered"] > acquired_before["covered"]):
            rank = (1, acquired["covered"], -row["nonterminal_operations"])
        else:
            rank = (0, 0, 0)
        ranks[key] = rank
    maximum = max(ranks.values()) if ranks else (0, 0, 0)
    good = [key for key, rank in ranks.items() if rank == maximum] if maximum[0] > 0 else []
    # A flat menu is not a fabricated directional label, even if all actions are known.
    if len(good) == len(comparable):
        good = []
    return {"label_grade": "A_actual_native_reference_progress_property_only",
        "target": "complete_delivery_or_acquisition_progress_then_control_ops_v1",
        "observed_action_ids": ids, "choice_action_ids": comparable if good else [],
        "good_action_ids": good, "preferences": [],
        "structural_ranks": {key: list(rank) for key, rank in ranks.items()},
        "scope": "All legal branches actually executed. Native span coverage and real control "
                 "operations, not Reader success, semantic sufficiency or a full-return oracle."}


class PrefixPolicy:
    def __init__(self, encoder: SmallControlModel, *, observe_only: bool) -> None:
        self.policy = EncoderCosineMemoryPolicy(encoder, reads=2)
        self.observe_only = observe_only

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        # Prefix construction only. Branch supervision still executes the FULL menu.
        base = [a for a in actions if a.kind != "READ" or (
            "index" in a.parameters and not a.parameters.get("observe_only")
            and not a.parameters.get("expand_context")
            and not a.parameters.get("history_directory"))]
        selected = self.policy.choose(state, base)
        action = next(a for a in base if a.id == selected)
        if self.observe_only and action.kind == "READ":
            parameters = {**action.parameters, "observe_only": True}
            return next(a.id for a in actions if a.kind == "READ" and a.parameters == parameters)
        return selected


def captured_prefix_states(manifest: dict[str, Any], event_id: str,
                           ) -> dict[str, dict[str, Any]]:
    """Load literal actual decisions, addressed by file/index rather than copied observations."""
    selectors = manifest["events"][event_id]
    selected = {}
    for selector in selectors:
        name, index = selector["name"], selector["record_index"]
        if (not isinstance(name, str) or not name or "/" in name or name in selected
                or not isinstance(index, int) or isinstance(index, bool) or index < 0):
            raise ValueError(
                "Captured state selectors require unique names and nonnegative indices")
        saved = read_jsonl(Path(selector["checkpoint_path"]))[index]
        if saved["event_id"] != event_id or saved["policy"] != selector["policy"]:
            raise ValueError("Captured decision belongs to another event or policy")
        selected[name] = saved
    if not selected:
        raise ValueError("Captured structural collection requires at least one actual decision")
    return selected


def collect(args: Any) -> None:
    import torch  # type: ignore[import-not-found]

    torch.set_num_threads(4)
    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    settings = read_json(args.reader_config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    histories = read_json(args.sources / "sources.json")["histories"][:args.roots]
    if not histories or any(history["split"] != "train" for history in histories):
        raise ValueError("Full-menu structural probe uses explicitly assigned TRAIN roots only")
    controls = {row["source_group"]: row for row in read_jsonl(args.controls)}
    captured_path = getattr(args, "captured_states", None)
    captured_manifest = read_json(captured_path) if captured_path else None
    encoder = None if captured_manifest is not None else SmallControlModel(
        SmallControlConfig("frozen_mlp", str(args.backbone.resolve())), device=args.device)
    if encoder is not None:
        encoder.train(False)
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "sources": str(args.sources), "collection": str(args.collection),
        "config": str(args.reader_config), "roots": len(histories), "closed_roots": 0,
        "device": args.device, "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "Reader_calls": 0, "sha_validation": False, "horizons": [0, 2],
        "captured_states": str(captured_path) if captured_path else None,
        "execution_contract": "stable_material_indices_search_scope_sync_v2",
        "scope": ("Actual complete legal menus from literal captured decisions. "
                  if captured_manifest is not None else
                  "Actual complete legal menus and matched K/O prefixes. ")
                 + "Native reference structural warm-start only. No Reader utility "
                   "or source-success claim."}
    write_json(args.output / "run.json", run)
    datasets: dict[int, list[dict[str, Any]]] = {0: [], 2: []}
    states, comparisons = [], []
    try:
        for history in histories:
            original = args.collection / "banks" / history["id"]
            bank = args.output / "banks" / history["id"]
            copy_source_bank(original / "memory.sqlite", bank)
            mapping = read_json(original / "source-map.json")
            write_json(bank / "source-map.json", mapping)
            with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                store.setup()
                store.conn.execute("PRAGMA query_only=ON")
                changes_before = store.conn.total_changes
                def service(*, owned_store: Any = store, identity: str = history["id"],
                            lock: Path = bank / "lock") -> MemoryService:
                    return MemoryService(owned_store, ("small-control-native", identity, "author"),
                        "author", lock, functional_contract="functional_v1")

                request = history["requests"][0]
                state, operations = environment(service(), request, capacity, args.material_tokens)
                state.budget.update(remaining_control_steps=8, reader_capacity_reserved=True)
                cold, cold_checkpoint = copy.deepcopy(state.project()), operations.checkpoint()
                selected: dict[str, dict[str, Any]] = (captured_prefix_states(
                    captured_manifest, history["id"] + "/" + request["id"])
                    if captured_manifest is not None else {})
                prefix_traces = {}
                for mode in (() if captured_manifest is not None else ("K", "O")):
                    assert encoder is not None
                    local = MemoryControlState(**copy.deepcopy(cold))
                    local, executor = environment(service(), request, capacity,
                        args.material_tokens, state=local, checkpoint=cold_checkpoint)
                    captured: dict[int, dict[str, Any]] = {}
                    def capture(event: dict[str, Any], *,
                                target: dict[int, dict[str, Any]] = captured,
                                owned_executor: Any = executor) -> None:
                        if event.get("phase") == "decision_input" and event["step"] in {0, 1, 3}:
                            target[event["step"]] = {"decision": copy.deepcopy(event),
                                "executor_checkpoint": owned_executor.checkpoint()}

                    trace = run_memory_control(local,
                        PrefixPolicy(encoder, observe_only=mode == "O"), executor,
                        max_steps=8, record=capture)
                    prefix_traces[mode] = trace
                    if 3 not in captured or len(captured[3]["decision"]["before"][
                            "observed_materials"]) != 2:
                        raise ValueError(
                            "Matched prefix did not acquire exactly two legal originals")
                    if mode == "K":
                        selected.update(initial=captured[0], search=captured[1], K=captured[3])
                    else:
                        selected["O"] = captured[3]
                if (captured_manifest is None
                        and selected["K"]["executor_checkpoint"]["observed"]
                        != selected["O"]["executor_checkpoint"]["observed"]):
                    raise ValueError("K/O prefixes acquired different actual material")
                write_json(bank / "prefix-trajectories.json", prefix_traces)
                write_json(bank / "states.json", selected)
                required = controls[history["source_group"]]["reference_support_spans"]
                for name, saved in selected.items():
                    event = saved["decision"]
                    before, menu = event["before"], event["actions"]
                    local = MemoryControlState(**copy.deepcopy(before))
                    local, baseline = environment(service(), request, capacity,
                        args.material_tokens, state=local, checkpoint=saved["executor_checkpoint"])
                    _, acquired_ranges = material_packet(baseline.service,
                        list(baseline.observed.values()), list(baseline.observed), mapping)
                    acquired_before = reference_coverage(required, acquired_ranges)
                    identity = history["id"] + "/" + request["id"] + "/" + name
                    states.append({"event_id": identity, "source_group": history["source_group"],
                        "state_type": name, "before": before, "actions": menu})
                    for horizon in [0, 2]:
                        outcomes = []
                        for action in menu:
                            local = MemoryControlState(**copy.deepcopy(before))
                            local, branch = environment(service(), request, capacity,
                                args.material_tokens, state=local,
                                checkpoint=saved["executor_checkpoint"])
                            if ([asdict(a) for a in branch.actions(local)] != menu
                                    or local.project() != before):
                                raise ValueError("Structural branch changed the actual before/menu")
                            result = execute_branch(branch, before, MemoryAction(**action),
                                event["step"], horizon, terminal_handoff="current",
                                policy_name="query_once_context")
                            packet, delivered = actual_packet(branch, mapping)
                            _, observed_ranges = material_packet(branch.service,
                                list(branch.observed.values()), list(branch.observed), mapping)
                            steps = []
                            for step in result["trace"]:
                                chosen = next(a for a in step["actions"]
                                              if a["id"] == step["selected"])
                                steps.append({"step": step["step"], "action": chosen,
                                    "selection_mode": step["selection_mode"],
                                    "result": step.get("result")})
                            outcomes.append({"action": action, "reason": result["reason"],
                                "delivered_coverage": reference_coverage(required, delivered),
                                "acquired_coverage": reference_coverage(required, observed_ranges),
                                "nonterminal_operations": sum(s["action"]["kind"] != "HANDOFF"
                                                              for s in steps),
                                "actual_delivered_source_ranges": delivered, "packet": packet,
                                "steps": steps})
                        supervision = structural_supervision(menu, outcomes, acquired_before)
                        datasets[horizon].append({"sample_id": identity + f"/h{horizon}",
                            "group_id": history["source_group"], "split": "train",
                            "observation": before, "actions": menu,
                            "offline_supervision": supervision, "provenance": {
                                "state_type": name, "horizon": horizon,
                                "label_scope": "actual_native_span_progress_not_Reader_utility"}})
                        comparisons.append({"event_id": identity, "horizon": horizon,
                            "acquired_before": acquired_before, "outcomes": outcomes})
                if store.conn.total_changes != changes_before:
                    raise ValueError("Read-only branch altered its source database")
            run["closed_roots"] += 1
            for horizon, rows in datasets.items():
                with (args.output / f"train-h{horizon}.jsonl").open("w") as stream:
                    for row in rows:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            write_json(args.output / "states.json", states)
            write_json(args.output / "outcomes.json", comparisons)
            write_json(args.output / "run.json", run)
            print(json.dumps({"closed_roots": run["closed_roots"], "states": len(states)}),
                  flush=True)
        run.update(status="COMPLETED", states=len(states),
            branches=sum(len(case["outcomes"]) for case in comparisons), SQL_changes=0)
    except Exception as error:
        run.update(status="FAILED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        run.update(wall_seconds=time.perf_counter()-tick, cpu_seconds=time.process_time()-cpu,
            encoder_counters=encoder.counters if encoder is not None else {},
            compute_ledger_status="pending_idle_settlement")
        write_json(args.output / "run.json", run)

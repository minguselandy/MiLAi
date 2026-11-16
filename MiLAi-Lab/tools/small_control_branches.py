"""Collect current-policy interventions using original real states and independent SQLite copies."""
from __future__ import annotations

import copy
import json
import math
import os
import random
import sqlite3
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from collect_qasper_operation_states import resolve_source_bank
from collected_handoff import replay_collected_prefix
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    MemoryAction,
)
from milai_lab.methods.small_control_model import SmallControlModel
from milai_lab.providers.contextual_capacity import HostCapacity
from prepare_collected_operation_feedback import execute_branch


def copy_source_bank(source: Path, destination: Path) -> None:
    """SQLite backup reads the source without creating/updating the original bank."""
    destination.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(destination / "memory.sqlite") as copied:
            original.backup(copied)


def select_pool(rows: list[dict[str, Any]], count: int, random_fraction: float,
                 seed: int) -> list[dict[str, Any]]:
    if not rows or any(row["split"] != "train" for row in rows):
        raise ValueError("Branch production requires declared TRAIN sources")
    rng = random.Random(seed)  # noqa: S311 -- source-balanced declared sampling
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["group_id"]].append(row)
    if count > len(groups) or not .30 <= random_fraction <= 1:
        raise ValueError("Use distinct sources and at least30percent random sampling")
    names = sorted(groups)
    rng.shuffle(names)
    random_count = math.ceil(count * random_fraction)
    random_groups = names[:random_count]
    selected = [{"row": rng.choice(groups[group]), "sampling": "random_source_then_state"}
                for group in random_groups]
    remaining = [name for name in names if name not in random_groups]
    # Observable K/O opportunity only; no feedback outcome or native proof used.
    priority = {name: [row for row in groups[name]
        if row["observation"].get("observed_materials")
        and sum(a["kind"] == "HANDOFF" for a in row["actions"]) > 1]
        for name in remaining}
    for group in remaining:
        if priority[group] and len(selected) < count:
            selected.append({"row": rng.choice(priority[group]), "sampling": "post_acquisition_KO"})
    if len(selected) != count:
        raise ValueError("Insufficient actual post-acquisition sources; do not invent states")
    return selected


class CaptureIndex:
    def __init__(self) -> None:
        self.legacy: dict[Path, dict[str, Any]] = {}
        self.preparations: dict[Path, dict[str, Any]] = {}
        self.histories: dict[Path, dict[str, Any]] = {}

    def locate(self, row: dict[str, Any]) -> dict[str, Any]:
        path = Path(row["provenance"]["legacy_path"])
        if path not in self.legacy:
            self.legacy[path] = {r["metadata"]["event_id"]: r for r in read_jsonl(path)}
        legacy = self.legacy[path][row["sample_id"]]
        references = [Path(p) for pair in legacy["feedback"]["comparisons"]
                      for p in pair.get("actual_readouts", [])]
        if not references:
            raise ValueError("No actual branch capture reference for this state")
        prepared = Path(read_json(references[0].parents[2] / "run.json")["prepared"])
        if prepared not in self.preparations:
            self.preparations[prepared] = {
                "run": read_json(prepared / "run.json"),
                "cases": {c["event_id"]: c for c in read_json(prepared / "cases.json")}}
        info = self.preparations[prepared]
        case = info["cases"][row["sample_id"]]
        if case["before"] != row["observation"] or case["actions"] != row["actions"]:
            raise ValueError("Saved neutral input differs from actual before/menu")
        collection = Path(info["run"]["collection"])
        if collection not in self.histories:
            self.histories[collection] = {h["source_group"]: h for h in read_json(
                collection / "sources.json")["histories"]}
        history = self.histories[collection][case["family"]]
        if history["split"] != "train":
            raise ValueError("Actual source bank is outside TRAIN")
        return {"collection": collection, "history": history, "case": case,
                "prepared": prepared, "bank": resolve_source_bank(
                    collection / "banks" / history["id"])}


def collect(args: Any) -> None:
    import torch  # type: ignore[import-not-found]

    torch.set_num_threads(4)
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    settings = read_json(args.reader_config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    selected = select_pool(read_jsonl(args.pool), args.states, args.random_fraction, args.seed)
    write_json(args.output / "selected-states.json", selected)
    model = SmallControlModel.load(args.checkpoint, device=args.device)
    rng = random.Random(args.seed)  # noqa: S311
    index = CaptureIndex()
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "checkpoint": str(args.checkpoint.resolve()), "pool": str(args.pool.resolve()),
        "config": str(args.reader_config.resolve()), "planned_states": len(selected),
        "closed_states": 0, "branches": 0, "Reader_calls": 0, "sha_validation": False,
        "horizons": args.horizons, "continuation_policy": "query_once_context(reads=4)",
        "terminal_handoff": "current", "automatic_retry": False,
        "random_source_states": sum(s["sampling"].startswith("random") for s in selected),
        "scope": "New real TRAIN interventions at historical states; not fresh-source confirmation"}
    write_json(args.output / "run.json", run)
    cases, decisions = [], []
    try:
        for ordinal, entry in enumerate(selected):
            row = entry["row"]
            location = index.locate(row)
            old = location["case"]
            state_root = args.output / f"state-{ordinal:03d}"
            state_root.mkdir(exist_ok=False)
            original = location["bank"] / "memory.sqlite"
            before_bank = state_root / "before"
            copy_source_bank(original, before_bank)
            with replay_collected_prefix(location["collection"], location["history"], old,
                    settings, capacity, target_step=old["step"],
                    bank_override=before_bank) as (operations, state):
                actions = [MemoryAction(**a) for a in old["actions"]]
                scores = model.score({"observation": state.project(),
                                      "actions": [asdict(a) for a in actions]})
                choice = scores.action_ids[max(range(len(scores.scores)),
                                               key=scores.scores.__getitem__)]
                fixed = FixedContextMemoryPolicy(reads=4).choose(state, actions)
                stop = next(a.id for a in actions if a.kind == "HANDOFF" and not a.parameters)
                nominations = [("immediate_stop", stop), ("fixed_context", fixed),
                               ("current_model", choice)]
                nominated_ids = {key for _, key in nominations}
                alternatives = [a for a in actions if a.id not in nominated_ids]
                if alternatives:
                    nominations.append(("random_alternative", rng.choice(alternatives).id))
                unique: list[MemoryAction] = []
                methods: dict[str, list[str]] = {}
                for name, key in nominations:
                    action = next(a for a in actions if a.id == key)
                    prior = next((a for a in unique if (a.kind, a.target, a.parameters) == (
                        action.kind, action.target, action.parameters)), None)
                    if prior is None:
                        unique.append(action)
                        methods[action.id] = []
                        prior = action
                    methods[prior.id].append(name)
                decision = {"sample_id": row["sample_id"], "group_id": row["group_id"],
                    "sampling": entry["sampling"], "before": state.project(),
                    "actions": [asdict(a) for a in actions], "selected": choice,
                    "model_scores": asdict(scores), "nominations": nominations,
                    "selected_was_old_observed": choice in row[
                        "offline_supervision"]["observed_action_ids"],
                    "original_bank": str(original), "copied_before_bank": str(before_bank)}
                decisions.append(decision)
                write_json(state_root / "decision.json", decision)
            for horizon in args.horizons:
                case: dict[str, Any] = {"family": row["group_id"],
                    "event_id": row["sample_id"] + f"/h{horizon}",
                    "case_key": row["sample_id"] + f"/h{horizon}",
                    "original_event_id": row["sample_id"], "horizon": horizon,
                    "request_id": old["request_id"], "state_index": ordinal,
                    "before": old["before"], "actions": old["actions"],
                    "choices": {method: action.id for action in unique
                                for method in methods[action.id]}, "branches": []}
                for branch_index, action in enumerate(unique):
                    branch_root = state_root / f"h{horizon}-branch-{branch_index}"
                    copy_source_bank(before_bank / "memory.sqlite", branch_root)
                    with replay_collected_prefix(location["collection"], location["history"], old,
                            settings, capacity, target_step=old["step"],
                            bank_override=branch_root) as (operations, _):
                        result = execute_branch(operations, old["before"], action, old["step"],
                            horizon, terminal_handoff="current", policy_name="query_once_context")
                        packet = controlled_reader_packet(operations.reader_evidence(),
                                                          "collection")
                        wire = copy.deepcopy(old["branches"][0]["readout_request"])
                        expected = {"model": settings["host"]["model"],
                            "temperature": settings["host"]["temperature"],
                            "max_tokens": settings["host"]["max_tokens"],
                            "chat_template_kwargs": {"enable_thinking": capacity.enable_thinking}}
                        if {key: wire[key] for key in expected} != expected:
                            raise ValueError("Conditional Reader frame uses a different config")
                        payload = json.loads(wire["messages"][1]["content"])
                        payload["memory"] = packet
                        wire["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False)
                        capacity.check(wire["messages"])
                        last = result["trace"][-1]
                        ok = result["reason"] != "operation_outcome_unknown" and last.get(
                            "result", {"ok": True}).get("ok", True)
                        case["branches"].append({"action": asdict(action),
                            "policies": methods[action.id], "continuation": result,
                            "execution_result": {"ok": ok, "status": result["reason"]},
                            "packet": packet, "body_tokens": capacity.text_tokens(json.dumps(
                                packet, ensure_ascii=False)), "readout_request": wire,
                            "source_bank": str(branch_root)})
                cases.append(case)
                write_json(args.output / "cases.json", cases)
            run.update(closed_states=ordinal + 1,
                       branches=sum(len(c["branches"]) for c in cases))
            write_json(args.output / "run.json", run)
            print(json.dumps({"closed_states": ordinal + 1, "branches": run["branches"]}),
                  flush=True)
        run["status"] = "COMPLETED"
    except Exception as error:
        run.update(status="FAILED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        run.update(cpu_seconds=time.process_time() - cpu,
                   wall_seconds=time.perf_counter() - started, model_counters=model.counters,
                   compute_ledger_status="pending_idle_settlement")
        write_json(args.output / "run.json", run)
        write_json(args.output / "cases.json", cases)
        write_json(args.output / "decisions.json", decisions)

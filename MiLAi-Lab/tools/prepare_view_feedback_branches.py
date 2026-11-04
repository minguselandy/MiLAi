"""Select a bounded source-balanced cohort of real calls for existing E2 replay."""
from __future__ import annotations

import argparse
import copy
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from feedback_choices import baseline_choice, captured_decisions, decision_actions, saved_decisions
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control_learning import decision_example

PREFIX_SLOTS = ("initial", "first_read", "second_read",
                "same_known_changed_requirement_or_return_limit")


def call_stratum(call: dict[str, Any]) -> tuple[bool, bool, bool, bool]:
    before = call["initial_observation"]
    return (
        bool(before["views"]),
        bool(before["task"].get("known_evidence")),
        "original_source" in call["request"].get("read_goal", {}).get("evidence", []),
        bool(call["public_message"].get("incoming_sources")),
    )


def branch_actions(call: dict[str, Any]) -> list[dict[str, Any]]:
    """Sample operation opportunities, not semantic outcomes or purported optimal actions."""
    by_kind: dict[str, dict[str, Any]] = {}
    for action in call["initial_actions"]:
        if not action["parameters"].get("observe_only"):
            by_kind.setdefault(action["kind"], action)
    view, _, originals, arrivals = call_stratum(call)
    if view:
        alternate = "READ" if originals else "REFRESH_VIEW" if arrivals else "SEARCH"
        preferred = ["HANDOFF", "USE_VIEW", alternate]
    else:
        preferred = ["HANDOFF", "SEARCH", "REFRESH_VIEW"]
    kinds = list(dict.fromkeys([*preferred, "READ", "USE_VIEW", "SEARCH", "REFRESH_VIEW"]))
    selected = [copy.deepcopy(by_kind[kind]) for kind in kinds if kind in by_kind][:3]
    if len(selected) < 2:
        used = {action["id"] for action in selected}
        selected.extend(copy.deepcopy(action) for action in call["initial_actions"]
                        if action["id"] not in used)
    return selected[:3]


def nominated_actions(call: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    """Allow different real bindings of the same operation in a reviewed branch proposal."""
    actual = {action["id"]: action for action in call["initial_actions"]}
    if not 2 <= len(ids) <= 3 or len(ids) != len(set(ids)) or any(i not in actual for i in ids):
        raise ValueError("Nominate two or three different captured action IDs")
    return [copy.deepcopy(actual[i]) for i in ids]


def parameter_actions(call: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    """Sample actual alternatives of one kind, retaining plain HANDOFF when offered."""
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for action in call["initial_actions"]:
        alternatives = by_kind[action["kind"]]
        if not any((a["target"], a["parameters"]) == (action["target"], action["parameters"])
                   for a in alternatives):
            alternatives.append(action)
    eligible = sorted(kind for kind, actions in by_kind.items() if len(actions) >= 2)
    if not eligible:
        return branch_actions(call)
    selected = rng.sample(by_kind[rng.choice(eligible)], 2)
    stop = [a for a in call["initial_actions"] if a["kind"] == "HANDOFF" and not a["parameters"]]
    for action in [*stop, *branch_actions(call)]:
        if action not in selected:
            selected.append(action)
        if len(selected) == 3:
            break
    return copy.deepcopy(selected)


def select_states(
    entries: list[dict[str, Any]], groups: list[str], per_group: int, seed: int,
    include: list[str], *, exact: bool = False,
) -> list[dict[str, Any]]:
    """Retain explicit diagnostic nominations, then diversify observable call contexts."""
    rng = random.Random(seed)  # noqa: S311 -- declared offline sampling
    available = {entry["capture"]: entry for entry in entries}
    if any(key not in available for key in include):
        raise ValueError("A nominated capture is not an eligible real state")
    if any(available[key]["family"] not in groups for key in include):
        raise ValueError("A nominated capture is outside the declared source groups")
    selected = []
    for group in groups:
        nominated = [available[key] for key in dict.fromkeys(include)
                     if available[key]["family"] == group]
        if len(nominated) > per_group:
            raise ValueError("Nominations exceed the declared per-source state budget")
        if exact:
            selected.extend(nominated)
            continue
        used = {entry["capture"] for entry in nominated}
        buckets: dict[tuple[bool, ...], list[dict[str, Any]]] = defaultdict(list)
        for entry in entries:
            if entry["family"] == group and entry["capture"] not in used:
                buckets[tuple(entry["stratum"])].append(entry)
        for values in buckets.values():
            rng.shuffle(values)
        order = sorted(buckets)
        rng.shuffle(order)
        chosen = list(nominated)
        while len(chosen) < per_group and any(buckets.values()):
            for key in order:
                if buckets[key] and len(chosen) < per_group:
                    chosen.append(buckets[key].pop())
        selected.extend(chosen)
    return selected


def state_phase(entry: dict[str, Any]) -> str:
    return "after_operation" if entry["control_step"] else "initial"


def select_quota_states(
    entries: list[dict[str, Any]], groups: list[str], quotas: dict[str, dict[str, int]],
    seed: int, include: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fixed collector/phase cells; missing reached states never borrow another cell's quota."""
    available = {entry["capture"]: entry for entry in entries}
    for capture in include:
        entry = available[capture]
        if (entry["family"] not in groups
                or state_phase(entry) not in quotas.get(entry["collection_policy"], {})):
            raise ValueError("A nomination is outside the declared collector/phase quota")
    selected, cells = [], []
    for collector, phases in quotas.items():
        for phase, count in phases.items():
            if phase not in {"initial", "after_operation"} or count < 0:
                raise ValueError("State quotas need a known phase and nonnegative count")
            pool = [entry for entry in entries if entry["collection_policy"] == collector
                    and state_phase(entry) == phase]
            captures = {entry["capture"] for entry in pool}
            chosen = select_states(pool, groups, count, seed,
                                   [key for key in include if key in captures])
            selected.extend(chosen)
            for group in groups:
                eligible = sum(entry["family"] == group for entry in pool)
                retained = sum(entry["family"] == group for entry in chosen)
                cells.append({"family": group, "collection_policy": collector, "phase": phase,
                    "quota": count, "eligible": eligible, "selected": retained,
                    "shortfall": count - retained})
    return selected, cells


def select_prefix_states(
    inventory: list[dict[str, Any]], report: dict[str, Any], groups: list[str], split: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Use exact reached prefixes, preserving missing and non-branchable cells separately."""
    if report["status"] != "PRIMARY_PREFIX_INVENTORY_CREATED;NO_BRANCH_QUALITY_LABELS":
        raise ValueError("Prefix branches require the actual primary-prefix inventory")
    if [r["family"] for r in report["records"]] != groups:
        raise ValueError("Each declared family must appear once, in the fixed prefix order")
    available = {str(Path(e["path"]).resolve()): e for e in inventory}
    selected: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    used: set[str] = set()
    for record in report["records"]:
        selection = record["selection"]
        slots = (selection["slots"] if selection is not None
                 else dict.fromkeys(PREFIX_SLOTS))
        if set(slots) != set(PREFIX_SLOTS):
            raise ValueError("Prefix inventory must retain all four declared slots")
        for name in PREFIX_SLOTS:
            slot = slots[name]
            cell = {"family": record["family"], "collection_policy": record["collector"],
                    "prefix_slot": name,
                    "primary_public_position": record["primary_public_position"],
                    "public_position": copy.deepcopy(record["public_position"])}
            if slot is None:
                cells.append({**cell, "status": "MISSING_PREFIX", "path": None,
                    "prefix_selection_status": (record["status"] if selection is None
                                                else selection["status"])})
                continue
            path = str(Path(slot["capture"]).resolve())
            if path not in available:
                raise ValueError("Selected prefix has no actual capture in this collection")
            entry = available[path]
            if (entry["family"] != record["family"] or entry["split"] != split
                    or entry["collection_policy"] != record["collector"]
                    or entry["message_id"] != record["primary_public_position"]
                    or entry["control_step"] != slot["control_step"]
                    or Path(entry["run"]).resolve() != Path(report["collection"]).resolve()):
                raise ValueError("Prefix identity differs from the actual source/call/step")
            if path in used:
                raise ValueError("One actual state cannot occupy multiple prefix slots")
            used.add(path)
            if not entry["eligible"]:
                cells.append({**cell, "status": "REACHED_NOT_BRANCHABLE", "path": path,
                              "reason": entry["reason"]})
                continue
            selected.append({**copy.deepcopy(entry), "prefix_slot": name,
                             "primary_public_position": record["primary_public_position"]})
            cells.append({**cell, "status": "SELECTED_FOR_BRANCHES", "path": path,
                          "capture": entry["capture"]})
    return selected, cells


def fresh_inventory(allocation: dict[str, Any], split: str) -> list[dict[str, Any]]:
    """Index only the exact fresh initial captures admitted to reserved cells."""
    entries = []
    for record in allocation["records"]:
        for slot in record["slots"]:
            if slot["origin"] != "fresh_request" or slot["capture"] is None:
                continue
            call = read_json(Path(slot["capture"]) / "call.json")
            eligible = len(branch_actions(call)) >= 2
            entries.append({"capture": f"fresh--{record['family']}--{slot['arm']}",
                "path": slot["capture"], "family": record["family"], "split": split,
                "run": slot["run"], "source_version": call["source_version"],
                "message_id": call["public_message"]["message_id"], "control_step": 0,
                "original_status": call["status"], "eligible": eligible,
                "reason": None if eligible else "fewer_than_two_actual_action_branches",
                "collection_policy": record["collector"], "state_origin": "fresh_request",
                "stratum": (*call_stratum(call), False,
                            bool(call["initial_observation"]["visible_evidence"]))})
    return entries


def select_allocated_states(
    inventory: list[dict[str, Any]], allocation: dict[str, Any], groups: list[str], split: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Four fixed positions, including missing fresh arms; no original READ2 refill."""
    if allocation["status"] != "FOUR_SLOT_ALLOCATION_RESOLVED_NO_QUALITY_LABELS":
        raise ValueError("Branch preparation requires a resolved pre-execution allocation")
    if [r["family"] for r in allocation["records"]] != groups:
        raise ValueError("Allocated families must preserve the declared collection order")
    available = {str(Path(e["path"]).resolve()): e for e in inventory}
    selected, cells = [], []
    used: set[str] = set()
    for record in allocation["records"]:
        if [s["slot"] for s in record["slots"]] != [1, 2, 3, 4]:
            raise ValueError("Every family must retain exactly four allocated positions")
        for slot in record["slots"]:
            cell = {"family": record["family"], "collection_policy": record["collector"],
                "prefix_slot": slot["role"], "slot": slot["slot"],
                "state_origin": slot["origin"], "allocation_status": slot["status"],
                "path": slot["capture"]}
            if slot["capture"] is None:
                cells.append({**cell, "status": "MISSING_PREFIX"})
                continue
            path = str(Path(slot["capture"]).resolve())
            entry = available[path]
            if (entry["family"] != record["family"] or entry["split"] != split
                    or entry["collection_policy"] != record["collector"]
                    or entry["control_step"] != slot["control_step"] or path in used):
                raise ValueError("Allocated state identity changed or occupies multiple slots")
            used.add(path)
            if not entry["eligible"]:
                cells.append({**cell, "status": "REACHED_NOT_BRANCHABLE",
                              "reason": entry["reason"]})
                continue
            selected.append({**copy.deepcopy(entry), "prefix_slot": slot["role"],
                "state_origin": slot["origin"], "allocated_slot": slot["slot"],
                "primary_public_position": record["source_record"]["primary_public_position"]})
            cells.append({**cell, "status": "SELECTED_FOR_BRANCHES", "capture": entry["capture"]})
    return selected, cells


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--groups", nargs="+", required=True)
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--exact-nominations", action="store_true",
                        help="Export only nominated actual states; do not fill missing slots")
    parser.add_argument("--bindings", type=Path,
                        help="JSON capture -> {actions: [actual IDs], reason: ...}; "
                             "explicit source-based branch proposals, not outcome labels")
    parser.add_argument("--per-group", type=int, default=6)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--split", choices=("train", "dev"), default="train")
    parser.add_argument("--include-control-steps", action="store_true",
                        help="Include captured post-operation decisions as branch starting states")
    parser.add_argument("--state-quotas", type=Path,
                        help="JSON collector policy -> {initial: n, after_operation: n}; "
                             "explicit per-source quotas replace pooled --per-group selection")
    parser.add_argument("--prefix-selection", type=Path,
                        help="Exact primary-prefix selection.json for one collection; "
                             "replaces pooled/phase quotas, with no missing-slot fill")
    parser.add_argument("--prefix-allocation", type=Path,
                        help="Resolved four-slot allocation with explicit fresh request arms")
    parser.add_argument("--branch-sampling", choices=(
        "operations", "post-operation-bindings", "current-decision"),
                        default="operations",
                        help="Optional seeded binding alternatives on actual post-operation states")
    scores = parser.add_mutually_exclusive_group()
    scores.add_argument("--decision-evaluation", type=Path,
                        help="Closed saved-model evaluator output over the actual full-menu inputs")
    scores.add_argument("--decision-collection", type=Path,
                        help="Reuse complete logits and actual selections from a closed collection")
    parser.add_argument("--decision-baseline", choices=(
                            "raw_context", "raw_delivery", "fixed_prefix", "rules"),
                        default="raw_context")
    parser.add_argument("--decision-baseline-reads", type=int, default=4)
    parser.add_argument("--continuation-steps", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.exact_nominations and args.state_quotas is not None:
        parser.error("Exact nominations and phase quotas are alternative state protocols")
    current_decision = args.branch_sampling == "current-decision"
    if current_decision != (args.decision_evaluation is not None
                            or args.decision_collection is not None):
        parser.error("Current-decision sampling requires its saved evaluation or scored collection")
    if current_decision and (args.prefix_selection is not None
                             or args.prefix_allocation is not None):
        parser.error("Current-decision is a separate protocol, not a replacement prefix experiment")
    if args.prefix_selection is not None and args.prefix_allocation is not None:
        parser.error("Choose original prefix selection or explicit fresh-slot allocation")
    exact_path = args.prefix_selection or args.prefix_allocation
    if exact_path is not None and (
            not args.include_control_steps or args.state_quotas is not None
            or args.include or args.bindings is not None):
        parser.error("Prefix selection needs control steps and excludes quotas/manual nominations")
    started, cpu = time.perf_counter(), time.process_time()
    decision_run: dict[str, Any] = {}
    decisions: dict[str, dict[str, Any]] = {}
    if args.decision_collection is not None:
        decision_run, decisions = captured_decisions(args.decision_collection)
    elif args.decision_evaluation is not None:
        decision_run, decisions = saved_decisions(args.decision_evaluation)
    prefix = read_json(args.prefix_selection) if args.prefix_selection is not None else None
    allocation = read_json(args.prefix_allocation) if args.prefix_allocation is not None else None
    exact = prefix or allocation
    if exact is not None and (len(args.runs) != 1 or args.runs[0].resolve() != Path(
            exact["collection"]).resolve()):
        parser.error("Prefix selection binds one declared actual collection")
    if allocation is not None:
        from allocate_known_budget_prefixes import resolve_record

        fixed = read_json(Path(allocation["input"]))
        if fixed["status"] != "FOUR_SLOT_ALLOCATION_FIXED_BEFORE_FRESH_EXECUTION":
            raise ValueError("Fresh branch slots need their original pre-execution allocation")
        for prior, actual in zip(fixed["records"], allocation["records"], strict=True):
            outputs = {s["arm"]: Path(s["run"]) for s in actual["slots"]
                       if s["origin"] == "fresh_request"}
            if resolve_record(prior, outputs) != actual:
                raise ValueError("Resolved allocation no longer matches the actual fresh attempts")
    entries, inventory, calls = [], [], {}
    collectors: dict[str, str] = {}
    for root in args.runs:
        driver = read_json(root / "driver.json")
        if driver["status"] == "RUNNING":
            raise ValueError("Finish the source run before freezing a branch cohort")
        banks = {}
        for history in read_json(root / "fixture.json")["histories"]:
            for request in history["requests"]:
                bank = (history["id"] if history.get("continuous")
                        and not request.get("independent") else
                        history["id"] + "-" + request["id"])
                banks[bank] = history
        call_root = root / "frozen-retrieval-calls"
        pattern = "**/call.json" if args.include_control_steps else "*/call.json"
        for path in sorted(call_root.glob(pattern)):
            call = read_json(path)
            capture = "--".join(path.parent.relative_to(call_root).parts)
            if capture in calls:
                raise ValueError("A real capture was included twice")
            calls[capture] = call
            history = banks[call["bank"]]
            entry = {"capture": capture, "path": str(path.parent.resolve()),
                     "family": history["source_group"], "split": history["split"],
                     "run": str(root), "source_version": driver["source_version"],
                     "message_id": call["public_message"]["message_id"],
                     "control_step": call.get("control_step", 0),
                     "original_status": call["status"], "eligible": False}
            if args.state_quotas is not None or exact is not None:
                source_root = call["source_root"]
                if source_root not in collectors:
                    collectors[source_root] = read_json(Path(source_root) / "input-freeze.json")[
                        "config"]["memory_control"]["policy"]
                entry["collection_policy"] = collectors[source_root]
            if call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}:
                entry["reason"] = "original_call_not_closed"
            elif not call["initial_actions"] or call["initial_observation"] is None:
                entry["reason"] = "no_actual_decision"
            elif history["split"] != args.split or history["source_group"] not in args.groups:
                entry["reason"] = "outside_declared_source_groups_or_split"
            elif current_decision and str(path.parent.resolve()) not in decisions:
                entry["reason"] = "full_menu_prediction_missing"
            elif not current_decision and len(branch_actions(call)) < 2:
                entry["reason"] = "fewer_than_two_actual_action_branches"
            else:
                stratum: tuple[bool, ...] = call_stratum(call)
                if args.include_control_steps:
                    stratum = (*stratum, bool(entry["control_step"]),
                               bool(call["initial_observation"]["visible_evidence"]))
                entry.update(eligible=True, stratum=stratum)
                entries.append(entry)
            inventory.append(entry)
    if allocation is not None:
        for entry in fresh_inventory(allocation, args.split):
            if entry["capture"] in calls:
                raise ValueError("Fresh capture name collides with an original capture")
            calls[entry["capture"]] = read_json(Path(entry["path"]) / "call.json")
            inventory.append(entry)
    bindings = read_json(args.bindings) if args.bindings is not None else {}
    include = list(dict.fromkeys([*args.include, *bindings]))
    quotas = read_json(args.state_quotas) if args.state_quotas is not None else None
    quota_cells = None
    prefix_cells = None
    if allocation is not None:
        selected, prefix_cells = select_allocated_states(
            inventory, allocation, args.groups, args.split)
    elif prefix is not None:
        selected, prefix_cells = select_prefix_states(inventory, prefix, args.groups, args.split)
    elif quotas is None:
        selected = select_states(entries, args.groups, args.per_group, args.seed, include,
                                 exact=args.exact_nominations)
    else:
        if not args.include_control_steps and any(
                phases.get("after_operation", 0) for phases in quotas.values()):
            parser.error("After-operation quotas require --include-control-steps")
        selected, quota_cells = select_quota_states(
            entries, args.groups, quotas, args.seed, include)
    args.output.mkdir(parents=True, exist_ok=False)
    captures = args.output / "captures"
    captures.mkdir()
    # Keep closed unselected calls in the replay cohort; selection never makes them negatives.
    for entry in inventory:
        if entry["original_status"] in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}:
            (captures / entry["capture"]).symlink_to(entry["path"], target_is_directory=True)
    controlled_frames = {}
    if allocation is not None:
        from prepare_known_budget_readout import prepare_controlled_readout

        preparations = {r["family"]: r["preparation"] for r in allocation["records"]}
        for entry in selected:
            if entry["state_origin"] == "fresh_request":
                frame = prepare_controlled_readout(
                    preparations[entry["family"]], Path(entry["path"]))
                path = args.output / "controlled-readout-frames" / (entry["capture"] + ".json")
                write_json(path, frame)
                controlled_frames[entry["capture"]] = str(path.resolve())
    policies = []
    decision_nominations = []
    binding_rng = random.Random(args.seed)  # noqa: S311 -- explicit data acquisition seed
    for index, entry in enumerate(selected):
        capture = entry["capture"]
        if current_decision:
            decision = decisions[str(Path(entry["path"]).resolve())]
            baseline = baseline_choice(calls[capture], args.decision_baseline,
                                       args.decision_baseline_reads)
            actions = decision_actions(calls[capture], decision["prediction"]["logits"], baseline,
                                       bindings[capture]["actions"] if capture in bindings else [])
            decision_nominations.append({"capture": capture,
                "argmax": decision["prediction"]["choice"], "baseline": baseline,
                "evaluation_index": decision["evaluation_index"], "actions": actions,
                **({"prediction_location": decision["prediction_location"]}
                   if "prediction_location" in decision else {}),
                "distinct_bindings": len(actions), "has_comparison": len(actions) > 1})
        elif capture in bindings:
            actions = nominated_actions(calls[capture], bindings[capture]["actions"])
        elif args.branch_sampling == "post-operation-bindings" and entry["control_step"]:
            actions = parameter_actions(calls[capture], binding_rng)
        else:
            actions = branch_actions(calls[capture])
        for branch_index, action in enumerate(actions):
            policies.append({
                "name": f"state-{index:03d}-branch-{branch_index:02d}",
                "capture": capture,
                "policy": {"policy": "fixed_context", "reads": 4},
                "intervention": {"first_action": action,
                                 "continuation_steps": args.continuation_steps},
                **({"host_readout_frame": controlled_frames[capture]}
                   if capture in controlled_frames else {}),
            })
    write_json(args.output / "policies.json", policies)
    with (args.output / "raw-selected-states.jsonl").open("w", encoding="utf-8") as stream:
        for index, entry in enumerate(selected):
            call = calls[entry["capture"]]
            metadata = {**entry, "row": index, "state_id": index, "task": "memory_operation",
                "event_id": f"{entry['run']}/{entry['capture']}/step-{entry['control_step']}",
                "training_event": f"{call['source_root']}/{call['bank']}/{entry['message_id']}"}
            row = decision_example({"before": call["initial_observation"],
                                    "actions": call["initial_actions"]}, metadata)
            if current_decision:
                scored = decisions[str(Path(entry["path"]).resolve())]["row"]
                # Preserve the scored request/instructions too, not merely its action IDs.
                row.update({key: copy.deepcopy(scored[key]) for key in ("state", "questions")})
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "selection.json", {
        "status": ("NO_EXECUTABLE_BRANCHES_PREFIX_DENOMINATORS_RETAINED"
                   if exact is not None and not policies else "PREPARED_NOT_EXECUTED"),
        "groups": args.groups, "seed": args.seed,
        "split": args.split,
        "include_control_steps": args.include_control_steps,
        "exact_nominations": args.exact_nominations,
        "per_group_maximum": (len(PREFIX_SLOTS) if exact is not None else args.per_group
                              if quotas is None else sum(
                                  n for phases in quotas.values() for n in phases.values())),
        "nominated_captures": include,
        **({"state_quotas": quotas, "quota_cells": quota_cells,
            "quota_shortfall": sum(cell["shortfall"] for cell in quota_cells)}
           if quota_cells is not None else {}),
        **({"prefix_selection": str(exact_path.resolve()),
            "prefix_cells": prefix_cells,
            "prefix_cell_statuses": dict(Counter(c["status"] for c in prefix_cells))}
           if exact_path is not None and prefix_cells is not None else {}),
        "binding_nominations": bindings,
        "branch_sampling": args.branch_sampling,
        **({"decision_evaluation": (str(args.decision_evaluation.resolve())
                                    if args.decision_evaluation is not None else None),
            "decision_collection": (str(args.decision_collection.resolve())
                                    if args.decision_collection is not None else None),
            "score_origin": decision_run.get("score_origin", "saved_evaluation"),
            "unscored_captures": decision_run.get("unscored", []),
            "decision_checkpoint": decision_run["checkpoint"],
            "decision_operation_state": decision_run["operation_state"],
            "decision_baseline": args.decision_baseline,
            "decision_baseline_reads": args.decision_baseline_reads,
            "decision_nominations": decision_nominations,
            "baseline_scope": ("Existing raw selector restricted to actually offered HANDOFF "
                "bindings; no further acquisition. Not end-to-end fixed Host."
                if args.decision_baseline == "raw_delivery" else
                "One legal action from the declared existing policy, not end-to-end fixed Host.")}
           if current_decision else {}),
        "selected": selected, "inventory": inventory, "states": len(selected),
        "branches": len(policies),
        "controlled_readout_frames": controlled_frames,
        "exported_raw_states": len(selected), "operation_labels_added": False,
        "group_states": dict(Counter(entry["family"] for entry in selected)),
        "groups_without_eligible_state": sorted(set(args.groups) - {
            entry["family"] for entry in selected}),
        "stratum_order": ["has_view", "known_evidence", "original_source_requested",
                          "actual_incoming_sources", *(["after_operation", "has_delivered_evidence"]
                                                       if args.include_control_steps else [])],
        "selection": ("Exact predeclared primary-prefix slots only; missing/unbranchable "
                      "cells remain without substitutes or negative labels."
                      if exact is not None else
                      "Declared diagnostic nominations, then round-robin observable strata; "
                      "no answers, semantic grades or action scores used for remaining selection."),
        "branch_selection": ("Full-menu saved argmax, declared simple baseline, optional explicit "
                            "alternatives; identical executable bindings once. Singletons retained."
                            if current_decision else
                            "Explicit binding nominations use actual offered actions. Other "
                            "representatives use operation opportunities, not presumed utility. "
                            "Optional post-step binding sampling chooses a kind uniformly, then "
                            "two distinct actual target/parameter bindings and a control. "
                            "For nested studies prepare the largest pool once and filter its "
                            "reviewed rows; do not resample branches for smaller cohorts."),
        "scope": "Actual captured initial or explicitly checkpointed post-operation states only. "
                 "No reconstruction is inferred from an observation or action trace alone. "
                 "Unselected/failed/missing states remain in inventory without negative labels.",
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu},
        "ledger_recorded": False,
    })


if __name__ == "__main__":
    main()

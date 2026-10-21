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

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control_learning import decision_example


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
    include: list[str],
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--groups", nargs="+", required=True)
    parser.add_argument("--include", action="append", default=[])
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
    parser.add_argument("--branch-sampling", choices=("operations", "post-operation-bindings"),
                        default="operations",
                        help="Optional seeded binding alternatives on actual post-operation states")
    parser.add_argument("--continuation-steps", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
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
            if args.state_quotas is not None:
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
            elif len(branch_actions(call)) < 2:
                entry["reason"] = "fewer_than_two_actual_action_branches"
            else:
                stratum: tuple[bool, ...] = call_stratum(call)
                if args.include_control_steps:
                    stratum = (*stratum, bool(entry["control_step"]),
                               bool(call["initial_observation"]["visible_evidence"]))
                entry.update(eligible=True, stratum=stratum)
                entries.append(entry)
            inventory.append(entry)
    bindings = read_json(args.bindings) if args.bindings is not None else {}
    include = list(dict.fromkeys([*args.include, *bindings]))
    quotas = read_json(args.state_quotas) if args.state_quotas is not None else None
    quota_cells = None
    if quotas is None:
        selected = select_states(entries, args.groups, args.per_group, args.seed, include)
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
    policies = []
    binding_rng = random.Random(args.seed)  # noqa: S311 -- explicit data acquisition seed
    for index, entry in enumerate(selected):
        capture = entry["capture"]
        if capture in bindings:
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
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "selection.json", {
        "status": "PREPARED_NOT_EXECUTED", "groups": args.groups, "seed": args.seed,
        "split": args.split,
        "include_control_steps": args.include_control_steps,
        "per_group_maximum": (args.per_group if quotas is None else
                              sum(n for phases in quotas.values() for n in phases.values())),
        "nominated_captures": include,
        **({"state_quotas": quotas, "quota_cells": quota_cells,
            "quota_shortfall": sum(cell["shortfall"] for cell in quota_cells)}
           if quota_cells is not None else {}),
        "binding_nominations": bindings,
        "branch_sampling": args.branch_sampling,
        "selected": selected, "inventory": inventory, "states": len(selected),
        "branches": len(policies),
        "exported_raw_states": len(selected), "operation_labels_added": False,
        "group_states": dict(Counter(entry["family"] for entry in selected)),
        "groups_without_eligible_state": sorted(set(args.groups) - {
            entry["family"] for entry in selected}),
        "stratum_order": ["has_view", "known_evidence", "original_source_requested",
                          "actual_incoming_sources", *(["after_operation", "has_delivered_evidence"]
                                                       if args.include_control_steps else [])],
        "selection": "Declared diagnostic nominations, then round-robin observable strata; "
                     "no answers, semantic grades or action scores used for remaining selection.",
        "branch_selection": "Explicit binding nominations use actual offered actions. Other "
                            "representatives use operation opportunities, not presumed utility. "
                            "Optional post-step binding sampling chooses a kind uniformly, then "
                            "two distinct actual target/parameter bindings and a control. "
                            "For nested studies prepare the largest pool once and filter its "
                            "reviewed rows; do not resample branches for smaller cohorts.",
        "scope": "Actual captured initial or explicitly checkpointed post-operation states only. "
                 "No reconstruction is inferred from an observation or action trace alone. "
                 "Unselected/failed/missing states remain in inventory without negative labels.",
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu},
        "ledger_recorded": False,
    })


if __name__ == "__main__":
    main()

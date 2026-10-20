"""Select a bounded source-balanced cohort of real calls for existing E2 replay."""
from __future__ import annotations

import argparse
import copy
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


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
        buckets: dict[tuple[bool, bool, bool, bool], list[dict[str, Any]]] = defaultdict(list)
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
    parser.add_argument("--continuation-steps", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    entries, inventory, calls = [], [], {}
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
        for path in sorted((root / "frozen-retrieval-calls").glob("*/call.json")):
            call, capture = read_json(path), path.parent.name
            if capture in calls:
                raise ValueError("A real capture was included twice")
            calls[capture] = call
            history = banks[call["bank"]]
            entry = {"capture": capture, "path": str(path.parent.resolve()),
                     "family": history["source_group"], "split": history["split"],
                     "run": str(root), "source_version": driver["source_version"],
                     "message_id": call["public_message"]["message_id"],
                     "original_status": call["status"], "eligible": False}
            if call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}:
                entry["reason"] = "original_call_not_closed"
            elif not call["initial_actions"] or call["initial_observation"] is None:
                entry["reason"] = "no_actual_decision"
            elif call["initial_observation"].get("observed_materials") is None:
                entry["reason"] = "pre_W4_observation"
            elif history["split"] != "train" or history["source_group"] not in args.groups:
                entry["reason"] = "outside_declared_training_groups"
            elif len(branch_actions(call)) < 2:
                entry["reason"] = "fewer_than_two_actual_action_branches"
            else:
                entry.update(eligible=True, stratum=call_stratum(call))
                entries.append(entry)
            inventory.append(entry)
    bindings = read_json(args.bindings) if args.bindings is not None else {}
    include = list(dict.fromkeys([*args.include, *bindings]))
    selected = select_states(entries, args.groups, args.per_group, args.seed, include)
    args.output.mkdir(parents=True, exist_ok=False)
    captures = args.output / "captures"
    captures.mkdir()
    # Keep closed unselected calls in the replay cohort; selection never makes them negatives.
    for entry in inventory:
        if entry["original_status"] in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}:
            (captures / entry["capture"]).symlink_to(entry["path"], target_is_directory=True)
    policies = []
    for index, entry in enumerate(selected):
        capture = entry["capture"]
        actions = (nominated_actions(calls[capture], bindings[capture]["actions"])
                   if capture in bindings else branch_actions(calls[capture]))
        for branch_index, action in enumerate(actions):
            policies.append({
                "name": f"state-{index:03d}-branch-{branch_index:02d}",
                "capture": capture,
                "policy": {"policy": "fixed_context", "reads": 4},
                "intervention": {"first_action": action,
                                 "continuation_steps": args.continuation_steps},
            })
    write_json(args.output / "policies.json", policies)
    write_json(args.output / "selection.json", {
        "status": "PREPARED_NOT_EXECUTED", "groups": args.groups, "seed": args.seed,
        "per_group_maximum": args.per_group, "nominated_captures": include,
        "binding_nominations": bindings,
        "selected": selected, "inventory": inventory, "states": len(selected),
        "branches": len(policies),
        "group_states": dict(Counter(entry["family"] for entry in selected)),
        "groups_without_eligible_state": sorted(set(args.groups) - {
            entry["family"] for entry in selected}),
        "stratum_order": ["has_view", "known_evidence", "original_source_requested",
                          "actual_incoming_sources"],
        "selection": "Declared diagnostic nominations, then round-robin observable strata; "
                     "no answers, semantic grades or action scores used for remaining selection.",
        "branch_selection": "Explicit binding nominations use actual offered actions. Other "
                            "representatives use operation opportunities, not presumed utility.",
        "scope": "Initial actual call states only; not arbitrary internal decision restoration. "
                 "Unselected/failed/missing states remain in inventory without negative labels.",
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu},
        "ledger_recorded": False,
    })


if __name__ == "__main__":
    main()

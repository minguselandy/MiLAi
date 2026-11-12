"""Join offline utility, optional existing semantic feedback, and shared old replay."""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
import time
from collections import defaultdict, deque
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from outcome_distillation import (
    active_support,
    attach_utilities,
    component_weights,
    is_main,
    mixed_windows,
)
from retrieval_feedback import validate_feedback


def dependency_groups(groups: list[list[str]]) -> dict[str, str]:
    """Use existing shared-source relations; never rewrite actual family/action bindings."""
    parent: dict[str, str] = {}

    def root(name: str) -> str:
        parent.setdefault(name, name)
        if parent[name] != name:
            parent[name] = root(parent[name])
        return parent[name]

    for group in groups:
        if not group or any(not isinstance(name, str) or not name for name in group):
            raise ValueError("Source dependency groups require original nonempty identity strings")
        for name in group:
            left, right = sorted((root(group[0]), root(name)))
            parent[right] = left
    return {name: root(name) for name in parent}


def annotate_dependencies(rows: list[dict], groups: dict[str, str]) -> None:
    for row in rows:
        meta = row["metadata"]
        if meta["family"] in groups:
            group = groups[meta["family"]]
            if meta.get("dependency_group", group) != group:
                raise ValueError("Declared source dependency group changed")
            meta["dependency_group"] = group


def balanced_replay(rows: list[dict], count: int, seed: int) -> list[dict]:
    """Select real old rows without replacement, round-robin by family then native event."""
    if count < 1 or count > len(rows):
        raise ValueError("Replay quota must fit the available original labelled rows")
    rng = random.Random(seed)  # noqa: S311 -- declared data preparation seed
    families = defaultdict(lambda: defaultdict(list))
    for row in rows:
        meta = row["metadata"]
        group = meta.get("dependency_group", meta["family"])
        event = (meta["family"], meta.get("training_event", meta["event_id"]))
        families[group][event].append(row)
    names = sorted(families)
    rng.shuffle(names)
    queues = {}
    for name in names:
        groups = list(families[name].values())
        rng.shuffle(groups)
        for group in groups:
            rng.shuffle(group)
        queues[name] = deque(deque(group) for group in groups)
    selected = []
    while len(selected) < count:
        for name in names:
            events = queues[name]
            if not events:
                continue
            group = events.popleft()
            selected.append(group.popleft())
            if group:
                events.append(group)
            if len(selected) == count:
                break
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("states", type=Path)
    parser.add_argument("scores", type=Path)
    parser.add_argument("replay", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--semantic", type=Path, nargs="+", default=[])
    parser.add_argument("--additional-block", type=Path, nargs=2, action="append", default=[],
                        metavar=("STATES", "SCORES"), help="Additional immutable closed data block")
    parser.add_argument("--active-main-only", action="store_true",
                        help="Keep the union of usable utility and actual semantic support; "
                             "report all original opportunities separately")
    parser.add_argument("--utility-flat-tolerance", type=float, default=1e-6,
                        help="Use the same declared numerical deadband as the student trainer")
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--replay-rows", type=int,
                        help="Source/event-balanced frozen subset of the existing operation pool")
    parser.add_argument("--source-clusters", type=Path,
                        help="Existing shared_family_clusters manifest or list of source groups")
    args = parser.parse_args()
    if not math.isfinite(args.utility_flat_tolerance) or args.utility_flat_tolerance < 0:
        parser.error("Utility deadband must be finite and nonnegative")
    started, cpu = time.perf_counter(), time.process_time()
    blocks = [(args.states, args.scores), *args.additional_block]
    rows, identities, block_records = [], set(), []
    for states_path, scores_path in blocks:
        score_run = read_json(scores_path.parent / "run.json")
        if score_run["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
            raise ValueError("Compile a closed scoring version, retaining unavailable scores")
        original = read_jsonl(states_path)
        block = attach_utilities(original, read_jsonl(scores_path))
        for row in block:
            event = row["metadata"]["event_id"]
            if event in identities:
                raise ValueError("Repeated event version across blocks; do not double its exposure")
            identities.add(event)
        rows.extend(block)
        block_records.append({"states": str(states_path.resolve()),
                              "scores": str(scores_path.resolve()), "rows": len(block),
                              "scoring_configuration": score_run.get("scoring_configuration")})
    original_count = len(rows)
    original_families = {r["metadata"]["family"] for r in rows}
    definitions = read_json(args.source_clusters) if args.source_clusters else []
    groups = dependency_groups(definitions["shared_family_clusters"]
                               if isinstance(definitions, dict) else definitions)
    annotate_dependencies(rows, groups)
    semantic = {}
    for path in args.semantic:
        for row in read_jsonl(path):
            event = row["metadata"]["event_id"]
            if event in semantic:
                raise ValueError("A semantic event was supplied more than once")
            validate_feedback(row)
            semantic[event] = row
    for row in rows:
        meta = row["metadata"]
        if meta["split"] != "train":
            raise ValueError("Training states must retain research TRAIN role")
        feedback = semantic.get(meta["event_id"])
        if feedback is not None:
            if any(row[k] != feedback[k] for k in ("state", "questions")):
                raise ValueError("Semantic feedback came from a different actual student input")
            for key in ("family", "split"):
                if meta[key] != feedback["metadata"][key]:
                    raise ValueError("Semantic feedback source role changed")
            row["feedback"] = copy.deepcopy(feedback["feedback"])
            meta["feedback_semantics"] = feedback["metadata"]["feedback_semantics"]
            validate_feedback(row)
    excluded = []
    if args.active_main_only:
        eligible = []
        for row in rows:
            if any(active_support(row, objective, target, True, args.utility_flat_tolerance)
                   for objective, target in (("utility-kl", None), ("pair", "delivery"),
                                              ("pair", "answer"))):
                eligible.append(row)
            else:
                excluded.append({"event_id": row["metadata"]["event_id"],
                                 "family": row["metadata"]["family"],
                                 "reason": "no_active_weak_or_semantic_target_in_frozen_version"})
        rows = eligible
    main_count = len(rows)
    main_families = {r["metadata"]["family"] for r in rows}
    primary_ids = {r["metadata"]["event_id"] for r in rows}
    replay = [r for r in read_jsonl(args.replay) if r["gold"] and not is_main(r)
              and r["metadata"]["event_id"] not in primary_ids]
    if any(r["metadata"]["split"] != "train" for r in replay):
        raise ValueError("Replay must retain research TRAIN role")
    annotate_dependencies(replay, groups)
    replay_available = len(replay)
    if args.replay_rows is not None:
        replay = balanced_replay(replay, args.replay_rows, args.seed)
    rows.extend(replay)
    for index, row in enumerate(rows):
        row["metadata"]["source_state_id"] = row["metadata"].get("state_id")
        row["metadata"].update(state_id=index, row=index)
    windows = mixed_windows(rows, args.passes, args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    if args.active_main_only:
        write_json(args.output / "inactive-opportunities.json", excluded)
    with (args.output / "train.jsonl").open("x") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "run.json", {
        "status": "COMPLETED", "states": str(args.states.resolve()),
        "scores": str(args.scores.resolve()), "semantic": [str(p.resolve()) for p in args.semantic],
        "blocks": block_records, "original_opportunity_states": original_count,
        "original_opportunity_families": len(original_families),
        "active_main_only": args.active_main_only, "inactive_opportunities": len(excluded),
        "utility_flat_tolerance": args.utility_flat_tolerance,
        "replay": str(args.replay.resolve()), "main_states": main_count,
        "main_families": len(main_families),
        "main_dependency_groups": len({r["metadata"].get(
            "dependency_group", r["metadata"]["family"]) for r in rows if is_main(r)}),
        "source_clusters": str(args.source_clusters.resolve()) if args.source_clusters else None,
        "replay_states": len(replay), "passes": args.passes, "seed": args.seed,
        "available_replay_states": replay_available,
        "replay_families": len({row["metadata"]["family"] for row in replay}),
        "replay_dependency_groups": len({r["metadata"].get(
            "dependency_group", r["metadata"]["family"]) for r in replay}),
        "replay_selection": "family/event round-robin without replacement"
                            if args.replay_rows is not None else "all available labelled rows",
        "planned_windows": len(windows),
        "primary_exposures": sum(is_main(rows[i]) for w in windows for _, i in w),
        "replay_exposures": sum(not is_main(rows[i]) for w in windows for _, i in w),
        "active_primary_states": {objective: sum(is_main(r) and w > 0 for r, w in
            zip(rows, component_weights(rows, objective, "delivery", True,
                                        args.utility_flat_tolerance), strict=True))
            for objective in ("pair", "utility-kl")},
        "no_sha_validation": True, "student_inputs_unchanged": True,
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu}})


if __name__ == "__main__":
    main()

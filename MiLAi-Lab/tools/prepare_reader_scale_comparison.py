"""Prepare expanded utility experience and a repeated-base comparison with shared replay."""
from __future__ import annotations

import argparse
import copy
import json
import math
import time
from pathlib import Path

from compile_reader_utility_data import annotate_dependencies, balanced_replay, dependency_groups
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from outcome_distillation import active_support, attach_utilities, is_main, mixed_windows


def prepare_comparison(base: list[dict], candidates: list[dict], old_replay: list[dict],
                       new_count: int, replay_count: int, groups: dict[str, str], seed: int
                       ) -> tuple[dict[str, list[dict]], dict]:
    primary = copy.deepcopy([r for r in base if is_main(r)])
    if not primary or new_count < 1:
        raise ValueError("Require a frozen primary prefix and positive real new-state count")
    base_ids = {r["metadata"]["event_id"] for r in primary}
    if len(base_ids) != len(primary):
        raise ValueError("Frozen primary events must be unique")
    seen, available = set(base_ids), []
    for original in candidates:
        meta = original["metadata"]
        if "utility" not in original:
            raise ValueError("New experience requires its actual scored utility records")
        if meta["event_id"] in seen:
            raise ValueError("Repeated event version is not new experience")
        seen.add(meta["event_id"])
        if meta["split"] != "train":
            raise ValueError("Expansion candidates must retain TRAIN role")
        if active_support(original, "utility-kl", None, True, 1e-4):
            available.append(copy.deepcopy(original))
    annotate_dependencies(primary, groups)
    annotate_dependencies(available, groups)
    if len(available) < new_count:
        raise ValueError(f"Only {len(available)} actual active new states; requested {new_count}")
    added = balanced_replay(available, new_count, seed)
    expanded = [*primary, *added]
    primary_ids = {r["metadata"]["event_id"] for r in expanded}
    replay = [copy.deepcopy(r) for r in old_replay if r["gold"] and not is_main(r)
              and r["metadata"]["event_id"] not in primary_ids]
    if any(r["metadata"]["split"] != "train" for r in [*primary, *replay]):
        raise ValueError("Base/replay role changed")
    annotate_dependencies(replay, groups)
    replay_available = len(replay)
    replay = balanced_replay(replay, replay_count, seed)
    # Shared primary/replay examples get identical permutation-seed IDs in both arms,
    # even though the smaller file has a deliberate gap before its replay IDs.
    for i, row in enumerate([*expanded, *replay]):
        row["metadata"].update(scale_parent_state_id=row["metadata"].get("state_id"),
                               state_id=i, row=i)
    arms = {"expanded": [*expanded, *replay],
            "repeat": copy.deepcopy([*primary, *replay])}
    repeat_passes = math.ceil(3 * len(expanded) / len(primary))
    schedules = {}
    for name, passes in (("expanded", 3), ("repeat", repeat_passes)):
        windows = mixed_windows(arms[name], passes, seed, 24, 8)
        schedules[name] = {"passes": passes, "updates": len(windows),
            "primary_exposures": sum(is_main(arms[name][i]) for w in windows for _, i in w),
            "replay_exposures": sum(not is_main(arms[name][i]) for w in windows for _, i in w)}
    return arms, {
        "base_primary_states": len(primary), "available_active_new_states": len(available),
        "selected_new_states": len(added), "expanded_primary_states": len(expanded),
        "expanded_raw_families": len({r["metadata"]["family"] for r in expanded}),
        "expanded_dependency_groups": len({r["metadata"].get(
            "dependency_group", r["metadata"]["family"]) for r in expanded}),
        "eligible_replay_pool": replay_available, "shared_replay_states": len(replay),
        "schedules": schedules,
        "repeat_over_expanded_primary_exposure_ratio": (
            schedules["repeat"]["primary_exposures"] / schedules["expanded"]["primary_exposures"]),
        "selection": "Source-dependency-group/event round robin without replacement; seed fixed. "
                     "Only actual executed/scored nonflat new states qualify. "
                     "Original prefix retained.",
        "scope": "Fresh fits from the same common initialization, shared replay and matching "
                 "permutation IDs for common examples. Whole-pass repetition approximately matches "
                 "primary/replay exposures; token/FLOP work and augmentation pass counts differ. "
                 "Expanded source/domain/condition mix differs; not a pure size intervention."
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_data", type=Path)
    parser.add_argument("replay", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--additional-block", type=Path, nargs=2, action="append", required=True,
                        metavar=("STATES", "SCORES"))
    parser.add_argument("--new-states", type=int, default=6644)
    parser.add_argument("--replay-rows", type=int, default=4096)
    parser.add_argument("--source-clusters", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    candidates, blocks = [], []
    for states, scores in args.additional_block:
        scored = read_json(scores.parent / "run.json")
        if scored["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
            raise ValueError("Use closed actual scoring versions only")
        candidates.extend(attach_utilities(read_jsonl(states), read_jsonl(scores)))
        blocks.append({"states": str(states.resolve()), "scores": str(scores.resolve()),
                       "scoring_configuration": scored.get("scoring_configuration")})
    definitions = read_json(args.source_clusters) if args.source_clusters else []
    groups = dependency_groups(definitions["shared_family_clusters"]
                               if isinstance(definitions, dict) else definitions)
    arms, report = prepare_comparison(read_jsonl(args.base_data / "train.jsonl"), candidates,
        read_jsonl(args.replay), args.new_states, args.replay_rows, groups, args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, rows in arms.items():
        directory = args.output / name
        directory.mkdir()
        with (directory / "train.jsonl").open("x") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "run.json", {**report, "status": "PREPARED_NOT_FITTED",
        "base_data": str(args.base_data.resolve()), "replay": str(args.replay.resolve()),
        "blocks": blocks,
        "source_clusters": str(args.source_clusters) if args.source_clusters else None,
        "seed": args.seed, "no_sha_validation": True,
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}})


if __name__ == "__main__":
    main()


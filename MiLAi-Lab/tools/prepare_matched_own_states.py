"""Match old/own reached TRAIN states by original source, native event and condition."""
from __future__ import annotations

import argparse
import copy
import json
import random
import time
from collections import defaultdict
from pathlib import Path

from compile_reader_utility_data import annotate_dependencies, dependency_groups
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from outcome_distillation import active_support, attach_utilities, is_main, mixed_windows


def match_states(old: list[dict], own: list[dict], replay_pool: list[dict],
                 groups: dict[str, str], seed: int = 0, passes: int = 3,
                 tolerance: float = 1e-4, exclude_replay_overlap: bool = False
                 ) -> tuple[dict[str, list[dict]], dict]:
    pools, counts, opportunities, requests = {}, {}, {}, {}
    for name, rows in (("old", old), ("own", own)):
        rows = copy.deepcopy(rows)
        annotate_dependencies(rows, groups)
        ids = set()
        strata = defaultdict(list)
        for row in rows:
            meta = row["metadata"]
            if meta["split"] != "train" or not meta.get("training_event"):
                raise ValueError("Require original TRAIN source and native event identity")
            if meta["event_id"] in ids or "utility" not in row:
                raise ValueError("Require unique actual events with attached utility records")
            ids.add(meta["event_id"])
            key = meta["family"], meta["training_event"], meta.get("condition", "")
            request = row["state"].get("task", {}).get("retrieval_request")
            if not request or (key in requests and requests[key] != request):
                raise ValueError("Matched native event changed its original request or K")
            requests[key] = request
            if active_support(row, "utility-kl", None, True, tolerance):
                strata[key].append(row)
        pools[name] = strata
        opportunities[name] = len(rows)
        counts[name] = sum(map(len, strata.values()))
    rng = random.Random(seed)  # noqa: S311 -- declared experimental sampling seed
    selected: dict[str, list[dict]] = {"old": [], "own": []}
    matched = []
    for key in sorted(set(pools["old"]) | set(pools["own"])):
        sizes = {name: len(pools[name][key]) for name in selected}
        quota = min(sizes.values())
        record = {"family": key[0], "training_event": key[1], "condition": key[2],
                  "available": sizes, "selected_each": quota, "selected_events": {}}
        for name in selected:
            rows = sorted(pools[name][key], key=lambda r: r["metadata"]["event_id"])
            rng.shuffle(rows)
            chosen = rows[:quota]
            selected[name].extend(chosen)
            record["selected_events"][name] = [r["metadata"]["event_id"] for r in chosen]
        matched.append(record)
    n = len(selected["old"])
    if n == 0 or n != len(selected["own"]):
        raise ValueError("No common active native-event/condition strata")
    primary_ids = {r["metadata"]["event_id"] for rows in selected.values() for r in rows}
    replay = copy.deepcopy([r for r in replay_pool if not is_main(r) and r["gold"]])
    if not replay or any(r["metadata"]["split"] != "train" for r in replay):
        raise ValueError("Require the same nonempty original TRAIN replay pool")
    replay_ids = [r["metadata"]["event_id"] for r in replay]
    overlap = sorted(primary_ids.intersection(replay_ids))
    if len(replay_ids) != len(set(replay_ids)) or (overlap and not exclude_replay_overlap):
        raise ValueError("Shared replay has duplicates or overlaps selected primary events")
    replay = [r for r in replay if r["metadata"]["event_id"] not in primary_ids]
    if not replay:
        raise ValueError("No original replay remains after declared overlap exclusion")
    annotate_dependencies(replay, groups)
    for index, row in enumerate(replay, n):
        row["metadata"].update(matched_parent_state_id=row["metadata"].get("state_id"),
                               state_id=index, row=index)
    arms, schedules = {}, {}
    for name, rows in selected.items():
        for index, row in enumerate(rows):
            row["metadata"].update(matched_parent_state_id=row["metadata"].get("state_id"),
                                   state_id=index, row=index)
        arms[name] = [*rows, *copy.deepcopy(replay)]
        windows = mixed_windows(arms[name], passes, seed, 24, 8)
        schedules[name] = {"updates": len(windows),
            "primary_exposures": sum(is_main(arms[name][i]) for w in windows for _, i in w),
            "replay_exposures": sum(not is_main(arms[name][i]) for w in windows for _, i in w)}
    assert schedules["old"] == schedules["own"]
    return arms, {"opportunities": opportunities, "active_available": counts,
        "selected_each": n, "not_selected_active": {name: counts[name] - n for name in counts},
        "raw_families": len({r["metadata"]["family"] for r in selected["old"]}),
        "dependency_groups": len({r["metadata"].get("dependency_group", r["metadata"]["family"])
                                  for r in selected["old"]}),
        "strata": matched, "original_replay_rows": len(replay_ids),
        "excluded_primary_replay_overlap": overlap,
        "replay_overlap_exclusion_enabled": exclude_replay_overlap,
        "shared_replay_rows": len(replay), "passes": passes,
        "seed": seed, "tolerance": tolerance, "schedules": schedules,
        "scope": "Common active source/native-event/condition support only. Each stratum uses "
                 "the smaller active count, selected without replacement or score-magnitude "
                 "ranking. Actual reached steps/inputs/menus/targets may differ and remain "
                 "unchanged. Unsupported and one-sided opportunities are retained in counts, "
                 "not negatives. Same replay and window counts do not equalize token/FLOP work. "
                 "This conditions away unmatched exploration coverage; report that separately."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--old-block", nargs=2, type=Path, required=True)
    parser.add_argument("--own-block", nargs=2, type=Path, required=True)
    parser.add_argument("--source-clusters", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--exclude-primary-replay-overlap", action="store_true",
                        help="Exclude the selected primary union from both replay pools; "
                             "report excluded original events, without replacement")
    args = parser.parse_args()
    t, cpu = time.perf_counter(), time.process_time()
    rows, configs, blocks = {}, [], {}
    for name, (states, scores) in (("old", args.old_block), ("own", args.own_block)):
        run = read_json(scores.parent / "run.json")
        if run["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
            raise ValueError("Wait for both immutable actual score versions to close")
        configs.append({key: run[key] for key in (
            "teacher", "scoring_configuration", "max_length", "batch_size", "padded_token_target")})
        rows[name] = attach_utilities(read_jsonl(states), read_jsonl(scores))
        blocks[name] = {"states": str(states.resolve()), "scores": str(scores.resolve())}
    if configs[0] != configs[1]:
        raise ValueError("Old and own states require the same scoring configuration")
    groups = dependency_groups(read_json(args.source_clusters)["shared_family_clusters"])
    arms, report = match_states(rows["old"], rows["own"], read_jsonl(args.replay), groups,
                                args.seed, args.passes,
                                exclude_replay_overlap=args.exclude_primary_replay_overlap)
    args.output.mkdir(exist_ok=False, parents=True)
    for name, arm in arms.items():
        directory = args.output / name
        directory.mkdir()
        with (directory / "train.jsonl").open("x") as stream:
            for row in arm:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "run.json", {**report, "status": "MATCHED_DATA_PREPARED_NOT_FITTED",
        "blocks": blocks, "scoring_configuration": configs[0],
        "replay_source": str(args.replay.resolve()), "no_sha_validation": True,
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - t}})


if __name__ == "__main__":
    main()

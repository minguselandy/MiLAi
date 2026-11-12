"""Join offline utility, optional existing semantic feedback, and shared old replay."""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from outcome_distillation import attach_utilities, component_weights, is_main, mixed_windows
from retrieval_feedback import validate_feedback


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("states", type=Path)
    parser.add_argument("scores", type=Path)
    parser.add_argument("replay", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--semantic", type=Path, nargs="+", default=[])
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    score_run = read_json(args.scores.parent / "run.json")
    if score_run["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
        raise ValueError("Compile a closed scoring version, retaining unavailable scores")
    original = read_jsonl(args.states)
    rows = attach_utilities(original, read_jsonl(args.scores))
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
    primary_ids = {r["metadata"]["event_id"] for r in rows}
    replay = [r for r in read_jsonl(args.replay) if r["gold"] and not is_main(r)
              and r["metadata"]["event_id"] not in primary_ids]
    if any(r["metadata"]["split"] != "train" for r in replay):
        raise ValueError("Replay must retain research TRAIN role")
    rows.extend(replay)
    for index, row in enumerate(rows):
        row["metadata"]["source_state_id"] = row["metadata"].get("state_id")
        row["metadata"].update(state_id=index, row=index)
    windows = mixed_windows(rows, args.passes, args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "train.jsonl").open("x") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "run.json", {
        "status": "COMPLETED", "states": str(args.states.resolve()),
        "scores": str(args.scores.resolve()), "semantic": [str(p.resolve()) for p in args.semantic],
        "replay": str(args.replay.resolve()), "main_states": len(original),
        "main_families": len({r["metadata"]["family"] for r in original}),
        "replay_states": len(replay), "passes": args.passes, "seed": args.seed,
        "planned_windows": len(windows),
        "primary_exposures": sum(is_main(rows[i]) for w in windows for _, i in w),
        "replay_exposures": sum(not is_main(rows[i]) for w in windows for _, i in w),
        "active_primary_states": {objective: sum(is_main(r) and w > 0 for r, w in
            zip(rows, component_weights(rows, objective, "delivery", True, 1e-6), strict=True))
            for objective in ("pair", "utility-kl")},
        "no_sha_validation": True, "student_inputs_unchanged": True,
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu}})


if __name__ == "__main__":
    main()

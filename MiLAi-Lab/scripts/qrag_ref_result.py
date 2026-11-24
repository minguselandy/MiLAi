"""Summarize the completed official optimizer schedule and fixed-roster retrieval evaluation."""

import argparse
import json
import statistics
from pathlib import Path


def summarize(run: Path, roster: Path) -> dict:
    curve = [
        json.loads(line)
        for line in (run / "tb_logs/reference-curve.jsonl").read_text().splitlines()
    ]
    if [r["optimizer_updates"] for r in curve] != list(range(0, 10001, 100)):
        raise ValueError("The official 10,000-update validation schedule is incomplete")
    rows = [json.loads(line) for line in (run / "eval_seed42.jsonl").read_text().splitlines()]
    groups = set(json.loads(roster.read_text())["groups"])
    if len(rows) != len(groups) or {r["id"] for r in rows} != groups:
        raise ValueError("Retrieval validation coverage differs from the frozen roster")
    return {
        "reference": "official MuSiQue-Ans GT/PQN with fixed TUNE retrieval validation",
        "optimizer_updates": curve[-1]["optimizer_updates"],
        "critic_transitions": curve[-1]["critic_transitions"],
        "evaluated_groups": len(groups),
        "training_clock_seconds_to_final_validation": curve[-1]["elapsed_seconds"],
        "peak_gpu_allocated_bytes": max(r["peak_gpu_allocated_bytes"] for r in curve),
        "initial_dev_gt_return": curve[0]["gt_dev_return"],
        "final_dev_gt_return": curve[-1]["gt_dev_return"],
        "best_dev_gt_return": max(r["gt_dev_return"] for r in curve),
        "best_actor_support_f1": statistics.mean(r["f1"] for r in rows),
        "best_actor_support_em": statistics.mean(r["em"] for r in rows),
        "best_actor_gt_return": statistics.mean(r["return"] for r in rows),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--roster", required=True, type=Path)
    args = parser.parse_args()
    result = summarize(args.run, args.roster)
    (args.run / "reference-result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

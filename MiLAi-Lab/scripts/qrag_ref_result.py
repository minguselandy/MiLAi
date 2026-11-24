"""Summarize the completed official optimizer schedule and fixed-roster retrieval evaluation."""

import argparse
import json
import statistics
from pathlib import Path


def summarize(run: Path, roster: Path, schedules: list[Path]) -> dict:
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
    fit_resource = json.loads((run.parent / "fit-resource.json").read_text())
    validation_attempts = [
        json.loads(line) for line in (run / "validation-resource.jsonl").read_text().splitlines()
    ]
    evaluation_resource = validation_attempts[-1]
    if fit_resource.get("exit_code") not in {None, 0} or evaluation_resource["exit_code"] != 0:
        raise ValueError("Training or retrieval evaluator returned an error")
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(7.2, 4.2), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    xs = [r["optimizer_updates"] for r in curve]
    ax.plot(xs, [r["gt_train_return"] for r in curve], color="0.62", label="Train")
    ax.plot(xs, [r["gt_dev_return"] for r in curve], color="#126782", label="Fixed dev (300)")
    ax.set(
        xlabel="Optimizer updates",
        ylabel="Mean GT episode return",
        title="Q-RAG Reference · MuSiQue-Ans",
    )
    ax.legend()
    fig.savefig(run / "reference-learning-curve.png", dpi=160)
    evaluation_seconds = sum(r["elapsed_seconds"] for r in validation_attempts)
    intervals = []
    for path in schedules:
        schedule = json.loads(path.read_text())
        if fit_resource.get("pid") is not None and schedule.get("ref_pid") == fit_resource["pid"]:
            if schedule.get("ended_ns") is None:
                raise ValueError("The matching fit scheduling interval is still open")
            intervals.append((schedule["started_ns"], schedule["ended_ns"]))
    merged = []
    for start, end in sorted(intervals):
        if end < start:
            raise ValueError("Inverted fit parking interval")
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    paused = sum(end - start for start, end in merged) / 1e9
    return {
        "one_gpu_training_job_hours": fit_resource["elapsed_seconds"] / 3600,
        "recorded_parked_seconds": paused,
        "one_gpu_fit_wall_hours_minus_recorded_parking": (fit_resource["elapsed_seconds"] - paused)
        / 3600,
        "matching_recorded_park_intervals": merged,
        "one_gpu_retrieval_job_hours": evaluation_seconds / 3600,
        "retrieval_validation_invocations": len(validation_attempts),
        "resource_unit": "One assigned GPU times process wall duration, including setup and I/O",
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
    parser.add_argument("--schedule", type=Path, action="append", default=[])
    args = parser.parse_args()
    result = summarize(args.run, args.roster, args.schedule)
    (args.run / "reference-result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

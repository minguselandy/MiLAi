"""Summarize the completed official optimizer schedule and fixed-roster retrieval evaluation."""

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import yaml


def complete_curve(run):
    curve = [
        json.loads(line)
        for line in (run / "tb_logs/reference-curve.jsonl").read_text().splitlines()
    ]
    if [r["optimizer_updates"] for r in curve] != list(range(0, 10001, 100)):
        raise ValueError("The official 10,000-update validation schedule is incomplete")
    return curve


def prepare_terminal(run, *, need_best=True):
    """Recover the official best actor only when the full schedule proves which actor won."""
    curve = complete_curve(run)
    required = {
        "best": max(curve, key=lambda r: r["gt_dev_return"])["optimizer_updates"],
        "last": curve[-1]["optimizer_updates"],
    }
    model_dir = Path(yaml.safe_load((run / "config.yaml").read_text())["checkpoint_dir"])
    model_dir.mkdir(parents=True, exist_ok=True)
    actors = run / "actors"
    actors.mkdir(exist_ok=True)
    pointer = run / "retained-actors/index.json"
    retained = json.loads(pointer.read_text())["actors"] if pointer.is_file() else {}
    for kind, step in required.items():
        zip_path = actors / f"{kind}.zip"
        receipt = actors / f"{kind}.json"
        source = retained.get(kind, {})
        if (
            source.get("optimizer_updates") == step
            and source.get("exact_tensors_verified", 0) > 0
            and Path(source["archive"]).stat().st_size == source["bytes"]
        ):
            if not zip_path.exists():
                os.link(source["archive"], zip_path)
            if not receipt.exists() and os.path.samefile(zip_path, source["archive"]):
                write_receipt(receipt, source)
        checkpoint = model_dir / f"model_{kind}.pt"
        if checkpoint.exists():
            continue
        if not zip_path.exists() or not receipt.exists():
            raise FileNotFoundError(f"Complete curve requires {kind} actor at update {step}")
        if kind == "best" and need_best:
            import torch
            from qrag_ref_actor_delta import read_xor_archive

            meta = json.loads(receipt.read_text())
            if meta.get("optimizer_updates") != step or meta.get("kind") != kind:
                raise ValueError("Persistent actor and complete curve identify different updates")
            actor, _ = read_xor_archive(zip_path, meta["base"])
            part = checkpoint.with_suffix(".part")
            torch.save(actor, part)
            part.replace(checkpoint)


def write_receipt(path, data):
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def archive_terminal(run, base):
    from qrag_ref_actor_delta import compact_trained

    curve = complete_curve(run)
    prepare_terminal(run, need_best=False)
    model_dir = Path(yaml.safe_load((run / "config.yaml").read_text())["checkpoint_dir"])
    for kind, row in (("best", max(curve, key=lambda r: r["gt_dev_return"])), ("last", curve[-1])):
        zip_path = run / "actors" / f"{kind}.zip"
        receipt = zip_path.with_suffix(".json")
        if zip_path.is_file() and receipt.is_file():
            record = json.loads(receipt.read_text())
            if (
                record.get("kind") == kind
                and record.get("optimizer_updates") == row["optimizer_updates"]
                and record["exact_tensors_verified"] > 0
                and zip_path.stat().st_size == record.get("bytes", record.get("delta_size"))
            ):
                continue
        record = compact_trained(model_dir / f"model_{kind}.pt", base, zip_path)
        record.update(kind=kind, optimizer_updates=row["optimizer_updates"])
        write_receipt(receipt, record)


def repair_tail(path):
    """Preserve a torn final write before another line is appended."""
    rows = 0
    discarded = 0
    if path.exists():
        with path.open("r+b") as stream:
            while True:
                at = stream.tell()
                line = stream.readline()
                if not line:
                    break
                try:
                    json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    if stream.read(1):
                        raise ValueError("Malformed interior validation row") from None
                    tail = path.with_suffix(f".interrupted-tail-{time.time_ns()}.bin")
                    tail.write_bytes(line)
                    stream.seek(at)
                    stream.truncate()
                    discarded = len(line)
                    break
                rows += 1
                if not line.endswith(b"\n"):
                    stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    return rows, discarded


def begin_validation(run):
    rows, discarded = repair_tail(run / "eval_seed42.jsonl")
    _, resource_loss = repair_tail(run / "validation-resource.jsonl")
    _, launch_loss = repair_tail(run / "validation-launches.jsonl")
    # A reboot may interrupt the evaluator before GNU time can settle the attempt.
    with (run / "validation-launches.jsonl").open("a") as launches:
        launches.write(
            json.dumps(
                {
                    "started_ns": time.time_ns(),
                    "previous_complete_rows": rows,
                    "preserved_torn_tail_bytes": discarded,
                    "preserved_resource_tail_bytes": resource_loss,
                    "preserved_launch_tail_bytes": launch_loss,
                }
            )
            + "\n"
        )
        launches.flush()
        os.fsync(launches.fileno())


def plot_curve(run, curve):
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


def summarize(run: Path, roster: Path, schedules: list[Path]) -> dict:
    curve = complete_curve(run)
    rows = [json.loads(line) for line in (run / "eval_seed42.jsonl").read_text().splitlines()]
    frozen = json.loads(roster.read_text())
    groups = set(frozen["groups"])
    if len(groups) != 300 or frozen["n"] != 300 or frozen["role"] != "TUNE":
        raise ValueError("Final retrieval requires the frozen 300-source REF TUNE roster")
    if len(rows) != len(groups) or {r["id"] for r in rows} != groups:
        raise ValueError("Retrieval validation coverage differs from the frozen roster")
    settled = run.parent / "fit-resource.json"
    if settled.is_file():
        fit_resource = json.loads(settled.read_text())
        time_scope = "Settled one-GPU process wall"
    else:
        # A power loss can remove the process before its exit-time observer writes a receipt.
        heartbeat_file = run / "retained-actors/live-resource.json"
        beat = json.loads(heartbeat_file.read_text()) if heartbeat_file.is_file() else {}
        observed = (
            beat["process_elapsed_to_observation_seconds"]
            if beat.get("live_at_observation")
            else 0.0
        )
        fit_resource = {
            "elapsed_seconds": max(observed, curve[-1]["elapsed_seconds"]),
            "pid": beat.get("pid"),
        }
        time_scope = "Lower bound from the completed curve and last durable live observation"

    validation_attempts = [
        json.loads(line) for line in (run / "validation-resource.jsonl").read_text().splitlines()
    ]
    evaluation_resource = validation_attempts[-1]
    if fit_resource.get("exit_code") not in {None, 0} or evaluation_resource["exit_code"] != 0:
        raise ValueError("Training or retrieval evaluator returned an error")
    evaluation_seconds = sum(r["elapsed_seconds"] for r in validation_attempts)
    launches = run / "validation-launches.jsonl"
    n_launched = len(launches.read_text().splitlines()) if launches.is_file() else None
    unsettled = max(0, n_launched - len(validation_attempts)) if n_launched is not None else None
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
        "fit_duration_scope": time_scope,
        "one_gpu_training_job_hours": fit_resource["elapsed_seconds"] / 3600,
        "recorded_parked_seconds": paused,
        "one_gpu_fit_wall_hours_minus_recorded_parking": (fit_resource["elapsed_seconds"] - paused)
        / 3600,
        "matching_recorded_park_intervals": merged,
        "one_gpu_retrieval_job_hours": evaluation_seconds / 3600,
        "retrieval_validation_settled_invocations": len(validation_attempts),
        "retrieval_validation_launches": n_launched,
        "unsettled_validation_invocations": unsettled,
        "validation_duration_scope": "settled invocations"
        if unsettled == 0
        else "known lower bound",
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
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--prepare-terminal", action="store_true")
    parser.add_argument("--begin-validation", action="store_true")
    parser.add_argument("--archive-terminal", type=Path, metavar="BASE_SAFETENSORS")
    parser.add_argument("--schedule", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.archive_terminal:
        archive_terminal(args.run, args.archive_terminal)
        raise SystemExit(0)
    if args.prepare_terminal:
        prepare_terminal(args.run)
        raise SystemExit(0)
    if args.begin_validation:
        begin_validation(args.run)
        raise SystemExit(0)
    if args.roster is None:
        parser.error("Summary requires --roster")
    result = summarize(args.run, args.roster, args.schedule)
    plot_curve(args.run, complete_curve(args.run))
    write_receipt(args.run / "reference-result.json", result)
    print(json.dumps(result, indent=2))

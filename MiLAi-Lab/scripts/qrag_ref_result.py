"""Summarize the completed official optimizer schedule and fixed-roster retrieval evaluation."""

import argparse
import fcntl
import json
import math
import os
import select
import subprocess
import time
from pathlib import Path

import yaml


def measured_curve(run):
    # An observer may read between the training process's write and final newline.
    raw = (run / "tb_logs/reference-curve.jsonl").read_bytes()
    complete = raw[: raw.rfind(b"\n") + 1]
    rows = [json.loads(line) for line in complete.splitlines()]
    if not rows or [r["optimizer_updates"] for r in rows] != list(range(0, 100 * len(rows), 100)):
        raise ValueError("Expected the measured prefix of the official validation schedule")
    if rows[-1]["optimizer_updates"] > 10_000 or any(
        not math.isfinite(r[k]) for r in rows for k in ("gt_train_return", "gt_dev_return")
    ):
        raise ValueError("Invalid recorded REF return or step")
    return rows


def complete_curve(run):
    curve = measured_curve(run)
    if curve[-1]["optimizer_updates"] != 10_000:
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


def begin_validation(run, roster=None):
    rows, discarded = repair_tail(run / "eval_seed42.jsonl")
    if rows and roster is not None:
        from qrag_ref_retrieval import grade_row

        expected = set(json.loads(roster.read_text())["groups"])
        seen = set()
        for line in (run / "eval_seed42.jsonl").read_text().splitlines():
            row = json.loads(line)
            if row["id"] not in expected or row["id"] in seen:
                raise ValueError("Retained native retrieval row violates the fixed roster")
            grade_row(row)
            seen.add(row["id"])
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


def draw_gt_history(ax, curve, train_label, dev_label, *, markers=False):
    x = [r["optimizer_updates"] for r in curve]
    train = ax.plot(
        x,
        [r["gt_train_return"] for r in curve],
        color="#a65e26",
        linewidth=1.9,
        linestyle="--",
        marker="s" if markers else None,
        markerfacecolor="white",
        markersize=6,
        label=train_label,
    )[0]
    dev = ax.plot(
        x,
        [r["gt_dev_return"] for r in curve],
        color="#126782",
        linewidth=2.4,
        marker="o" if markers else None,
        markersize=5,
        label=dev_label,
    )[0]
    return train, dev


def plot_progress(run):
    from matplotlib import font_manager, rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import MaxNLocator

    curve = measured_curve(run)
    latest = curve[-1]["optimizer_updates"]
    installed = {f.name for f in font_manager.fontManager.ttflist}
    font = next(
        (n for n in ("Noto Sans CJK SC", "WenQuanYi Micro Hei", "SimHei") if n in installed), None
    )
    cn = font is not None
    with rc_context({"font.family": font or "DejaVu Sans", "axes.unicode_minus": False}):
        fig = Figure(figsize=(8.6, 4.9), facecolor="white")
        FigureCanvasAgg(fig)
        ax = fig.add_axes([0.09, 0.21, 0.86, 0.54])
        fig.text(
            0.09,
            0.94,
            "Q-RAG Reference  ·  MuSiQue-Ans",
            fontsize=18,
            weight="bold",
            color="#1b2e39",
            va="top",
        )
        cn_caption = (
            f"已验证 {latest:,} / 10,000 次优化器更新 "
            f"({latest / 100:.1f}%)  ·  {len(curve)} 个实测检查点"
        )
        en_caption = (
            f"{latest:,} / 10,000 optimizer updates validated ({latest / 100:.1f}%)"
            f" · {len(curve)} measured checkpoints"
        )
        caption = cn_caption if cn else en_caption
        fig.text(0.09, 0.862, caption, fontsize=10.5, color="#455a64", va="top")
        train, dev = draw_gt_history(
            ax,
            curve,
            "训练平均 GT 回报" if cn else "Mean train GT return",
            "DEV 全证据覆盖率" if cn else "DEV support coverage",
            markers=True,
        )
        fig.legend(
            handles=[train, dev],
            loc="upper left",
            bbox_to_anchor=(0.087, 0.807),
            ncol=2,
            frameon=False,
            fontsize=10,
            borderaxespad=0,
            handlelength=2.6,
        )
        ax.set_axisbelow(True)
        ax.grid(axis="y", color="#d6dfe2", linewidth=0.7)
        ax.spines[["top", "right"]].set_visible(False)
        for side in ("bottom", "left"):
            ax.spines[side].set_color("#afbec4")
        ax.tick_params(labelsize=10, color="#adbcc2", labelcolor="#3b505c")
        ax.set_xlabel("优化器更新次数" if cn else "Optimizer updates", fontsize=11)
        ax.set_ylabel("均值" if cn else "Mean", fontsize=11)
        margin = max(1, latest * 0.023)
        ax.set_xlim(-margin, max(latest, 1) + margin)
        maxval = max(max(r["gt_train_return"], r["gt_dev_return"]) for r in curve)
        top = min(1.0, max(0.1, math.ceil((maxval + 0.025) * 10) / 10))
        ax.set_ylim(-0.025 * top, top)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        if len(curve) <= 12:
            ax.set_xticks([r["optimizer_updates"] for r in curve])
        latest_score = curve[-1]["gt_dev_return"]
        n = int(curve[-1].get("dev_episodes", 300))
        ax.annotate(
            f"{round(n * latest_score)}/{n}",
            xy=(latest, latest_score),
            xytext=(-6, 9 if latest_score < 0.91 * top else -14),
            textcoords="offset points",
            ha="right",
            color="#07556a",
            fontsize=9,
        )
        note = (
            "训练回报在首次收齐证据时给分。额外读取会降低奖励。"
            "DEV 指固定 300 题中收齐全部支持证据的比例。"
            if cn
            else (
                "Training rewards penalize extra reads at first completion. "
                "DEV measures full support coverage on the same 300 questions."
            )
        )
        fig.text(0.09, 0.050, note, fontsize=9 if cn else 8.6, color="#455a64", va="bottom")
        target = run / "reference-learning-curve-progress.png"
        tmp = target.with_suffix(".part")
        fig.savefig(tmp, dpi=165, format="png")
        tmp.replace(target)
    return target


def plot_curve(run, curve, actors):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(10.2, 4.3), layout="constrained")
    FigureCanvasAgg(fig)
    ax, score = fig.subplots(1, 2, gridspec_kw={"width_ratios": [2.0, 1.0]})
    draw_gt_history(ax, curve, "Train (extra-read penalty)", "DEV coverage (300)")
    ax.set(
        xlabel="Optimizer updates",
        ylabel="Mean GT episode return",
        title="Q-RAG Reference · MuSiQue-Ans",
    )
    ax.axhline(curve[0]["gt_dev_return"], color="0.45", linestyle=":", label="Initial dev")
    ax.legend()
    stages = ("initial", "best", "final")
    for offset, name, label, color in (
        (-0.18, "support_f1", "Support F1", "#126782"),
        (0.18, "support_coverage_em", "Coverage EM", "#d07936"),
    ):
        score.bar(
            [i + offset for i in range(3)],
            [actors[k]["means"][name] for k in stages],
            width=0.34,
            color=color,
            label=label,
        )
    score.set(
        xticks=range(3),
        xticklabels=["Initial", "Best", "Final"],
        ylim=(0, 1),
        title="Native retrieval · same 300",
        ylabel="Mean score",
    )
    score.legend()
    fig.savefig(run / "reference-learning-curve.png", dpi=160)


def finalize_after_pid(run, pid, start_ticks):
    """Wait on the exact existing trainer. Never restart training or signal it."""
    if not start_ticks:
        raise ValueError("A bound Linux process start tick is required")
    out = run / "terminal-owner.json"
    with (run / ".terminal-owner.lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = os.pidfd_open(pid)
        try:
            proc = Path(f"/proc/{pid}")
            cmd = (proc / "cmdline").read_bytes().split(b"\0")
            tick = int((proc / "stat").read_text().split()[21])
            if (
                tick != start_ticks
                or b"train_q_rag.py" not in cmd
                or os.fsencode("logger.log_dir=" + str(run.parent)) not in cmd
            ):
                raise ValueError("Finalizer cannot bind this process to the supplied training run")
            state = {
                "owner_pid": os.getpid(),
                "session_id": os.getsid(0),
                "trainer_pid": pid,
                "trainer_start_ticks": tick,
                "upstream_run": str(run),
                "started_ns": time.time_ns(),
                "phase": "waiting_for_training_exit",
            }
            write_receipt(out, state)
            poller = select.poll()
            poller.register(fd, select.POLLIN)
            poller.poll()
            elapsed = time.clock_gettime(time.CLOCK_BOOTTIME) - tick / os.sysconf("SC_CLK_TCK")
        finally:
            os.close(fd)
        write_receipt(
            run.parent / "terminal-process-window.json",
            {
                "pid": pid,
                "elapsed_seconds": elapsed,
                "exit_code": None,
                "measurement": "Process start tick to finalizer pidfd exit notification",
            },
        )
        try:
            complete_curve(run)
            state.update(phase="retrieval_validation", training_exit_ns=time.time_ns())
            write_receipt(out, state)
            launcher = Path(__file__).with_name("qrag_reference.sh")
            with (run.parent / "retrieval-validation.log").open("a") as log:
                subprocess.run(  # noqa: S603 -- local evaluator, fixed argv, no shell
                    [str(launcher), "evaluate", str(run)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            if not (run / "reference-result.json").is_file() or not all(
                (run / "actors" / f"{kind}.json").is_file() for kind in ("best", "last")
            ):
                raise RuntimeError("Terminal summary or durable actor receipt missing")
        except Exception as exc:
            state.update(phase="incomplete", error_type=type(exc).__name__, detail=str(exc))
            write_receipt(out, state)
            raise
        state.update(phase="completed", finished_ns=time.time_ns())
        write_receipt(out, state)


def failure_diagnostic_evidence(run, native, curve):
    root = run.parent.parent.parent
    cfg = yaml.safe_load((run / "config.yaml").read_text())
    hyper = cfg.get("algo", {}).get("pqn", {}).get("hyperparams", {})
    evidence = {
        "data_and_environment": root / "ref/preflight.json",
        "fixed_dev_menu_and_support_reachability": root / "ref/fixed-dev-gt-difficulty.json",
        "matched_terminal_gradient_cpu_readback": root
        / "ref/reboot-drill/terminal-gradient-implementation/summary.json",
        "actual_optimizer_measurements": run / "optimizer-progress.jsonl",
        "real_validation_curve": run / "tb_logs/reference-curve.jsonl",
        "actual_fit_recipe": run / "config.yaml",
        "upstream_td_returns_and_twin_mse": root / "reference/Q-RAG/rl/agents/pqn.py",
        "upstream_feedback_and_termination": root / "reference/Q-RAG/rl/feedback/feedback.py",
        "native_termination_witness": run / "retrieval/final/native-protocol.json",
    }
    probes = (
        [json.loads(s) for s in evidence["actual_optimizer_measurements"].read_text().splitlines()]
        if evidence["actual_optimizer_measurements"].is_file()
        else []
    )
    measured = [r["backbone_probe_max_change"] for r in probes if "backbone_probe_max_change" in r]
    return {
        "references": {
            key: {"path": str(path), "present": path.is_file()} for key, path in evidence.items()
        },
        "actual_fit_updates": curve[-1]["optimizer_updates"],
        "observed_backbone_change": max(measured) if measured else None,
        "observed_optimizer_moment_dtypes": sorted(
            {str(r["optimizer_moment_dtype"]) for r in probes if r.get("optimizer_moment_dtype")}
        ),
        "pqn_parameters": {k: hyper.get(k) for k in ("gamma", "Lambda", "tau", "alpha")},
        "terminal_stop": native["common_protocol"],
        "matched_terminal_td_probe": native["actors"]["final"].get("terminal_gradient_probe")
        is not None,
        "historical_intermediate_ema_and_gradients": (
            "Unavailable from the published inference actors"
        ),
    }


def ancillary_resources(run):
    """Other recorded GPU job windows in this fit lineage, excluding its three actor passes."""
    items = []
    ref_root = run.parent.parent
    lineage_file = ref_root / "active-fit.json"
    lineage = json.loads(lineage_file.read_text()) if lineage_file.is_file() else {}
    cutover = ref_root / "precutover-resource-summary.json"
    if cutover.is_file() and str(run.resolve()) in (
        lineage.get("original_run"),
        lineage.get("replacement_run"),
    ):
        prior = json.loads(cutover.read_text())
        for field, scope in (
            ("stopped_original_one_gpu_process_wall_seconds", "superseded initial validation"),
            ("exposure_replay_one_gpu_log_interval_seconds", prior["replay_interval_basis"]),
        ):
            items.append(dict(scope=scope, seconds=prior[field], source=str(cutover)))
    if lineage.get("replacement_run") == str(run.resolve()):
        old = Path(lineage["original_run"])
        window = old.parent / "terminal-process-window.json"
        previous = (
            json.loads(window.read_text())
            if window.is_file()
            else lineage.get("original_process_window", {})
        )
        items.append(
            dict(
                scope="interrupted prior fit including parking",
                seconds=previous.get("elapsed_seconds"),
                source=str(window if window.is_file() else lineage_file),
            )
        )
        costs = old / "interrupted-best-retrieval/validation-resource.jsonl"
        if costs.is_file():
            with costs.open() as stream:
                settled = [json.loads(line) for line in stream if line.endswith("\n")]
            items.append(
                dict(
                    scope="interrupted actor retrieval on fixed TUNE",
                    seconds=sum(row["elapsed_seconds"] for row in settled),
                    settled_attempts=len(settled),
                    source=str(costs),
                )
            )
    for probe_file in sorted(run.glob("native-restart-probe*.json")):
        probe = json.loads(probe_file.read_text())
        items.append(
            dict(
                scope="independent native restart replay",
                seconds=probe["one_gpu_wall_seconds"],
                source=str(probe_file),
            )
        )
    known = sum(row["seconds"] for row in items if row["seconds"] is not None)
    return {"windows": items, "known_gpu_job_hours": known / 3600}


def summarize(run: Path, roster: Path, schedules: list[Path]) -> dict:
    curve = complete_curve(run)
    from qrag_ref_retrieval import paired_evaluation

    native = paired_evaluation(run, json.loads(roster.read_text()), curve)
    actors = native["actors"]
    settled = run.parent / "fit-resource.json"
    if not settled.is_file() and (run.parent / "terminal-process-window.json").is_file():
        settled = run.parent / "terminal-process-window.json"
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

    if fit_resource.get("exit_code") not in {None, 0}:
        raise ValueError("The reference fit returned an error")
    resources = [row["resource"] for row in actors.values()]
    evaluation_hours = sum(r["one_gpu_job_hours"] for r in resources)
    n_attempts = sum(r["settled_invocations"] for r in resources)
    n_launched = (
        sum(r["launches"] for r in resources)
        if all(r["launches"] is not None for r in resources)
        else None
    )
    unsettled = (
        sum(r["unsettled_invocations"] for r in resources) if n_launched is not None else None
    )
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
    ancillary = ancillary_resources(run)
    return {
        "other_recorded_ref_costs": ancillary,
        "known_ref_gpu_job_hours_including_prior_work": (
            fit_resource["elapsed_seconds"] / 3600
            + evaluation_hours
            + ancillary["known_gpu_job_hours"]
        ),
        "fit_duration_scope": time_scope,
        "one_gpu_training_job_hours": fit_resource["elapsed_seconds"] / 3600,
        "recorded_parked_seconds": paused,
        "one_gpu_fit_wall_hours_minus_recorded_parking": (fit_resource["elapsed_seconds"] - paused)
        / 3600,
        "matching_recorded_park_intervals": merged,
        "one_gpu_retrieval_job_hours": evaluation_hours,
        "native_retrieval": native,
        "failure_diagnostic_evidence": failure_diagnostic_evidence(run, native, curve),
        "retrieval_validation_settled_invocations": n_attempts,
        "retrieval_validation_launches": n_launched,
        "unsettled_validation_invocations": unsettled,
        "validation_duration_scope": "settled invocations"
        if unsettled == 0
        else "known lower bound",
        "resource_unit": "One assigned GPU times process wall duration, including setup and I/O",
        "reference": "official MuSiQue-Ans GT/PQN with fixed TUNE retrieval validation",
        "optimizer_updates": curve[-1]["optimizer_updates"],
        "critic_transitions": curve[-1]["critic_transitions"],
        "evaluated_groups": 300,
        "training_clock_seconds_to_final_validation": curve[-1]["elapsed_seconds"],
        "peak_gpu_allocated_bytes": max(r["peak_gpu_allocated_bytes"] for r in curve),
        "initial_dev_gt_return": curve[0]["gt_dev_return"],
        "final_dev_gt_return": curve[-1]["gt_dev_return"],
        "best_dev_gt_return": max(r["gt_dev_return"] for r in curve),
        "best_actor_support_f1": actors["best"]["means"]["support_f1"],
        "best_actor_support_em": actors["best"]["means"]["support_coverage_em"],
        "best_actor_gt_return": actors["best"]["means"]["gt_return"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--plot-progress", action="store_true")
    parser.add_argument("--prepare-terminal", action="store_true")
    parser.add_argument("--begin-validation", action="store_true")
    parser.add_argument("--archive-terminal", type=Path, metavar="BASE_SAFETENSORS")
    parser.add_argument("--schedule", type=Path, action="append", default=[])
    parser.add_argument("--follow-pid", type=int)
    parser.add_argument("--start-ticks", type=int)
    args = parser.parse_args()
    if args.plot_progress:
        print(plot_progress(args.run))
        raise SystemExit(0)
    if args.follow_pid is not None:
        finalize_after_pid(args.run.resolve(), args.follow_pid, args.start_ticks)
        raise SystemExit(0)
    if args.archive_terminal:
        archive_terminal(args.run, args.archive_terminal)
        raise SystemExit(0)
    if args.prepare_terminal:
        prepare_terminal(args.run, need_best=False)
        raise SystemExit(0)
    if args.begin_validation:
        begin_validation(args.run, args.roster)
        raise SystemExit(0)
    if args.roster is None:
        parser.error("Summary requires --roster")
    result = summarize(args.run, args.roster, args.schedule)
    plot_curve(args.run, complete_curve(args.run), result["native_retrieval"]["actors"])
    write_receipt(args.run / "reference-result.json", result)
    print(json.dumps(result, indent=2))

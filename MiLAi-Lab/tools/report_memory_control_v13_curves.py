"""Bind a real feedback checkpoint to its frozen DEV readout and render matched learning curves."""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path

from report_memory_control_v13_feedback import billed_usage, record_billed_tokens


def read(path):
    return json.loads(path.read_text())


def fit_window_usage(directory):
    rows = [read(path) for path in sorted((directory / "fit-windows").glob("*.json"))]
    closed = [
        row
        for row in rows
        if row["state"] in {"returned", "failed"}
        and row["device_count"] == 1
        and row.get("wall_seconds", -1) >= 0
    ]
    return dict(
        measured_hours=sum(row["wall_seconds"] for row in closed) / 3600,
        complete=bool(rows)
        and len(closed) == len(rows)
        and not any(row["earlier_unmetered_fit"] for row in rows),
        closed_invocations=len(closed),
        failed_invocations=sum(row["state"] == "failed" for row in closed),
        measurement_scopes=sorted({row["scope"] for row in rows}),
    )


def qr_usage(directory, calls):
    updates = [(p, read(p)) for p in sorted((directory / "updates").glob("*.json"))]
    boundary, last = next((p, u) for p, u in updates if u["feedback_calls"] == calls)
    last_position = int(boundary.stem)
    tokens, known, exposure, new, unknown = 0, 0, 0, 0, 0
    provider = Counter()
    paid = set()
    for path in (directory / "receipts").glob("*.json.gz"):
        position = int(path.name.split("_episode", 1)[1].split("_task", 1)[0])
        if position > last_position:
            continue
        with gzip.open(path) as stream:
            r = json.load(stream)
        exposure += r["feedback_exposure"]
        if r.get("actual_requests") is None:
            unknown += 1
        else:
            new += r["actual_requests"]
            if r["actual_requests"]:
                span = range(r["ledger_before"], r["ledger_after"])
                if len(span) != r["actual_requests"] or paid.intersection(span):
                    raise ValueError("QR receipts disagree with their newly charged ledger slots")
                paid.update(span)
        record_billed_tokens(provider, r)
        if r["feedback_exposure"]:
            i, o = (r["costs"].get("reader_" + part + "_tokens") for part in ("input", "output"))
            if i is not None and o is not None:
                known += 1
                tokens += i + o
    if exposure != calls:
        raise ValueError("QR update and trajectory receipts disagree at checkpoint")
    return dict(
        exposure=exposure,
        new_requests=new,
        unknown_new=unknown,
        tokens=tokens if known == exposure else None,
        **billed_usage(provider, new, unknown),
        fit_gpu_hours=last["cumulative_fit_seconds"] / 3600
        if last.get("cumulative_fit_seconds") is not None
        else None,
        acquisition_and_fit_gpu_hours=last.get("controller_gpu_residency_hours"),
    )


def value_usage(rollouts, fits):
    from report_memory_control_v13_feedback import report

    accounting = report(rollouts)
    if len(set(p.resolve() for p in fits)) != len(fits):
        raise ValueError("Duplicate fit cost")
    fit_seconds = 0.0
    parked_seconds = 0.0
    fit_windows = {}
    root = rollouts[0].resolve().parent
    phase_path = root / "initial-schedule.json"
    phase = read(phase_path) if phase_path.exists() else {}
    for p in fits:
        info = read(p / "run.json")
        if info["status"] != "completed" or not info["cuda_peak_bytes"]:
            raise ValueError("Expected a closed CUDA fit with measured time")
        fit_seconds += info["wall_seconds"]
        fit_windows[str(p.resolve())] = fit_window_usage(p)
        # The fit loop's perf_counter includes the parked interval; GPU memory stayed resident.
        if (
            (root / "weights/s1").is_dir()
            and p.samefile(root / "weights/s1")
            and phase.get("ended_ns")
            and phase.get("started_ns")
        ):
            parked_seconds += (phase["ended_ns"] - phase["started_ns"]) / 1e9
    collect_hours = 0.0
    for p in rollouts:
        coverage = [read(f) for f in (p / "compute").glob("*.json")]
        if not coverage:
            cfg = read(p / "round.json")
            if cfg["sampling_checkpoint"] or cfg["continuation_policy_id"] != "pi0-fixedcontext-4":
                collect_hours = None
                break
        collect_hours += sum(v["controller_gpu_residency_hours"] for v in coverage)
    tokens = known = 0
    for rnd in accounting["rounds"]:
        for axis in ("reader_input_tokens", "reader_output_tokens"):
            stat = rnd["resources"].get(axis, {})
            tokens += stat.get("exposed_total", 0)
            known += stat.get("exposed_observations", 0)
    calls = accounting["total_feedback_exposure"]
    measured_fit_hours = (
        sum(record["measured_hours"] for record in fit_windows.values())
        if fit_windows and all(record["complete"] for record in fit_windows.values())
        else None
    )
    selection = {
        key: sum(
            values[key]
            for rnd in accounting["rounds"]
            for values in rnd["selection_exposure_by_source"].values()
        )
        for key in (
            "reserved_uniform_exposure",
            "fallback_uniform_exposure",
            "positive_priority_exposure",
        )
    }
    selection["unattributed_exposure"] = calls - sum(selection.values())
    return dict(
        selection=selection,
        exposure=calls,
        new_requests=accounting["verified_unique_new_reader_requests"],
        unknown_new=accounting["unknown_request_count_receipts_in_distinct_directories"],
        tokens=tokens if known == 2 * calls else None,
        **accounting["newly_billed_usage"],
        fit_gpu_hours=fit_seconds / 3600,
        fit_job_window_gpu_hours=measured_fit_hours,
        fit_job_windows=fit_windows,
        registered_fit_parking_hours=parked_seconds / 3600,
        fit_wall_hours_excluding_registered_parking=(fit_seconds - parked_seconds) / 3600,
        acquisition_and_fit_gpu_hours=None
        if collect_hours is None or measured_fit_hours is None
        else collect_hours + measured_fit_hours,
    )


def point(args):
    from report_memory_control_v13_deployment import summarize_run

    deployment = summarize_run(args.evaluation)
    protocol = read(args.evaluation / "protocol.json")
    cohort = protocol["population"]
    if cohort["role"] != "dev" or cohort.get("v13_role") != "curve":
        raise ValueError("Feedback learning curves require the frozen natural DEV curve cohort")
    usage = qr_usage(args.qr, args.calls) if args.qr else value_usage(args.rollouts, args.fits)
    if usage["exposure"] != args.calls:
        raise ValueError("Declared checkpoint differs from charged supervision")
    if args.qr:
        evidence = read(Path(deployment["arm"]["checkpoint"]) / "training.json")
        if evidence["calls"] != args.calls or evidence["seed"] != args.acquisition_seed:
            raise ValueError("Readout does not use the specified QR checkpoint")
    elif Path(deployment["arm"]["checkpoint"]).parent.resolve() != args.fits[-1].resolve():
        raise ValueError("Readout checkpoint and last fitted controller differ")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out = dict(
        method=args.method,
        acquisition_seed=args.acquisition_seed,
        fit_seed=args.fit_seed,
        usage=usage,
        deployment=deployment,
        cohort=cohort,
        acquisition_paths=[str(p.resolve()) for p in args.rollouts],
        fit_paths=[str(p.resolve()) for p in args.fits],
        qr_path=str(args.qr) if args.qr else None,
    )
    pending = args.output.with_suffix(".tmp")
    pending.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n")
    pending.replace(args.output)


def plot(args):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = [read(p) for p in args.points]
    baselines = (
        [d for d in read(args.baselines) if d["arm"]["policy"] != "G"] if args.baselines else []
    )
    cohorts = [r["cohort"] for r in rows]
    cohorts.extend(read(Path(d["path"]) / "protocol.json")["population"] for d in baselines)
    if not cohorts:
        raise ValueError("Supply at least one measured checkpoint or deployable baseline")
    ref = cohorts[0]
    if ref.get("v13_role") != "curve" or any(cohort != ref for cohort in cohorts):
        raise ValueError(
            "All plotted checkpoints must share the same tasks, budgets and Reader seeds"
        )
    series = {}
    for r in rows:
        key = (r["method"], r["acquisition_seed"], r["fit_seed"])
        series.setdefault(key, []).append(r)
    if any(len({r["usage"]["exposure"] for r in group}) != len(group) for group in series.values()):
        raise ValueError("Duplicate checkpoint inside a series")
    baseline_labels = {}
    for d in baselines:
        a = d["arm"]
        if a["policy"] == "gte_relevance":
            label = f"GTE relevance ({a['reads']} reads, {a['precision']})"
        elif a["policy"] == "B1":
            label = f"BM25 ({a['reads']} reads)"
        else:
            label = a["name"]
        baseline_labels[a["name"]] = label
    tasks = ref["tasks"]
    groups = {(t["dataset"], t["native_group"]) for t in tasks}
    cohort_title = (
        f"Natural DEV ({len(tasks)} tasks, {len(groups)} native groups, "
        f"{ref['material_budget']:,} memory tokens)"
    )
    args.output.mkdir(parents=True, exist_ok=True)
    for field, unit in (
        ("exposure", "Feedback exposures, including imported measurements"),
        ("billed_reader_calls", "New Reader calls in the arm's data, including shared warm"),
        ("tokens", "Input + output tokens in exposed feedback (same Reader)"),
        ("billed_reader_tokens", "Newly billed provider input + output tokens in the arm's data"),
        ("acquisition_and_fit_gpu_hours", "Controller GPU-hours during fits and collection"),
    ):
        if not any(r["usage"].get(field) is not None for r in rows):
            continue
        fig, axes = plt.subplots(2, 2, sharex=True, figsize=(10, 7.5), layout="constrained")
        for ax, axis in zip(
            axes.flat, ("Macro", "musique_full", "qasper", "personamem_v2"), strict=True
        ):
            for label, group in sorted(series.items()):
                points = sorted(
                    (r for r in group if r["usage"].get(field) is not None),
                    key=lambda r: r["usage"]["exposure"],
                )
                x = [r["usage"][field] for r in points]
                bounds = [
                    r["deployment"]["macro_range_points"]
                    if axis == "Macro"
                    else [100 * v for v in r["deployment"]["native"][axis]["full_range"]]
                    for r in points
                ]
                ax.plot(
                    x,
                    [v[0] for v in bounds],
                    marker="o",
                    label=f"{label[0]} (a{label[1]}/f{label[2]})",
                )
                ax.vlines(x, [v[0] for v in bounds], [v[1] for v in bounds], linewidth=2)
            for position, d in enumerate(baselines):
                bound = (
                    d["macro_range_points"]
                    if axis == "Macro"
                    else [100 * v for v in d["native"][axis]["full_range"]]
                )
                ax.axhline(
                    bound[0],
                    color=f"C{position + len(series)}",
                    linewidth=1,
                    linestyle="--",
                    label=baseline_labels[d["arm"]["name"]],
                )
                if bound[0] != bound[1]:
                    ax.axhspan(bound[0], bound[1], alpha=0.12, color=f"C{position + len(series)}")
            ax.set_title(axis)
            ax.grid(alpha=0.2)
            ax.set_ylabel("Native quality (points)")
            ax.ticklabel_format(axis="x", style="sci", scilimits=(0, 4))
        axes[0, 0].legend(fontsize=8)
        fig.suptitle(cohort_title)
        fig.supxlabel(unit)
        fig.savefig(args.output / (field + ".pdf"))
        plt.close(fig)
    for filename, dimensions in (
        (
            "deployment-resources",
            (
                ("reader_input_tokens", "Reader input tokens / task"),
                ("reader_output_tokens", "Reader output tokens / task"),
                ("controller_gpu_ms", "Controller forward GPU-ms / task"),
            ),
        ),
        ("deployment-latency", (("p50", "End-to-end p50 (ms)"), ("p95", "End-to-end p95 (ms)"))),
    ):
        fig, axes = plt.subplots(
            1,
            len(dimensions),
            sharey=True,
            figsize=(4.3 * len(dimensions), 4.2),
            layout="constrained",
        )
        for ax, (field, axis_label) in zip(axes, dimensions, strict=True):
            data = [
                (
                    f"{label[0]} (a{label[1]}/f{label[2]})",
                    [r["deployment"] for r in sorted(group, key=lambda v: v["usage"]["exposure"])],
                    "o-",
                )
                for label, group in sorted(series.items())
            ]
            data.extend((baseline_labels[d["arm"]["name"]], [d], "D") for d in baselines)
            for position, (label, group, style) in enumerate(data):
                xs, ys = [], []
                for d in group:
                    if field in ("p50", "p95"):
                        stat = d["live_readout_plus_load_ms"]
                        val = stat[field] if stat["n"] == d["actual_reader_calls"] else None
                    else:
                        stat = d["resources"].get(field, {"n": 0})
                        val = (
                            stat["total"] / stat["n"]
                            if stat["n"] and stat["n"] == d["actual_reader_calls"]
                            else None
                        )
                    if val is not None:
                        xs.append(val)
                        ys.append(d["macro_range_points"][0])
                if xs:
                    ax.plot(xs, ys, style, label=label, color=f"C{position % 10}")
            ax.set_xlabel(axis_label)
            if ax is axes[0]:
                ax.set_ylabel("Macro quality lower bound (points)")
            ax.grid(alpha=0.2)
        fig.suptitle(cohort_title)
        axes[0].legend(fontsize=8)
        fig.savefig(args.output / (filename + ".pdf"))
        fig.savefig(args.output / (filename + ".png"), dpi=120)
        plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    acc = sub.add_parser("point")
    acc.add_argument("--evaluation", type=Path, required=True)
    acc.add_argument("--method", required=True)
    acc.add_argument("--calls", type=int, required=True)
    acc.add_argument("--acquisition-seed", type=int, default=11)
    acc.add_argument("--fit-seed", type=int, default=11)
    inputs = acc.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--qr", type=Path)
    inputs.add_argument("--rollouts", nargs="+", type=Path, default=[])
    acc.add_argument("--fits", nargs="+", type=Path, default=[])
    acc.add_argument("--output", type=Path, required=True)
    drawing = sub.add_parser("plot")
    drawing.add_argument("--points", nargs="*", type=Path, default=[])
    drawing.add_argument(
        "--baselines", type=Path, help="Measured deployment report on the same natural DEV tasks"
    )
    drawing.add_argument("--output", type=Path, required=True)
    opts = p.parse_args()
    if opts.cmd == "point":
        if not opts.qr and not opts.fits:
            p.error("A value-learning checkpoint must identify all constituent fits")
        point(opts)
    else:
        plot(opts)

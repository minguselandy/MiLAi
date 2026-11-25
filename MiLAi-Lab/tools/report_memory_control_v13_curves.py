"""Bind a real feedback checkpoint to its frozen DEV readout and render matched learning curves."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
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


def collection_window_usage(directory):
    cfg = read(directory / "round.json")
    rows = [read(p) for p in sorted((directory / "compute").glob("*.json"))]
    learned = (
        cfg.get("sampling_checkpoint") or cfg["continuation_policy_id"] != "pi0-fixedcontext-4"
    )
    observed = []
    incomplete = 0
    for row in rows:
        measured = row.get("controller_gpu_residency_hours")
        devices = row.get("controller_devices")
        cpu_only = (
            not learned if devices is None else all(d.split(":")[0] == "cpu" for d in devices)
        )
        if measured is not None:
            if not math.isfinite(measured) or measured < 0 or (cpu_only and measured != 0):
                raise ValueError("Collection device and measured GPU residency disagree")
            observed.append(measured)
        elif cpu_only:
            observed.append(0.0)
        if not cpu_only and (measured is None or not row.get("complete_invocation")):
            incomplete += 1
    return dict(
        measured_hours=sum(observed) if observed or not learned else None,
        complete=(bool(rows) or not learned) and incomplete == 0,
        recorded_invocations=len(rows),
        unfinished_invocations=sum(not r.get("complete_invocation") for r in rows),
        incomplete_gpu_windows=incomplete,
    )


def qr_boundary(directory, calls):
    for path in sorted((directory / "updates").glob("*.json")):
        update = read(path)
        if update["feedback_calls"] == calls:
            return path, update
    raise FileNotFoundError(f"No QR update at {calls} calls under {directory}")


def qr_gpu_usage(update):
    residence = update.get("controller_gpu_residency_hours")
    if residence is not None and (not math.isfinite(residence) or residence < 0):
        raise ValueError("Invalid QR controller residency")
    incomplete = update.get("earlier_incomplete_compute_invocations")
    cpu_only = update.get("controller_device", "").split(":")[0] == "cpu" and residence == 0
    complete = residence is not None and (incomplete == 0 or cpu_only)
    return dict(
        acquisition_and_fit_gpu_hours=residence if complete else None,
        observed_acquisition_and_fit_gpu_hours=residence,
        controller_gpu_hours_complete=complete,
        earlier_incomplete_compute_invocations=incomplete,
    )


def qr_usage(directory, calls):
    boundary, last = qr_boundary(directory, calls)
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
        **qr_gpu_usage(last),
    )


def value_gpu_usage(rollouts, fits):
    fit_windows = {str(p.resolve()): fit_window_usage(p) for p in fits}
    collection_windows = {str(p.resolve()): collection_window_usage(p) for p in rollouts}
    fit_hours = sum(window["measured_hours"] for window in fit_windows.values())
    fit_complete = bool(fit_windows) and all(w["complete"] for w in fit_windows.values())
    observed = [
        window["measured_hours"] for window in fit_windows.values() if window["closed_invocations"]
    ] + [
        window["measured_hours"]
        for window in collection_windows.values()
        if window["measured_hours"] is not None
    ]
    known_hours = sum(observed) if observed else None
    complete = (
        fit_complete
        and bool(collection_windows)
        and all(w["complete"] for w in collection_windows.values())
    )
    return dict(
        fit_job_window_gpu_hours=fit_hours if fit_complete else None,
        fit_job_windows=fit_windows,
        collection_gpu_windows=collection_windows,
        observed_acquisition_and_fit_gpu_hours=known_hours,
        controller_gpu_hours_complete=complete,
        acquisition_and_fit_gpu_hours=known_hours if complete else None,
    )


def value_usage(rollouts, fits):
    from report_memory_control_v13_feedback import report

    accounting = report(rollouts)
    if len(set(p.resolve() for p in fits)) != len(fits):
        raise ValueError("Duplicate fit cost")
    fit_seconds = 0.0
    parked_seconds = 0.0
    root = rollouts[0].resolve().parent
    phase_path = root / "initial-schedule.json"
    phase = read(phase_path) if phase_path.exists() else {}
    for p in fits:
        info = read(p / "run.json")
        if info["status"] != "completed" or not info["cuda_peak_bytes"]:
            raise ValueError("Expected a closed CUDA fit with measured time")
        fit_seconds += info["wall_seconds"]
        # The fit loop's perf_counter includes the parked interval; GPU memory stayed resident.
        if (
            (root / "weights/s1").is_dir()
            and p.samefile(root / "weights/s1")
            and phase.get("ended_ns")
            and phase.get("started_ns")
        ):
            parked_seconds += (phase["ended_ns"] - phase["started_ns"]) / 1e9
    tokens = known = 0
    for rnd in accounting["rounds"]:
        for axis in ("reader_input_tokens", "reader_output_tokens"):
            stat = rnd["resources"].get(axis, {})
            tokens += stat.get("exposed_total", 0)
            known += stat.get("exposed_observations", 0)
    calls = accounting["total_feedback_exposure"]
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
        registered_fit_parking_hours=parked_seconds / 3600,
        fit_wall_hours_excluding_registered_parking=(fit_seconds - parked_seconds) / 3600,
        **value_gpu_usage(rollouts, fits),
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


def export_cost_table(directory, points, baselines):
    """Write the measurements behind the curves. Empty cells retain unmeasured quantities."""
    training_axes = {
        "exposure": "training_feedback_exposures",
        "tokens": "training_exposed_reader_tokens",
        "billed_reader_calls": "training_billed_reader_calls",
        "billed_reader_input_tokens": "training_billed_reader_input_tokens",
        "billed_reader_output_tokens": "training_billed_reader_output_tokens",
        "fit_gpu_hours": "training_reported_fit_loop_wall_hours",
        "fit_job_window_gpu_hours": "training_fit_job_gpu_hours",
        "observed_acquisition_and_fit_gpu_hours": "training_observed_controller_gpu_hours",
        "acquisition_and_fit_gpu_hours": "training_collection_and_fit_controller_gpu_hours",
    }
    records = []
    deployments = [
        (row["method"], row["acquisition_seed"], row["fit_seed"], row["usage"], row["deployment"])
        for row in sorted(
            points,
            key=lambda p: (
                p["method"],
                p["acquisition_seed"],
                p["fit_seed"],
                p["usage"]["exposure"],
            ),
        )
    ]
    # These fixed controls use no new V13 training feedback or fit GPU-hours.
    for d in baselines:
        deployments.append((d["arm"]["name"], None, None, dict.fromkeys(training_axes, 0), d))
    for method, acq, seed, usage, d in deployments:
        row = dict(method=method, acquisition_seed=acq, fit_seed=seed)
        row.update({column: usage.get(axis) for axis, column in training_axes.items()})
        row["training_controller_gpu_hours_complete"] = (
            True if acq is None else usage.get("controller_gpu_hours_complete")
        )
        row.update(
            dev_tasks=d["registered_tasks"],
            dev_native_groups=d["registered_groups"],
            material_budget_tokens=d["material_budget"],
            macro_quality_lower_points=d["macro_range_points"][0],
            macro_quality_upper_points=d["macro_range_points"][1],
        )
        for source in ("musique_full", "qasper", "personamem_v2"):
            observed = d["native"][source]
            low, high = observed["full_range"]
            row[source + "_quality_lower_points"] = 100 * low
            row[source + "_quality_upper_points"] = 100 * high
            row[source + "_unobserved_units"] = observed["unknown"]
        row["dev_known_new_reader_calls"] = d["actual_reader_calls"]
        row["dev_reader_charge_lower_bound_only"] = d.get("reader_charge_lower_bound_only")
        for axis in (
            "reader_input_tokens",
            "reader_output_tokens",
            "controller_gpu_ms",
            "pool_and_bm25_wall_ms",
            "navigation_and_admission_wall_ms",
        ):
            stat = d["resources"].get(axis, {})
            row["dev_" + axis + "_observed_tasks"] = stat.get("n", 0)
            row["dev_" + axis + "_observed_total"] = stat.get("total") if stat.get("n") else None
        latency = d["live_readout_plus_load_ms"]
        row.update(
            dev_latency_observed_tasks=latency["n"],
            dev_p50_with_load_ms=latency["p50"],
            dev_p95_with_load_ms=latency["p95"],
            deployment_path=d["path"],
        )
        records.append(row)
    if records:
        path = directory / "checkpoint-costs.csv"
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        tmp.replace(path)


def read_curve_point(path):
    row = read(path)
    usage = row["usage"]
    if "controller_gpu_hours_complete" in usage:
        return row
    # Legacy points stored a number even when an earlier GPU meter stopped mid-run.
    # Reconstruct coverage from timing receipts without reloading outcomes or models.
    saved = usage.get("acquisition_and_fit_gpu_hours")
    usage.update(
        observed_acquisition_and_fit_gpu_hours=saved,
        acquisition_and_fit_gpu_hours=None,
        controller_gpu_hours_complete=False,
    )
    if row.get("qr_path"):
        try:
            _, update = qr_boundary(Path(row["qr_path"]), usage["exposure"])
        except FileNotFoundError:
            return row
        usage.update(qr_gpu_usage(update))
    elif row.get("acquisition_paths") and row.get("fit_paths"):
        rollouts = [Path(p) for p in row["acquisition_paths"]]
        fits = [Path(p) for p in row["fit_paths"]]
        if all((p / "round.json").is_file() for p in rollouts) and all(
            (p / "fit-windows").is_dir() for p in fits
        ):
            usage.update(value_gpu_usage(rollouts, fits))
    if saved is not None and not usage["controller_gpu_hours_complete"]:
        measured = usage.get("observed_acquisition_and_fit_gpu_hours")
        usage["observed_acquisition_and_fit_gpu_hours"] = max(saved, measured or 0)
    return row


def plot(args):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = [read_curve_point(p) for p in args.points]
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
    export_cost_table(args.output, rows, baselines)
    for field, unit in (
        ("exposure", "Feedback exposures, including imported measurements"),
        ("billed_reader_calls", "New Reader calls in the arm's data, including shared warm"),
        ("tokens", "Input + output tokens in exposed feedback (same Reader)"),
        ("billed_reader_tokens", "Newly billed provider input + output tokens in the arm's data"),
        ("fit_job_window_gpu_hours", "GPU-hours in dedicated controller fitting jobs"),
        ("acquisition_and_fit_gpu_hours", "Controller GPU-hours during fits and collection"),
    ):
        if not any(r["usage"].get(field) is not None for r in rows):
            (args.output / (field + ".pdf")).unlink(missing_ok=True)
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
                if not points:
                    continue
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
            latency = field in ("p50", "p95")
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
                    stat = d["live_readout_plus_load_ms"] if latency else d["resources"].get(field)
                    if not stat or not stat["n"] or stat["n"] != d["registered_tasks"]:
                        continue
                    xs.append(stat[field] if latency else stat["total"] / stat["n"])
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

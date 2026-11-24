"""Bind a real feedback checkpoint to its frozen DEV readout and render matched learning curves."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def qr_usage(directory, calls):
    updates = [(p, read(p)) for p in sorted((directory / "updates").glob("*.json"))]
    boundary, last = next((p, u) for p, u in updates if u["feedback_calls"] == calls)
    last_position = int(boundary.stem)
    tokens, known, exposure, new, unknown = 0, 0, 0, 0, 0
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
        fit_gpu_hours=last["cumulative_fit_seconds"] / 3600,
        acquisition_and_fit_gpu_hours=last["controller_gpu_residency_hours"],
    )


def value_usage(rollouts, fits):
    from report_memory_control_v13_feedback import report

    accounting = report(rollouts)
    if len(set(p.resolve() for p in fits)) != len(fits):
        raise ValueError("Duplicate fit cost")
    fit_seconds = 0.0
    for p in fits:
        info = read(p / "run.json")
        if info["status"] != "completed" or not info["cuda_peak_bytes"]:
            raise ValueError("Expected a closed CUDA fit with measured time")
        fit_seconds += info["wall_seconds"]
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
    return dict(
        exposure=calls,
        new_requests=accounting["verified_unique_new_reader_requests"],
        unknown_new=accounting["unknown_request_count_receipts_in_distinct_directories"],
        tokens=tokens if known == 2 * calls else None,
        fit_gpu_hours=fit_seconds / 3600,
        acquisition_and_fit_gpu_hours=None
        if collect_hours is None
        else collect_hours + fit_seconds / 3600,
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
    args.output.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n")


def plot(args):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = [read(p) for p in args.points]
    ref = rows[0]["cohort"]
    if any(r["cohort"] != ref for r in rows):
        raise ValueError(
            "All plotted checkpoints must share the same tasks, budgets and Reader seeds"
        )
    series = {}
    for r in rows:
        key = (r["method"], r["acquisition_seed"], r["fit_seed"])
        series.setdefault(key, []).append(r)
    if any(len({r["usage"]["exposure"] for r in group}) != len(group) for group in series.values()):
        raise ValueError("Duplicate checkpoint inside a series")
    args.output.mkdir(parents=True, exist_ok=True)
    for field, unit in (
        ("exposure", "Training feedback calls exposed to each arm"),
        ("tokens", "Training feedback input + output tokens (same Reader)"),
        ("acquisition_and_fit_gpu_hours", "Controller GPU-hours during fits and collection"),
    ):
        fig, axes = plt.subplots(2, 2, sharex=True, figsize=(10, 7.5), layout="constrained")
        for ax, axis in zip(
            axes.flat, ("Macro", "musique_full", "qasper", "personamem_v2"), strict=True
        ):
            for label, group in sorted(series.items()):
                points = sorted(
                    (r for r in group if r["usage"][field] is not None),
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
            ax.set_title(axis)
            ax.grid(alpha=0.2)
            ax.set_ylabel("Native quality (points)")
            ax.ticklabel_format(axis="x", style="sci", scilimits=(0, 4))
        axes[0, 0].legend(fontsize=8)
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
            1, len(dimensions), figsize=(4.3 * len(dimensions), 4.2), layout="constrained"
        )
        for ax, (field, title) in zip(axes, dimensions, strict=True):
            for label, group in sorted(series.items()):
                xs, ys = [], []
                for r in sorted(group, key=lambda v: v["usage"]["exposure"]):
                    d = r["deployment"]
                    if field in ("p50", "p95"):
                        stat = d["live_readout_plus_load_ms"]
                        val = stat[field] if stat["n"] == d["actual_reader_calls"] else None
                    else:
                        stat = d["resources"][field]
                        val = (
                            stat["total"] / stat["n"]
                            if stat["n"] and stat["n"] == d["actual_reader_calls"]
                            else None
                        )
                    if val is not None:
                        xs.append(val)
                        ys.append(d["macro_range_points"][0])
                ax.plot(xs, ys, "o-", label=f"{label[0]} (a{label[1]}/f{label[2]})")
            ax.set_xlabel(title)
            ax.set_ylabel("Macro quality lower bound (points)")
            ax.grid(alpha=0.2)
        axes[0].legend(fontsize=8)
        fig.savefig(args.output / (filename + ".pdf"))
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
    drawing.add_argument("--points", nargs="+", type=Path, required=True)
    drawing.add_argument("--output", type=Path, required=True)
    opts = p.parse_args()
    if opts.cmd == "point":
        if not opts.qr and not opts.fits:
            p.error("A value-learning checkpoint must identify all constituent fits")
        point(opts)
    else:
        plot(opts)

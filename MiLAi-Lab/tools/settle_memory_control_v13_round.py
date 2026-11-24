"""Compare closed native DEV checkpoints and advance the planned three arms from 12k to 24k."""

from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import write_json
from milai_lab.scorers.memory_control_episode_metrics import (
    QUALITY_AXES,
    input_result,
    paired_comparison,
)
from milai_lab.scorers.memory_control_native import musique_pair
from report_memory_control_v13_deployment import summarize_run
from report_memory_control_v13_feedback import per_round
from run_memory_control_v13_rounds import json_file

METHODS = ("QR", "DQ", "PQ-U", "PQ-A")


def point_path(root, method, seed, calls):
    tag = f"qr-a{seed}-f{seed}" if method == "QR" else f"a{seed}-f{seed}-{method}"
    return root / "curve-points" / f"{tag}-{calls}.json"


def ticks(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return None
    fields = text.rpartition(")")[2].split()
    return None if fields[0] in {"Z", "X"} else fields[19]


def wait_for(root, seed, calls, owners):
    bound = {method: (pid, ticks(pid)) for method, pid in owners.items()}
    while True:
        missing = {m for m in METHODS if not point_path(root, m, seed, calls).is_file()}
        if not missing:
            return
        for method in missing:
            pid, start = bound.get(method, (None, None))
            if not start or ticks(pid) != start:
                raise RuntimeError(f"Missing {method} {calls} point and no live bound producer")
        time.sleep(30)


def wait_initial_fit(root, checkpoint, owner):
    """Wait on the real trainer for this output. A replacement can retain the same fit."""
    directory = checkpoint.parent

    def matches(pid):
        try:
            args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            output = Path(os.fsdecode(args[args.index(b"--output") + 1]))
            return (
                b"milai_lab.runners.pretrained_control_train" in args
                and args[args.index(b"--objective") + 1] == b"evidence"
                and output.samefile(directory)
                and ticks(pid) is not None
            )
        except (OSError, ValueError, IndexError):
            return False

    while True:
        record = json_file(directory / "run.json")
        if record["status"] == "completed":
            if not record["reload_scores_equal"] or not (checkpoint / "control.pt").is_file():
                raise ValueError("Completed evidence fit lacks its verified final checkpoint")
            return
        if not matches(owner):
            owner = next(
                (
                    int(p.name)
                    for p in Path("/proc").iterdir()
                    if p.name.isdigit() and matches(int(p.name))
                ),
                None,
            )
            if owner is None:
                raise RuntimeError("No running evidence fit owns the incomplete output")
        write_json(
            root / "main-study-status.json",
            dict(
                stage="waiting_for_evidence_fit",
                study_pid=os.getpid(),
                s1_owner=owner,
                checkpoint=str(checkpoint),
            ),
        )
        time.sleep(45)


def qr_prefix(root, seed):
    from evaluate_qrag_milai_checkpoints import producer_live

    train = root / f"qr-{seed}"
    while not all(point_path(root, "QR", seed, n).is_file() for n in (6000, 12000)):
        with (train / ".curve.lock").open("a") as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(30)
                continue
        store = root / "staging/qr" / ("formal" if seed == 11 else f"formal-{seed}")
        if (
            not producer_live(train)
            and not (store / "checkpoint-12000" / "training.json").is_file()
        ):
            invoke("run_qrag_milai_after_warm.py", "--root", root, "--seed", seed, "--calls", 12000)
        invoke(
            "evaluate_qrag_milai_checkpoints.py",
            "--root",
            root,
            "--seed",
            seed,
            "--calls",
            6000,
            12000,
        )


def comparison(policy, baseline, repeats):
    result = paired_comparison([policy], baseline, repeats=repeats, seed=20261125)
    fields = (
        "configured_tasks",
        "independent_groups",
        "paired_measurements_complete",
        "quality_delta_points",
        "quality_interval_95",
        "reader_input_token_savings",
        "token_savings_interval_95",
        "source_strata",
        "shared_request_sensitivity",
    )
    return {field: result[field] for field in fields}


def examples(policy, baseline):
    """Representative DEV disagreements; preserve the complete native MuSiQue pair."""
    ap, left = input_result(policy)
    bp, right = input_result(baseline)
    population = ap["population"]
    if (
        population != bp["population"]
        or population["role"] != "dev"
        or any(json_file(path / "run.json")["status"] != "COMPLETED" for path in (policy, baseline))
    ):
        raise ValueError("Failure examples require completed same-roster DEV policies")
    groups = defaultdict(list)
    excluded = population.get("predeclared_unevaluable_tasks", {})
    for t in population["tasks"]:
        if str(t["task_id"]) not in excluded:
            groups[t["dataset"], t["native_group"]].append(t["task_id"])
    counts = defaultdict(Counter)
    observations = defaultdict(list)
    diagnostic = defaultdict(lambda: defaultdict(list))
    for (source, group), members in groups.items():
        units = [members] if source == MUSIQUE else [[i] for i in members]
        for ids in units:
            if any(not r[i].get("grade") for r in (left, right) for i in ids):
                counts[source]["unobserved"] += 1
                continue
            scores = []
            for name, result in (("candidate", left), ("baseline", right)):
                grades = [result[i]["grade"]["native_metrics"] for i in ids]
                if source == MUSIQUE:
                    pair = musique_pair(grades)
                    supp = next(g for g in grades if g["gold_answerable"])
                    unsupp = next(g for g in grades if not g["gold_answerable"])
                    measured = diagnostic[name]
                    measured["answerable_answer_f1"].append(supp["answer_f1"])
                    measured["answerable_sufficiency_correct"].append(supp["sufficiency_correct"])
                    measured["unanswerable_sufficiency_correct"].append(
                        unsupp["sufficiency_correct"]
                    )
                    measured["both_sufficiency_correct"].append(pair["group_sufficiency"])
                    measured["f1_removed_by_pair_gate"].append(
                        supp["answer_f1"] - pair[QUALITY_AXES[source]]
                    )
                    scores.append(pair[QUALITY_AXES[source]])
                else:
                    scores.append(grades[0][QUALITY_AXES[source]])
            delta = scores[0] - scores[1]
            direction = "lower" if delta < 0 else "higher" if delta > 0 else "equal"
            counts[source][direction] += 1
            if delta:
                observations[source, direction].append(
                    dict(
                        group=group,
                        task_ids=ids,
                        quality_delta=delta,
                        candidate_score=scores[0],
                        baseline_score=scores[1],
                    )
                )
    selected = []
    for (source, direction), rows in sorted(observations.items()):
        center = median(r["quality_delta"] for r in rows)
        major = min(rows, key=lambda r: (-abs(r["quality_delta"]), r["group"], r["task_ids"]))
        alternatives = [r for r in rows if r["group"] != major["group"]]
        picks = [("largest_absolute", major)]
        if alternatives:
            picks.append(
                (
                    "near_median",
                    min(
                        alternatives,
                        key=lambda r: (abs(r["quality_delta"] - center), r["group"], r["task_ids"]),
                    ),
                )
            )
        for setting, row in picks:
            picked = dict(row, dataset=source, direction=direction, criterion=setting)
            for name, result in (("candidate", left), ("baseline", right)):
                picked[name + "_episodes"] = [
                    dict(
                        task_id=i,
                        prefix=result[i]["actual_cold_prefix"],
                        reason=result[i]["control"]["reason"],
                        status=result[i]["status"],
                        material_tokens=result[i]["costs"].get("reader_material_tokens"),
                        reader_input_tokens=result[i]["costs"].get("reader_input_tokens"),
                    )
                    for i in row["task_ids"]
                ]
            selected.append(picked)
    return dict(
        native_unit_counts=counts,
        musique={
            name: {k: {"n": len(v), "mean": fmean(v)} for k, v in stats.items()}
            for name, stats in diagnostic.items()
        },
        selected=selected,
        candidate=str(policy),
        baseline=str(baseline),
    )


def settle(root, seed, calls, repeats):
    points = {m: json_file(point_path(root, m, seed, calls)) for m in METHODS}
    paths = {}
    deployment = {}
    for method, record in points.items():
        if (
            record["method"] != method
            or record["fit_seed"] != seed
            or record["acquisition_seed"] != seed
            or record["usage"]["exposure"] != calls
            or record["cohort"] != points["DQ"]["cohort"]
        ):
            raise ValueError("Checkpoint cohort or budget differs from its registration")
        paths[method] = Path(record["deployment"]["path"])
        deployment[method] = record["deployment"]
    uniform = points["PQ-U"]["acquisition_paths"]
    active = points["PQ-A"]["acquisition_paths"]
    if points["DQ"]["acquisition_paths"] != uniform or uniform[0] != active[0]:
        raise ValueError("DQ and PQ-U need identical packs; both samplers require common warm data")
    for family in ("gte-batch8", "rule"):
        choice = json_file(root / "baselines" / f"{family}-selection.json")["selected"]
        paths[family] = root / "baselines/curve" / choice
        deployment[family] = summarize_run(paths[family])
    write_json(
        root / "curve-baseline-deployments.json", [deployment[k] for k in ("rule", "gte-batch8")]
    )
    contrasts = {}
    for candidate, base in (
        ("DQ", "gte-batch8"),
        ("PQ-U", "DQ"),
        ("PQ-A", "PQ-U"),
        ("PQ-A", "QR"),
        ("QR", "rule"),
        ("PQ-A", "rule"),
    ):
        result = comparison(paths[candidate], paths[base], repeats)
        left = deployment[candidate]["macro_range_points"]
        right = deployment[base]["macro_range_points"]
        result["difference_range_given_unobserved"] = [left[0] - right[1], left[1] - right[0]]
        result["quality_observations_complete"] = left[0] == left[1] and right[0] == right[1]
        contrasts[f"{candidate} vs {base}"] = result
    headroom = {}
    for method, directory in (("PQ-U", uniform[-1]), ("PQ-A", active[-1])):
        row, _ = per_round(Path(directory))
        headroom[method] = dict(
            pool=row["source_coverage"], measured=row["finite_measured_pool_gain_over_handoff"]
        )
    result = dict(
        phase="fixed_pool_mechanism" if calls == 6000 else "natural_policy_iteration",
        cumulative_feedback_per_learning_arm=calls,
        acquisition_seed=seed,
        fitting_seed=seed,
        quality_contrasts=contrasts,
        measured_action_headroom=headroom,
        checkpoints={m: str(point_path(root, m, seed, calls)) for m in METHODS},
        reader_accounting={m: v["usage"] for m, v in points.items()},
        conclusion_scope=(
            "Exploratory DEV contrasts conditional on one fitting and one acquisition seed."
        ),
    )
    result["examples"] = {
        f"{candidate} vs {base}": examples(paths[candidate], paths[base])
        for candidate, base in (("PQ-U", "DQ"), ("PQ-A", "PQ-U"), ("DQ", "gte-batch8"))
    }
    path = root / f"dev-review-a{seed}-{calls}.json"
    write_json(path, result)
    return result


def invoke(script, *args):
    subprocess.run(  # noqa: S603 -- fixed local experiment script and argv
        [sys.executable, str(Path(__file__).with_name(script)), *map(str, args)], check=True
    )


def extend(args):
    root = args.root.resolve()
    with (root / f".extension-{args.seed}.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.drive_initial is not None:
            if not all(
                point_path(root, m, args.seed, 12000).is_file() for m in ("DQ", "PQ-U", "PQ-A")
            ):
                wait_initial_fit(root, args.s1, args.drive_initial)
                write_json(
                    root / "main-study-status.json",
                    dict(stage="initial_12k_rounds", study_pid=os.getpid()),
                )
                invoke(
                    "run_memory_control_v13_rounds.py",
                    "--root",
                    root,
                    "--s1",
                    args.s1,
                    "--weights",
                    args.weights,
                    "--curve",
                    root / "rosters/curve-2048.json",
                    "--until",
                    12000,
                    "--acquisition-seed",
                    args.seed,
                    "--fit-seed",
                    args.seed,
                )
            qr_prefix(root, args.seed)
        owners = {m: args.qr_owner if m == "QR" else args.paired_owner for m in METHODS}
        wait_for(root, args.seed, 12000, owners)
        if args.drive_initial is not None or args.paired_owner or args.qr_owner:
            # A long fit can outlive code fixes. Run the settled stage from the
            # current worktree only after all four real 12k points are published.
            argv = [
                sys.executable,
                "-u",
                str(Path(__file__).resolve()),
                "--root",
                str(root),
                "--seed",
                str(args.seed),
                "--repeats",
                str(args.repeats),
                "extend",
                "--s1",
                str(args.s1),
                "--weights",
                str(args.weights),
                "--plot-python",
                args.plot_python,
            ]
            os.execv(sys.executable, argv)  # noqa: S606 -- current interpreter and explicit local argv
        # Both mechanism and on-policy contrasts are measured before spending the next round.
        settle(root, args.seed, 6000, args.repeats)
        review = settle(root, args.seed, 12000, args.repeats)
        # The plan specifies a second frozen online policy iteration. Record the actual
        # signal by source so a negative line is preserved across the required extension.
        write_json(
            root / f"extension-a{args.seed}.json",
            dict(
                stage="24k second on-policy collection",
                based_on=str(root / f"dev-review-a{args.seed}-12000.json"),
                source_spread={
                    method: {
                        source: counts.get("nonconstant_quality_packs", 0)
                        for source, counts in row["pool"].items()
                    }
                    for method, row in review["measured_action_headroom"].items()
                },
                incremental_feedback_per_arm=12000,
                objective_comparison="DQ receives the same next-round results as PQ-U",
                conditional_sampler_replicates_launched=False,
            ),
        )
        if not point_path(root, "QR", args.seed, 24000).exists():
            # The final 12k evaluation can publish moments before the 12k trainer exits.
            training_lock = root / f"qr-{args.seed}" / ".lock"
            with training_lock.open() as owner:
                fcntl.flock(owner, fcntl.LOCK_EX)
            closed = (
                root
                / "staging/qr"
                / ("formal" if args.seed == 11 else f"formal-{args.seed}")
                / "checkpoint-24000"
            )
            if not (
                (closed / "control.pt").is_file()
                and (closed / "training.json").is_file()
                and json_file(closed / "training.json")["calls"] == 24000
                and json_file(closed / "training.json")["seed"] == args.seed
            ):
                invoke(
                    "run_qrag_milai_after_warm.py",
                    "--root",
                    root,
                    "--seed",
                    args.seed,
                    "--calls",
                    24000,
                )
            invoke(
                "evaluate_qrag_milai_checkpoints.py",
                "--root",
                root,
                "--seed",
                args.seed,
                "--calls",
                24000,
            )
        invoke(
            "run_memory_control_v13_rounds.py",
            "--root",
            root,
            "--s1",
            args.s1,
            "--weights",
            args.weights,
            "--curve",
            root / "rosters/curve-2048.json",
            "--until",
            24000,
            "--acquisition-seed",
            args.seed,
            "--fit-seed",
            args.seed,
        )
        settle(root, args.seed, 24000, args.repeats)
        all_points = [
            point_path(root, m, args.seed, n) for m in METHODS for n in (6000, 12000, 24000)
        ]
        subprocess.run(  # noqa: S603 -- local plot entry and validated point paths
            [
                args.plot_python,
                str(Path(__file__).with_name("report_memory_control_v13_curves.py")),
                "plot",
                "--points",
                *map(str, all_points),
                "--baselines",
                str(root / "curve-baseline-deployments.json"),
                "--output",
                str(root / f"figures-a{args.seed}"),
            ],
            check=True,
        )
        for method in METHODS:
            row = json_file(point_path(root, method, args.seed, 24000))
            invoke(
                "calibrate_memory_control_v13_baselines.py",
                "--root",
                root,
                "--family",
                "checkpoint",
                "--checkpoint",
                row["deployment"]["arm"]["checkpoint"],
                "--selected-readouts",
                "tune",
            )
        # Restrict the independent optimizer seeds to the development-selected
        # outcome families. All paid acquisition packages remain those of seed 11.
        invoke(
            "repeat_memory_control_v13_finalists.py",
            "--root",
            root,
            "--acquisition-seed",
            args.seed,
            "repeat",
            "--weights",
            args.weights,
            "--s1",
            args.s1,
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--repeats", type=int, default=5000)
    sub = p.add_subparsers(dest="mode", required=True)
    report = sub.add_parser("report")
    report.add_argument("--calls", type=int, required=True, choices=(6000, 12000, 24000))
    cases = sub.add_parser("examples")
    cases.add_argument("--policy", type=Path, required=True)
    cases.add_argument("--baseline", type=Path, required=True)
    cases.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("extend")
    run.add_argument("--s1", type=Path, required=True)
    run.add_argument("--weights", type=Path, required=True)
    run.add_argument(
        "--drive-initial",
        type=int,
        metavar="S1_PID",
        help="Own the 12k paired stage once this live evidence fit closes",
    )
    run.add_argument("--paired-owner", type=int)
    run.add_argument("--qr-owner", type=int)
    run.add_argument(
        "--plot-python", default=sys.executable, help="Python interpreter with Matplotlib available"
    )
    args = p.parse_args()
    if args.mode == "report":
        settle(args.root, args.seed, args.calls, args.repeats)
    elif args.mode == "examples":
        write_json(args.output, examples(args.policy, args.baseline))
    else:
        extend(args)

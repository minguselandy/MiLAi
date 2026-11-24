"""Select the fixed Reader deployment baselines on CALIBRATION, then evaluate frozen choices."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from statistics import fmean

from milai_lab.scorers.memory_control_episode_metrics import SOURCES, input_result, percentiles
from run_memory_control_v13_evaluation import save


def fixed_grid(base, candidates):
    for policy, reads, level in candidates:
        name = f"{policy}-{reads}" + (f"-{level}" if level else "")
        if policy == "gte_relevance":
            name += f"-batch{base['object_batch']}"
        arm = dict(base, policy=policy, reads=reads, name=name)
        if level:
            arm["precision"] = level
        yield name, arm


def evaluate(args, arm, role, population):
    path = args.root / "baseline-arms" / (arm["name"] + ".json")
    if path.exists() and json.loads(path.read_text()) != arm:
        raise ValueError(f"Existing candidate definition differs: {path}")
    save(path, arm)
    out = args.root / "baselines" / role / arm["name"]
    subprocess.run(  # noqa: S603 -- fixed local entry point and argv, no shell
        [
            sys.executable,
            str(Path(__file__).with_name("run_memory_control_v13_evaluation.py")),
            "evaluate",
            "--data",
            str(args.data),
            "--population",
            str(population),
            "--arm",
            str(path),
            "--output",
            str(out),
            "--device",
            args.device,
        ],
        check=True,
    )
    return out


def measured(out):
    summary = json.loads((out / "summary.json").read_text())
    _, episodes = input_result(out)
    latency = {s: [] for s in SOURCES}
    for row in episodes.values():
        v = row["costs"].get("episode_live_readout_ms")
        if v is not None:
            latency[row["dataset"]].append(v)
    if summary["available_case_macro_quality_points"] is None or not all(latency.values()):
        raise ValueError("Need three-source native quality and actual latency")
    return dict(
        quality=summary["available_case_macro_quality_points"],
        mean_source_p50_ms=fmean(percentiles(v, 0.5) for v in latency.values()),
        latency_n={s: len(v) for s, v in latency.items()},
        run=str(out),
    )


def checkpoint_grid(common, checkpoint):
    checkpoint = checkpoint.resolve()
    if not (checkpoint / "control.pt").is_file():
        raise FileNotFoundError(checkpoint / "control.pt")
    if (checkpoint / "training.json").is_file():
        contract = json.loads((checkpoint / "training.json").read_text())
        if (
            not contract.get("fitted_groups")
            or contract["supervision_mode"] != "online_pqn_terminal"
        ):
            raise ValueError("QR grid requires an online native-outcome checkpoint")
        family = f"qr-seed{contract['seed']}-{contract['calls']}-lambda"
        settings = dict(policy="qrag_milai", feedback_calls=contract["calls"])
    else:
        info = json.loads((checkpoint.parent / "run.json").read_text())
        contract = info["contract"]
        if info["status"] != "completed" or not info["reload_scores_equal"] or contract["probe"]:
            raise ValueError("Outcome grid requires a complete trained and reloaded checkpoint")
        family = checkpoint.parent.name + "-lambda"
        settings = dict(policy="pretrained_checkpoint")
    candidates = []
    for penalty in (0.0, 0.02, 0.05, 0.1, 0.2):
        name = f"{family}-{penalty:.2f}"
        arm = dict(
            common,
            **settings,
            name=name,
            utility_lambda=penalty,
            checkpoint=str(checkpoint),
            seed=contract["seed"],
        )
        candidates.append((name, arm))
    return family, candidates


def main(args):
    common = dict(environment="qrag_milai_v13", observation_protocol="semantic_nav_delta_v2")
    if args.family == "checkpoint":
        if args.checkpoint is None:
            raise ValueError("Checkpoint calibration requires --checkpoint")
        family, candidates = checkpoint_grid(common, args.checkpoint)
    elif args.family == "gte":
        if args.backbone is None:
            raise ValueError("Native relevance grid requires --backbone")
        family = "gte-batch8"
        candidates = list(
            fixed_grid(
                dict(common, backbone=str(args.backbone.resolve()), object_batch=8),
                [("gte_relevance", r, level) for r in (2, 4) for level in ("R2", "R3")],
            )
        )
    else:
        family = "rule"
        candidates = list(
            fixed_grid(common, [("B1", 2, None), ("B1", 4, None), ("B2", 4, None), ("B3", 4, None)])
        )
    out = args.root / "baselines"
    calibration = args.root / "rosters/calibration-2048.json"
    rule = (
        "Within one native macro point of family maximum, minimize equally weighted source "
        "p50 live end-to-end ms; break ties by quality then name."
    )
    reg = dict(population=str(calibration), candidates=[a for _, a in candidates], selection=rule)
    contract = out / f"{family}-registration.json"
    if contract.exists() and json.loads(contract.read_text()) != reg:
        raise ValueError("Calibration protocol changed")
    save(contract, reg)
    rows = {n: measured(evaluate(args, arm, "calibration", calibration)) for n, arm in candidates}
    cutoff = max(r["quality"] for r in rows.values()) - 1.0
    eligible = [n for n, r in rows.items() if r["quality"] >= cutoff]
    chosen = min(eligible, key=lambda n: (rows[n]["mean_source_p50_ms"], -rows[n]["quality"], n))
    save(
        out / f"{family}-selection.json",
        dict(selected=chosen, criterion=rule, candidates=rows),
    )
    arm = dict(candidates)[chosen]
    for cohort in args.selected_readouts:
        evaluate(args, arm, cohort, args.root / f"rosters/{cohort}-2048.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--data", type=Path, default=Path("/cra/milai-datasets/memory_control_v1_2")
    )
    parser.add_argument("--backbone", type=Path)
    parser.add_argument("--family", choices=("rule", "gte", "checkpoint"), required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument(
        "--selected-readouts",
        nargs="+",
        choices=("curve", "tune"),
        default=("curve", "tune"),
        help="Natural DEV populations for the frozen choice",
    )
    parser.add_argument("--device", default="cuda")
    main(parser.parse_args())

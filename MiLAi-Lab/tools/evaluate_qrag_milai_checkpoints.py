"""Verify each published QR checkpoint and bind its natural DEV readout to metered exposure."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from milai_lab.datasets.memory_control_report import write_json
from run_qrag_milai_after_warm import read, running


def producer_live(directory):
    if running(directory):
        return True
    launcher = read(directory / "launch.json").get("pid")
    if not launcher:
        return False
    try:
        argv = Path(f"/proc/{launcher}/cmdline").read_bytes()
    except FileNotFoundError:
        return False
    return b"run_qrag_milai_after_warm.py" in argv or b"milai_lab.runners.qrag_milai_train" in argv


def invoke(directory, tool, *args):
    argv = [sys.executable, str(Path(__file__).with_name(tool)), *map(str, args)]
    with (directory / "curve-commands.log").open("a", buffering=1) as log:
        while True:
            log.write(json.dumps({"started_ns": time.time_ns(), "argv": argv}) + "\n")
            with (directory / "curve-worker.log").open("a+b") as output:
                start = output.tell()
                result = subprocess.run(argv, stdout=output, stderr=subprocess.STDOUT)  # noqa: S603
                if result.returncode == 0:
                    break
                output.seek(max(start, output.tell() - 4096))
                tail = output.read().decode(errors="replace")
                if "CUDA out of memory" not in tail and "OutOfMemoryError" not in tail:
                    raise RuntimeError(
                        f"{tool} failed with status {result.returncode}: {tail[-1024:]}"
                    )
                log.write(
                    "CUDA allocation failed. Retrying this checkpoint window.\n"
                )
                time.sleep(30)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--dataset", type=Path, default=Path("/cra/milai-datasets/memory_control_v1_2"))
    p.add_argument("--seed", type=int, default=11)
    p.add_argument(
        "--calls", nargs="+", type=int, choices=(6000, 12000, 24000), default=[6000, 12000]
    )
    args = p.parse_args()
    root = args.root.resolve()
    train = root / f"qr-{args.seed}"
    roster = root / "rosters/curve-2048.json"
    manifest = read(roster)
    if (
        manifest.get("role") != "dev"
        or manifest.get("v13_role") != "curve"
        or manifest["material_budget"] != 2048
    ):
        raise ValueError("Use the registered natural V13 curve roster")
    with (train / ".curve.lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for n in sorted(set(args.calls)):
            tag = f"qr-a{args.seed}-f{args.seed}-{n}"
            base = root / "staging/qr" / ("formal" if args.seed == 11 else f"formal-{args.seed}")
            checkpoint = base / f"checkpoint-{n}"
            arm_file = root / "arms" / (tag + ".json")
            results = root / "eval" / tag
            dest = root / "curve-points" / (tag + ".json")
            while not checkpoint.is_dir():
                live = producer_live(train)
                write_json(
                    train / "curve-status.json",
                    dict(
                        pid=os.getpid(),
                        observed_ns=time.time_ns(),
                        awaiting_checkpoint=str(checkpoint),
                        producer_live=live,
                        roster_tasks=len(manifest["tasks"]),
                    ),
                )
                if not live:
                    raise RuntimeError(
                        "QR producer exited before the registered checkpoint was published"
                    )
                time.sleep(30)
            binding = read(checkpoint / "training.json")
            if (
                binding["calls"] != n
                or binding["seed"] != args.seed
                or binding["observation_protocol"] != "semantic_nav_delta_v2"
                or not binding["fitted_groups"]
            ):
                raise ValueError("Unexpected QR training checkpoint binding")
            verify = train / f"verified-{n}.json"
            if not read(verify).get("comparison_to_live_scores"):
                invoke(
                    train,
                    "verify_qrag_milai_checkpoint.py",
                    "--run",
                    train,
                    "--checkpoint",
                    checkpoint,
                    "--device",
                    "cuda:0",
                )
            arm = dict(
                name=tag,
                policy="qrag_milai",
                checkpoint=str(checkpoint),
                feedback_calls=n,
                seed=args.seed,
                utility_lambda=read(train / "run.json")["utility_lambda"],
                environment="qrag_milai_v13",
                observation_protocol=binding["observation_protocol"],
            )
            if arm_file.exists() and read(arm_file) != arm:
                raise ValueError("Frozen QR DEV arm differs")
            write_json(arm_file, arm)
            write_json(
                train / "curve-status.json",
                dict(
                    pid=os.getpid(),
                    checkpoint=str(checkpoint),
                    state="evaluating",
                    evaluation=str(results),
                    roster_tasks=len(manifest["tasks"]),
                ),
            )
            invoke(
                train,
                "run_memory_control_v13_evaluation.py",
                "evaluate",
                "--arm",
                arm_file,
                "--population",
                roster,
                "--data",
                args.dataset,
                "--output",
                results,
                "--device",
                "cuda:0",
            )
            invoke(
                train,
                "report_memory_control_v13_curves.py",
                "point",
                "--method",
                "QR",
                "--calls",
                n,
                "--qr",
                train,
                "--evaluation",
                results,
                "--acquisition-seed",
                args.seed,
                "--fit-seed",
                args.seed,
                "--output",
                dest,
            )
        write_json(
            train / "curve-status.json",
            dict(
                pid=os.getpid(),
                state="complete",
                feedback_checkpoints=sorted(set(args.calls)),
                observed_ns=time.time_ns(),
            ),
        )


if __name__ == "__main__":
    main()

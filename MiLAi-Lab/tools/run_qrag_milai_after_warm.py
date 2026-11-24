"""Launch online QR after the shared warm data and measured resource pilot finish."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import json
import os
import statistics
import sys
import time
from pathlib import Path


def running(directory: Path) -> bool:
    # All producers hold this flock through final artifacts. A stale file is not a live job.
    lock = directory / ".lock"
    if not lock.exists():
        return False
    with lock.open("r") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--calls", type=int, choices=(12000, 24000), default=12000)
    args = p.parse_args()
    root = args.root.resolve()
    warm = root / f"warm-{args.seed}"
    pilot = root / "qr-s0"
    pilot_weights = root / "staging/qr/s0/checkpoint-48"
    output = root / f"qr-{args.seed}"
    output.mkdir(exist_ok=True)
    receipts = root / "staging/qr/formal-receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    link = output / "receipts"
    if not link.exists():
        link.symlink_to(receipts, target_is_directory=True)
    note = output / "launch.json"

    def save(data):
        part = note.with_suffix(".part")
        part.write_text(json.dumps(data, indent=2))
        part.replace(note)

    while True:
        paid = read(warm / "progress.json").get("feedback_calls", 0)
        warm_live, pilot_live = running(warm), running(pilot)
        warm_done = paid == 2000 and not warm_live
        pilot_done = (pilot_weights / "control.pt").is_file() and (
            read(pilot_weights / "training.json").get("calls") == 48
        )
        status = {
            "pid": os.getpid(),
            "observed_ns": time.time_ns(),
            "warm_calls": paid,
            "warm_owner_live": warm_live,
            "pilot_owner_live": pilot_live,
            "pilot_checkpoint_complete": pilot_done,
        }
        save(status)
        if warm_done and pilot_done:
            break
        if (not warm_done and not warm_live) or (not pilot_done and not pilot_live):
            raise RuntimeError("Upstream owner exited before the required artifacts were complete")
        time.sleep(30)

    costs = []
    for path in sorted((warm / "packs").glob("*.json.gz")):
        with gzip.open(path) as f:
            row = json.load(f)
        if (
            row["split_role"],
            row["collection_round"],
            row["acquisition_method"],
            row["continuation_mode"],
        ) != ("train", 0, "uniform", "full_episode"):
            raise ValueError("The QR cost unit requires common uniform warm TRAIN packs")
        costs.extend(o["future_cost"] for o in row["outcomes"] if o["future_cost_observed"])
    scale = max(1.0, statistics.median(costs))
    params = [
        "-u",
        "-m",
        "milai_lab.runners.qrag_milai_train",
        "--backbone",
        str(root / "staging/qr/gte-multilingual-base"),
        "--output",
        str(output),
        "--checkpoint-root",
        str(root / "staging/qr/formal"),
        "--batch",
        "32",
        "--seed",
        str(args.seed),
        "--calls",
        str(args.calls),
        "--cost-scale",
        str(scale),
    ]
    save(dict(status, measured_warm_costs=len(costs), cost_scale=scale, training_command=params))
    os.execv(sys.executable, [sys.executable, *params])  # noqa: S606 -- current Python, bound args


if __name__ == "__main__":
    main()

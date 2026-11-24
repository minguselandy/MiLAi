"""Launch online QR with its frozen Host-only cost unit under the study phase scheduler."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
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
    report = root / "frozen-host-cost-scale.json"
    pilot = root / "qr-s0"
    pilot_weights = root / "staging/qr/s0/checkpoint-48"
    output = root / f"qr-{args.seed}"
    output.mkdir(exist_ok=True)
    formal = root / "staging/qr" / ("formal" if args.seed == 11 else f"formal-{args.seed}")
    receipts = formal.with_name(formal.name + "-receipts")
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
        pilot_live = running(pilot)
        binding = read(pilot_weights / "training.json")
        pilot_done = (pilot_weights / "control.pt").is_file() and binding.get("calls") == 48
        status = dict(
            pid=os.getpid(),
            observed_ns=time.time_ns(),
            pilot_owner_live=pilot_live,
            pilot_checkpoint_complete=pilot_done,
            host_cost_unit_path=str(report),
            host_cost_unit_ready=False,
            phase_unit="qr",
        )
        if report.is_file() and pilot_done:
            try:
                from milai_lab.methods.control_cost_scale import load_host_cost_scale

                scale, _ = load_host_cost_scale(
                    report, dataset_run_id=binding["dataset_run_id"], budget=2048
                )
            except (ValueError, KeyError, TypeError, ImportError) as error:
                status["validation_error"] = str(error)
            else:
                status.update(
                    host_cost_unit_ready=True,
                    cost_scale=scale,
                    cost_statistic="median_host_terminal_prompt_tokens",
                )
        save(status)
        if status["host_cost_unit_ready"]:
            break
        if not pilot_done and not pilot_live:
            raise RuntimeError("QR resource pilot exited before its checkpoint was published")
        time.sleep(15)
    params = [
        "-u",
        "-m",
        "milai_lab.runners.qrag_milai_train",
        "--backbone",
        str(root / "staging/qr/gte-multilingual-base"),
        "--output",
        str(output),
        "--checkpoint-root",
        str(formal),
        "--batch",
        "32",
        "--seed",
        str(args.seed),
        "--calls",
        str(args.calls),
        "--host-cost-scale",
        str(report),
    ]
    save(dict(status, training_command=params))
    os.execv(sys.executable, [sys.executable, *params])  # noqa: S606 -- current Python, bound args


if __name__ == "__main__":
    main()

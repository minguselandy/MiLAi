"""Run the frozen source/reference training matrix serially, retaining first failures."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    protocol = read_json(args.protocol)
    source_root = args.source_root.resolve()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "protocol.json", protocol)
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=",".join(map(str, protocol["physical_gpus"])),
               PYTHONPATH=f"{source_root / 'src'}:{source_root / 'tools'}",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    run: dict[str, Any] = {
           "status": "RUNNING", "pid": os.getpid(), "source_version": args.source_version,
           "source_root": str(source_root), "planned_jobs": protocol["planned_jobs"],
           "jobs": [], "automatic_retry": False, "started_epoch": time.time()}
    write_json(root / "driver.json", run)
    budget = Path(protocol["budget"])
    try:
        for seed in protocol["seeds"]:
            conditions = protocol["conditions"] if seed % 2 == 0 else protocol["conditions"][::-1]
            for condition in conditions:
                name = f"{condition}-seed{seed}"
                output = root / "runs" / condition / str(seed)
                command = [sys.executable, str(source_root / "tools/train_bounded_laya.py"),
                    str(Path(protocol["data"]) / condition), protocol["base_checkpoint"],
                    str(output), "--budget", str(budget),
                    "--compute-phase", f"source_selection_v2_train_{condition}_seed{seed}",
                    "--optimizer-updates", str(protocol["optimizer_updates"]),
                    "--dev-data", protocol["common_dev"], "--seed", str(seed),
                    "--max-len", str(protocol["max_len"]),
                    "--head-max-len", str(protocol["head_max_len"]),
                    "--backend", protocol["backend"], "--objective", protocol["objective"],
                    "--evaluate-train", "--train-eval-final-only", "--shuffle-options"]
                write_json(root / f"{name}-command.json", command)
                write_json(root / f"{name}-budget-before.json", read_json(budget))
                started = time.perf_counter()
                with (root / f"{name}.stdout.log").open("w") as stdout, \
                        (root / f"{name}.stderr.log").open("w") as stderr:
                    child = subprocess.Popen(  # noqa: S603 -- frozen argv, no shell
                        command, cwd=source_root, env=env, stdout=stdout, stderr=stderr)
                    run["active"] = {"condition": condition, "seed": seed,
                                     "pid": child.pid, "output": str(output)}
                    write_json(root / "driver.json", run)
                    print(json.dumps({"started": run["active"]}), flush=True)
                    code = child.wait()
                write_json(root / f"{name}-budget-after.json", read_json(budget))
                run["jobs"].append({"condition": condition, "seed": seed, "returncode": code,
                    "output": str(output), "wall_seconds_including_process": time.perf_counter()
                    - started})
                write_json(root / "driver.json", run)
                print(json.dumps({"finished": run["jobs"][-1]}), flush=True)
                if code or read_json(output / "run.json")["status"] != "COMPLETED":
                    raise RuntimeError(f"Frozen job failed: {name}; no retry or later dispatch")
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        run["finished_epoch"] = time.time()
        write_json(root / "driver.json", run)


if __name__ == "__main__":
    main()

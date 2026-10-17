"""Execute frozen all-seed probes and two fixed4 QA cohorts after training closes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    root, source = args.root.absolute(), args.source_root.absolute()
    protocol = read_json(root / "protocol.json")
    if (root / "driver.json").exists():
        raise ValueError("This finite cohort already has a dispatch record; no automatic replay")
    run: dict[str, Any] = {"status": "WAITING_FOR_TRAINING", "pid": os.getpid(),
        "source_version": args.source_version, "source_root": str(source), "stages": [],
        "started_epoch": time.time(), "automatic_retry": False}
    write_json(root / "driver.json", run)
    budget = Path(protocol["budget"])
    cuda, http = protocol["cuda_python"], protocol["http_python"]
    env = dict(os.environ, PYTHONPATH=f"{source / 'src'}:{source / 'tools'}",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")

    def stage(name: str, command: list[str], gpu: str | None = None) -> None:
        write_json(root / f"{name}-command.json", command)
        write_json(root / f"{name}-budget-before.json", read_json(budget))
        started = time.perf_counter()
        child_env = dict(env)
        if gpu is not None:
            child_env["CUDA_VISIBLE_DEVICES"] = gpu
        with (root / f"{name}.stdout.log").open("w") as stdout, \
                (root / f"{name}.stderr.log").open("w") as stderr:
            child = subprocess.Popen(  # noqa: S603 -- frozen argv, no shell
                command, cwd=source, env=child_env, stdout=stdout, stderr=stderr)
            run["active"] = {"stage": name, "pid": child.pid, "physical_gpus": gpu}
            write_json(root / "driver.json", run)
            print(json.dumps({"started": run["active"]}), flush=True)
            code = child.wait()
        write_json(root / f"{name}-budget-after.json", read_json(budget))
        run["stages"].append({"name": name, "returncode": code,
                              "wall_seconds": time.perf_counter() - started})
        write_json(root / "driver.json", run)
        print(json.dumps({"finished": run["stages"][-1]}), flush=True)
        if code:
            raise RuntimeError(f"Frozen stage failed without retry: {name}")

    try:
        while True:
            training = read_json(Path(protocol["training_root"]) / "driver.json")
            if training["status"] == "COMPLETED":
                break
            if training["status"] != "RUNNING":
                raise RuntimeError("Training did not close successfully; evaluation not dispatched")
            time.sleep(5)
        run.update(status="RUNNING", training_source_version=training["source_version"],
                   model_dispatch_epoch=time.time())
        write_json(root / "driver.json", run)
        lengths = ["--max-len", str(protocol["max_len"]),
                   "--head-max-len", str(protocol["head_max_len"])]
        for model in protocol["models"]:
            if model["probe"]:
                for kind, data, variants in (
                    ("presentation", protocol["common_dev"],
                     protocol["robustness"]["presentation_variants"]),
                    ("evidence", protocol["robustness"]["evidence_contrasts"], ["original"]),
                ):
                    name = f"{kind}-{model['name']}"
                    stage(name, [cuda, "tools/probe_bounded_invariance.py", data,
                        model["checkpoint"], str(root / "probes" / kind / model["name"]),
                        "--budget", str(budget), "--compute-phase", f"source_selection_v2_{name}",
                        *lengths, "--variants", *variants], "2")
            for cohort in protocol["cohorts"]:
                folder = Path(cohort["root"])
                name = f"select-{cohort['name']}-{model['name']}"
                stage(name, [cuda, "tools/run_bounded_reader_selection.py", "select",
                    str(folder / "cases.jsonl"), str(folder / "selections" / model["name"]),
                    "--backend", "laya", "--checkpoint", model["checkpoint"],
                    "--budget", str(budget), "--compute-phase", f"source_selection_v2_{name}",
                    *lengths, "--selection-only" if model["selection_only"] else "--fixed4-only"],
                    "2,3")
        for cohort in protocol["cohorts"]:
            folder, path = Path(cohort["root"]), cohort["protocol"]
            stage(f"dense-{cohort['name']}", [http, "tools/global_reader_controls.py", "dense",
                  path, str(folder / "selections/dense")])
            for phase, destination in (("preview", "preview"), ("predict", "reader")):
                stage(f"{destination}-{cohort['name']}", [http, "tools/run_musique_reader.py",
                      path, str(folder / destination), "--phase", phase])
            stage(f"score-{cohort['name']}", [http, "tools/run_musique_reader.py", path,
                  str(folder / "score"), "--phase", "score", "--predictions",
                  str(folder / "reader")])
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        run["finished_epoch"] = time.time()
        write_json(root / "driver.json", run)


if __name__ == "__main__":
    main()

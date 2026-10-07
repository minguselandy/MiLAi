"""Run a declared paired method suite serially on the existing shared ledger."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.edit_benchmarks import run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--benchmark", choices=["halumem", "longmemeval", "all"], default="halumem")
    args = parser.parse_args()
    settings = read_json(args.config)
    completed = []
    for arm in settings["arms"]:
        configured = copy.deepcopy(settings)
        configured["arm"] = arm
        configured.pop("arms")
        run(configured, args.output / arm, args.benchmark)
        completed.append(arm)
        write_json(
            args.output / "suite-progress.json",
            {
                "completed_arms": completed,
                "selected_arms": settings["arms"],
                "experiment_name": settings["experiment_name"],
            },
        )


if __name__ == "__main__":
    main()

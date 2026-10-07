"""Execute the frozen external comparison serially on the continuous ledger."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.edit_external import run_external

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=["all", "predict", "score"], default="all")
    args = parser.parse_args()
    settings = read_json(args.config)
    completed = []
    for arm in settings["arms"]:
        selected = copy.deepcopy(settings)
        selected.pop("arms")
        selected["arm"] = arm
        run_external(selected, args.output / arm, args.phase)
        completed.append(arm)
        write_json(
            args.output / ("suite-progress.json" if args.phase == "all"
                           else f"suite-{args.phase}-progress.json"),
            {"completed_arms": completed, "phase": args.phase},
        )

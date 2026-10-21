"""Compose declared train/dev components; never replace pending trajectories with labels."""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from retrieval_mixture import combine_components


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    recipe = read_json(args.recipe)
    paths = {path for component in recipe["components"] for path in component["files"]}
    sources = {path: read_jsonl(Path(path))
               for path in sorted(paths)}
    components = []
    for component in recipe["components"]:
        families = set(component["families"]) if "families" in component else None
        rows = [row for path in component["files"] for row in sources[path]
                if families is None or row["metadata"]["family"] in families]
        components.append({**component, "rows": rows})
    data, masses = combine_components(components)
    args.output.mkdir(parents=True, exist_ok=False)
    for split, rows in data.items():
        with (args.output / f"{split}.jsonl").open("w") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "mixture.json", masses)
    labelled = sum(bool(row["gold"]) for row in data["train"])
    report = {"status": "MIXTURE_PREPARED_NOT_FITTED", "recipe": str(args.recipe),
        "splits": {split: {"rows": len(rows), "labelled": sum(bool(r["gold"]) for r in rows),
            "families": len({r["metadata"]["family"] for r in rows}),
            "labelled_families": len({r["metadata"]["family"] for r in rows if r["gold"]}),
            "component_rows": dict(Counter(r["metadata"]["component"] for r in rows)),
            "labelled_component_rows": dict(Counter(r["metadata"]["component"]
                                                     for r in rows if r["gold"]))}
            for split, rows in data.items()},
        "loss_mixture": masses, "suggested_two_pass_updates": math.ceil(2 * labelled / 16),
        "sampling": "Uniform shuffled passes over labelled rows, not stratified component quotas. "
                    "Loss normalizes within component/family/event, then applies declared masses. "
                    "Actual sampled rows and tokens must be reported from fitting.",
        "state_ids": "Assigned over all train then dev rows before masking, outside model input.",
        "scope": recipe["scope"], "public_inputs_and_gold_changed": False,
        "model_calls": 0, "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu, "ledger_recorded": False}
    write_json(args.output / "preparation.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()

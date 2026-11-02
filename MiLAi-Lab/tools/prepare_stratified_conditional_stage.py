"""Export known condition/label coverage while retaining rare conditional pairs."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.datasets.conditional_exposure import condition_stratified_auxiliary_panel
from milai_lab.harness.artifact_io import read_jsonl, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    started = time.process_time()
    panel = condition_stratified_auxiliary_panel(read_jsonl(args.source / "matrix.jsonl"),
        read_jsonl(args.source / "condition-pairs.jsonl"), seed=args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, values in [("train", panel["rows"]), ("selected-pairs", panel["pairs"])]:
        with (args.output / (name + ".jsonl")).open("w", encoding="utf-8") as stream:
            for row in values:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "slots.json", panel["slots"])
    write_json(args.output / "missing-condition-labels.json", panel["missing_condition_labels"])
    for name in ["groups.json", "query-units.json"]:
        (args.output / name).write_bytes((args.source / name).read_bytes())
    report = {"status": "STRATIFIED_CONDITIONAL_TRAIN_PANEL_CREATED;NOT_FITTED",
        "source": str(args.source.resolve()), "seed": args.seed, "counts": panel["counts"],
        "selection": "Keep all known change and stable-positive pairs; choose one seeded "
                     "stable-negative pair per query when available; then fill one known "
                     "positive and negative per actual condition if not already represented. "
                     "Missing strata are explicit, never inferred. Each selected cell occurs once.",
        "identity": "Only metadata.state_id is added as original matrix position. All visible "
                    "inputs, target provenance and native identities remain unchanged.",
        "scope": "Training exposure preparation, not label validation or a new loss. "
                 "Single-condition queries remain represented. Development/confirmation are "
                 "not admitted. A later full-pass recipe must measure actual tokens and loss "
                 "weights; additional auxiliary cost is separate from matched operation draws.",
        "model_calls": 0, "ledger_recorded": False, "no_sha_validation": True,
        "cpu_seconds_pending": time.process_time() - started}
    write_json(args.output / "preparation.json", report)
    print(report["counts"])


if __name__ == "__main__":
    main()

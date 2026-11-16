"""Export a complete condition-pair panel for an existing short auxiliary training stage."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.datasets.conditional_exposure import paired_auxiliary_panel
from milai_lab.harness.artifact_io import read_jsonl, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pair-budget", type=int, required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    started = time.process_time()
    panel = paired_auxiliary_panel(read_jsonl(args.source / "matrix.jsonl"),
        read_jsonl(args.source / "condition-pairs.jsonl"), pair_budget=args.pair_budget,
        seed=args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, rows in (("train", panel["rows"]), ("selected-pairs", panel["pairs"])):
        with (args.output / (name + ".jsonl")).open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "slots.json", panel["slots"])
    write_json(args.output / "preparation.json", {
        "status": "PAIRED_AUXILIARY_PANEL_CREATED;NOT_TRAINED",
        "source": str(args.source.resolve()), "pair_budget": args.pair_budget,
        "seed": args.seed, "counts": panel["counts"],
        "selection": "All known change and stable-positive pairs, then one seeded known pair "
                     "per remaining query; fill remaining slots from a seeded shuffle without "
                     "pair replacement. Full source matrix/unknowns remain in source.",
        "identity": "Only derived metadata.state_id is assigned the original matrix position. "
                    "Repeated cells retain event_id, training_event, source IDs and all labels. "
                    "No new source or independent state is claimed.",
        "training_contract": "A full pass sees every selected pair on both sides. Existing "
                    "family/event loss normalization applies; not equal class weighting, "
                    "simultaneous pair loss, or a new training runtime. Development data must "
                    "be supplied explicitly to the existing trainer.",
        "model_calls": 0, "ledger_recorded": False,
        "cpu_seconds_pending": time.process_time() - started,
    })
    print(panel["counts"])


if __name__ == "__main__":
    main()

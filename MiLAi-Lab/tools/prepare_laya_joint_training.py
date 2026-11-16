"""Freeze shared augmented event groups for CE and CE+joint-consistency training."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from laya_joint_training import epoch_examples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.data / "train.jsonl").read_text().splitlines()]
    args.output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for epoch in range(args.epochs):
        examples = epoch_examples(rows, args.seed, epoch)
        (args.output / f"epoch-{epoch}.jsonl").write_text("".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in examples))
        summaries.append({"epoch": epoch, "groups": len(examples),
            "sequences": sum(len(row["expected"]) for row in examples),
            "labels": dict(Counter(v for row in examples for v in row["expected"].values()))})
    for split in ("dev", "calibration", "test"):
        (args.output / f"{split}.jsonl").write_bytes((args.data / f"{split}.jsonl").read_bytes())
    manifest = {"source_data": str(args.data.resolve()), "epochs": summaries, "seed": args.seed,
        "independent_source_events": len(rows),
        "source_families": sorted({row["metadata"]["family_id"] for row in rows}),
        "conditions": ["ce", "consistency"], "same_actual_groups_for_both_conditions": True,
        "alias_permutations_are_not_independent_events": True,
        "calibration": "disabled; reserved external family not consumed",
        "test": "reserved previously exposed family, not used for training or selection"}
    (args.output / "preparation.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

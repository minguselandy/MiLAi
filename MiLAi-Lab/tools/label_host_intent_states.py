"""Compile an offline source review; observed state/questions remain unchanged."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.retrieval_supervision import annotate_decisions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("states", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.states.read_text().splitlines()]
    result = annotate_decisions(rows, read_json(args.reviews)["reviews"])
    args.output.mkdir(parents=True, exist_ok=False)
    for split in ("train", "dev"):
        with (args.output / f"{split}.jsonl").open("w") as stream:
            for row in result:
                if row["metadata"]["split"] == split:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"states": len(result), "labelled": sum(bool(row["gold"]) for row in result),
        "status_counts": dict(Counter(row["metadata"]["label_status"] for row in result)),
        "states_source": str(args.states), "reviews": str(args.reviews),
        "input_changes": 0, "teacher_actions_copied": False,
        "scope": "Source-supported short-term preferences; other options not declared illegal"}
    write_json(args.output / "labels.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()

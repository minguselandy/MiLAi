"""Add reviewed actual Writer inputs as Impact decisions, without using old targets."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from milai_lab.methods.dependency_memory import impact_request
from milai_lab.methods.laya_impact import impact_payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("references", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    splits = {s: [json.loads(line) for line in
                  (args.original / f"{s}.jsonl").read_text().splitlines()]
              for s in ("train", "dev", "calibration", "test")}
    references = {r["example_id"]: r for r in (
        json.loads(line) for line in args.references.read_text().splitlines())}
    for review in map(json.loads, args.reviews.read_text().splitlines()):
        row = references[review["event_id"]]
        request = impact_request(
            row["input"]["delivery"], row["mapping"], row["input"]["observed_date"])
        payload = impact_payload(request["messages"], request["schema"])
        aliases = list(row["mapping"]["units"])
        if set(review["labels"]) != set(aliases):
            raise ValueError("Review does not cover the actual delivered units")
        expected = {f"unit_{i}": review["labels"][alias]["label"] for i, alias in enumerate(aliases)
                    if review["labels"][alias]["label"] is not None}
        splits[review["split"]].append({**payload, "expected": expected, "metadata": {
            **review, "reference_file": str(args.references), "provenance": row["provenance"],
            "reviewer": "assistant source review, not an old-model target",
            "conversion": "Actual before/current source only; no old targets or outcomes",
            "exposure": "previously exposed author development; not blind"}})
    groups = {}
    for split, rows in splits.items():
        for row in rows:
            family = row["metadata"]["family_id"]
            if family in groups and groups[family] != split:
                raise ValueError("Family crosses splits")
            groups[family] = split
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {}
    for split, rows in splits.items():
        (args.output / f"{split}.jsonl").write_text("".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        summary[split] = {"events": len(rows),
            "families": sorted({r["metadata"]["family_id"] for r in rows}),
            "labels": dict(Counter(label for row in rows for label in row["expected"].values())),
            "masked": sum(len(r["questions"]) - len(r["expected"]) for r in rows)}
    (args.output / "preparation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

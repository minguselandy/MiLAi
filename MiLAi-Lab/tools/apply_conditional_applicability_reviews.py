"""Create a reviewed view for one split; preserve the complete native-only export."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.datasets.conditional_reviews import (
    apply_development_applicability_reviews,
    apply_training_applicability_reviews,
)
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("native", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--split", choices=("train", "dev"), default="train")
    args = parser.parse_args()
    started = time.process_time()
    bundle = read_json(args.reviews)
    selection = read_json(Path(bundle["selection"]))
    if Path(selection["source_matrix"]).resolve() != (args.native / "matrix.jsonl").resolve():
        raise ValueError("Reviews were selected from a different declared native matrix")
    expected = {event for family in selection["families"] for event in family["selected_event_ids"]}
    if expected != {r["event_id"] for r in bundle["records"]}:
        raise ValueError("Keep every preselected review position, including unknown judgments")
    native = read_jsonl(args.native / "matrix.jsonl")
    if any(row["metadata"]["split"] != args.split for row in native):
        raise ValueError("Declared split differs from the native matrix; never relabel partitions")
    apply = (apply_training_applicability_reviews if args.split == "train"
             else apply_development_applicability_reviews)
    result = apply(
        native, read_jsonl(args.native / "condition-pairs.jsonl"), bundle["records"])
    args.output.mkdir(parents=True, exist_ok=False)
    for name, values in (("matrix", result["matrix"]), ("condition-pairs", result["pairs"]),
                         (args.split, [row for row in result["matrix"] if row["gold"]])):
        with (args.output / (name + ".jsonl")).open("w", encoding="utf-8") as stream:
            for row in values:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    for name in ("groups.json", "query-units.json"):
        (args.output / name).write_bytes((args.native / name).read_bytes())
    view = "TRAINING" if args.split == "train" else "DEVELOPMENT"
    report = {"status": f"SEPARATE_SOURCE_REVIEWED_{view}_VIEW_CREATED;NOT_FITTED",
        "native": str(args.native.resolve()), "reviews": str(args.reviews.resolve()),
        "split": args.split,
        "counts": result["counts"], "native_gold_preserved": True,
        "visible_inputs_unchanged": all(all(a[k] == z[k] for k in ("state", "questions"))
            for a, z in zip(native, result["matrix"], strict=True)),
        "scope": f"Only originally unjudged {args.split} cells gain attributed source-author "
                 "judgments. Unknown reviews remain masked; quotes bind the supplied material, "
                 "not independent semantic/factual truth. Native-only results are historical and "
                 "not overwritten. No operation/Host outcomes or model improvement established.",
        "new_experiment_model_jobs": 0, "ledger_recorded": False,
        "cpu_seconds_pending": time.process_time() - started, "no_sha_validation": True}
    write_json(args.output / "preparation.json", report)
    print(report["status"], report["counts"])


if __name__ == "__main__":
    main()

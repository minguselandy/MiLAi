"""Project reviewed proofs to open-only supervision on the existing visible state.

All source and reference states are exported with their own masks. A separate
matched diagnostic uses only states where both admit an open action. Its exclusions
do not shrink the main training exports; STOP never becomes an invented open.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.bounded_evidence import selection_payload
from reviewed_reader_supervision import relabel


def open_target(gold: dict[str, Any]) -> dict[str, float]:
    probabilities = gold["next"]["probabilities"] if gold else {}
    selected = {key: value for key, value in probabilities.items()
                if key.startswith("open_") and value > 0}
    total = sum(selected.values())
    return {key: value / total for key, value in selected.items()}


def project(rows: list[dict[str, Any]], reviews: list[dict[str, Any]], split: str
            ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    reviewed, review_stats = relabel(rows, reviews, split)
    exports: dict[str, list[dict[str, Any]]] = {
        "source": [], "reference": [], "paired_source": [], "paired_reference": []}
    exclusions: Counter[str] = Counter()
    changed = 0
    for row in reviewed:
        source_target = open_target(row["gold"])
        reference_target = open_target(row["reference_gold"])
        state = row["state"]
        payload = selection_payload(state["question"], state["read_evidence"],
                                    state["candidates"])
        projected = {**copy.deepcopy(row), **payload,
                     "gold": {"next": {"probabilities": source_target}} if source_target else {}}
        projected["metadata"]["supervision_task"] = "fixed_budget_open_only"
        # Preserve ambiguous/complete/exhausted states with empty gold for diagnostics.
        exports["source"].append(projected)
        reference = copy.deepcopy(projected)
        reference["gold"] = ({"next": {"probabilities": reference_target}}
                             if reference_target else {})
        reference["metadata"]["label_scope"] = "Native reference, full open-only state export"
        reference["metadata"]["label_status"] = row["metadata"]["original_label_status"]
        exports["reference"].append(reference)
        if source_target and reference_target:
            exports["paired_source"].append(projected)
            exports["paired_reference"].append(reference)
            changed += source_target != reference_target
        else:
            exclusions[row["metadata"]["label_status"] if not source_target
                       else "reference_has_no_open_target"] += 1
    return exports, {
        "source_review": review_stats, "source_states": len(reviewed),
        "source_labelled": sum(bool(r["gold"]) for r in exports["source"]),
        "reference_labelled": sum(bool(r["gold"]) for r in exports["reference"]),
        "paired_states": len(exports["paired_source"]), "paired_changed_targets": changed,
        "pair_exclusions": dict(exclusions),
        "comparison_scope": "Conditional on both supervision schemes having a valid open target; "
                            "not a comparison of STOP correctness or all source states.",
        "source_family_count": len({r["metadata"]["family"] for r in reviewed}),
        "paired_family_count": len({r["metadata"]["family"]
                                    for r in exports["paired_source"]})}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decisions", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    review = read_json(args.review)
    stats = {}
    for split in ("train", "dev"):
        rows = [json.loads(line) for line in
                (args.decisions / f"{split}.jsonl").read_text().splitlines()]
        exports, stats[split] = project(rows, review["cases"], split)
        for name, records in exports.items():
            folder = args.output / name
            folder.mkdir(exist_ok=True)
            (folder / f"{split}.jsonl").write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    write_json(args.output / "preparation.json", {"splits": stats, "model_calls": 0,
        "sha_checks": False, "content_fingerprints": False,
        "scope": "Full source/reference open-only exports with their own masks; "
                 "paired intersection is a conditional diagnostic only"})


if __name__ == "__main__":
    main()

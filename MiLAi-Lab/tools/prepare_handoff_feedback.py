"""Reuse actual same-pool HANDOFF outcomes as partial, fully bound pair supervision."""
from __future__ import annotations

import argparse
import copy
import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from retrieval_feedback import feedback_counts, validate_feedback


def reviewed_relation(left: str, right: str, target: str) -> str:
    """Only explicit complete/sufficient endpoints establish a quality direction.

    Two incomplete packets may differ greatly. Failures, qualified answers and
    unknown material judgments retain unknown quality, rather than a negative/tie.
    """
    positive, negative = ("complete", "incomplete") if target == "answer" else (
        "sufficient", "insufficient")
    if left == right == positive:
        return "tie"
    if (left, right) == (positive, negative):
        return "left"
    if (left, right) == (negative, positive):
        return "right"
    return "unknown"


def compile_feedback(rows: list[dict[str, Any]], reviews: list[dict[str, Any]],
                     outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_case = {record["case"]: record for record in outcomes}
    compiled = []
    for index, original in enumerate(rows):
        if original["metadata"]["split"] != "train":
            raise ValueError("This feedback slice requires existing research-TRAIN states")
        selected: dict[str, dict[str, Any]] = {}
        for review in reviews:
            if review["state_index"] != index:
                continue
            actual = by_case[review["case"]]
            action = actual["tool"]["action"]
            key = action["id"]
            if (review["family"] != original["metadata"]["family"]
                    or actual["state_index"] != index or actual["family"] != review["family"]
                    or action != review["actual_action"] or action["kind"] != "HANDOFF"
                    or key not in original["questions"]["next"]["criteria"]
                    or action["parameters"] != original["metadata"]["action_parameters"][key]):
                raise ValueError("Review differs from the executed full HANDOFF binding")
            # One binding is one candidate even when multiple policies executed it.
            if key in selected:
                if any(selected[key][field] != review[field]
                       for field in ("answer_status", "material_status")):
                    raise ValueError("Repeated binding has conflicting reviews; retain uncertainty")
            else:
                selected[key] = review
        row = copy.deepcopy(original)
        row["gold"] = {}
        pairs = []
        for (left, a), (right, b) in itertools.combinations(selected.items(), 2):
            pairs.append({"left": left, "right": right,
                "answer": reviewed_relation(a["answer_status"], b["answer_status"], "answer"),
                "delivery": reviewed_relation(
                    a["material_status"], b["material_status"], "delivery"),
                "actual_cases": [a["case"], b["case"]]})
        row["feedback"] = {"comparisons": pairs}
        row["metadata"].update(
            label_status="executed_handoff_quality_relations",
            feedback_scope="Same acquired pool, actual bindings and retained first readouts; "
                           "positive ties mean coarse reviewed sufficiency/completion only",
            actual_branch_cases=[r["case"] for r in reviews if r["state_index"] == index])
        validate_feedback(row)
        compiled.append(row)
    return compiled


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("states", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("outcomes", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = compile_feedback(read_jsonl(args.states), read_json(args.reviews)["records"],
                            read_json(args.outcomes)["records"])
    args.output.mkdir(parents=True, exist_ok=False)
    # Keep all raw unknowns; the first legacy pair fit uses only known directions.
    fit = [row for row in rows if any(pair["delivery"] in {"left", "right"}
                                    for pair in row["feedback"]["comparisons"])]
    for name, records in (("raw", rows), ("delivery-fit", fit)):
        with (args.output / f"{name}.jsonl").open("w") as stream:
            for row in records:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "manifest.json", {
        "status": "ACTUAL_HANDOFF_FEEDBACK_COMPILED_NOT_FITTED",
        "inputs": {name: str(getattr(args, name).resolve())
                   for name in ("states", "reviews", "outcomes")},
        "states": len(rows), "source_families": len({r["metadata"]["family"] for r in rows}),
        "delivery_direction_fit_states": len(fit),
        "relations": {target: dict(Counter(pair[target] for row in rows
                      for pair in row["feedback"]["comparisons"]))
                      for target in ("answer", "delivery")},
        "feedback": {target: feedback_counts(rows, target) for target in ("answer", "delivery")},
        "new_model_calls": 0, "new_host_calls": 0, "no_sha_validation": True,
        "scope": "Initial reusable I2 TRAIN slice. Historical outcomes reused, not new experiments "
                 "or generalization evidence. Full states/menus preserved; "
                 "unknowns are not negatives."})


if __name__ == "__main__":
    main()

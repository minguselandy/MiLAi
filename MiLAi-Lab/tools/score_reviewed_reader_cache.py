"""Re-score saved first dev predictions against separately reviewed source labels.

No model is loaded or called. Compare old/new targets on the same admitted states;
masked-state exclusions are reported separately rather than credited as gains.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from evaluate_bounded_laya import score_predictions
from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviewed", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("runs", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    start, cpu = time.perf_counter(), time.process_time()
    rows = [json.loads(x) for x in args.reviewed.read_text().splitlines()]
    originals = [json.loads(x) for x in args.original.read_text().splitlines()]
    arms = {}
    for name, run_name, epoch in (
        ("laya_zero", "ce-c20-v1", 0), ("laya_ce", "ce-c20-v1", 4),
        ("linear_ce", "linear-c20-v1", 4), ("logits_zero", "logits-c20-v1", 0),
        ("logits_lora", "logits-c20-v1", 4),
    ):
        run = args.runs / run_name
        lengths = read_json(run / "lengths.json")["dev"]
        selected_original, admitted_original, admitted, predictions, admitted_predictions = (
            [], [], [], [], [])
        changes = []
        for row in rows:
            index = row["metadata"]["original_state_index"]
            original = originals[index]
            if any(row[k] != original[k] for k in ("state", "questions")):
                raise ValueError("Reviewed labels changed the frozen runtime projection")
            length = lengths[index]
            if isinstance(length, dict):
                if length["event_id"] != row["metadata"]["event_id"]:
                    raise ValueError("Saved encoder prediction ordering changed")
                length = length["sequence_tokens"]
            predicted = read_json(run / "dev" / str(epoch) / f"{index}.json")
            if predicted["input_tokens"] != length or set(predicted["probabilities"]) != set(
                    row["questions"]["next"]["criteria"]):
                raise ValueError("Saved prediction has different length or offered actions")
            selected_original.append(original)
            predictions.append(predicted)
            if not row["gold"]:
                continue
            admitted.append(row)
            admitted_original.append(original)
            admitted_predictions.append(predicted)
            choice = predicted["choice"]
            before = original["gold"]["next"]["probabilities"].get(choice, 0) > 0
            after = row["gold"]["next"]["probabilities"].get(choice, 0) > 0
            if before != after:
                changes.append({"event_id": row["metadata"]["event_id"], "choice": choice,
                                "original_accepted": before, "reviewed_accepted": after,
                                "original_gold": original["gold"], "reviewed_gold": row["gold"]})
        arms[name] = {
            "prediction_source": str((run / "dev" / str(epoch)).resolve()),
            "original_on_all_selected": score_predictions(selected_original, predictions),
            "original_on_same_admitted_states": score_predictions(
                admitted_original, admitted_predictions),
            "reviewed_on_same_admitted_states": score_predictions(admitted, admitted_predictions),
            "changed_acceptance": changes,
        }
    write_json(args.output, {"status": "CACHED_FIRST_PREDICTIONS_REVIEWED", "arms": arms,
        "selected_states": len(rows), "admitted_states": sum(bool(r["gold"]) for r in rows),
        "source_rows": len({r["metadata"]["row"] for r in rows}),
        "source_families": len({r["metadata"]["family"] for r in rows}),
        "cache_alignment": "Frozen original index; encoder event_id; every input length and "
                           "action set checked. Reviewed visible state/questions equal original.",
        "wall_seconds": time.perf_counter() - start, "cpu_seconds": time.process_time() - cpu,
        "new_model_calls": 0, "weights_changed": False, "official_qa_scores_changed": False,
        "scope": "Targeted exposed dev diagnosis, not a new performance benchmark or proof "
                 "that relabelling improves training. Predictions are original training-time "
                 "float32 dev outputs; not new checkpoint reloads or new inference."})


if __name__ == "__main__":
    main()

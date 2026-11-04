"""Bind regenerated A0/A1 panels to the original mixed replay and row budgets."""
from __future__ import annotations

import argparse
import copy
import json
import time
from collections import Counter, defaultdict, deque
from pathlib import Path

from conditional_training import conditional_training_groups
from milai_lab.datasets.conditional_reviews import binary_label
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from retrieval_mixture import mixture_event_weights


def condition(row: dict) -> tuple:
    return tuple(row["metadata"][k] for k in ("family", "query_unit", "training_event"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("control_data", type=Path)
    parser.add_argument("legacy_panel", type=Path)
    parser.add_argument("native_panel", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    original = read_jsonl(args.control_data / "train.jsonl")
    legacy = read_jsonl(args.legacy_panel / "train.jsonl")
    native = read_jsonl(args.native_panel / "train.jsonl")
    conditional = [r for r in original if r["metadata"]["component"] == "conditional"]
    legacy_ids = {r["metadata"]["event_id"] for r in legacy}
    native_ids = {r["metadata"]["event_id"] for r in native}
    assert legacy_ids == {r["metadata"]["event_id"] for r in conditional}
    original_by_id = {r["metadata"]["event_id"]: r for r in conditional}
    for row in legacy:
        expected = copy.deepcopy(row)
        previous = original_by_id[row["metadata"]["event_id"]]
        expected["metadata"].update({k: previous["metadata"][k]
                                     for k in ("state_id", "task", "component")})
        assert expected == previous
    replacements: dict[tuple, deque] = defaultdict(deque)
    for row in native:
        if row["metadata"]["event_id"] not in legacy_ids:
            assert binary_label(row) is False
            replacements[condition(row)].append(row)
    improved = []
    for original_row in original:
        row = original_row
        if (row["metadata"]["component"] == "conditional"
                and row["metadata"]["event_id"] not in native_ids):
            assert binary_label(row) is False
            row = copy.deepcopy(replacements[condition(row)].popleft())
            row["metadata"].update({k: original_row["metadata"][k]
                                     for k in ("state_id", "task", "component")})
        improved.append(row)
    assert not any(replacements.values())
    new_conditional = [r for r in improved if r["metadata"]["component"] == "conditional"]
    assert {r["metadata"]["event_id"] for r in new_conditional} == native_ids
    assert Counter((condition(r), binary_label(r)) for r in conditional) == Counter(
        (condition(r), binary_label(r)) for r in new_conditional)
    masses = read_json(args.control_data / "mixture.json")
    train0 = [r for r in original if r["gold"]]
    train1 = [r for r in improved if r["gold"]]
    assert mixture_event_weights(train0, masses) == mixture_event_weights(train1, masses)
    args.output.mkdir(parents=True, exist_ok=False)
    groups = {}
    for name, rows, panel in [("a0", original, args.legacy_panel),
                              ("a1", improved, args.native_panel)]:
        destination = args.output / name
        destination.mkdir()
        with (destination / "train.jsonl").open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        for file in ("dev.jsonl", "mixture.json"):
            (destination / file).write_bytes((args.control_data / file).read_bytes())
        (destination / "selected-pairs.jsonl").write_bytes(
            (panel / "selected-pairs.jsonl").read_bytes())
        groups[name] = len(conditional_training_groups(
            [r for r in rows if r["gold"]], read_jsonl(destination / "selected-pairs.jsonl"), 0))
    write_json(args.output / "comparison-preparation.json", {
        "control_data": str(args.control_data.resolve()),
        "legacy_panel": str(args.legacy_panel.resolve()),
        "native_panel": str(args.native_panel.resolve()),
        "raw_rows_each": len(original), "known_rows_each": len(train0),
        "replaced_negatives": len(native_ids - legacy_ids), "two_row_groups_each": groups,
        "condition_label_counts_identical": True, "per_slot_loss_weights_identical": True,
        "positive_and_replay_rows_literal_equal": True, "common_dev_literal_equal": True,
        "state_id_semantics": "Keep original row slots, including replacement slots, so positive "
                              "and replay option RNG identities are unchanged between arms.",
        "cpu_seconds_pending": time.process_time() - started,
        "model_calls": 0, "no_sha_validation": True,
    })
    print(f"Prepared matched A0/A1: {len(train0)} known rows each, "
          f"{len(native_ids - legacy_ids)} same-condition replacements")


if __name__ == "__main__":
    main()

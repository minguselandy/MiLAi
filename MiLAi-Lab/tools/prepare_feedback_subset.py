"""Derive nested feedback arms from one matched pool without resampling or recompiling labels."""
from __future__ import annotations

import argparse
import copy
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from retrieval_feedback import feedback_counts


def subset_pairs(
    feedback: list[dict[str, Any]], control: list[dict[str, Any]],
    parent: dict[str, Any], groups: list[str], updates: int,
) -> tuple[list[int], dict[str, Any]]:
    """An original feedback row keeps its exact replay and CE replacement in every cohort."""
    size = parent["feedback_states"]
    if len(feedback) != 2 * size or len(control) != 2 * size or feedback[size:] != control[size:]:
        raise ValueError("Parent feedback/control files are not the declared matched pairs")
    for i, row in enumerate(feedback[:size]):
        if (row["metadata"]["event_id"] != parent["length_matching"][i]["feedback_event"]
                or feedback[size+i]["metadata"]["event_id"] != parent["shared_replay_event_ids"][i]
                or control[i]["metadata"]["event_id"] != parent["additional_control_event_ids"][i]):
            raise ValueError("Parent matching identities or order changed")
    selected = [i for i, row in enumerate(feedback[:size]) if row["metadata"]["family"] in groups]
    indices = [*selected, *(size + i for i in selected)]
    shared = [feedback[i] for i in indices]
    control_subset = [control[i] for i in indices]
    actual = {feedback[i]["metadata"]["family"] for i in selected}
    return indices, {"status": "MATCHED_SUBSET_PREPARED_NOT_FITTED", "requested_groups": groups,
        "actual_feedback_groups": sorted(actual),
        "groups_without_feedback": sorted(set(groups) - actual),
        "feedback_states": len(selected), "shared_states": len(indices),
        "continued_ce_states": len(indices), "old_replay_states": len(selected),
        "parent_feedback_indices": selected, "parent_training_line_indices": indices,
        "optimizer_updates": updates, "row_draws_each_arm": updates * 16, "effective_batch": 16,
        "feedback": {target: feedback_counts(shared, target) for target in ("answer", "delivery")},
        "shared_replay_event_ids": [parent["shared_replay_event_ids"][i] for i in selected],
        "additional_control_event_ids": [parent["additional_control_event_ids"][i]
                                         for i in selected],
        "length_matching": [copy.deepcopy(parent["length_matching"][i]) for i in selected],
        "old_replay_component_counts": dict(Counter(r["metadata"]["component"]
                                                     for r in shared[len(selected):])),
        "control_component_counts": dict(Counter(r["metadata"]["component"]
                                                 for r in control_subset)),
        "old_replay_families": len({r["metadata"]["family"] for r in shared[len(selected):]}),
        "scope": "Same original IDs,labels,inputs and per-state matched rows. No branch,source "
                 "or replay resampling;actual subset component counts may differ from nominal "
                 "parent quotas. Feedback group count is separate from old replay families.",
        "labels_recompiled": False, "native_inputs_reencoded": False, "model_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent", type=Path)
    parser.add_argument("groups", type=Path, help="A frozen source-cohort selection.json")
    parser.add_argument("output", type=Path)
    parser.add_argument("--optimizer-updates", type=int, required=True)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    groups = read_json(args.groups)["selected_groups"]
    indices, report = subset_pairs(read_jsonl(args.parent / "feedback/train.jsonl"),
        read_jsonl(args.parent / "continued-ce/train.jsonl"),
        read_json(args.parent / "preparation.json"), groups, args.optimizer_updates)
    args.output.mkdir(parents=True, exist_ok=False)
    for arm in ("feedback", "continued-ce"):
        source, target = args.parent / arm, args.output / arm
        target.mkdir()
        with (source / "train.jsonl").open("rb") as stream:
            lines = [line for line in stream if line.strip()]
        (target / "train.jsonl").write_bytes(b"".join(lines[i] for i in indices))
        for name in ("dev.jsonl", "feedback-dev.jsonl"):
            if (source / name).exists():
                shutil.copy2(source / name, target / name)
    report.update(parent=str(args.parent), group_selection=str(args.groups), ledger_recorded=False,
        compute={"cpu_seconds": time.process_time() - cpu,
                 "wall_seconds": time.perf_counter() - started})
    write_json(args.output / "preparation.json", report)
    print({key: report[key] for key in ("status", "feedback_states", "shared_states",
                                      "optimizer_updates", "groups_without_feedback")})


if __name__ == "__main__":
    main()

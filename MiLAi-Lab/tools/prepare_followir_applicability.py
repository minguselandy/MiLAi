"""Export the previously grouped FollowIR release as candidate applicability tasks."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from milai_lab.datasets.followir import applicability_row
from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("groups", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    rows = [json.loads(line) for line in args.source.read_text().splitlines()]
    groups = read_json(args.groups)["groups"]
    allocated = [index for group in groups for index in group["rows"]]
    if sorted(allocated) != list(range(len(rows))):
        raise ValueError("Source allocation must cover every row exactly once")
    args.output.mkdir(parents=True, exist_ok=False)
    counts = {}
    for split in ("train", "dev"):
        selected = [group for group in groups if group["split"] == split]
        examples = [applicability_row(rows[index], index, group)
                    for group in selected for index in group["rows"]]
        with (args.output / f"{split}.jsonl").open("w") as stream:
            for example in examples:
                stream.write(json.dumps(example, ensure_ascii=False) + "\n")
        counts[split] = {"groups": len(selected), "rows": len(examples),
            "published_labels": dict(Counter(rows[index]["label"]
                for group in selected for index in group["rows"]))}
    summary = {
        "status": "AUXILIARY_CANDIDATE_TASK_PREPARED_NOT_FITTED",
        "source": str(args.source), "allocation": str(args.groups), "splits": counts,
        "task": "instruction_applicability",
        "inputs": "Literal query, instruction as read_goal.purpose, and candidate document.",
        "targets": "Published true/false candidate labels; teacher score is not used.",
        "qualification": "Not Host trajectories or operation/stop/refresh labels. Published "
                         "labels have not been independently reviewed. T1 mixing, complete-input "
                         "audit and task-specific evaluation remain to be implemented.",
        "operation_training_data_modified": False, "model_calls": 0,
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu, "ledger_recorded": False,
    }
    write_json(args.output / "preparation.json", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()

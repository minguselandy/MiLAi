"""Project registered train/dev sources for actual Host collection; no policy labels."""
from __future__ import annotations

import argparse
import copy
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.datasets.intent_training import (
    add_storage_requests,
    memops_intent_history,
    musique_intent_request,
)
from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("allocation", type=Path)
    parser.add_argument("old_lab", type=Path)
    parser.add_argument("authored", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    allocation = read_json(args.allocation)
    storage_families = set()
    for operation in ("Update", "Remember", "Reflect", "TrajectoryOps"):
        storage_families.add(next(r["family"] for r in allocation["train"]["memops"]
                                  if r["operation_type"] == operation))
    paths = [args.old_lab / name for name in (
        "artifacts/dynamic-memory-control/memops-expanded-train-v1/histories.json",
        "artifacts/dynamic-memory-control/prepared-followups-v9/inputs/own-train-histories.json",
        "artifacts/dynamic-memory-control/memops-dev-baselines-v1/fixture.json")]
    old_histories = {h["id"]: h for path in paths for h in read_json(path)["histories"]}
    histories, references = [], []
    row_roles: dict[int, tuple[str, dict[str, Any]]] = {}
    for split in ("train", "dev"):
        for allocated in allocation[split]["memops"]:
            original = old_histories["memops_" + allocated["family"]]
            if original["split"] != split:
                raise ValueError("Inherited MemOps split differs from the allocated source")
            history = memops_intent_history(original)
            if split == "train" and allocated["family"] in storage_families:
                history = add_storage_requests(history)
            histories.append(history)
            references.append({"dataset": "memops", "split": split,
                "source_group": original["source_family"], "original": original})
        for allocated in allocation[split]["musique"]:
            for index in allocated["source_rows"]:
                row_roles[index] = (split, allocated)
    multihop: dict[str, dict[str, Any]] = {}
    with Path(allocation["musique_source_file"]).open() as stream:
        for index, line in enumerate(stream):
            if index not in row_roles:
                continue
            split, allocated = row_roles[index]
            row = json.loads(line)
            if row["id"] != allocated["question_id"]:
                raise ValueError("Selected MuSiQue row no longer identifies the allocated question")
            family = allocated["family"]
            history = multihop.setdefault(family, {"id": family, "source_group": family,
                "split": split, "sources": [], "requests": []})
            history["requests"].append(musique_intent_request(row, index))
            references.append({"dataset": "musique", "split": split, "source_group": family,
                               "row": index, "original": row})
    histories.extend(multihop.values())
    authored_groups = set(allocation["dev"]["authored"])
    histories.extend({**copy.deepcopy(h), "split": "dev"}
        for h in read_json(args.authored)["histories"] if h["source_group"] in authored_groups)
    counts = {split: {"groups": sum(h["split"] == split for h in histories),
                     "requests_per_interface": sum(len(h["requests"]) for h in histories
                                                   if h["split"] == split)}
              for split in ("train", "dev")}
    if (counts["train"]["groups"], counts["dev"]["groups"]) != (
        allocation["train_groups"], allocation["dev_groups"]
    ):
        raise ValueError("Prepared source groups do not cover the registered allocation")
    write_json(args.output / "histories.json", {"schema": "host_intent_t0_histories_v1",
        "scope": "Actual sources and public tasks; operation labels not supplied",
        "histories": histories})
    with (args.output / "offline-references.jsonl").open("w") as stream:
        for reference in references:
            stream.write(json.dumps(reference, ensure_ascii=False) + "\n")
    write_json(args.output / "preparation.json", {"status": "PREPARED_NOT_COLLECTED",
        "allocation": str(args.allocation), "counts": counts,
        "request_counts_by_group": dict(Counter(len(h["requests"]) for h in histories)),
        "interfaces": ["query_only", "rich"], "primary_collection_policy": "rules",
        "controlled_storage_families": sorted(storage_families),
        "storage_rule": "First allocated train background per operation type; store first/last "
                        "literal user turns using actual APIs. No ideal semantic view. "
                        "Independent current/first-version query banks; original cuts untouched.",
        "planned_host_positions": 2 * sum(c["requests_per_interface"] for c in counts.values()),
        "memops_rule": "First and last arrival cut, retaining every intervening original turn; "
                       "old expected answers remain only in offline-references.jsonl",
        "musique_rule": "Every allocated corpus variant, no answer/support/decomposition in input",
        "source_review": "Inherited MemOps source review; new request/state labels unreviewed. "
                         "MuSiQue native references are weak supervision, not semantic judgment.",
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
        "model_calls": 0, "ledger_recorded": False})
    print(json.dumps(counts))


if __name__ == "__main__":
    main()

"""Group a declared public train intake, then export candidate applicability examples."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from milai_lab.datasets.promptriever import (
    base_query_id,
    candidate_rows,
    group_promptriever,
    source_keys,
)
from milai_lab.harness.artifact_io import read_jsonl, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ordinary-negatives", type=int, default=1)
    parser.add_argument("--instruction-negatives", type=int, default=1)
    parser.add_argument("--dev-fraction", type=float, default=.2)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if min(args.ordinary_negatives, args.instruction_negatives) < 0:
        parser.error("Negative candidate limits must be nonnegative")
    if not 0 < args.dev_fraction < 1:
        parser.error("Development fraction must be between zero and one")
    started, cpu = time.perf_counter(), time.process_time()
    rows = read_jsonl(args.source)
    groups = group_promptriever(rows, seed=args.seed, dev_fraction=args.dev_fraction)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "groups.json", {"groups": groups})
    splits, identities = {}, {}
    for split in ("train", "dev"):
        selected = [group for group in groups if group["split"] == split]
        indices = [i for group in selected for i in group["rows"]]
        identities[split] = {key for i in indices for key in source_keys(rows[i])}
        examples = [example for group in selected for i in group["rows"]
                    for example in candidate_rows(rows[i], i, group,
                        ordinary_negatives=args.ordinary_negatives,
                        instruction_negatives=args.instruction_negatives)]
        with (args.output / f"{split}.jsonl").open("w", encoding="utf-8") as stream:
            for example in examples:
                stream.write(json.dumps(example, ensure_ascii=False) + "\n")
        variants: dict[str, set[bool]] = {}
        for i in indices:
            variants.setdefault(base_query_id(rows[i]), set()).add(rows[i]["has_instruction"])
        splits[split] = {
            "raw_rows": len(indices), "families": len(selected), "base_queries": len(variants),
            "complete_query_pairs": sum(len(v) == 2 for v in variants.values()),
            "expanded_candidates": len(examples),
            "candidate_kinds": dict(Counter(r["metadata"]["candidate_kind"] for r in examples)),
        }
    overlap = identities["train"] & identities["dev"]
    report = {
        "status": "AUXILIARY_CANDIDATES_PREPARED_NOT_FITTED", "source": str(args.source),
        "source_url": "https://huggingface.co/datasets/samaya-ai/msmarco-w-instructions",
        "license": "Non-commercial research; inherits MS MARCO and generating-model terms.",
        "raw_rows": len(rows), "families": len(groups), "splits": splits,
        "largest_family_rows": max(len(g["rows"]) for g in groups),
        "largest_family_base_queries": max(len(g["base_query_ids"]) for g in groups),
        "cross_split_overlap": {kind: sum(key[0] == kind for key in overlap)
                                for kind in ("base_query", "query", "docid", "document")},
        "seed": args.seed, "dev_fraction": args.dev_fraction,
        "ordinary_negatives": args.ordinary_negatives,
        "instruction_negatives": args.instruction_negatives,
        "scope": "Partition of this entire supplied intake, not global or pretraining isolation. "
                 "Published membership, not reviewed labels or operation trajectories. "
                 "Larger intakes must be regrouped together before use.",
        "model_calls": 0, "operation_labels": 0,
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu}, "ledger_recorded": False,
    }
    write_json(args.output / "preparation.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()

"""Export a candidate union from an existing allocated training intake, without label filling."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.datasets.conditional_applicability import compile_condition_union
from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("groups", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dataset", choices=("promptriever", "followir"), required=True)
    parser.add_argument("--split", choices=("train", "dev"), default="train")
    parser.add_argument("--max-groups", type=int)
    args = parser.parse_args()
    if args.max_groups is not None and args.max_groups < 1:
        parser.error("Select at least one group")
    started = time.process_time()
    groups = [g for g in read_json(args.groups)["groups"] if g["split"] == args.split]
    groups = groups[:args.max_groups]
    selected = {index for group in groups for index in group["rows"]}
    # File iteration keeps embedded Unicode separators inside their literal JSON records.
    # Unselected rows, including the other split, are never parsed for this conversion.
    with args.source.open(encoding="utf-8") as stream:
        rows = {index: json.loads(line) for index, line in enumerate(stream) if index in selected}
    result = compile_condition_union(rows, groups, args.dataset)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, values in (("matrix", result["matrix"]), ("condition-pairs", result["pairs"]),
                         (args.split, [row for row in result["matrix"] if row["gold"]])):
        with (args.output / (name + ".jsonl")).open("w", encoding="utf-8") as stream:
            for row in values:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "groups.json", {"groups": groups})
    write_json(args.output / "query-units.json", {"units": result["units"]})
    report = {"status": "CONDITION_UNION_PREPARED_WITH_NATIVE_KNOWN_MASKS;NOT_FITTED",
        "source": str(args.source.resolve()), "allocation": str(args.groups.resolve()),
        "dataset": args.dataset, "split": args.split, "max_groups": args.max_groups,
        "selection": "Declared prefix of existing allocated groups in source order; no labels "
                     "or contrast outcomes used for selection. Existing splits unchanged.",
        "counts": result["counts"],
        "model_input": "Literal query, purpose and native title/text candidate. Native IDs, "
                       "membership labels, masks and teacher fields stay outside state/questions.",
        "unknowns": "Missing and conflicting native judgments retained in matrix with empty "
                    "gold; only known cells exported to the supervised split file. No inferred "
                    "negative/positive labels across conditions or changed document versions.",
        "scope": "Published candidate applicability, not operation labels or Host outcomes. "
                 "Change/stability requires an identical query and candidate in two judged "
                 "conditions. These paired classification metrics do not replace FollowIR p-MRR.",
        "model_calls": 0, "operation_labels": 0, "no_sha_validation": True,
        "ledger_recorded": False, "cpu_seconds_pending": time.process_time() - started}
    write_json(args.output / "preparation.json", report)
    print(report["status"], report["counts"])


if __name__ == "__main__":
    main()

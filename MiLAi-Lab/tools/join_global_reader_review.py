"""Join frozen first-response annotations without conflating abstention and retrieval.

All source-contract numbers are conditional on the recorded author interpretation,
not independent gold. Ambiguous full-pool cases retain explicit coverage counts.
"""

from __future__ import annotations

import argparse
import fcntl
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from export_global_reader_responses import response_id
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits


def verdict(annotation: dict[str, Any], disposition: str) -> dict[str, Any]:
    valid = annotation["output_contract"] == "valid"
    grounded_answer = (
        annotation["answer_target"] == "correct"
        and annotation["source_grounding"] == "supported_by_delivered_material"
    )
    cited_answer = grounded_answer and annotation["citation_grounding"] == "adequate"
    abstention = (
        annotation["answer_target"] == "no_answer"
        and annotation["source_grounding"] == "correct_insufficiency"
    )
    task = (
        None
        if disposition == "masked"
        else bool(valid and (cited_answer if disposition == "supported" else abstention))
    )
    return {
        "reader_response_pass": bool(valid and (cited_answer or abstention)),
        "grounded_target_answer": grounded_answer,
        "source_contract_task_pass": task,
        "qualified_response": annotation["answer_target"] == "ambiguous_or_qualified",
        "schema_or_generation_failure": annotation["output_contract"]
        in {"schema_or_generation_failure", "missing"},
        "contract_failure": not valid,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("receipt_report", type=Path)
    parser.add_argument("annotations", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    receipts = read_json(args.receipt_report)
    review = read_json(args.annotations)
    annotations = review["annotations"]
    required = {
        response_id(r["reader_call_key"])
        for arm in receipts["arms"].values()
        for r in arm["source_delivery"]
    }
    if required != set(annotations):
        raise ValueError("Complete unique-response annotation coverage is required")
    arms = {}
    for name, arm in receipts["arms"].items():
        counts: Counter[str] = Counter()
        families: dict[str, list[int]] = defaultdict(list)
        strata: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        rows = []
        for row in arm["source_delivery"]:
            rid = response_id(row["reader_call_key"])
            result = verdict(annotations[rid], row["disposition"])
            counts["positions"] += 1
            counts["source_" + row["disposition"]] += 1
            for field, value in result.items():
                if value is not None:
                    counts[field] += int(value)
            task = result["source_contract_task_pass"]
            if task is not None:
                families[row["family"]].append(int(task))
                strata[row["disposition"]][row["family"]].append(int(task))
            rows.append({**row, "response_id": rid, "annotation": annotations[rid], **result})
        means = {kind: mean(mean(v) for v in groups.values()) for kind, groups in strata.items()}
        arms[name] = {
            "counts": dict(counts),
            "eligible_families": len(families),
            "family_macro_task_pass": mean(mean(v) for v in families.values()),
            "source_class_family_macro": means,
            "balanced_source_class_macro": mean(means.values()),
            "cases": rows,
        }
    args.output.mkdir(parents=True, exist_ok=False)
    result = {
        "status": "ALL_FIRST_RESPONSES_AUTHOR_REVIEWED_AND_JOINED",
        "arms": arms,
        "unique_responses_reviewed": len(required),
        "reviewer_is_independent": False,
        "scope": "Conditional source-contract outcomes under recorded source/response "
        "interpretations. Correct Reader abstention on a deficient selected subset "
        "is not task success when a source-supported answer exists in the full pool. "
        "Masked cases and qualified responses are retained separately. Native metrics "
        "and first outputs are unchanged; not universal or independent-gold accuracy.",
    }
    write_json(args.output / "report.json", result)
    measures = {
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "analyses": 1,
    }
    budget_path = Path(read_json(args.root / "protocol.json")["reader"]["budget_path"])
    with budget_path.with_name("budget.json.http-owner.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        budget = RunBudget(RunLimits(**read_json(budget_path)["limits"]), budget_path)
        budget.record_compute("global_reader_semantic_review_join", measures)
    write_json(args.output / "compute.json", measures)
    print(result["status"])


if __name__ == "__main__":
    main()

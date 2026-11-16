"""Describe both frozen cohorts by family, source disposition and decomposition size.

This only reads first outputs and completed annotations. Qualified grounded
alternatives are counted separately, never turned into errors by subtraction from
the stricter unqualified-response count. No model selection or calls occur here.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    families: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if row["source_contract_task_pass"] is not None:
            families[row["family"]].append(int(row["source_contract_task_pass"]))
    native = [row["native_f1"] for row in rows if row["native_positive"]]
    strata = {}
    for kind in ("supported", "pool_insufficient", "masked"):
        subset = [row for row in rows if row["disposition"] == kind]
        strata[kind] = {
            "cases": len(subset),
            "families": len({row["family"] for row in subset}),
            "task_pass": sum(row["source_contract_task_pass"] is True for row in subset)
            if kind != "masked"
            else None,
        }
    qualified = [
        row for row in rows if row["annotation"]["answer_target"] == "ambiguous_or_qualified"
    ]
    grounded_qualified = sum(
        row["annotation"]["source_grounding"] == "supported_by_delivered_material"
        and row["annotation"]["citation_grounding"] == "adequate"
        and row["annotation"]["output_contract"] == "valid"
        for row in qualified
    )
    return {
        "cases": len(rows),
        "families": len({row["family"] for row in rows}),
        "native_positive_cases": len(native),
        "native_positive_f1_with_missing_zero": mean(native) if native else None,
        "source_strata": strata,
        "source_eligible_cases": sum(map(len, families.values())),
        "source_eligible_families": len(families),
        "source_family_macro_task_pass": mean(mean(v) for v in families.values())
        if families
        else None,
        "unqualified_response_pass": sum(row["reader_response_pass"] for row in rows),
        "qualified_responses": len(qualified),
        "grounded_cited_valid_qualified_responses": grounded_qualified,
        "remaining_qualified_responses": len(qualified) - grounded_qualified,
        "matching_target_without_confirmed_grounding": sum(
            row["annotation"]["answer_target"] == "correct"
            and row["annotation"]["source_grounding"] != "supported_by_delivered_material"
            for row in rows
        ),
        "contract_failures": sum(row["contract_failure"] for row in rows),
        "generation_or_schema_failures": sum(row["schema_or_generation_failure"] for row in rows),
    }


def collect(root: Path) -> dict[str, Any]:
    protocol = read_json(root / "protocol.json")
    semantic = read_json(root / "semantic-final/report.json")
    if semantic["status"] != "ALL_FIRST_RESPONSES_AUTHOR_REVIEWED_AND_JOINED":
        raise ValueError("Complete first-response review is required before cohort aggregation")
    labels = {
        row["case_id"]: row
        for row in (json.loads(x) for x in Path(protocol["labels"]).read_text().splitlines())
    }
    steps = {
        row["metadata"]["row"]: row["metadata"]["steps"]
        for row in (
            json.loads(x) for x in Path(protocol["invariance"]["data"]).read_text().splitlines()
        )
    }
    native = read_json(root / "score/results.json")["arms"]
    sys.path.insert(0, protocol["official_scorer"])
    from metrics.answer import AnswerMetric

    arms = {}
    for name, arm in semantic["arms"].items():
        rows = []
        for item in arm["cases"]:
            label = labels[item["case"]]
            observation = native[name]["observations"][item["case"]]
            metric = AnswerMetric()
            metric(
                "" if observation["missing"] else observation["prediction"]["predicted_answer"],
                [label["source"]["answer"], *label["source"]["answer_aliases"]],
            )
            rows.append(
                {
                    **item,
                    "steps": steps[label["source_row"]],
                    "native_positive": label["source"]["answerable"],
                    "native_f1": metric.get_metric()[1],
                }
            )
        arms[name] = {
            "all": summarize(rows),
            "by_steps": {
                str(step): summarize([row for row in rows if row["steps"] == step])
                for step in (2, 3, 4)
            },
            "by_family": {
                family: summarize([row for row in rows if row["family"] == family])
                for family in sorted({row["family"] for row in rows})
            },
        }
    receipts = read_json(root / "receipt-review/report.json")
    return {
        "root": str(root),
        "arms": arms,
        "actual_reader_usage_already_charged": receipts["actual_reader_usage"],
        "dense_cost_already_charged": receipts["dense_control"],
        "complete_cost_source": str(root / "receipt-review/report.json"),
        "source_annotation_scope": semantic["scope"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dev_root", type=Path)
    parser.add_argument("reserved_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    report = {
        "status": "BOTH_COHORTS_ALL_MODELS_DESCRIPTIVELY_SUMMARIZED",
        "dev": collect(args.dev_root),
        "reserved": collect(args.reserved_root),
        "model_calls": 0,
        "model_work_rebilled": False,
        "scope": "Decomposition size is an existing dataset stratum, not controlled difficulty "
        "or minimal proof length. Families and source dispositions retain separate denominators. "
        "No stratum with no cases is assigned zero accuracy. Qualified grounded answers remain "
        "described separately; unqualified-pass complements are not error counts. Source "
        "judgments are development-assistant review, not independent adjudicated gold.",
    }
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "report.json", report)
    measures = {
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "analyses": 1,
    }
    budget_path = Path(read_json(args.reserved_root / "protocol.json")["reader"]["budget_path"])
    with budget_path.with_name("budget.json.http-owner.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        budget = RunBudget(RunLimits(**read_json(budget_path)["limits"]), budget_path)
        budget.record_compute("global_reader_cohort_stratification", measures)
    write_json(args.output / "compute.json", measures)
    print(report["status"])


if __name__ == "__main__":
    main()

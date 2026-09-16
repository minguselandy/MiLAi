#!/usr/bin/env python3
"""Close the residual P0 stop-policy gap found by the matched characterization."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime" / "src"
for path in (ROOT, RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from milai.application.query_planner import QueryPlanner
from milai.application.sufficiency import decide_sufficiency
from milai.domain.retrieval import RetrievalRequest

from evals.dg14.benchmark import _atomic_json
from evals.dg17.measurement import (
    load_answer_bearing_labels,
    sha256_file,
)

MATCHED_PATH = ROOT / "var/dg17/q1/dg17-q1-p0-matched-20260827-002/receipt.json"
MATCHED_SHA256 = "d9c9d304fef3c9d5becf71d875f5d48df4242813bd289dadd338f9f948ac94cb"


class FocusedP0Error(RuntimeError):
    """The frozen matched input or focused P0 denominator drifted."""


def run(output: Path) -> dict[str, Any]:
    if output.exists():
        raise FocusedP0Error("output exists; choose a fresh receipt path")
    if sha256_file(MATCHED_PATH) != MATCHED_SHA256:
        raise FocusedP0Error("matched characterization receipt identity drifted")
    matched = json.loads(MATCHED_PATH.read_text(encoding="utf-8"))
    _envelope, cases, labels = load_answer_bearing_labels()
    records: list[dict[str, Any]] = []
    for case in cases:
        label = labels[case.case_id]
        query = f"Recall previous history evidence: {case.question}"
        request = RetrievalRequest(
            route="L1",
            query=query,
            memory_intent="HISTORY",
            consistency="CANONICAL_REQUIRED",
            limit=10,
        )
        plan = QueryPlanner().plan(request)
        decision, reason = decide_sufficiency(
            request,
            plan,
            [
                {
                    "kind": "EVIDENCE_OBSERVATION",
                    "evidence_id": f"synthetic-candidate-{case.case_id}",
                    "content": query,
                }
            ],
            [],
            None,
            stage="FTS",
        )
        gold_operator = str(label["gold_ir"]["operator"])
        records.append(
            {
                "case_id": case.case_id,
                "gold_operator": gold_operator,
                "runtime_plan_operator": plan.operator,
                "decision": decision.model_dump(mode="json"),
                "reason": reason,
                "wrong_complete": gold_operator != "LOOKUP" and decision.complete,
                "lookup_completed": gold_operator == "LOOKUP" and decision.complete,
            }
        )
    wrong = [record["case_id"] for record in records if record["wrong_complete"]]
    lookup_cases = [record for record in records if record["gold_operator"] == "LOOKUP"]
    if len(records) != 10 or len(lookup_cases) != 1:
        raise FocusedP0Error("focused P0 denominator drifted")
    receipt: dict[str, Any] = {
        "schema": "milai.dg17.q1-p0-focused.v0.1",
        "status": (
            "PASS_P0_WRONG_COMPLETE_ZERO"
            if not wrong and lookup_cases[0]["lookup_completed"]
            else "FAIL_P0"
        ),
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / NO_PROVIDER_CALL",
        "matched_characterization": {
            "path": str(MATCHED_PATH.relative_to(ROOT)),
            "sha256": MATCHED_SHA256,
            "status": matched.get("status"),
            "summaries": matched.get("summaries"),
        },
        "denominators": {
            "case_count": len(records),
            "non_lookup_case_count": len(records) - len(lookup_cases),
            "lookup_case_count": len(lookup_cases),
            "provider_calls": 0,
            "automatic_retries": 0,
            "formal_holdout_consumed": False,
        },
        "gates": {
            "wrong_complete": f"{len(wrong)}/{len(records) - len(lookup_cases)}",
            "lookup_regression": (
                "0/1" if lookup_cases[0]["lookup_completed"] else "1/1"
            ),
        },
        "records": records,
    }
    _atomic_json(output, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "var/dg17/q1/dg17-q1-p0-focused-20260827-001.json",
    )
    args = parser.parse_args()
    receipt = run(args.output)
    print(json.dumps({"output": str(args.output), "status": receipt["status"]}))


if __name__ == "__main__":
    main()

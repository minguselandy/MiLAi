from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.benchmark import dg11_measurement
from scripts import dg11_state

DEFAULT_RUN = ROOT / "var/dg10/runs/lme-confirmation-20260823-003"
DEFAULT_DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"


def _load_relevant_sessions(dataset: Path, selected: set[str]) -> dict[str, list[str]]:
    rows = json.loads(dataset.read_text(encoding="utf-8"))
    result: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("question_id") not in selected:
            continue
        values = row.get("answer_session_ids")
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("selected LongMemEval answer-session contract failed")
        result[str(row["question_id"])] = list(values)
    if set(result) != selected:
        raise ValueError("selected LongMemEval labels are incomplete")
    return result


def run(run_id: str, source_run: Path, dataset: Path) -> dict[str, Any]:
    raw_path = source_run / "raw-records.json"
    report_path = source_run / "report.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    selected = {str(value) for value in report["dataset"]["selected_source_ids"]}
    metrics = dg11_measurement.recompute(
        raw["records"],
        relevant_sessions=_load_relevant_sessions(dataset, selected),
    )
    frozen_v1 = report["aggregates"]
    for arm in ("NO_MEMORY", "NAIVE_RAG", "MILAI_T3A"):
        observed = metrics["arms"][arm]["scorer_v1"]
        if (
            observed["normalized_f1_mean"] != frozen_v1[arm]["normalized_f1_mean"]
            or observed["exact_match_mean"] != frozen_v1[arm]["exact_match_mean"]
        ):
            raise ValueError("DG-10 frozen aggregate cannot be reproduced")
    milai = metrics["arms"]["MILAI_T3A"]
    result = {
        "schema": "milai.dg11.offline-baseline.v1",
        "run_id": run_id,
        "work_package": "DG11-00",
        "status": "PASS",
        "decision": "BASELINE_READY",
        "source_run_id": raw["run_id"],
        "source_raw_sha256": dg11_state.sha256(raw_path),
        "source_report_sha256": dg11_state.sha256(report_path),
        "dataset_sha256": dg11_state.sha256(dataset),
        "case_denominator": metrics["case_count"],
        "record_denominator": metrics["record_count"],
        "metrics": metrics,
        "summary": {
            "milai_hit_at_3": milai["retrieval_hit_at_k_mean"],
            "milai_relevant_coverage_at_3": milai["relevant_coverage_at_k_mean"],
            "milai_answer_span_survival_on_hit": milai[
                "answer_span_survival_on_hit"
            ],
            "milai_unknown_count": milai["unknown_count"],
            "milai_hit_and_v1_f1_zero_count": milai[
                "hit_and_v1_f1_zero_count"
            ],
            "milai_hit_and_answer_span_missing_count": milai[
                "hit_and_answer_span_missing_count"
            ],
            "v1_f1_delta_vs_rag": metrics["paired"]["scorer_v1"][
                "milai_minus_naive_rag_f1_mean"
            ],
            "v2_f1_delta_vs_rag": metrics["paired"]["scorer_v2"][
                "milai_minus_naive_rag_f1_mean"
            ],
        },
        "provider_requests": 0,
        "development_ai_reviews": 0,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.record_result(result, phase="BASELINE_READY", work_package="DG11-00")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute the DG-11 baseline offline")
    parser.add_argument("--run-id", default="dg11-offline-baseline-001")
    parser.add_argument("--source-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    result = run(args.run_id, args.source_run.resolve(), args.dataset.resolve())
    print(json.dumps({
        "run_id": result["run_id"],
        "status": result["status"],
        "provider_requests": result["provider_requests"],
        "summary": result["summary"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

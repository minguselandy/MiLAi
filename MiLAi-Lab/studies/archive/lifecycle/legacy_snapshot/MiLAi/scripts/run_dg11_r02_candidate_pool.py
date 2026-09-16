from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg11_state

INPUTS = ROOT / "var/dg11/holdout/v1/holdout-inputs.json"
DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
ENV_FILE = ROOT / "runtime/.env"
PYTHON = ROOT / "runtime/.venv/bin/python"
MCP_PYTHON = ROOT / "integrations/mcp/.venv/bin/python"


def _merge_pool_records(
    cases: list[dict[str, Any]],
    base_records: dict[str, dict[str, Any]],
    repair_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    expected_ids = [str(case["source_id"]) for case in cases]
    if set(base_records).difference(expected_ids) or set(repair_records).difference(
        expected_ids
    ):
        raise RuntimeError("R02 resume pool contains an unexpected source ID")
    merged = []
    for source_id in expected_ids:
        record = repair_records.get(source_id, base_records.get(source_id))
        if record is None:
            raise RuntimeError("R02 resume pool is missing a source ID")
        merged.append(record)
    return merged


def run(run_id: str, *, resume_pool_run: Path | None = None) -> dict[str, Any]:
    run_dir = ROOT / "var/dg11/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    source = json.loads(INPUTS.read_text(encoding="utf-8"))
    cases = [
        case for case in source["cases"] if case["category"] == "multi-session"
    ]
    if len(cases) != 30:
        raise RuntimeError("R02 multi-session denominator drifted")
    inputs = {
        "schema": "milai.dg11.holdout-inputs.v1",
        "label_fields_present": False,
        "source_ids": [case["source_id"] for case in cases],
        "cases": cases,
    }
    input_path = run_dir / "label-free-inputs.json"
    output_path = run_dir / "candidate-pool-contexts.json"
    dg11_state.atomic_json(input_path, inputs)
    worker_inputs = inputs
    worker_input_path = input_path
    worker_output_path = output_path
    base_records: dict[str, dict[str, Any]] = {}
    resumed_from_run_id: str | None = None
    if resume_pool_run is not None:
        base_payload = json.loads(
            (resume_pool_run / "candidate-pool-contexts.json").read_text(encoding="utf-8")
        )
        if base_payload.get("schema") != "milai.dg11.holdout-contexts.v1":
            raise RuntimeError("R02 resume pool schema drifted")
        base_records = {
            str(record["source_id"]): record for record in base_payload["records"]
        }
        repair_cases = [
            case
            for case in cases
            if not base_records.get(str(case["source_id"]), {})
            .get("trace", {})
            .get("retrieved_session_ids")
        ]
        if not repair_cases:
            raise RuntimeError("R02 resume pool has no invalid records to repair")
        worker_inputs = {
            **inputs,
            "source_ids": [case["source_id"] for case in repair_cases],
            "cases": repair_cases,
        }
        worker_input_path = run_dir / "repair-inputs.json"
        worker_output_path = run_dir / "repair-contexts.json"
        dg11_state.atomic_json(worker_input_path, worker_inputs)
        resumed_from_run_id = resume_pool_run.name
    environment = dict(os.environ)
    environment.update(
        {
            "DG10_MCP_HOST_PYTHON": str(MCP_PYTHON),
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    command = [
        str(PYTHON),
        "-m",
        "evals.benchmark.dg11_holdout_context_worker",
        "--inputs",
        str(worker_input_path),
        "--output",
        str(worker_output_path),
        "--env-file",
        str(ENV_FILE),
        "--identity",
        "current",
        "--workers",
        "2",
        "--expected-cases",
        str(len(worker_inputs["cases"])),
        "--recall-limit",
        "10",
    ]
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if completed.returncode != 0:
        raise RuntimeError("R02 candidate-pool worker failed")
    worker_payload = json.loads(worker_output_path.read_text(encoding="utf-8"))
    if base_records:
        repair_records = {
            str(record["source_id"]): record for record in worker_payload["records"]
        }
        payload = {
            **worker_payload,
            "records": _merge_pool_records(cases, base_records, repair_records),
        }
        dg11_state.atomic_json(output_path, payload)
    else:
        payload = worker_payload
    if payload.get("schema") != "milai.dg11.holdout-contexts.v1":
        raise RuntimeError("R02 candidate-pool output schema drifted")
    records = {record["source_id"]: record for record in payload["records"]}
    if len(records) != len(cases):
        raise RuntimeError("R02 candidate-pool output denominator drifted")
    rows = {
        row["question_id"]: row
        for row in json.loads(DATASET.read_text(encoding="utf-8"))
        if row.get("question_id") in records
    }
    measurements = []
    for source_id, record in records.items():
        relevant = {str(value) for value in rows[source_id]["answer_session_ids"]}
        retrieved = [str(value) for value in record["trace"]["retrieved_session_ids"]]
        top3 = relevant.intersection(retrieved[:3])
        top10 = relevant.intersection(retrieved)
        measurements.append(
            {
                "source_id": source_id,
                "relevant_session_count": len(relevant),
                "retrieved_session_ids": retrieved,
                "retrieval_hit_at_3": int(bool(top3)),
                "retrieval_hit_at_10": int(bool(top10)),
                "relevant_coverage_at_3": round(len(top3) / len(relevant), 6),
                "relevant_coverage_at_10": round(len(top10) / len(relevant), 6),
            }
        )
    summary = {
        "case_count": len(measurements),
        "empty_pool_count": sum(
            not record["trace"]["retrieved_session_ids"]
            for record in payload["records"]
        ),
        "pool_size_min": min(
            len(record["trace"]["retrieved_session_ids"])
            for record in payload["records"]
        ),
        "pool_size_mean": round(
            mean(
                len(record["trace"]["retrieved_session_ids"])
                for record in payload["records"]
            ),
            3,
        ),
        "recall_transports": sorted(
            {str(record["trace"].get("recall_transport")) for record in payload["records"]}
        ),
        "recall_statuses": sorted(
            {str(record["trace"].get("recall_status")) for record in payload["records"]}
        ),
        "retrieval_hit_at_3": round(
            mean(record["retrieval_hit_at_3"] for record in measurements), 6
        ),
        "retrieval_hit_at_10": round(
            mean(record["retrieval_hit_at_10"] for record in measurements), 6
        ),
        "relevant_coverage_at_3": round(
            mean(record["relevant_coverage_at_3"] for record in measurements), 6
        ),
        "relevant_coverage_at_10": round(
            mean(record["relevant_coverage_at_10"] for record in measurements), 6
        ),
    }
    valid_pool = (
        summary["empty_pool_count"] == 0
        and summary["pool_size_min"] >= 4
        and summary["recall_transports"] == ["AUTHORIZED_HTTP_RETRIEVAL"]
        and set(summary["recall_statuses"]).issubset({"OK", "DEGRADED"})
    )
    result = {
        "schema": "milai.dg11.r02-candidate-pool.v1",
        "run_id": run_id,
        "work_package": "DG11-R02",
        "status": "PASS" if valid_pool else "FAILED",
        "decision": (
            "B1_POOL_COLLECTED" if valid_pool else "B1_POOL_INVALID_OR_EMPTY"
        ),
        "provider_requests": 0,
        "hidden_provider_calls": 0,
        "development_ai_reviews": 0,
        "resumed_from_run_id": resumed_from_run_id,
        "repaired_case_count": len(worker_inputs["cases"]) if base_records else 0,
        "summary": summary,
        "records": measurements,
    }
    dg11_state.atomic_json(run_dir / "result.json", result)
    dg11_state.append_ledger(
        {
            "run_id": run_id,
            "work_package": "DG11-R02",
            "status": result["status"],
            "decision": result["decision"],
            "provider_requests": 0,
            "development_ai_reviews": 0,
            "metrics": summary,
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--resume-pool-run", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    result = run(
        args.run_id,
        resume_pool_run=(
            args.resume_pool_run.resolve() if args.resume_pool_run is not None else None
        ),
    )
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

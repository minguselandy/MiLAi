"""Apply released InstructIR metrics offline; qrels never enter the retrieval runner."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.datasets.instructir import evaluate_rankings
from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    queries = [json.loads(line)
               for line in (args.release / "queries.jsonl").read_text().splitlines()]
    qrels: dict[str, dict[str, int]] = {}
    for line in (args.release / "qrels/test.jsonl").read_text().splitlines():
        row = json.loads(line)
        qrels.setdefault(row["query-id"], {})[row["corpus-id"]] = row["score"]
    driver = read_json(args.run / "driver.json")
    cohort = read_json(args.run / "query-cohort.json")["queries"]
    if cohort != [row["_id"] for row in queries]:
        raise ValueError("Declared query cohort differs from the complete selected release")
    results = read_json(args.run / "rankings.json")
    report = evaluate_rankings(queries, qrels, results)
    report.update(run_status=driver["status"], completed_positions=len(driver["completed"]),
        planned_positions=len(queries),
        full_cohort_closed=driver["status"] in {"COMPLETED", "COMPLETED_WITH_FAILURES"}
            and len(driver["completed"]) == len(queries),
        ranking_protocol=driver["ranking_protocol"],
        query_success_scope="Execution completion is separate from native retrieval relevance. "
            "A partial run retains the full denominator but is not a final full-cohort result.",
        wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu,
        model_calls=0, ledger_recorded=False)
    write_json(args.output, report)
    print(json.dumps({key: report[key] for key in (
        "run_status", "full_cohort_closed", "queries", "query_groups", "metrics")}))


if __name__ == "__main__":
    main()

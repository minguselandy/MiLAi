"""Native QASPER answer agreement on bound operation states, grouped by original source."""
from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def native_event_input(case: dict[str, Any], branch: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    """Keep repeat states separate while retaining the original question and source grouping."""
    event = case["event_id"]
    gold = {case["family"]: {"qas": [{"question_id": event,
                                    "answers": case["native_control"]["annotations"]}]}}
    prediction = None
    if branch["readout_status"] == "COMPLETED":
        prediction = {"question_id": event, "predicted_answer": branch["answer"],
                      "predicted_evidence": []}
    return gold, prediction


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compiled", type=Path)
    parser.add_argument("official_evaluator", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    manifest = read_json(args.compiled / "manifest.json")
    readout_run = read_json(Path(manifest["readouts"]) / "run.json")
    if readout_run["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
        raise ValueError("Native scoring requires a closed bound first-readout matrix")
    cases = read_json(args.compiled / "review-inputs.json")
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    with tempfile.TemporaryDirectory(prefix="native-", dir=args.output) as directory:
        gold_path = Path(directory) / "gold.json"
        predictions_path = Path(directory) / "predictions.jsonl"
        for case in cases:
            for branch in case["branches"]:
                gold, prediction = native_event_input(case, branch)
                write_json(gold_path, gold)
                predictions_path.write_text(json.dumps(prediction, ensure_ascii=False) + "\n"
                                            if prediction is not None else "")
                completed = subprocess.run(  # noqa: S603 -- inspected local native evaluator
                    [sys.executable, str(args.official_evaluator.resolve()),
                     "--gold", str(gold_path), "--predictions", str(predictions_path)],
                    check=True, capture_output=True, text=True)
                native = json.loads(completed.stdout)
                results.append({"family": case["family"], "event_id": case["event_id"],
                    "native_question_id": case["native_control"]["native_question_id"],
                    "action": branch["action"], "policies": branch["policies"],
                    "readout": branch["readout"], "status": branch["readout_status"],
                    "Answer F1": native["Answer F1"],
                    "Missing predictions": native["Missing predictions"]})
    by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        for policy in row["policies"]:
            by_method[policy].append(row)
    metrics = {}
    for policy, rows in by_method.items():
        families: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            families[row["family"]].append(row["Answer F1"])
        source_means = {family: sum(values) / len(values) for family, values in families.items()}
        completed_scores = [r["Answer F1"] for r in rows if r["status"] == "COMPLETED"]
        metrics[policy] = {"states": len(rows), "sources": len(families),
            "status_counts": dict(Counter(r["status"] for r in rows)),
            "state_mean_answer_f1_missing_zero": sum(r["Answer F1"] for r in rows) / len(rows),
            "completed_state_mean_answer_f1": (sum(completed_scores) / len(completed_scores)
                                                if completed_scores else None),
            "source_means": source_means,
            "source_macro_answer_f1_missing_zero": sum(source_means.values()) / len(source_means)}
    write_json(args.output / "results.json", results)
    parent_cpu = time.process_time() - cpu
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = (children.ru_utime + children.ru_stime
                 - children_before.ru_utime - children_before.ru_stime)
    write_json(args.output / "summary.json", {
        "status": "COMPLETED_NATIVE_AGREEMENT_NOT_SEMANTIC_SUCCESS",
        "compiled": str(args.compiled.resolve()),
        "official_evaluator": str(args.official_evaluator.resolve()), "metrics": metrics,
        "scope": "Score the fixed literal answer field, with no posthoc extraction or repair. "
                 "Legacy outputs retain their full original answer strings. Repeated state IDs "
                 "are scoring positions, not independent sources. Missing firsts score zero by "
                 "native protocol and retain execution status; evidence F1 is not reported because "
                 "packet citation labels are not native annotated paragraph predictions.",
        "no_sha_validation": True, "new_model_calls": 0,
        "compute": {"cpu_seconds": parent_cpu + child_cpu,
                    "parent_cpu_seconds": parent_cpu,
                    "native_evaluator_child_cpu_seconds": child_cpu,
                    "wall_seconds": time.perf_counter() - started},
        "cpu_scope": "Parent plus native evaluator children once; do not add components again"})


if __name__ == "__main__":
    main()

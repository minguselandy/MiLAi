"""Bind closed conditional readouts to native QASPER answers and actual material ranges."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from collect_qasper_operation_states import (
    complete,
    covered_sources,
    handoff_items,
    reference_proofs,
)
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.memory_control import MemoryAction


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("readouts", type=Path)
    parser.add_argument("controls", type=Path)
    parser.add_argument("official_evaluator", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    run = read_json(args.readouts / "run.json")
    if run["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
        raise ValueError("Score only the complete declared first-readout matrix")
    cases = read_json(args.prepared / "cases.json")
    paths = read_json(args.readouts / "readout-paths.json")
    collection = Path(read_json(args.prepared / "run.json")["collection"])
    controls = {(row["source_group"], row["request_id"]): row for row in read_jsonl(args.controls)}
    raw = {row["event_id"]: row for row in read_jsonl(collection / "branches.jsonl")}
    gold = {
        case["family"]: {
            "qas": [
                {
                    "question_id": controls[case["family"], case["request_id"]][
                        "native_question_id"
                    ],
                    "answers": controls[case["family"], case["request_id"]]["annotations"],
                }
            ]
        }
        for case in cases
    }
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "gold.json", gold)
    per_case = []
    for case in cases:
        native = controls[case["family"], case["request_id"]]
        proofs = reference_proofs(native)
        original = raw[case["event_id"]]
        source_map = read_json(Path(case["original_Source_bank"]) / "source-map.json")
        observed = {item["item_index"]: item for item in original["before"]["observed_materials"]}
        scopes = {
            item["item_index"]: {
                "kind": item["evidence"]["kind"],
                "source_ranges": item["source_ranges"],
            }
            for item in original["before"]["retrieved_scopes"]
        }
        operations = SimpleNamespace(
            observed=observed,
            opened={i: item for i, item in observed.items() if item["selected"]},
            retrieved_scopes=lambda scopes=scopes: scopes,
        )
        entry = {
            "family": case["family"],
            "request_id": case["request_id"],
            "native_question_id": native["native_question_id"],
            "native_answer_annotations": native["annotations"],
            "question": original["before"]["task"]["request"],
            "policies": {},
        }
        for policy in paths:
            branch = next(b for b in case["branches"] if policy in b["policies"])
            record_path = Path(paths[policy][case["family"]])
            record = read_json(record_path)
            if (
                record["family"] != case["family"]
                or record["request_id"] != case["request_id"]
                or record["event_id"] != case["event_id"]
                or record["action"] != branch["action"]
                or read_json(Path(record["request"])) != branch["readout_request"]
            ):
                raise ValueError(
                    "Readout does not belong to the actual selected packet and request"
                )
            selected = handoff_items(MemoryAction(**branch["action"]), operations)
            coverage = covered_sources(
                selected, source_map["mapping"], source_map["source_lengths"]
            )
            entry["policies"][policy] = {
                "readout": str(record_path.resolve()),
                "status": record["status"],
                "answer": record["answer"],
                "action": branch["action"],
                "packet": branch["packet"],
                "packet_tokens": branch["body_tokens"],
                "usage": record.get("usage"),
                "reference_proof_complete": complete(proofs, coverage) if proofs else None,
                "delivered_native_sources": sorted(coverage),
            }
        per_case.append(entry)
    write_json(args.output / "review-inputs.json", per_case)
    metrics = {}
    for policy in paths:
        predicted_path = args.output / f"{policy}-predictions.jsonl"
        with predicted_path.open("w") as stream:
            for case in per_case:
                result = case["policies"][policy]
                if result["status"] == "COMPLETED":
                    stream.write(
                        json.dumps(
                            {
                                "question_id": case["native_question_id"],
                                "predicted_answer": result["answer"],
                                "predicted_evidence": [],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        result = subprocess.run(  # noqa: S603 -- existing local official evaluator, explicit argv
            [
                sys.executable,
                str(args.official_evaluator.resolve()),
                "--gold",
                str((args.output / "gold.json").resolve()),
                "--predictions",
                str(predicted_path.resolve()),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        metrics[policy] = {
            "official": json.loads(result.stdout),
            "completed": sum(c["policies"][policy]["status"] == "COMPLETED" for c in per_case),
            "reference_complete": sum(
                c["policies"][policy]["reference_proof_complete"] is True for c in per_case
            ),
            "reference_unknown": sum(
                c["policies"][policy]["reference_proof_complete"] is None for c in per_case
            ),
            "packet_tokens": sum(c["policies"][policy]["packet_tokens"] for c in per_case),
        }
    fixed_equivalence = {
        policy: sum(
            next(b["packet"] for b in case["branches"] if policy in b["policies"])
            == next(
                r["packet"]
                for r in raw[case["event_id"]]["results"]
                if r["action"]["id"] == "handoff"
            )
            for case in cases
        )
        for policy in paths
    }
    report = {
        "status": "CLOSED_CONDITIONAL_READOUT_NATIVE_AGREEMENT_NOT_SEMANTIC_SUCCESS",
        "families": len(cases),
        "metrics": metrics,
        "exact_fixed_current_packet_matches": fixed_equivalence,
        "readout_run": run,
        "official_evaluator": str(args.official_evaluator.resolve()),
        "scope": "Full literal answer strings, no favorable extraction or failed-answer repair. "
        "Official F1 measures lexical agreement, not complete semantic task success; "
        "Evidence F1 is not interpreted because the answer wire has no evidence prediction. "
        "All eight fixed source positions retained; semantic source review separate. "
        "Fixed-current equal packets are an available simple baseline, not model innovation.",
        "new_model_calls": 0,
        "no_sha_validation": True,
        "compute": {
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
        },
    }
    write_json(args.output / "summary.json", report)
    print(json.dumps({"metrics": metrics, "exact_fixed_current_packet_matches": fixed_equivalence}))


if __name__ == "__main__":
    main()

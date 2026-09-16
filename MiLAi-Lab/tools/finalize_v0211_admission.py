"""Account for all frozen positions when the first-wave qualification gate stops execution."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from check_v0210_control import LAB, write
from milai_lab.methods.state_control import digest


def finalize(root: Path) -> dict:
    manifest = json.loads((root / "candidate-manifest.json").read_text())
    qualification = json.loads((root / "evaluation/source-qualification.json").read_text())
    contract = json.loads((root / "evaluation/evaluation_contract.json").read_text())
    source = json.loads((root / "source-fidelity.json").read_text())
    export = json.loads((root / "source-export-result.json").read_text())
    assert qualification["first_wave"]["status"] == "EXPOSED_NEAR_DUPLICATE"
    assert qualification["first_wave"]["question_id"] == manifest["first_wave_named_candidates"][0]
    assert not qualification["first_wave"]["replacement_allowed"]
    for record in (qualification, contract):
        for filename, expected in record["input_hashes"].items():
            assert digest((root / filename).read_bytes()) == expected, filename
    qualified = {r["question_id"]: r for r in qualification["cases"]}
    evaluations = {r["question_id"]: r for r in contract["cases"]}
    rows, fit_rows = [], []
    for slot in manifest["slots"]:
        identity = slot["question_id"]
        if identity is None:
            status = "NOT_RUN_NO_ELIGIBLE_NEW_PARTITION"
        elif slot["ordinal"] == 0:
            status = "NOT_RUN_FIRST_WAVE_EXPOSED_NEAR_DUPLICATE"
        else:
            status = "NOT_RUN_SEQUENTIAL_BRANCH_NOT_ENTERED"
        row = {**slot, "status": status, "generations": 0, "raw_tokens": 0,
               "first_answer": None, "correctness": "NOT_EVALUATED",
               "support_presented": "NOT_RUN", "behavioral_failure_layer": None,
               "qualification": qualified[identity]["status"] if identity else "NO_CANDIDATE"}
        rows.append(row)
        if identity:
            assert identity in evaluations
            fit_rows.append({"question_id": identity, "run_id": slot["run_id"],
                             "tier": "small", "haystack_count": 100,
                             "source_completeness": "PASS_FULL_ORIGINAL_TEXT_AND_IMAGES",
                             "status": "FIT_UNVERIFIED", "reason": (
                                 "Admission stops before online Host/tool execution; "
                                 "image generation, MCP isolation and reachability not exercised"),
                             "X2b": "NOT_RUN", "modality_downgrade": False})
    assert len(rows) == 69 and len(fit_rows) == len(evaluations) == 10
    write(root / "position-ledger.json", rows)
    write(root / "backend-fit.json", fit_rows)
    write(root / "branch-log.json", [{"wave": 1, "planned_positions": 9,
          "planned_named_candidates": 1, "qualified_first_wave_candidates": 0,
          "evidence": "evaluation/source-qualification.json#/first_wave",
          "decision": "STOPPED_RESOURCE_OR_PROTOCOL_LIMIT",
          "reason": "EXPOSURE_QUALIFICATION_GATE_NO_SUBSTITUTION",
          "next_queue": None, "remaining_positions": 60,
          "observed_use_failures": 0, "behavior_evaluable_denominator": 0}])
    paths = [LAB / "configs/v0211-external-diagnostic.json",
             LAB / "data/manifests/v0211-exposure-review.json",
             LAB / "src/milai_lab/methods/external_diagnostic.py",
             *sorted((LAB / "tools").glob("*v0211*.py"))]
    write(root / "implementation-pin.json", {str(p.relative_to(LAB)): digest(p.read_bytes())
                                            for p in paths})
    result = {"status": "STOPPED_RESOURCE_OR_PROTOCOL_LIMIT",
              "reason": "NO_ELIGIBLE_FIRST_WAVE_EXTERNAL_SAMPLE_NO_REPLACEMENT",
              "X0": "PARTIAL_NOT_X0_READY", "A0_DIAGNOSTIC_COMPLETE": False,
              "target_positions": 69, "unique_named_candidates": 10,
              "unfilled_target_positions": 59, "position_statuses": dict(Counter(
                  r["status"] for r in rows)), "qualification_counts": qualification["counts"],
              "actual_model_requests": 0, "actual_raw_tokens": 0, "paid_requests": 0,
              "benchmark_judge_requests": 0, "reservations": 0,
              "subagent_review": "MODEL_ASSISTED_ORCHESTRATOR_LABOR_NOT_HUMAN_OR_FREE",
              "all_behavior_metrics": "NOT_EVALUABLE_0_OF_0_NO_QA_INFERENCE",
              "candidate_gate": "NOT_ESTABLISHED", "core_signal": "NOT_ESTABLISHED",
              "intervention": "NOT_ENTERED_NOT_AUTHORIZED", "source_export": export,
              "source_integrity": source["status"], "product_source_changes": False,
              "product_service_started": False, "agent_memory_mutations": 0,
              "harness_ingest": "SOURCE_FILES_ONLY_200_TRAJECTORIES_NO_PRODUCT_INGEST",
              "public_service_changes": False, "protected_question_records_opened": 0,
              "current_candidates_opened_for_offline_qualification": 10,
              "cleanup": "NO_OWNED_SERVICES_STARTED_SOURCE_FILES_AND_EVIDENCE_RETAINED",
              "baseline": "KEEP_0.1.15_A0", "schema": "NO-GO FOR SCHEMA FREEZE"}
    write(root / "admission-result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(finalize(args.root.resolve())))

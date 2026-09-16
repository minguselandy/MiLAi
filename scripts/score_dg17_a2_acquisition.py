#!/usr/bin/env python3
"""Score sealed DG-17 A2 per-slot acquisition output without Reader calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg14.benchmark import _atomic_json
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg17.a1_acquisition import (
    evaluate_a1_gate,
    q6_baseline,
    score_a1_records,
    summarize_a1_records,
)
from evals.dg17.measurement import load_answer_bearing_labels
from evals.dg17.q1r_causality import validate_context_archive

A2_POSTGRES_TEST = (
    "tests/integration/test_projection_worker.py::"
    "test_dg17_a2_product_path_executes_typed_slot_probes_and_retains_fusion_provenance"
)


class A2ScoreError(RuntimeError):
    """An A2 sealed input, prerequisite, or factor denominator drifted."""


def run(
    *,
    run_id: str,
    output: Path,
    context_archive: Path,
    context_archive_sha256: str,
    producer_receipt: Path,
    producer_receipt_sha256: str,
    a0_receipt: Path,
    a0_receipt_sha256: str,
    q6_receipt: Path,
    q6_receipt_sha256: str,
    q8_receipt: Path,
    q8_receipt_sha256: str,
    a1_receipt: Path,
    a1_receipt_sha256: str,
    focused_postgres_receipt: Path,
    focused_postgres_receipt_sha256: str,
    runtime_full_gate: Path,
    runtime_full_gate_sha256: str,
    static_gate_log: Path,
    static_gate_log_sha256: str,
) -> dict[str, Any]:
    if output.exists():
        raise A2ScoreError("output exists; choose a fresh output path")
    started = time.perf_counter()
    archive = _verified_object(context_archive, context_archive_sha256)
    producer = _verified_object(producer_receipt, producer_receipt_sha256)
    cases, selection = load_public_dev_cases()
    case_ids = [str(case.case_id) for case in cases]
    records = validate_context_archive(archive, case_ids=case_ids)
    if (
        producer.get("status") != "SUCCEEDED"
        or producer.get("labels_loaded") is not False
        or producer.get("formal_holdout_consumed") is not False
        or producer.get("historical_answer_reuse") is not False
        or producer.get("case_count") != 10
        or producer.get("record_count") != 40
        or producer.get("retrieval_execution_count") != 20
        or producer.get("same_execution_policy_views_per_retrieval") != 2
        or producer.get("context_archive", {}).get("sha256")
        != context_archive_sha256
    ):
        raise A2ScoreError("A2 producer receipt failed the label-free boundary")

    # Gold answer-bearing labels open only after the product archive is sealed.
    _label_envelope, labeled_cases, labels = load_answer_bearing_labels()
    if [str(case.case_id) for case in labeled_cases] != case_ids:
        raise A2ScoreError("A2 label denominator drifted")
    a0 = _verified_object(a0_receipt, a0_receipt_sha256)
    q6 = _verified_object(q6_receipt, q6_receipt_sha256)
    q8 = _verified_object(q8_receipt, q8_receipt_sha256)
    a1 = _verified_object(a1_receipt, a1_receipt_sha256)
    focused = _verified_object(
        focused_postgres_receipt, focused_postgres_receipt_sha256
    )
    full_gate = _verified_object(runtime_full_gate, runtime_full_gate_sha256)
    static_text = _verified_text(static_gate_log, static_gate_log_sha256)
    if a0.get("status") != "PASS":
        raise A2ScoreError("A0 prerequisite is not PASS")
    if q6.get("status") != "CHARACTERIZED" or q8.get("status") != "CHARACTERIZED":
        raise A2ScoreError("frozen Q6/Q8 identity drifted")
    if a1.get("status") != "A1_FACTOR_PASS_CUMULATIVE_GATE_PARTIAL":
        raise A2ScoreError("A1 factor disposition does not authorize A2")
    if (
        focused.get("status") != "PASS"
        or focused.get("pytest_exit_code") != 0
        or A2_POSTGRES_TEST not in focused.get("tests", [])
    ):
        raise A2ScoreError("A2 real PostgreSQL product-path gate is not PASS")
    if (
        full_gate.get("status") != "PASS"
        or full_gate.get("pytest_exit_code") != 0
        or int(full_gate.get("pytest_passed", 0)) < 434
        or full_gate.get("cleanup", {}).get("status") != "PASS"
    ):
        raise A2ScoreError("A2 full Runtime regression gate is not PASS")
    if not all(
        marker in static_text
        for marker in (
            "20 passed",
            "All checks passed!",
            "Success: no issues found in 102 source files",
        )
    ):
        raise A2ScoreError("A2 focused/static/strict-mypy gate is not PASS")

    cells = score_a1_records(records, labels=labels)
    summaries = summarize_a1_records(cells)
    baseline = q6_baseline(q6)
    gate = evaluate_a1_gate(
        summaries,
        cells,
        baseline=baseline,
        a0_required_evidence_coverage=int(
            a0.get("summary", {}).get("unique_required_evidence_count", -1)
        ),
        automatic_retries=0,
    )
    previous = _summary(a1, "2048")
    current = _summary({"summaries": summaries}, "2048")
    deltas = {
        "required_evidence_atom_hits": (
            int(current["required_evidence_atom_hits"])
            - int(previous["required_evidence_atom_hits"])
        ),
        "answer_bearing_source_turn_hits": (
            int(current["answer_bearing_source_turn_hits"])
            - int(previous["answer_bearing_source_turn_hits"])
        ),
        "operator_ready_case_count": (
            int(current["operator_ready_case_count"])
            - int(previous["operator_ready_case_count"])
        ),
        "packing_loss_count": (
            int(current["packing_loss_count"]) - int(previous["packing_loss_count"])
        ),
    }
    factor_checks = {
        "typed_slot_probe_contract_real_postgresql": True,
        "full_runtime_regression": True,
        "strict_mypy_ruff_focused_tests": True,
        "wrong_complete_zero": gate["checks"]["wrong_complete_zero"],
        "wrong_scope_or_authority_zero": gate["checks"][
            "wrong_scope_or_authority_zero"
        ],
        "current_q6_correct_cases_retained_2_of_2": gate["checks"][
            "current_q6_correct_cases_retained_2_of_2"
        ],
        "automatic_retries_zero": True,
        "atom_acquisition_no_regression_from_a1": deltas[
            "required_evidence_atom_hits"
        ]
        >= 0,
        "source_turn_acquisition_no_regression_from_a1": deltas[
            "answer_bearing_source_turn_hits"
        ]
        >= 0,
        "operator_ready_no_regression_from_a1": deltas[
            "operator_ready_case_count"
        ]
        >= 0,
    }
    factor_status = "PASS_TO_A3" if all(factor_checks.values()) else "PARTIAL"
    acquisition_trace_count = sum(
        isinstance(record.get("semantic_mediators"), Mapping)
        and isinstance(record["semantic_mediators"].get("acquisition_trace"), Mapping)
        for record in records
        if record.get("policy") == "DG17_QUERY_SPECIFIC_STOP"
    )
    receipt = {
        "schema": "milai.dg17.a2-per-slot-acquisition.v0.1",
        "status": (
            "A2_FACTOR_PASS_CUMULATIVE_GATE_PARTIAL"
            if factor_status == "PASS_TO_A3" and gate["status"] != "PASS"
            else "A2_FACTOR_PASS"
            if factor_status == "PASS_TO_A3"
            else "PARTIAL"
        ),
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / PRODUCT_ACQUISITION_MEDIATOR",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": selection["formal_source_id_overlap"],
        "single_factor": {
            "factor": "TYPED_PER_SLOT_RAW_FTS_PROBES_AND_PROVENANCE_PRESERVING_RRF",
            "baseline": "A1_TURN_FIRST_WITH_UNTYPED_SLOT_QUERY_TUPLES",
            "candidate": "ACQUISITION_PLAN_V01_PER_SLOT_QUOTA_RRF_V1",
            "role_boost": False,
            "lexical_enrichment": False,
            "evidence_dense": False,
            "evidence_reranker": False,
            "context_compiler_change": False,
            "reader_prompt_change": False,
        },
        "implementation_identity": {
            path: _binding(ROOT / path, _sha256(ROOT / path))
            for path in (
                "runtime/src/milai/domain/acquisition.py",
                "runtime/src/milai/application/acquisition.py",
                "runtime/src/milai/application/retrieval.py",
                "runtime/tests/unit/test_dg17_acquisition_plan.py",
                "runtime/tests/integration/test_projection_worker.py",
                "scripts/score_dg17_a2_acquisition.py",
            )
        },
        "label_boundary": {
            "archive_sealed_before_labels": True,
            "producer_labels_loaded": False,
            "product_path_label_access_count": 0,
            "scoring_labels_loaded_after_seal": True,
        },
        "bound_artifacts": {
            "context_archive": _binding(context_archive, context_archive_sha256),
            "producer_receipt": _binding(producer_receipt, producer_receipt_sha256),
            "a0_receipt": _binding(a0_receipt, a0_receipt_sha256),
            "q6_receipt": _binding(q6_receipt, q6_receipt_sha256),
            "q8_receipt": _binding(q8_receipt, q8_receipt_sha256),
            "a1_receipt": _binding(a1_receipt, a1_receipt_sha256),
            "focused_postgresql_gate": _binding(
                focused_postgres_receipt, focused_postgres_receipt_sha256
            ),
            "runtime_full_gate": _binding(runtime_full_gate, runtime_full_gate_sha256),
            "static_gate_log": _binding(static_gate_log, static_gate_log_sha256),
        },
        "provenance_gate": {
            "real_product_path_test_count": 1,
            "real_product_path_test_passed": 1,
            "candidate_envelopes_asserted": 2,
            "probe_slot_channel_rank_provenance_asserted": True,
            "archive_current_policy_trace_count": acquisition_trace_count,
            "archive_current_policy_trace_denominator": 20,
            "archive_trace_boundary": (
                "Q1R_PRODUCER_PROCESS_PRECEDED_ACQUISITION_TRACE_ARCHIVE_FIELD"
                if acquisition_trace_count == 0
                else "ARCHIVED"
            ),
        },
        "baseline": baseline,
        "previous_a1_summary_2048": previous,
        "summaries": summaries,
        "mediator_delta_from_a1_2048": deltas,
        "cells": cells,
        "cumulative_acquisition_gate": gate,
        "factor_disposition": {
            "status": factor_status,
            "checks": factor_checks,
            "A3_authorized": factor_status == "PASS_TO_A3",
            "A10_authorized": gate["status"] == "PASS",
        },
        "efficiency": {
            "producer_experiment_wall_ms": producer.get("experiment_wall_ms"),
            "scoring_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            "retrieval_executions": 20,
            "reader_calls": 0,
            "auxiliary_model_calls": 0,
            "automatic_retries": 0,
        },
        "claim_boundary": {
            "A3_authorized": factor_status == "PASS_TO_A3",
            "A10_authorized": False,
            "final_lme_authorized": False,
            "release_claim_authorized": False,
            "quality_claim_authorized": False,
        },
    }
    _atomic_json(output, receipt)
    return receipt


def _summary(receipt: Mapping[str, Any], budget: str) -> Mapping[str, Any]:
    summaries = receipt.get("summaries")
    if not isinstance(summaries, Mapping) or not isinstance(summaries.get(budget), Mapping):
        raise A2ScoreError(f"acquisition summary {budget} is missing")
    return summaries[budget]


def _verified_object(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise A2ScoreError(f"artifact identity drifted: {path}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise A2ScoreError(f"artifact is not an object: {path}")
    return value


def _verified_text(path: Path, expected_sha256: str) -> str:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise A2ScoreError(f"artifact identity drifted: {path}")
    return raw.decode("utf-8")


def _binding(path: Path, sha256: str) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    for name in (
        "context-archive",
        "producer-receipt",
        "a0-receipt",
        "q6-receipt",
        "q8-receipt",
        "a1-receipt",
        "focused-postgres-receipt",
        "runtime-full-gate",
        "static-gate-log",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
        parser.add_argument(f"--{name}-sha256", required=True)
    args = parser.parse_args()
    receipt = run(
        run_id=args.run_id,
        output=args.output,
        context_archive=args.context_archive,
        context_archive_sha256=args.context_archive_sha256,
        producer_receipt=args.producer_receipt,
        producer_receipt_sha256=args.producer_receipt_sha256,
        a0_receipt=args.a0_receipt,
        a0_receipt_sha256=args.a0_receipt_sha256,
        q6_receipt=args.q6_receipt,
        q6_receipt_sha256=args.q6_receipt_sha256,
        q8_receipt=args.q8_receipt,
        q8_receipt_sha256=args.q8_receipt_sha256,
        a1_receipt=args.a1_receipt,
        a1_receipt_sha256=args.a1_receipt_sha256,
        focused_postgres_receipt=args.focused_postgres_receipt,
        focused_postgres_receipt_sha256=args.focused_postgres_receipt_sha256,
        runtime_full_gate=args.runtime_full_gate,
        runtime_full_gate_sha256=args.runtime_full_gate_sha256,
        static_gate_log=args.static_gate_log,
        static_gate_log_sha256=args.static_gate_log_sha256,
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "factor_disposition": receipt["factor_disposition"],
                "cumulative_gate": receipt["cumulative_acquisition_gate"],
                "receipt": str(args.output),
                "receipt_sha256": _sha256(args.output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if receipt["claim_boundary"]["A3_authorized"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

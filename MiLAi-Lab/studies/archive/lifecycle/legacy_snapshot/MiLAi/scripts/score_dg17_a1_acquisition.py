#!/usr/bin/env python3
"""Score a sealed A1 product Context archive without any Reader calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
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
    evaluate_a1_factor_disposition,
    evaluate_a1_gate,
    q6_baseline,
    score_a1_records,
    summarize_a1_records,
)
from evals.dg17.measurement import load_answer_bearing_labels
from evals.dg17.q1r_causality import validate_context_archive


class A1ScoreError(RuntimeError):
    """A sealed A1 input or bound prerequisite failed validation."""


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
    focused_postgres_receipt: Path,
    focused_postgres_receipt_sha256: str,
    runtime_full_gate: Path,
    runtime_full_gate_sha256: str,
) -> dict[str, Any]:
    if output.exists():
        raise A1ScoreError("output exists; choose a fresh output path")
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
        raise A1ScoreError("A1 producer receipt failed the label-free boundary")

    # Only after the immutable product archive is validated do scoring labels open.
    _label_envelope, labeled_cases, labels = load_answer_bearing_labels()
    if [str(case.case_id) for case in labeled_cases] != case_ids:
        raise A1ScoreError("A1 label denominator drifted")
    a0 = _verified_object(a0_receipt, a0_receipt_sha256)
    q6 = _verified_object(q6_receipt, q6_receipt_sha256)
    q8 = _verified_object(q8_receipt, q8_receipt_sha256)
    focused = _verified_object(
        focused_postgres_receipt, focused_postgres_receipt_sha256
    )
    full_gate = _verified_object(runtime_full_gate, runtime_full_gate_sha256)
    if a0.get("status") != "PASS" or focused.get("status") != "PASS":
        raise A1ScoreError("A1 prerequisite receipt is not PASS")
    if full_gate.get("status") != "PASS" or full_gate.get("pytest_exit_code") != 0:
        raise A1ScoreError("A1 full Runtime gate is not PASS")
    if q6.get("status") != "CHARACTERIZED" or q8.get("status") != "CHARACTERIZED":
        raise A1ScoreError("A1 frozen Q6/Q8 characterization identity drifted")

    cells = score_a1_records(records, labels=labels)
    summaries = summarize_a1_records(cells)
    baseline = q6_baseline(q6)
    a0_coverage = int(a0.get("summary", {}).get("unique_required_evidence_count", -1))
    # The sealed Q1R producer has no Provider/Reader call or retry loop. Its exact
    # 10 cases x 2 budgets retrieval denominator above is therefore the retry
    # witness; the v0.1 producer receipt predates an explicit retry-count field.
    automatic_retries = 0
    gate = evaluate_a1_gate(
        summaries,
        cells,
        baseline=baseline,
        a0_required_evidence_coverage=a0_coverage,
        automatic_retries=automatic_retries,
    )
    factor_disposition = evaluate_a1_factor_disposition(gate)
    receipt = {
        "schema": "milai.dg17.a1-turn-first-acquisition.v0.1",
        "status": (
            "A1_FACTOR_PASS_CUMULATIVE_GATE_PARTIAL"
            if factor_disposition["status"] == "PASS_TO_A2"
            and gate["status"] != "PASS"
            else "A1_TURN_FIRST_PASS"
            if gate["status"] == "PASS"
            else "PARTIAL"
        ),
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / PRODUCT_ACQUISITION_MEDIATOR",
        "run_id": run_id,
        "implementation_identity": {
            "scorer": _binding(
                ROOT / "evals/dg17/a1_acquisition.py",
                _sha256(ROOT / "evals/dg17/a1_acquisition.py"),
            ),
            "runner": _binding(Path(__file__).resolve(), _sha256(Path(__file__).resolve())),
        },
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": selection["formal_source_id_overlap"],
        "single_factor": {
            "factor": "RAW_EVIDENCE_FTS_PRIMARY_UNIT",
            "baseline": "SESSION_MAX_SCORE_WITH_SESSION_BACKFILL",
            "candidate": "TURN_FIRST_FTS_SEED",
            "role_boost": False,
            "lexical_enrichment": False,
            "evidence_dense": False,
            "evidence_reranker": False,
            "context_compiler_change": False,
            "reader_prompt_change": False,
        },
        "label_boundary": {
            "archive_sealed_before_labels": True,
            "producer_labels_loaded": False,
            "product_path_label_access_count": 0,
            "scoring_labels_loaded_after_seal": True,
        },
        "measurement_boundary": {
            "candidate_boundary": "RUNTIME_SELECTED_SOURCE_REFS_UNION_OPERATOR_OPERANDS",
            "candidate_interpretation": (
                "Evidence-window source identities plus deterministic operator operand "
                "source identities at the Runtime Context boundary; the sealed archive "
                "does not expose the larger pre-cutoff repository pool"
            ),
            "retained_interpretation": (
                "an acquired labeled source retained as an Evidence window, or an "
                "operator operand whose exact labeled span remains in the Reader-visible "
                "derived result"
            ),
            "packing_loss_interpretation": (
                "selected labeled source whose exact labeled span is absent from the "
                "Reader-visible Context"
            ),
        },
        "bound_artifacts": {
            "context_archive": _binding(context_archive, context_archive_sha256),
            "producer_receipt": _binding(producer_receipt, producer_receipt_sha256),
            "a0_receipt": _binding(a0_receipt, a0_receipt_sha256),
            "q6_receipt": _binding(q6_receipt, q6_receipt_sha256),
            "q8_receipt": _binding(q8_receipt, q8_receipt_sha256),
            "focused_postgresql_gate": _binding(
                focused_postgres_receipt, focused_postgres_receipt_sha256
            ),
            "runtime_full_gate": _binding(runtime_full_gate, runtime_full_gate_sha256),
        },
        "baseline": baseline,
        "summaries": summaries,
        "cells": cells,
        "gate": gate,
        "factor_disposition": factor_disposition,
        "efficiency": {
            "producer_experiment_wall_ms": producer.get("experiment_wall_ms"),
            "scoring_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            "retrieval_executions": producer.get("retrieval_execution_count"),
            "reader_calls": 0,
            "auxiliary_model_calls": 0,
            "automatic_retries": automatic_retries,
            "automatic_retry_witness": (
                "Q1R_PRODUCER_HAS_NO_PROVIDER_OR_RETRY_LOOP_AND_EXACTLY_20_RETRIEVALS"
            ),
        },
        "claim_boundary": {
            "A2_authorized": factor_disposition["A2_authorized"],
            "A10_authorized": factor_disposition["A10_authorized"],
            "final_lme_authorized": False,
            "release_claim_authorized": False,
            "quality_claim_authorized": False,
        },
    }
    _atomic_json(output, receipt)
    return receipt


def _verified_object(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise A1ScoreError(f"artifact identity drifted: {path}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise A1ScoreError(f"artifact is not an object: {path}")
    return value


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
        "focused-postgres-receipt",
        "runtime-full-gate",
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
        focused_postgres_receipt=args.focused_postgres_receipt,
        focused_postgres_receipt_sha256=args.focused_postgres_receipt_sha256,
        runtime_full_gate=args.runtime_full_gate,
        runtime_full_gate_sha256=args.runtime_full_gate_sha256,
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "gate": receipt["gate"],
                "receipt": str(args.output),
                "receipt_sha256": _sha256(args.output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if receipt["claim_boundary"]["A2_authorized"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.dg17.measurement import ORACLE_ARMS
from evals.dg17.q0_multiseed import Q0MultiSeedError, build_q0_multiseed_receipt


def _write_receipt(path: Path, *, run_ordinal: int, vary_answer: bool = False) -> None:
    results: list[dict[str, Any]] = []
    for case_ordinal in range(10):
        arms = []
        for arm_ordinal, arm in enumerate(ORACLE_ARMS):
            answer = (
                "variant"
                if vary_answer and case_ordinal == 0 and arm_ordinal == 0
                else "stable"
            )
            arms.append(
                {
                    "arm": arm,
                    "status": "SUCCEEDED",
                    "answer": answer,
                    "answer_sha256": answer,
                    "score": {
                        "exact_match": 1,
                        "normalized_f1": 1.0,
                    },
                    "provider_calls": 1,
                    "provider_latency_ms": 100.0 + run_ordinal,
                    "completion_tokens": 2,
                    "context_truncated": False,
                    "seed": run_ordinal * 100 + case_ordinal,
                }
            )
        results.append(
            {
                "case_id": f"case-{case_ordinal}",
                "query_class": "EPISODIC",
                "diagnosis": "NO_ORACLE_DELTA",
                "arms": arms,
            }
        )
    receipt = {
        "schema": "milai.dg17.q0-measurement.v0.1",
        "status": "Q0_CHARACTERIZED",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "run_id": f"run-{run_ordinal}",
        "dg16_terminal_freeze": {"sha256": "frozen"},
        "labels": {"sha256": "labels"},
        "label_boundary": {"status": "PASS"},
        "reader": {"model_id": "reader"},
        "aggregate": {"case_count": 10},
        "by_query_class": {"EPISODIC": {"case_count": 10}},
        "oracle_ladder": {
            "status": "COMPLETED_WITH_TYPED_UNAVAILABLE",
            "single_run_causal_claim_authorized": False,
            "predicted_ir_source": "MemoryQueryCompiler actual v0.2 output",
            "diagnostic_success_policy": "strict exact_match=1; raw F1 remains reported",
            "arms": list(ORACLE_ARMS),
            "results": results,
        },
    }
    path.write_text(json.dumps(receipt), encoding="utf-8")


def _write_annotation_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "milai.dg17.answer-bearing-annotation-manifest.v0.1",
                "label_artifact_sha256": "labels",
                "annotation": {
                    "independent_reviewer_identity": None,
                    "independent_review_status": "PENDING",
                    "adjudication_status": "PENDING",
                },
                "validation_completed": {
                    "semantic_operator_independently_validated": False,
                    "required_slots_independently_validated": False,
                    "join_relations_independently_validated": False,
                },
            }
        ),
        encoding="utf-8",
    )


def test_q0_multiseed_requires_complete_independent_seed_cells(tmp_path: Path) -> None:
    paths = [tmp_path / f"receipt-{ordinal}.json" for ordinal in range(3)]
    for ordinal, path in enumerate(paths, start=1):
        _write_receipt(path, run_ordinal=ordinal)
    manifest = tmp_path / "manifest.json"
    _write_annotation_manifest(manifest)

    report = build_q0_multiseed_receipt(
        paths, annotation_manifest_path=manifest
    )

    assert report["status"] == "Q0_MULTI_SEED_ORACLE_CHARACTERIZED"
    assert report["run_count"] == 3
    assert report["cell_count"] == report["provider_calls"] == 120
    assert report["aggregate"]["answer_unstable_cell_count"] == 0
    assert report["aggregate"]["per_arm"][ORACLE_ARMS[0]][
        "exact_match_mean"
    ] == 1.0
    assert report["authoritative_for_q0_measurement_gate"] is False
    assert report["annotation_manifest"]["gate_disposition"] == (
        "PROVISIONAL_PENDING_INDEPENDENT_REVIEW"
    )
    assert report["causal_claim_authorized"] is False


def test_q0_multiseed_reports_answer_instability(tmp_path: Path) -> None:
    paths = [tmp_path / f"receipt-{ordinal}.json" for ordinal in range(3)]
    for ordinal, path in enumerate(paths, start=1):
        _write_receipt(path, run_ordinal=ordinal, vary_answer=ordinal == 3)
    manifest = tmp_path / "manifest.json"
    _write_annotation_manifest(manifest)

    report = build_q0_multiseed_receipt(
        paths, annotation_manifest_path=manifest
    )

    assert report["aggregate"]["answer_unstable_cell_count"] == 1
    assert report["aggregate"]["score_unstable_cell_count"] == 0


def test_q0_multiseed_rejects_duplicate_run_identity(tmp_path: Path) -> None:
    paths = [tmp_path / f"receipt-{ordinal}.json" for ordinal in range(3)]
    for ordinal, path in enumerate(paths, start=1):
        _write_receipt(path, run_ordinal=ordinal)

    paths[2].write_bytes(paths[1].read_bytes())

    with pytest.raises(Q0MultiSeedError, match="run IDs must be unique"):
        build_q0_multiseed_receipt(paths)

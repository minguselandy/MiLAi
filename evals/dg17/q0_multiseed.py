"""Aggregate corrected DG-17 Q0 oracle runs across fixed seed identities."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from evals.dg17.measurement import ORACLE_ARMS

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ANNOTATION_MANIFEST = (
    ROOT / "docs/dg17/answer-bearing-labels-annotation-manifest.v0.1.json"
)


class Q0MultiSeedError(RuntimeError):
    """A corrected Q0 receipt is incomplete, inconsistent, or duplicated."""


def build_q0_multiseed_receipt(
    receipt_paths: Sequence[Path],
    *,
    annotation_manifest_path: Path = DEFAULT_ANNOTATION_MANIFEST,
) -> dict[str, Any]:
    """Validate and aggregate at least three complete 40-cell Q0 receipts."""

    if len(receipt_paths) < 3:
        raise Q0MultiSeedError("at least three corrected Q0 runs are required")
    loaded = [_load(path) for path in receipt_paths]
    values = [item["value"] for item in loaded]
    _validate_common_identity(values)
    run_ids = [str(value["run_id"]) for value in values]
    if len(set(run_ids)) != len(run_ids):
        raise Q0MultiSeedError("corrected Q0 run IDs must be unique")
    annotation_manifest = _load_annotation_manifest(
        annotation_manifest_path, values[0]["labels"]
    )
    independent_review_complete = _independent_review_complete(
        annotation_manifest["value"]
    )

    case_order = [str(row["case_id"]) for row in values[0]["oracle_ladder"]["results"]]
    cells: dict[tuple[str, str], list[Mapping[str, Any]]] = {
        (case_id, arm): [] for case_id in case_order for arm in ORACLE_ARMS
    }
    diagnoses: Counter[str] = Counter()
    total_provider_calls = 0
    for value in values:
        results = value["oracle_ladder"]["results"]
        if [str(row.get("case_id")) for row in results] != case_order:
            raise Q0MultiSeedError("corrected Q0 case order drifted")
        for row in results:
            diagnoses[str(row.get("diagnosis"))] += 1
            arms = row.get("arms")
            if not isinstance(arms, list) or [arm.get("arm") for arm in arms] != list(
                ORACLE_ARMS
            ):
                raise Q0MultiSeedError("corrected Q0 arm order drifted")
            for arm in arms:
                _validate_cell(arm)
                total_provider_calls += int(arm["provider_calls"])
                cells[(str(row["case_id"]), str(arm["arm"]))].append(arm)

    if total_provider_calls != len(values) * len(case_order) * len(ORACLE_ARMS):
        raise Q0MultiSeedError("corrected Q0 provider-call accounting drifted")
    stability_rows: list[dict[str, Any]] = []
    for (case_id, arm), samples in cells.items():
        seeds = {int(sample["seed"]) for sample in samples}
        if len(samples) != len(values) or len(seeds) != len(values):
            raise Q0MultiSeedError("corrected Q0 seed identities are not independent")
        answers = {str(sample["answer_sha256"]) for sample in samples}
        scores = {
            (
                int(sample["score"]["exact_match"]),
                float(sample["score"]["normalized_f1"]),
            )
            for sample in samples
        }
        stability_rows.append(
            {
                "case_id": case_id,
                "arm": arm,
                "seed_count": len(seeds),
                "unique_answer_count": len(answers),
                "answer_stable": len(answers) == 1,
                "score_stable": len(scores) == 1,
                "exact_match_rate": round(
                    mean(int(sample["score"]["exact_match"]) for sample in samples),
                    9,
                ),
                "normalized_f1_mean": round(
                    mean(
                        float(sample["score"]["normalized_f1"])
                        for sample in samples
                    ),
                    9,
                ),
            }
        )

    per_arm = {
        arm: _arm_summary(
            [
                sample
                for (case_id, cell_arm), samples in cells.items()
                if cell_arm == arm
                for sample in samples
            ]
        )
        for arm in ORACLE_ARMS
    }
    return {
        "schema": "milai.dg17.q0-multiseed-oracle.v0.1",
        "status": "Q0_MULTI_SEED_ORACLE_CHARACTERIZED",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "authoritative_for_q0_measurement_gate": independent_review_complete,
        "causal_claim_authorized": False,
        "release_claim_authorized": False,
        "run_count": len(values),
        "case_count": len(case_order),
        "arm_count": len(ORACLE_ARMS),
        "cell_count": len(values) * len(case_order) * len(ORACLE_ARMS),
        "provider_calls": total_provider_calls,
        "automatic_retries": 0,
        "context_truncations": 0,
        "case_order": case_order,
        "arms": list(ORACLE_ARMS),
        "source_receipts": [
            {
                "path": item["path"],
                "sha256": item["sha256"],
                "run_id": value["run_id"],
            }
            for item, value in zip(loaded, values, strict=True)
        ],
        "annotation_manifest": {
            "path": annotation_manifest["path"],
            "sha256": annotation_manifest["sha256"],
            "independent_review_complete": independent_review_complete,
            "gate_disposition": (
                "ELIGIBLE_FOR_Q0_MEASUREMENT_GATE"
                if independent_review_complete
                else "PROVISIONAL_PENDING_INDEPENDENT_REVIEW"
            ),
        },
        "frozen_identity": {
            "dg16_terminal_freeze": values[0]["dg16_terminal_freeze"],
            "labels": values[0]["labels"],
            "label_boundary": values[0]["label_boundary"],
            "reader": values[0]["reader"],
            "predicted_ir_source": values[0]["oracle_ladder"][
                "predicted_ir_source"
            ],
            "diagnostic_success_policy": values[0]["oracle_ladder"][
                "diagnostic_success_policy"
            ],
        },
        "aggregate": {
            "per_arm": per_arm,
            "answer_unstable_cell_count": sum(
                not row["answer_stable"] for row in stability_rows
            ),
            "answer_stability_denominator": len(stability_rows),
            "score_unstable_cell_count": sum(
                not row["score_stable"] for row in stability_rows
            ),
            "diagnosis_counts_across_runs": dict(sorted(diagnoses.items())),
        },
        "stability_rows": stability_rows,
    }


def _load_annotation_manifest(
    path: Path, label_identity: object
) -> dict[str, Any]:
    resolved = path if path.is_absolute() else ROOT / path
    raw = resolved.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise Q0MultiSeedError("answer-bearing annotation manifest is malformed")
    labels = label_identity if isinstance(label_identity, Mapping) else {}
    if (
        value.get("schema")
        != "milai.dg17.answer-bearing-annotation-manifest.v0.1"
        or value.get("label_artifact_sha256") != labels.get("sha256")
    ):
        raise Q0MultiSeedError("answer-bearing annotation manifest identity drifted")
    try:
        recorded_path = str(resolved.relative_to(ROOT))
    except ValueError:
        recorded_path = str(resolved)
    return {
        "path": recorded_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "value": value,
    }


def _independent_review_complete(value: Mapping[str, Any]) -> bool:
    annotation = value.get("annotation")
    validation = value.get("validation_completed")
    return (
        isinstance(annotation, Mapping)
        and annotation.get("independent_reviewer_identity") not in {None, ""}
        and annotation.get("independent_review_status") == "ACCEPTED"
        and annotation.get("adjudication_status") == "COMPLETE"
        and isinstance(validation, Mapping)
        and validation.get("semantic_operator_independently_validated") is True
        and validation.get("required_slots_independently_validated") is True
        and validation.get("join_relations_independently_validated") is True
    )


def _load(path: Path) -> dict[str, Any]:
    resolved = path if path.is_absolute() else ROOT / path
    raw = resolved.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise Q0MultiSeedError(f"Q0 receipt is not an object: {resolved}")
    try:
        recorded_path = str(resolved.relative_to(ROOT))
    except ValueError:
        recorded_path = str(resolved)
    return {
        "path": recorded_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "value": value,
    }


def _validate_common_identity(values: Sequence[Mapping[str, Any]]) -> None:
    first = values[0]
    expected = {
        "schema": "milai.dg17.q0-measurement.v0.1",
        "status": "Q0_CHARACTERIZED",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
    }
    identity_keys = (
        "dg16_terminal_freeze",
        "labels",
        "label_boundary",
        "reader",
        "aggregate",
        "by_query_class",
    )
    for value in values:
        if any(value.get(key) != expected_value for key, expected_value in expected.items()):
            raise Q0MultiSeedError("corrected Q0 receipt status/schema drifted")
        ladder = value.get("oracle_ladder")
        if (
            not isinstance(ladder, Mapping)
            or ladder.get("status") != "COMPLETED_WITH_TYPED_UNAVAILABLE"
            or ladder.get("single_run_causal_claim_authorized") is not False
            or ladder.get("predicted_ir_source")
            != "MemoryQueryCompiler actual v0.2 output"
            or ladder.get("arms") != list(ORACLE_ARMS)
            or not isinstance(ladder.get("results"), list)
            or len(ladder["results"]) != 10
        ):
            raise Q0MultiSeedError("corrected Q0 oracle contract drifted")
        if any(value.get(key) != first.get(key) for key in identity_keys):
            raise Q0MultiSeedError("corrected Q0 frozen identity drifted")


def _validate_cell(cell: Mapping[str, Any]) -> None:
    score = cell.get("score")
    if (
        cell.get("status") != "SUCCEEDED"
        or cell.get("provider_calls") != 1
        or cell.get("context_truncated") is not False
        or not isinstance(cell.get("seed"), int)
        or not isinstance(cell.get("answer_sha256"), str)
        or not isinstance(score, Mapping)
        or score.get("exact_match") not in {0, 1}
        or not isinstance(score.get("normalized_f1"), (int, float))
        or not isinstance(cell.get("provider_latency_ms"), (int, float))
        or not isinstance(cell.get("completion_tokens"), int)
    ):
        raise Q0MultiSeedError("corrected Q0 cell is incomplete or unavailable")


def _arm_summary(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    exact_matches = [int(sample["score"]["exact_match"]) for sample in samples]
    f1_values = [float(sample["score"]["normalized_f1"]) for sample in samples]
    latencies = [float(sample["provider_latency_ms"]) for sample in samples]
    completion_tokens = [int(sample["completion_tokens"]) for sample in samples]
    return {
        "sample_count": len(samples),
        "exact_match_mean": round(mean(exact_matches), 9),
        "exact_match_seed_pstdev": round(pstdev(exact_matches), 9),
        "normalized_f1_mean": round(mean(f1_values), 9),
        "normalized_f1_seed_pstdev": round(pstdev(f1_values), 9),
        "provider_latency_mean_ms": round(mean(latencies), 3),
        "provider_latency_p95_ms": round(_percentile(latencies, 0.95), 3),
        "completion_tokens_mean": round(mean(completion_tokens), 3),
        "unknown_answer_count": sum(
            str(sample.get("answer")) == "UNKNOWN" for sample in samples
        ),
    }


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise Q0MultiSeedError("percentile requires samples")
    index = max(0, min(len(ordered) - 1, int(quantile * len(ordered) - 1e-12)))
    return ordered[index]


__all__ = [
    "DEFAULT_ANNOTATION_MANIFEST",
    "Q0MultiSeedError",
    "build_q0_multiseed_receipt",
]

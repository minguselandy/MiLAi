"""Descriptive MF-06 A/C comparison over already sealed DG-28 effects.

This module does not run another retrieval experiment.  It compares the
matched Raw+Simple and Formed+Raw-fallback+Simple arms that were already
sealed by DG-28, and keeps the research hypothesis unresolved when the
development sample is too small for the preregistered effect gate.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from milai.domain.requirement_state import canonical_sha256

RAW_SIMPLE_SCORE = Path(
    "var/dg28/lite/dg28-lite-lexical-union-20260830-001/score.json"
)
FORMED_SIMPLE_SCORE = Path(
    "var/dg28/formation/dg28-formation-consumption-20260830-002/score.json"
)
MF03_RECEIPT = Path(
    "var/mf03/mf03-formation-sidecar-20260830-004/receipt.json"
)


class MF06DiagnosticError(RuntimeError):
    """A sealed source arm drifted or is not comparable."""


def build_factorial_diagnostic(root: Path) -> dict[str, Any]:
    """Compare the matched A/C arms without claiming a new causal effect."""

    root = root.resolve()
    raw_score = _object(root / RAW_SIMPLE_SCORE)
    formed_score = _object(root / FORMED_SIMPLE_SCORE)
    mf03_receipt = _object(root / MF03_RECEIPT)
    _verify_digest(raw_score, "score_digest")
    _verify_digest(formed_score, "score_digest")
    _verify_digest(mf03_receipt, "receipt_digest")

    if raw_score.get("status") != "PASS_DG28_LITE_RETRIEVAL_GAIN":
        raise MF06DiagnosticError("RAW_SIMPLE_ARM_NOT_SEALED_PASS")
    if formed_score.get("status") != "PASS_DG28_FORMATION_CONSUMPTION_CLOSURE":
        raise MF06DiagnosticError("FORMED_SIMPLE_ARM_NOT_SEALED_PASS")
    if mf03_receipt.get("status") != "PASS_MF03_FORMATION_IDENTITY_TIME":
        raise MF06DiagnosticError("FORMATION_FIDELITY_GATE_NOT_PASS")

    raw_arm = _mapping(raw_score.get("treatment"), "raw treatment")
    formed_baseline = _mapping(formed_score.get("baseline"), "formed baseline")
    formed_arm = _mapping(formed_score.get("treatment"), "formed treatment")
    if raw_arm != formed_baseline:
        raise MF06DiagnosticError("A_C_MATCHED_BASELINE_DRIFT")
    if raw_arm.get("candidate_group_ids") != formed_arm.get("candidate_group_ids"):
        raise MF06DiagnosticError("A_C_CANDIDATE_POOL_DRIFT")
    if raw_arm.get("candidate_count") != formed_arm.get("candidate_count"):
        raise MF06DiagnosticError("A_C_CANDIDATE_COUNT_DRIFT")

    target_groups = sorted(
        str(value)
        for value in _sequence(
            formed_arm.get("target_candidate_group_ids"), "target candidate groups"
        )
    )
    raw_bound = {
        str(value)
        for value in _sequence(
            raw_arm.get("target_binding_group_ids"), "raw target bindings"
        )
    }
    formed_bound = {
        str(value)
        for value in _sequence(
            formed_arm.get("target_binding_group_ids"), "formed target bindings"
        )
    }
    if not raw_bound.issubset(set(target_groups)) or not formed_bound.issubset(
        set(target_groups)
    ):
        raise MF06DiagnosticError("TARGET_BINDING_OUTSIDE_DENOMINATOR")

    paired: list[dict[str, Any]] = [
        {
            "equivalence_group_id": group,
            "raw_simple": int(group in raw_bound),
            "formed_simple": int(group in formed_bound),
            "paired_delta": int(group in formed_bound) - int(group in raw_bound),
        }
        for group in target_groups
    ]
    differences = [int(row["paired_delta"]) for row in paired]
    denominator = len(paired)
    if denominator == 0:
        raise MF06DiagnosticError("EMPTY_FACTORIAL_DENOMINATOR")
    delta = sum(differences) / denominator
    ci_low, ci_high = _exact_paired_bootstrap_interval(differences)
    net_additional = len(formed_bound - raw_bound) - len(raw_bound - formed_bound)
    precision_raw = float(raw_arm["accepted_binding_precision"])
    precision_formed = float(formed_arm["accepted_binding_precision"])
    wrong_complete_raw = int(raw_arm["wrong_complete"])
    wrong_complete_formed = int(formed_arm["wrong_complete"])

    effect_checks = {
        "formation_fidelity_pass": True,
        "delta_f_at_least_0_05": delta >= 0.05,
        "net_additional_valid_obligations_at_least_2": net_additional >= 2,
        "paired_ci_lower_above_zero": ci_low > 0.0,
        "accepted_binding_precision_non_regression": precision_formed >= precision_raw,
        "wrong_complete_zero": wrong_complete_raw == wrong_complete_formed == 0,
        "candidate_pool_matched": True,
    }
    ml_h1_established = all(effect_checks.values())
    output: dict[str, Any] = {
        "schema": "milai.mf06.descriptive-factorial.v0.1",
        "run_id": "mf06-ac-descriptive-20260830-001",
        "status": (
            "PASS_ML_H1_FORMATION_UTILITY"
            if ml_h1_established
            else "DESCRIPTIVE_FORMATION_GAIN_ML_H1_NOT_ESTABLISHED"
        ),
        "comparison": {
            "arm_a": "RAW_PLUS_SIMPLE",
            "arm_c": "FORMED_PLUS_RAW_FALLBACK_PLUS_SIMPLE",
            "denominator": denominator,
            "raw_simple_valid_binding_recall": len(raw_bound) / denominator,
            "formed_simple_valid_binding_recall": len(formed_bound) / denominator,
            "delta_f": delta,
            "net_additional_valid_obligations": net_additional,
            "paired_bootstrap_95_percent": [ci_low, ci_high],
            "paired_rows": paired,
        },
        "effect_checks": effect_checks,
        "research_disposition": {
            "ml_h1_established": ml_h1_established,
            "reason": (
                "PREREGISTERED_EFFECT_GATE_PASSED"
                if ml_h1_established
                else "ONE_NET_OBLIGATION_AND_CI_INCLUDES_ZERO_ON_DEV_SET"
            ),
            "engineering_finding": (
                "FORMATION_CLOSED_THE_REMAINING_MATCHED_BINDING_WITHOUT_"
                "NEW_CANDIDATES_OR_QUERY_TIME_MODEL_CALLS"
            ),
        },
        "adaptive_arms": {
            "arm_b": "NOT_ENTERED_NO_AUTHORIZED_RAW_ADAPTIVE_EFFECT",
            "arm_d": "NOT_ENTERED_NO_FORMED_SIMPLE_RESIDUAL",
            "dg29_entry": False,
        },
        "cost_match": {
            "candidate_count": int(formed_arm["candidate_count"]),
            "additional_query_time_model_calls": 0,
            "additional_official_acquisition_calls": 0,
            "additional_refinding_rounds": 0,
        },
        "source_artifacts": {
            "raw_simple_score": _identity(root, root / RAW_SIMPLE_SCORE),
            "formed_simple_score": _identity(root, root / FORMED_SIMPLE_SCORE),
            "mf03_receipt": _identity(root, root / MF03_RECEIPT),
        },
        "formal_holdout_used": False,
        "experimental_feature_flags": "OFF",
    }
    output["receipt_digest"] = canonical_sha256(output)
    return output


def validate_factorial_diagnostic(root: Path, receipt: Mapping[str, Any]) -> None:
    """Recompute the diagnostic and require byte-independent semantic identity."""

    observed = dict(receipt)
    _verify_digest(observed, "receipt_digest")
    expected = build_factorial_diagnostic(root)
    if observed != expected:
        raise MF06DiagnosticError("MF06_DIAGNOSTIC_REPLAY_MISMATCH")


def _exact_paired_bootstrap_interval(
    differences: Sequence[int],
) -> tuple[float, float]:
    """Return exact percentile bounds for resampling the paired rows.

    The support is tiny for the development set, so dynamic convolution gives
    an exact bootstrap distribution without a random seed or Monte Carlo noise.
    """

    n = len(differences)
    if n == 0:
        raise MF06DiagnosticError("EMPTY_BOOTSTRAP_SAMPLE")
    counts = {value: differences.count(value) / n for value in set(differences)}
    distribution: dict[int, float] = {0: 1.0}
    for _ in range(n):
        next_distribution: dict[int, float] = {}
        for total, probability in distribution.items():
            for value, draw_probability in counts.items():
                next_distribution[total + value] = (
                    next_distribution.get(total + value, 0.0)
                    + probability * draw_probability
                )
        distribution = next_distribution
    return (
        _weighted_quantile(distribution, 0.025) / n,
        _weighted_quantile(distribution, 0.975) / n,
    )


def _weighted_quantile(distribution: Mapping[int, float], quantile: float) -> int:
    cumulative = 0.0
    for value in sorted(distribution):
        cumulative += distribution[value]
        if cumulative + math.ulp(cumulative) >= quantile:
            return value
    return max(distribution)


def _verify_digest(value: Mapping[str, Any], field: str) -> None:
    material = dict(value)
    observed = material.pop(field, None)
    if observed != canonical_sha256(material):
        raise MF06DiagnosticError(f"SOURCE_DIGEST_INVALID:{field}")


def _identity(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _object(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MF06DiagnosticError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MF06DiagnosticError(f"MAPPING_REQUIRED:{label}")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MF06DiagnosticError(f"SEQUENCE_REQUIRED:{label}")
    return value

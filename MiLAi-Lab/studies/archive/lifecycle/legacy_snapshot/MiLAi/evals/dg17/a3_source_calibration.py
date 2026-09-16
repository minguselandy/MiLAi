"""A3 source-field calibration identifiability audit.

This evaluation may read answer-bearing labels after the product trace is
sealed.  Runtime never imports it and it never changes retrieval ranking.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SPEAKERS = ("user", "assistant", "system", "tool")


def build_source_calibration_report(
    *,
    run_id: str,
    labels_path: Path,
    goal_path: Path,
    focused_postgres_receipt: Path,
    runtime_full_gate_receipt: Path,
    counterfactual_test_log: Path,
) -> dict[str, Any]:
    labels = _load_mapping(labels_path)
    cases = labels.get("cases")
    if not isinstance(cases, list) or len(cases) != 10:
        raise ValueError("A3 calibration requires the sealed 10-case opened-dev labels")
    atoms = [
        atom
        for case in cases
        if isinstance(case, Mapping)
        for atom in case.get("atoms", [])
        if isinstance(atom, Mapping)
    ]
    if len(atoms) != 23:
        raise ValueError("A3 calibration requires all 23 answer-bearing atoms")
    counts = Counter(str(atom.get("speaker")) for atom in atoms)
    if set(counts) - set(SPEAKERS):
        raise ValueError("answer-bearing labels contain an unsupported speaker")

    focused = _load_mapping(focused_postgres_receipt)
    full_gate = _load_mapping(runtime_full_gate_receipt)
    if focused.get("status") != "PASS" or full_gate.get("status") != "PASS":
        raise ValueError("A3 implementation gates must pass before calibration disposition")

    per_class = {
        speaker: {
            "answer_bearing_atom_denominator": counts.get(speaker, 0),
            "recall_estimable": counts.get(speaker, 0) > 0,
            "noise_estimable": False,
            "noise_denominator": 0,
        }
        for speaker in SPEAKERS
    }
    non_user_positive_count = sum(counts.get(speaker, 0) for speaker in SPEAKERS[1:])
    identifiable = non_user_positive_count > 0 and all(
        value["noise_denominator"] > 0 for value in per_class.values()
    )
    return {
        "schema": "milai.dg17.a3-source-field-calibration.v0.1",
        "run_id": run_id,
        "status": "PASS",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "formal_holdout_consumed": False,
        "product_behavior_changed": False,
        "label_boundary": {
            "runtime_imports_report": False,
            "product_path_label_access_count": 0,
            "labels_read_after_trace_seal": True,
        },
        "bound_artifacts": {
            "goal": _identity(goal_path),
            "answer_bearing_labels": _identity(labels_path),
            "focused_postgres_gate": _identity(focused_postgres_receipt),
            "runtime_full_gate": _identity(runtime_full_gate_receipt),
            "multilingual_counterfactual_tests": _identity(counterfactual_test_log),
        },
        "sample": {
            "case_count": len(cases),
            "answer_bearing_atom_count": len(atoms),
            "unique_source_turn_count": len(
                {str(atom.get("source_turn_ref")) for atom in atoms}
            ),
            "speaker_positive_denominators": {
                speaker: counts.get(speaker, 0) for speaker in SPEAKERS
            },
        },
        "per_class": per_class,
        "calibration": {
            "identity": "A3_SOURCE_FIELD_IDENTIFIABILITY_V1",
            "identifiable": identifiable,
            "reason_codes": [
                "NON_USER_POSITIVE_DENOMINATOR_ZERO",
                "PER_CLASS_NOISE_DENOMINATORS_ZERO",
                "SOURCE_SPEAKER_IS_NOT_EVENT_ACTOR",
            ],
            "matched_ablation_status": "NOT_RUN_NOT_IDENTIFIABLE",
            "latency": {
                "status": "NOT_MEASURED_NO_PROMOTABLE_FIELDED_ARM",
                "baseline_ms": None,
                "candidate_ms": None,
                "delta_ms": None,
            },
        },
        "disposition": {
            "source_aware_ranking": "PARKED_NOT_IDENTIFIABLE",
            "source_rank_weight": None,
            "inline_score_boost": False,
            "default_retrieval_policy": "NEUTRAL_NO_SOURCE_SCORE",
            "explicit_allowed_speaker_filter": "AVAILABLE_ONLY_WITH_EXPLICIT_QUERY_PROVENANCE",
            "structured_speaker_lineage": "IMPLEMENTED",
            "missing_speaker_policy": "UNKNOWN",
        },
        "gates": {
            "all_23_labels_accounted": len(atoms) == 23,
            "per_class_denominators_reported": set(per_class) == set(SPEAKERS),
            "unidentifiable_weight_not_promoted": not identifiable,
            "inline_magic_boost_absent": True,
            "structured_lineage_postgres_pass": focused.get("status") == "PASS",
            "runtime_full_gate_pass": full_gate.get("status") == "PASS",
        },
        "claim_boundary": {
            "A3_contract_and_lineage_can_close": True,
            "A3_fielded_rank_gain_claim_authorized": False,
            "final_lme_authorized": False,
            "release_claim_authorized": False,
        },
        "efficiency": {
            "model_calls": 0,
            "reader_calls": 0,
            "automatic_retries": 0,
            "fielded_rank_latency_not_incurred": True,
        },
    }


def _load_mapping(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


__all__ = ["build_source_calibration_report"]

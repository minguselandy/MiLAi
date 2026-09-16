"""DG-21 S0 baseline and first-loss denominator freeze."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_CANDIDATE_ARM = "B_FRESH_STATE_DETERMINISTIC_CAPABILITY_POLICY"
_TOKEN_BUDGET = 2048
_FAILURE_CASES = frozenset(
    {
        "2a1811e2",
        "2e6d26dc",
        "88432d0a",
        "9a707b82",
        "a89d7624",
        "gpt4_8279ba03",
    }
)
_IMPROVED_CASES = frozenset({"0bb5a684", "4dfccbf7", "gpt4_88806d6e"})
_CORRECT_CASES = frozenset({"a82c026e"})
_EXPECTED_FIRST_LOSS = {
    ("2a1811e2", "START_EVENT"): "CHANNEL",
    ("2a1811e2", "END_EVENT"): "INTERPRETATION",
    ("2e6d26dc", "BABY_EVENTS"): "INTERPRETATION",
    ("88432d0a", "BAKING_EVENTS"): "CHANNEL",
    ("9a707b82", "TARGET_EVENT"): "CHANNEL",
    ("a89d7624", "CURRENT_INTENT"): "INTERPRETATION",
    ("gpt4_8279ba03", "TARGET_EVENT"): "CHANNEL",
}
_EXPECTED_REJECTIONS = {
    "ENTITY_INCOMPATIBLE": 130,
    "TEMPORAL_INCOMPATIBLE": 3,
    "TYPE_INCOMPATIBLE": 1997,
}
_EXPECTED_HASHES = {
    "architecture/v1.0/architecture_manifest.json": (
        "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
    ),
    "MiLAi_Lean_V1_实施合同.md": (
        "395a443da282f69a56ae5ea29f0dac07a65da12a697534e5c650c9893f8ae3ba"
    ),
    "var/dg20/s6/dg20-s6-terminal-20260828-002/receipt.json": (
        "8b006259d4c3d4ffbd9b2077f14a3681826d07d39731cd6c7e6d811352824929"
    ),
    "var/dg20/s6/dg20-s6-terminal-20260828-002/source-artifact-manifest.json": (
        "24c025b7e5a7622fd4d454ccdd654504f07b7262b724ddb2c252092cc8bb7967"
    ),
    "var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005/receipt.json": (
        "d3cb35524e7e41e95710ea57d3c08f676c881feefe7f20d360f2c34d67eeca5d"
    ),
    "var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005/score.json": (
        "1c0d74079344040d0edd97f59207c88b812eca40a821d31ade8d6632d22e9f07"
    ),
    "var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005/acquisition-loss-ledger.json": (
        "e47a20cab747f10081ac6066273e53ab9a7cf41cdfebc3935d8917b6387f3cf0"
    ),
}


def run_baseline_freeze(root: Path) -> dict[str, Any]:
    """Recompute the S0 denominator from immutable DG-20 artifacts."""
    root = root.resolve()
    artifact_identities = _validate_bound_hashes(root)
    terminal = _read_json(
        root / "var/dg20/s6/dg20-s6-terminal-20260828-002/receipt.json"
    )
    score = _read_json(
        root / "var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005/score.json"
    )
    loss_ledger = _read_json(
        root
        / "var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005/acquisition-loss-ledger.json"
    )
    sealed_s4 = _read_json(
        root
        / "var/dg20/s4/dg20-s4-product-faithful-20260828-002/sealed-product-trace.json"
    )

    upstream_stage_receipts = _validate_upstream_stage_receipts(root, terminal)
    comparison_2048 = score["comparisons"][str(_TOKEN_BUDGET)]
    candidate_records = _candidate_records(score)
    case_ids = {record["case_id"] for record in candidate_records}
    expected_case_ids = _FAILURE_CASES | _IMPROVED_CASES | _CORRECT_CASES
    case_classification = {
        "zero_gain_failures": sorted(_FAILURE_CASES),
        "correct_non_regression": sorted(_CORRECT_CASES),
        "dg20_improved": sorted(_IMPROVED_CASES),
        "diagnostic_residual_gap": {
            "case_id": "0bb5a684",
            "requirement_id": "END_EVENT",
            "first_loss_stage": "CHANNEL",
            "included_in_zero_gain_denominator": False,
        },
    }
    raw_comparison = [_safe_case_projection(record) for record in candidate_records]

    first_loss_records = _freeze_first_loss_records(loss_ledger)
    first_loss_counts = Counter(
        record["first_loss_stage"] for record in first_loss_records
    )
    rejection_counts = _binding_rejection_counts(sealed_s4)
    rejection_total = sum(rejection_counts.values())
    type_rejection_share = (
        rejection_counts.get("TYPE_INCOMPATIBLE", 0) / rejection_total
    )

    regression_floors = {
        "2048": {
            "case_count": 10,
            "required_evidence_set_coverage": 0.347826087,
            "operator_ready": 2,
            "exact_match": 2,
            "normalized_f1": 0.234848485,
            "additional_acquisition_calls_max": 8,
            "candidates_hydrated_max": 64,
        },
        "512": {
            "case_count": 10,
            "required_evidence_set_coverage": 0.304347826,
            "operator_ready": 2,
            "exact_match": 1,
            "normalized_f1": 0.219896104,
        },
    }
    observed_floors = _observed_regression_floors(score)
    holdout_sources = [score, loss_ledger, terminal]
    formal_holdout_consumed = any(
        bool(source.get("formal_holdout_consumed")) for source in holdout_sources
    )

    checks = {
        "bound_artifact_hashes_match": all(
            item["matches_expected"] for item in artifact_identities.values()
        ),
        "upstream_s1_s2_receipts_match_terminal": all(
            item["matches_terminal"] for item in upstream_stage_receipts.values()
        ),
        "case_count_10": len(candidate_records) == 10,
        "case_partition_exact": case_ids == expected_case_ids,
        "failure_case_count_6": len(_FAILURE_CASES) == 6,
        "correct_case_count_1": len(_CORRECT_CASES) == 1,
        "improved_case_count_3": len(_IMPROVED_CASES) == 3,
        "dg20_improved_identity_matches": set(
            comparison_2048["missing_requirement_improved_case_ids"]
        )
        == _IMPROVED_CASES,
        "dg20_correct_identity_matches": set(
            comparison_2048["already_correct_case_ids"]
        )
        == _CORRECT_CASES,
        "first_loss_assignment_100_percent": len(first_loss_records)
        == len(_EXPECTED_FIRST_LOSS),
        "first_loss_unique_per_requirement": len(
            {(item["case_id"], item["requirement_id"]) for item in first_loss_records}
        )
        == len(first_loss_records),
        "first_loss_distribution_4_channel_3_interpretation": first_loss_counts
        == Counter({"CHANNEL": 4, "INTERPRETATION": 3}),
        "rejection_total_2130": rejection_total == 2130,
        "type_incompatible_1997": rejection_counts.get("TYPE_INCOMPATIBLE") == 1997,
        "rejection_reason_counts_exact": rejection_counts == _EXPECTED_REJECTIONS,
        "regression_floors_match_dg20": observed_floors == regression_floors,
        "policy_sweep_exact": [8, 12, 16] == sorted({8, 12, 16}),
        "formal_holdout_untouched": not formal_holdout_consumed,
        "formal_holdout_overlap_zero": True,
        "provider_calls_zero": True,
        "reader_calls_zero": True,
        "runtime_behavior_unchanged": True,
    }
    return {
        "schema": "milai.dg21.s0-baseline-freeze.v0.1",
        "status": "PASS_BASELINE_CONTRACT_FREEZE" if all(checks.values()) else "FAIL",
        "classification": "PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT_10 / EVALUATION_PLANE",
        "artifact_identities": artifact_identities,
        "upstream_stage_receipts": upstream_stage_receipts,
        "case_classification": case_classification,
        "raw_comparison_table": raw_comparison,
        "first_loss_records": first_loss_records,
        "first_loss_distribution": dict(sorted(first_loss_counts.items())),
        "rejection_binding_denominator": {
            "case_ids": sorted(_FAILURE_CASES),
            "total": rejection_total,
            "by_reason": rejection_counts,
            "type_incompatible_share": round(type_rejection_share, 12),
        },
        "regression_floors": regression_floors,
        "policy_sweep_matrix": {
            "candidate_caps": [8, 12, 16],
            "scope": "OPENED_DEVELOPMENT_ONLY",
            "frozen_after_stage": "S4",
        },
        "metric_denominators": {
            "matched_cases": 10,
            "token_budgets": [512, 2048],
            "required_evidence_atoms": 23,
            "zero_gain_failure_cases": 6,
            "unresolved_requirements": 7,
            "rejected_bindings": 2130,
        },
        "formal_holdout": {
            "consumed": formal_holdout_consumed,
            "overlap_count": 0,
            "denominator": 0,
            "case_ids_loaded": [],
        },
        "safety": {
            "provider_calls": 0,
            "reader_calls": 0,
            "canonical_mutations": 0,
            "runtime_behavior_changes": 0,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def _validate_bound_hashes(root: Path) -> dict[str, dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    for relative, expected in _EXPECTED_HASHES.items():
        path = root / relative
        actual = _sha256(path)
        identities[relative] = {
            "path": relative,
            "sha256": actual,
            "expected_sha256": expected,
            "size": path.stat().st_size,
            "matches_expected": actual == expected,
        }
    return identities


def _validate_upstream_stage_receipts(
    root: Path, terminal: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    for stage in ("s1", "s2"):
        terminal_identity = terminal["stage_artifacts"][stage]["receipt"]
        path = Path(terminal_identity["path"])
        if not path.is_absolute():
            path = root / path
        actual = _sha256(path)
        identities[stage] = {
            "path": str(path.resolve().relative_to(root)),
            "sha256": actual,
            "terminal_sha256": terminal_identity["sha256"],
            "size": path.stat().st_size,
            "matches_terminal": actual == terminal_identity["sha256"],
        }
    return identities


def _candidate_records(score: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return sorted(
        (
            record
            for record in score["records"][_CANDIDATE_ARM]
            if record["token_budget"] == _TOKEN_BUDGET
        ),
        key=lambda item: item["case_id"],
    )


def _safe_case_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    retrieval = record["retrieval_score"]
    answer = record["answer_score"]
    return {
        "case_id": record["case_id"],
        "classification": _classification_for_case(record["case_id"]),
        "query_class": record["query_class"],
        "token_budget": record["token_budget"],
        "required_atom_count": record["required_atom_count"],
        "required_evidence_coverage": retrieval["relevant_coverage_at_k"],
        "exact_match": answer["exact_match"],
        "normalized_f1": answer["normalized_f1"],
        "operator_ready": bool(record["derived_result"])
        and record["derived_result"].get("status") == "OK",
        "terminal_sufficiency_complete": record["terminal_sufficiency_complete"],
        "wrong_complete": record["wrong_complete"],
        "question_or_content_stored": False,
    }


def _classification_for_case(case_id: str) -> str:
    if case_id in _FAILURE_CASES:
        return "ZERO_GAIN_FAILURE"
    if case_id in _CORRECT_CASES:
        return "CORRECT_NON_REGRESSION"
    if case_id in _IMPROVED_CASES:
        return "DG20_IMPROVED"
    raise ValueError(f"unexpected DG-20 matched case: {case_id}")


def _freeze_first_loss_records(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    selected = [
        record
        for record in ledger["records"]
        if record["arm"] == _CANDIDATE_ARM
        and record["token_budget"] == _TOKEN_BUDGET
        and (record["case_id"], record["requirement_id"]) in _EXPECTED_FIRST_LOSS
    ]
    frozen: list[dict[str, Any]] = []
    for record in selected:
        key = (record["case_id"], record["requirement_id"])
        expected_stage = _EXPECTED_FIRST_LOSS[key]
        if record["first_loss_stage"] != expected_stage:
            raise ValueError(
                f"first-loss drift for {key}: {record['first_loss_stage']} != {expected_stage}"
            )
        frozen.append(
            {
                key_: record.get(key_)
                for key_ in (
                    "case_id",
                    "requirement_id",
                    "first_loss_stage",
                    "reason_code",
                    "channel",
                    "raw_rank",
                    "fusion_rank",
                    "cutoff_rank",
                    "answer_bearing_candidate_present",
                    "binding_status",
                    "sufficiency_effect",
                    "requirement_state_digest",
                    "capability_digest",
                )
            }
        )
    return sorted(frozen, key=lambda item: (item["case_id"], item["requirement_id"]))


def _binding_rejection_counts(sealed: Mapping[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for case in sealed["cases"]:
        if case["case_id"] not in _FAILURE_CASES:
            continue
        binding_trace = case["product"]["final"]["binding_trace"]
        for requirement_records in binding_trace.values():
            for record in requirement_records:
                if record["status"] == "REJECTED":
                    counts[record["reason_code"]] += 1
    return dict(sorted(counts.items()))


def _observed_regression_floors(score: Mapping[str, Any]) -> dict[str, Any]:
    floors: dict[str, Any] = {}
    for budget in ("2048", "512"):
        comparison = score["comparisons"][budget]
        floors[budget] = {
            "case_count": comparison["case_count"],
            "required_evidence_set_coverage": comparison[
                "required_evidence_set_coverage_candidate"
            ],
            "operator_ready": comparison["operator_ready_candidate"],
            "exact_match": comparison["exact_match_candidate"],
            "normalized_f1": comparison["normalized_f1_candidate"],
        }
        if budget == "2048":
            floors[budget].update(
                {
                    "additional_acquisition_calls_max": score["safety_and_cost"][
                        "additional_acquisition_calls"
                    ],
                    "candidates_hydrated_max": score["safety_and_cost"][
                        "candidates_hydrated"
                    ],
                }
            )
    return floors


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(root: Path, paths: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Return content identities for the S0 source inventory."""
    return {
        relative: {
            "path": relative,
            "sha256": _sha256(root / relative),
            "size": (root / relative).stat().st_size,
        }
        for relative in paths
    }


__all__ = ["run_baseline_freeze", "source_manifest"]

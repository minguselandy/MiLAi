"""Machine stop gates for DG-25 label-free generation and post-seal scoring."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from milai.domain.requirement_state import canonical_sha256

GenerationStage = Literal["S3A_E1_LABEL_FREE", "S4A_E2_LABEL_FREE"]
GenerationPhase = Literal["PRE_GENERATION", "POST_GENERATION"]
ScorePhase = Literal["PRE_SCORE", "POST_SCORE"]

S3A_REQUIRED_BINDINGS = (
    "execution_delta_manifest_digest",
    "all_arm_seal_protocol_digest",
    "readiness_source_manifest_digest",
    "case_order_digest",
    "e1_action_manifest_digest",
    "e1_config_set_digest",
    "e1_common_pool_binding_digest",
    "e1_channel_query_identities_digest",
    "e1_caps_digest",
    "cost_ledger_schema_digest",
    "s3a_generator_source_sha256",
    "s3a_sealer_source_sha256",
    "s3a_runner_source_sha256",
    "final_k",
    "expected_arm_count",
)


def stop_evaluation_contract() -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema": "milai.dg25.stop-evaluation-contract.v0.1",
        "schedule": [
            "S3A_E1_LABEL_FREE_GENERATE_AND_SEAL",
            "S4A_E2_LABEL_FREE_GENERATE_AND_SEAL",
            "FRESH_INDEPENDENT_SCORING_AUTHORIZATION",
            "S4B_JOINT_E1_E2_POST_SEAL_SCORE",
        ],
        "generation_gate": {
            "labels_loaded": False,
            "scoring_executed": False,
            "reader_model_provider_controller_calls": 0,
            "formal_holdout_consumed": False,
            "candidate_default": False,
            "canonical_mutations": 0,
            "automatic_retries": 0,
            "exact_readiness_binding_equality": True,
            "pre_generation_existing_output_directory": False,
            "post_generation_output_set_and_seal_recomputed": True,
        },
        "generation_required_bindings": {
            "S3A_E1_LABEL_FREE": list(S3A_REQUIRED_BINDINGS),
            "S4A_E2_LABEL_FREE": [
                "execution_delta_manifest_digest",
                "all_arm_seal_protocol_digest",
                "readiness_source_manifest_digest",
                "case_order_digest",
                "e2_common_input_digest",
                "e2_config_set_digest",
                "e2_caps_digest",
                "cost_ledger_schema_digest",
                "s4a_generator_source_sha256",
                "s4a_sealer_source_sha256",
                "s4a_runner_source_sha256",
                "expected_arm_count",
            ],
        },
        "pre_score_required_bindings": [
            "execution_delta_manifest_digest",
            "all_arm_seal_protocol_digest",
            "effect_scorer_contract_digest",
            "effect_scorer_source_sha256",
            "e2_common_input_digest",
            "readiness_source_manifest_digest",
            "case_order_digest",
            "stop_rule_registry_sha256",
            "e1_action_manifest_digest",
            "e1_config_set_digest",
            "e2_config_set_digest",
            "e1_common_pool_binding_digest",
            "e1_caps_digest",
            "e2_caps_digest",
            "cost_ledger_schema_digest",
            "e1_all_arm_seal_digest",
            "e2_all_arm_seal_digest",
            "combined_all_arm_seal_digest",
            "independent_scoring_authorization_digest",
        ],
        "machine_rules": [
            {"id": "STOP_IDENTITY_DRIFT", "field": "identity_drift", "expected": 0},
            {"id": "STOP_LABEL_BEFORE_SEAL", "field": "label_before_seal", "expected": 0},
            {"id": "STOP_UNMATCHED_POOL_K", "field": "pool_k_mismatch", "expected": 0},
            {"id": "STOP_INVALID_PLAN", "field": "invalid_plan_count", "expected": 0},
            {"id": "STOP_BUDGET_OVERFLOW", "field": "budget_overflow", "expected": 0},
            {
                "id": "STOP_PRECISION",
                "field": "accepted_binding_precision",
                "expected": 1.0,
                "phase": "POST_SCORE",
            },
            {
                "id": "STOP_WRONG_COMPLETE",
                "field": "wrong_complete",
                "expected": 0,
                "phase": "POST_SCORE",
            },
            {"id": "STOP_BOUNDARY_DRIFT", "field": "boundary_drift", "expected": 0},
            {"id": "STOP_FORBIDDEN_CALL", "field": "forbidden_calls", "expected": 0},
            {
                "id": "STOP_POST_SCORE_ADAPTATION",
                "field": "post_score_adaptation",
                "expected": 0,
            },
        ],
        "aggregate_requirements": {
            "all_preregistered_arm_outputs": 16,
            "final_k": 8,
            "e1_and_e2_seals_required_before_registry_open": True,
            "fresh_independent_authorization_required": True,
            "automatic_retries": 0,
        },
    }
    contract["contract_digest"] = canonical_sha256(contract)
    return contract


def evaluate_generation_gate(
    *,
    stage: GenerationStage,
    phase: GenerationPhase,
    observations: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail closed on exact identities as well as label/call boundaries."""

    contract = stop_evaluation_contract()
    stage_bindings = contract["generation_required_bindings"].get(stage)
    if not isinstance(stage_bindings, list):
        raise TypeError("DG25_GENERATION_STAGE_BINDINGS_UNKNOWN")
    binding_checks = _exact_binding_checks(
        fields=[str(field) for field in stage_bindings],
        observations=observations,
        expected_bindings=expected_bindings,
    )
    checks = {
        "known_label_free_stage": stage in {"S3A_E1_LABEL_FREE", "S4A_E2_LABEL_FREE"},
        "known_generation_phase": phase in {"PRE_GENERATION", "POST_GENERATION"},
        "labels_not_loaded": observations.get("labels_loaded") is False,
        "registry_content_not_loaded": (
            observations.get("registry_content_loaded") is False
        ),
        "scoring_not_executed": observations.get("scoring_executed") is False,
        "forbidden_calls_zero": (
            observations.get("reader_model_provider_controller_calls") == 0
        ),
        "formal_holdout_untouched": observations.get("formal_holdout_consumed") is False,
        "candidate_default_off": observations.get("candidate_default") is False,
        "canonical_mutations_zero": observations.get("canonical_mutations") == 0,
        "automatic_retries_zero": observations.get("automatic_retries") == 0,
    }
    if phase == "PRE_GENERATION":
        checks.update(
            {
                "output_directory_absent": observations.get("output_directory_exists")
                is False,
                "no_outputs_written": observations.get("arm_output_count") == 0,
                "seal_not_written": observations.get("all_arm_seal_present") is False,
            }
        )
    else:
        expected_count = expected_bindings.get("expected_arm_count")
        checks.update(
            {
                "exact_output_count": observations.get("arm_output_count")
                == expected_count,
                "arm_order_exact": observations.get("arm_order_exact") is True,
                "output_content_digests_recomputed": (
                    observations.get("output_content_digests_recomputed") is True
                ),
                "execution_bindings_recomputed": (
                    observations.get("execution_bindings_recomputed") is True
                ),
                "all_arm_seal_recomputed": (
                    observations.get("all_arm_seal_recomputed") is True
                ),
                "partial_duplicate_or_reordered_outputs_zero": (
                    observations.get("partial_duplicate_or_reordered_outputs") == 0
                ),
                "case_order_exact": observations.get("case_order_exact") is True,
            }
        )
    passed = all(checks.values()) and all(
        item["passed"] for item in binding_checks.values()
    )
    return {
        "schema": "milai.dg25.generation-stop-evaluation.v0.2",
        "stage": stage,
        "phase": phase,
        "passed": passed,
        "checks": checks,
        "binding_checks": binding_checks,
        "disposition": "PROCEED_LABEL_FREE_ONLY" if passed else "STOP",
    }


def evaluate_score_gate(
    *,
    phase: ScorePhase,
    observations: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate pre/post-score rules without opening a registry or mutating output."""

    contract = stop_evaluation_contract()
    rules: list[dict[str, Any]] = []
    for raw_rule in contract["machine_rules"]:
        if not isinstance(raw_rule, Mapping):
            raise TypeError("stop rules must be mappings")
        rule_phase = raw_rule.get("phase")
        field = str(raw_rule["field"])
        if rule_phase == "POST_SCORE" and phase == "PRE_SCORE":
            rules.append(
                {
                    "id": raw_rule["id"],
                    "field": field,
                    "status": "NOT_EVALUATED_PRE_SCORE",
                    "passed": True,
                }
            )
            continue
        observed = observations.get(field)
        expected = raw_rule["expected"]
        passed = observed == expected
        rules.append(
            {
                "id": raw_rule["id"],
                "field": field,
                "expected": expected,
                "observed": observed,
                "status": "PASS" if passed else "STOP",
                "passed": passed,
            }
        )

    bindings = contract["pre_score_required_bindings"]
    if not isinstance(bindings, list):
        raise TypeError("pre-score bindings must be a list")
    binding_checks = _exact_binding_checks(
        fields=[str(field) for field in bindings],
        observations=observations,
        expected_bindings=expected_bindings,
    )
    schedule_checks = {
        "e1_all_arm_seal_present": observations.get("e1_all_arm_seal_present") is True,
        "e2_all_arm_seal_present": observations.get("e2_all_arm_seal_present") is True,
        "combined_all_arm_seal_present": (
            observations.get("combined_all_arm_seal_present") is True
        ),
        "all_16_outputs_sealed": observations.get("all_arm_output_count") == 16,
        "independent_scoring_authorized": (
            observations.get("independent_scoring_authorized") is True
        ),
        "automatic_retries_zero": observations.get("automatic_retries") == 0,
    }
    if phase == "PRE_SCORE":
        schedule_checks.update(
            {
                "stage_is_s4b_pre_score": observations.get("stage") == "S4B_PRE_SCORE",
                "labels_not_yet_loaded": observations.get("labels_loaded") is False,
                "scoring_not_yet_executed": observations.get("scoring_executed") is False,
            }
        )
    else:
        schedule_checks.update(
            {
                "stage_is_s4b_post_score": observations.get("stage") == "S4B_POST_SCORE",
                "labels_loaded_only_after_seal": observations.get("labels_loaded") is True,
                "scoring_executed_once": observations.get("scoring_executed") is True,
                "score_execution_count_one": observations.get("score_execution_count") == 1,
            }
        )
    passed = (
        all(item["passed"] for item in rules)
        and all(item["passed"] for item in binding_checks.values())
        and all(schedule_checks.values())
    )
    return {
        "schema": "milai.dg25.score-stop-evaluation.v0.1",
        "phase": phase,
        "passed": passed,
        "disposition": "PROCEED" if passed else "STOP",
        "contract_digest": contract["contract_digest"],
        "rules": rules,
        "binding_checks": binding_checks,
        "schedule_checks": schedule_checks,
    }


def _exact_binding_checks(
    *,
    fields: list[str],
    observations: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for field in fields:
        expected = expected_bindings.get(field)
        observed = observations.get(field)
        passed = expected is not None and observed == expected
        checks[field] = {
            "expected": expected,
            "observed": observed,
            "passed": passed,
            "status": "PASS" if passed else "STOP",
        }
    return checks


__all__ = [
    "S3A_REQUIRED_BINDINGS",
    "evaluate_generation_gate",
    "evaluate_score_gate",
    "stop_evaluation_contract",
]

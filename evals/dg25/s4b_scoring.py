"""Pure DG-25 S4B review validation and scored-report projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from evals.dg25.effect_scorer import (
    E1_ARM_ORDER,
    E2_ARM_ORDER,
    canonical_sha256,
)

S4B_OFFICIAL_RUN_ID = "dg25-s4b-joint-score-20260830-001"
S4B_REVIEW_SCHEMA = "milai.dg25.s4b-independent-review.v0.1"
S4B_REVIEW_VERDICT = "AUTHORIZE_S4B_JOINT_E1_E2_POST_SEAL_SCORE"

SCORED_ARTIFACT_FILENAMES = {
    "joint_score": "joint-score.json",
    "routing_selection_report": "routing-selection-ablation-report.json",
    "component_unique_report": "component-unique-contribution-report.json",
    "rule_leave_one_out_report": "rule-leave-one-out-report.json",
    "temporal_ablation_report": "temporal-ablation-report.json",
    "final_minimal_policy": "final-minimal-policy.json",
    "pre_score_gate": "pre-score-stop-gate.json",
    "post_score_gate": "post-score-stop-gate.json",
}

AUTHORIZATION_FIELDS = {
    "schema",
    "authorized",
    "scope",
    "official_s4b_run_id",
    "combined_all_arm_seal_digest",
    "readiness_bindings_digest",
    "readiness_request_digest",
    "readiness_receipt_sha256",
    "scorer_source_amendment_digest",
    "effect_scorer_contract_digest",
    "effect_scorer_source_sha256",
    "gold_registry_sha256",
    "proof_registry_sha256",
    "failure_index_sha256",
    "failure_index_line_count",
    "readiness_bindings",
    "authorized_attempts",
    "automatic_retries",
    "labels_authorized_after_pre_score_gate",
    "registry_content_authorized_after_pre_score_gate",
    "scoring_authorized",
    "e3_authorized",
    "reader_model_provider_controller_calls",
    "formal_holdout_authorized",
    "candidate_default_authorized",
}


def validate_scoring_review(
    review: Mapping[str, Any],
    *,
    expected_request_digest: str,
    expected_authorization_bindings: Mapping[str, Any],
    reviewed_readiness_receipt: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate one fresh review and return its scorer-facing authorization."""

    if set(review) != {
        "schema",
        "reviewer_role",
        "verdict",
        "reviewed_readiness_receipt",
        "authorization_request_digest",
        "findings",
        "authorization",
        "review_digest",
    }:
        raise ValueError("DG25_S4B_REVIEW_FIELD_SET_MISMATCH")
    if (
        review.get("schema") != S4B_REVIEW_SCHEMA
        or review.get("reviewer_role") != "INDEPENDENT_SECONDARY_CODEX_REVIEWER"
        or review.get("verdict") != S4B_REVIEW_VERDICT
        or review.get("authorization_request_digest") != expected_request_digest
        or review.get("reviewed_readiness_receipt")
        != dict(reviewed_readiness_receipt)
    ):
        raise ValueError("DG25_S4B_REVIEW_BINDING_MISMATCH")
    findings = review.get("findings")
    if not isinstance(findings, Sequence) or isinstance(findings, (str, bytes)):
        raise TypeError("DG25_S4B_REVIEW_FINDINGS_INVALID")
    if any(not isinstance(item, Mapping) for item in findings):
        raise TypeError("DG25_S4B_REVIEW_FINDING_INVALID")
    material = dict(review)
    observed_review_digest = material.pop("review_digest", None)
    if observed_review_digest != canonical_sha256(material):
        raise ValueError("DG25_S4B_REVIEW_DIGEST_MISMATCH")

    authorization = _mapping(review.get("authorization"), "authorization")
    authorization_material = dict(authorization)
    observed_authorization_digest = authorization_material.pop(
        "authorization_digest", None
    )
    if set(authorization_material) != AUTHORIZATION_FIELDS:
        raise ValueError("DG25_S4B_AUTHORIZATION_FIELD_SET_MISMATCH")
    if observed_authorization_digest != canonical_sha256(authorization_material):
        raise ValueError("DG25_S4B_AUTHORIZATION_DIGEST_MISMATCH")
    expected = dict(expected_authorization_bindings)
    exact = {
        "schema": "milai.dg25.independent-scoring-authorization.v0.1",
        "authorized": True,
        "scope": "S4B_JOINT_E1_E2_POST_SEAL_SCORE",
        "official_s4b_run_id": S4B_OFFICIAL_RUN_ID,
        "readiness_request_digest": expected_request_digest,
        "readiness_receipt_sha256": reviewed_readiness_receipt.get("sha256"),
        "readiness_bindings": expected,
        "authorized_attempts": 1,
        "automatic_retries": 0,
        "labels_authorized_after_pre_score_gate": True,
        "registry_content_authorized_after_pre_score_gate": True,
        "scoring_authorized": True,
        "e3_authorized": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_authorized": False,
        "candidate_default_authorized": False,
    }
    if any(authorization.get(key) != value for key, value in exact.items()):
        raise ValueError("DG25_S4B_AUTHORIZATION_SCOPE_OR_BINDING_MISMATCH")
    for key in (
        "combined_all_arm_seal_digest",
        "readiness_bindings_digest",
        "scorer_source_amendment_digest",
        "effect_scorer_contract_digest",
        "effect_scorer_source_sha256",
        "gold_registry_sha256",
        "proof_registry_sha256",
        "failure_index_sha256",
        "failure_index_line_count",
    ):
        if authorization.get(key) != expected.get(key):
            raise ValueError(f"DG25_S4B_AUTHORIZATION_BINDING_MISMATCH:{key}")
    return authorization


def build_scored_reports(score: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Project the immutable joint score into preregistered DG-25 reports."""

    _validate_joint_score(score)
    arm_scores = _mapping(score.get("arm_scores"), "arm scores")
    sequential = _mapping_sequence(
        score.get("order_conditional_contributions"), "sequential contributions"
    )
    unique = _mapping_sequence(
        score.get("full_minus_one_contributions"), "unique contributions"
    )

    routing = _with_digest(
        {
            "schema": "milai.dg25.routing-selection-ablation.v0.1",
            "score_digest": score["score_digest"],
            "combined_all_arm_seal_digest": score[
                "combined_all_arm_seal_digest"
            ],
            "arm_order": list(E1_ARM_ORDER),
            "arm_scores": {arm: dict(_mapping(arm_scores[arm], arm)) for arm in E1_ARM_ORDER},
            "order_conditional_contributions": [
                dict(item) for item in sequential if item.get("arm_id") in E1_ARM_ORDER
            ],
            "first_loss_by_arm": {
                arm: dict(
                    _mapping(
                        _mapping(arm_scores[arm], arm).get("first_loss_distribution"),
                        "first loss",
                    )
                )
                for arm in E1_ARM_ORDER
            },
            "inference": "PAIRED_OPENED_DEVELOPMENT_DESCRIPTIVE_ONLY",
            "post_score_adaptation": False,
        },
        "report_digest",
    )
    component = _with_digest(
        {
            "schema": "milai.dg25.component-unique-contribution.v0.1",
            "score_digest": score["score_digest"],
            "control_arm": "R5_NO_SYNONYM_NORMALIZATION",
            "full_minus_one_contributions": [dict(item) for item in unique],
            "decision_rule": (
                "retain only a preregistered removable component whose control-minus-drop "
                "pair loses coverage or proof satisfaction while precision is 1.0 and "
                "WrongComplete is zero"
            ),
            "post_score_adaptation": False,
        },
        "report_digest",
    )

    with_synonym = _mapping(arm_scores["R4"], "R4")
    without_synonym = _mapping(
        arm_scores["R5_NO_SYNONYM_NORMALIZATION"], "R5"
    )
    scorer_policy = _mapping(score.get("final_minimal_policy"), "scorer policy")
    synonym_retained = "SYNONYM_NORMALIZATION" in _string_sequence(
        scorer_policy.get("retained_components"), "retained components"
    )
    rule_leave_one_out = _with_digest(
        {
            "schema": "milai.dg25.rule-leave-one-out.v0.1",
            "score_digest": score["score_digest"],
            "rule": "SYNONYM_NORMALIZATION",
            "with_rule_arm": "R4",
            "without_rule_arm": "R5_NO_SYNONYM_NORMALIZATION",
            "covered_group_delta_without_rule": int(without_synonym["covered_groups"])
            - int(with_synonym["covered_groups"]),
            "proof_satisfied_delta_without_rule": int(
                without_synonym["proof_obligations_satisfied"]
            )
            - int(with_synonym["proof_obligations_satisfied"]),
            "decision": "RETAIN" if synonym_retained else "REMOVE",
            "generality_parked": synonym_retained,
            "post_score_adaptation": False,
        },
        "report_digest",
    )

    temporal_contributions = [
        dict(item) for item in sequential if item.get("arm_id") in E2_ARM_ORDER
    ]
    temporal_dispositions = _temporal_dispositions(temporal_contributions)
    temporal = _with_digest(
        {
            "schema": "milai.dg25.temporal-ablation.v0.1",
            "score_digest": score["score_digest"],
            "arm_order": list(E2_ARM_ORDER),
            "arm_scores": {arm: dict(_mapping(arm_scores[arm], arm)) for arm in E2_ARM_ORDER},
            "order_conditional_contributions": temporal_contributions,
            "component_dispositions": temporal_dispositions,
            "t2_preregistered_applicability": "NOT_APPLICABLE_FOR_BOTH_FROZEN_INPUTS",
            "post_score_adaptation": False,
        },
        "report_digest",
    )

    routing_retained = _string_sequence(
        scorer_policy.get("retained_components"), "retained components"
    )
    routing_removed = _string_sequence(
        scorer_policy.get("removed_components"), "removed components"
    )
    temporal_retained = [
        str(item["component"])
        for item in temporal_dispositions
        if item["decision"] == "RETAIN"
    ]
    temporal_removed = [
        str(item["component"])
        for item in temporal_dispositions
        if item["decision"] == "REMOVE"
    ]
    final_policy = _with_digest(
        {
            "schema": "milai.dg25.final-minimal-policy.v0.1",
            "score_digest": score["score_digest"],
            "routing_base_arm": scorer_policy["base_arm"],
            "temporal_base_arm": "T0",
            "retained_components": sorted(set(routing_retained + temporal_retained)),
            "removed_components": sorted(set(routing_removed + temporal_removed)),
            "safety_necessity": {
                "EVENT_IDENTITY_DEDUP_V01": "PREREGISTERED_SYNTHETIC_COUNTEREXAMPLE",
                "BOUNDED_RANGE_SCAN_PROOF_V02": (
                    "PREREGISTERED_FALSE_COMPLETE_PREVENTION"
                ),
            },
            "synonym_generality_parked": scorer_policy[
                "synonym_generality_parked"
            ],
            "selection_uses_only_preregistered_pairs": True,
            "post_score_adaptation": False,
            "candidate_default": False,
            "formal_holdout_consumed": False,
        },
        "policy_digest",
    )
    return {
        "joint_score": dict(score),
        "routing_selection_report": routing,
        "component_unique_report": component,
        "rule_leave_one_out_report": rule_leave_one_out,
        "temporal_ablation_report": temporal,
        "final_minimal_policy": final_policy,
    }


def _temporal_dispositions(
    contributions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    component_by_arm = {
        "T1": "INTERVAL_TIME_NORMALIZATION",
        "T2": "UNIQUE_ANCHOR_RELATIVE_RESOLUTION",
        "T3": "EVENT_IDENTITY_DEDUP_V01",
        "T4": "BOUNDED_RANGE_SCAN_PROOF_V02",
    }
    by_arm = {str(item["arm_id"]): item for item in contributions}
    result: list[dict[str, Any]] = []
    for arm_id in E2_ARM_ORDER[1:]:
        delta = by_arm[arm_id]
        efficacy = int(delta["covered_group_delta"]) > 0 or int(
            delta["proof_satisfied_delta"]
        ) > 0
        safety = arm_id in {"T3", "T4"}
        dependency = arm_id == "T1"
        safe = (
            delta.get("precision_preserved") is True
            and delta.get("wrong_complete_zero") is True
        )
        retain = safe and (efficacy or safety or dependency)
        rationale = (
            "UNSAFE_STOP"
            if not safe
            else "PAIRED_EFFICACY"
            if efficacy
            else "PREREGISTERED_SYNTHETIC_SAFETY_NECESSITY"
            if safety
            else "PROOF_V02_DEPENDENCY"
            if dependency
            else "NO_UNIQUE_EFFECT_AND_NOT_APPLICABLE"
        )
        result.append(
            {
                "arm_id": arm_id,
                "component": component_by_arm[arm_id],
                "decision": "RETAIN" if retain else "REMOVE",
                "rationale": rationale,
                "paired_delta": dict(delta),
            }
        )
    return result


def _validate_joint_score(score: Mapping[str, Any]) -> None:
    if (
        score.get("schema") != "milai.dg25.e1-e2-effect-score.v0.1"
        or score.get("post_score_adaptation") is not False
        or score.get("reader_model_provider_controller_calls") != 0
        or score.get("formal_holdout_consumed") is not False
    ):
        raise ValueError("DG25_S4B_JOINT_SCORE_BOUNDARY_INVALID")
    material = dict(score)
    observed = material.pop("score_digest", None)
    if observed != canonical_sha256(material):
        raise ValueError("DG25_S4B_JOINT_SCORE_DIGEST_MISMATCH")
    arm_scores = _mapping(score.get("arm_scores"), "arm scores")
    if set(arm_scores) != {*E1_ARM_ORDER, *E2_ARM_ORDER}:
        raise ValueError("DG25_S4B_SCORE_ARM_SET_MISMATCH")


def _with_digest(
    material: dict[str, Any], digest_field: str
) -> dict[str, Any]:
    return {**material, digest_field: canonical_sha256(material)}


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _mapping_sequence(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"{label} items must be mappings")
        result.append(item)
    return result


def _string_sequence(value: object, label: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    if any(not isinstance(item, str) for item in value):
        raise TypeError(f"{label} items must be strings")
    return [str(item) for item in value]


__all__ = [
    "AUTHORIZATION_FIELDS",
    "S4B_OFFICIAL_RUN_ID",
    "S4B_REVIEW_SCHEMA",
    "S4B_REVIEW_VERDICT",
    "SCORED_ARTIFACT_FILENAMES",
    "build_scored_reports",
    "validate_scoring_review",
]

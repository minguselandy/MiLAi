"""Pure post-seal scorer for DG-25 E1/E2 matched replays.

This module has no filesystem or Runtime imports.  The caller must first
verify one immutable combined all-arm seal and a fresh independent scoring
authorization, then pass already-opened scorer registries as mappings.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any
from urllib.parse import unquote

SCORER_IDENTITY = "milai-dg25-e1-e2-post-all-arm-seal-effect-scorer-v0.1"
E1_ARM_ORDER = (
    "R0",
    "R0P",
    "R1",
    "R2",
    "R3",
    "R4",
    "R5_NO_SYNONYM_NORMALIZATION",
    "R_FINAL_DROP_UNIFIED_PROOF_FIRST",
    "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION",
    "R_FINAL_DROP_ROLE_RESERVATION",
    "R_FINAL_DROP_SOFT_LEXICAL_FEATURES",
)
E2_ARM_ORDER = ("T0", "T1", "T2", "T3", "T4")
COST_LEDGER_FIELDS = (
    "logical_selected_actions",
    "physical_repository_calls",
    "replayed_repository_calls",
    "returned_rows",
    "range_rows_scanned",
    "candidates_returned",
    "candidates_hydrated",
    "candidates_bound",
    "candidates_shown_to_reader",
    "state_passes",
    "reader_calls",
    "latency_ms",
)
_SOURCE_REF = re.compile(r"^([^?]+)(?:\?|$)")
_LONGMEM_SOURCE_REF = re.compile(
    r"^longmemeval://case/([^/]+)/session/(\d+)/([^/]+)/turn/(\d+)(?:\?|$)"
)


def scorer_contract() -> dict[str, Any]:
    """Return immutable schemas, metric definitions, and decision rules."""

    contract: dict[str, Any] = {
        "schema": "milai.dg25.effect-scorer-contract.v0.1",
        "scorer_identity": SCORER_IDENTITY,
        "accepted_input_schemas": {
            "combined_seal": "milai.dg25.e1-e2-all-arm-seal.v0.2",
            "arm_output": "milai.dg25.label-free-arm-output.v0.2",
            "gold_registry": "gold-equivalence-registry-v0.1",
            "proof_registry": "proof-obligation-registry-v0.1",
            "authorization": "milai.dg25.independent-scoring-authorization.v0.1",
        },
        "required_arm_order": {"E1": list(E1_ARM_ORDER), "E2": list(E2_ARM_ORDER)},
        "fixed_denominators": {
            "opened_development_queries": 10,
            "evidence_equivalence_groups": 23,
            "proof_obligations": 37,
        },
        "metric_definitions": {
            "TargetRequirementCandidateRecallAtK": (
                "gold equivalence groups with at least one legal final-K selected source "
                "turn divided by all 23 frozen groups"
            ),
            "RequiredEvidenceCoverageAtK": (
                "gold equivalence groups with at least one legal final-K selected source "
                "turn carrying label-free Binding status MATCH divided by all 23 groups"
            ),
            "TargetRequirementBindingGain": (
                "arm covered-group count minus paired R0P covered-group count"
            ),
            "AcceptedBindingPrecision": (
                "distinct label-free MATCH bindings whose source belongs to a frozen gold "
                "group for the same query/requirement divided by all distinct MATCH bindings; "
                "defined as 1.0 when no MATCH binding exists"
            ),
            "ProofObligationSatisfactionRate": (
                "required proof obligation IDs reported SATISFIED divided by all 37 obligations"
            ),
            "RangeMembershipAccuracy": (
                "gold-group source rows with predicted IN_RANGE divided by gold-group source "
                "rows carrying a range-membership prediction"
            ),
            "DistinctEventIdentityAccuracy": (
                "covered gold groups mapped one-to-one to resolved event identity digests"
            ),
            "WrongComplete": (
                "a requirement reports COMPLETE while a required equivalence group or proof "
                "obligation for that query/requirement is unsatisfied"
            ),
        },
        "first_loss_reasons": [
            "TERMINAL_SURVIVAL",
            "SELECTED_NOT_BOUND",
            "NOT_SELECTED_AT_FIXED_K",
        ],
        "component_decision_rules": {
            "sequential_deltas": "order-conditional only; never order-independent",
            "retention": (
                "retain a removable component only when its preregistered full-minus-one arm "
                "loses covered groups or proof satisfaction with precision=1.0 and WrongComplete=0"
            ),
            "optional_union_tie": (
                "remove optional union when mediator/proof results tie and logical/replay/hydration "
                "cost is no lower"
            ),
            "synonym_rule": (
                "exclude synonym normalization when R5 has no paired mediator/proof loss; if a "
                "loss exists, retain only with generality explicitly PARKED"
            ),
            "safety_components": (
                "Proof V02 or event identity may be retained by a preregistered synthetic safety "
                "necessity even when opened-development efficacy delta is zero"
            ),
        },
        "cost_ledger_fields": list(COST_LEDGER_FIELDS),
        "required_execution_bindings": [
            "execution_delta_manifest_digest",
            "all_arm_seal_protocol_digest",
            "readiness_source_manifest_digest",
            "case_order_digest",
            "effect_scorer_contract_digest",
            "effect_scorer_source_sha256",
            "stop_rule_registry_sha256",
            "e1_action_manifest_digest",
            "e1_config_set_digest",
            "e2_config_set_digest",
            "e1_common_pool_binding_digest",
            "e2_common_input_digest",
            "e1_caps_digest",
            "e2_caps_digest",
            "cost_ledger_schema_digest",
            "final_k",
        ],
        "claim_boundary": {
            "labels": "historically label-informed opened-development",
            "inference": "paired descriptive effects only; no statistical/generalization claim",
            "formal_holdout": "untouched",
        },
        "side_effects": {
            "filesystem_reads": 0,
            "filesystem_writes": 0,
            "repository_calls": 0,
            "runtime_imports": 0,
            "reader_model_provider_controller_calls": 0,
            "automatic_retries": 0,
        },
    }
    contract["contract_digest"] = canonical_sha256(contract)
    return contract


def score_all_arms(
    *,
    combined_seal: Mapping[str, Any],
    arm_outputs: Mapping[str, Mapping[str, Any]],
    gold_registry: Mapping[str, Any],
    proof_registry: Mapping[str, Any],
    authorization: Mapping[str, Any],
    expected_contract_digest: str,
    expected_readiness_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """Score all E1/E2 arms only after joint seal and independent authorization."""

    contract = scorer_contract()
    if expected_contract_digest != contract["contract_digest"]:
        raise ValueError("DG25_SCORER_CONTRACT_DIGEST_MISMATCH")
    _validate_authorization(authorization, combined_seal)
    _validate_combined_seal(
        combined_seal,
        arm_outputs,
        expected_readiness_bindings=expected_readiness_bindings,
    )
    _validate_registries(gold_registry, proof_registry)

    groups = _gold_groups(gold_registry)
    obligations = _proof_obligations(proof_registry)
    if len(groups) != 23 or len(obligations) != 37:
        raise ValueError("DG25_FROZEN_DENOMINATOR_MISMATCH")
    query_ids = {key[0] for key in groups}
    if len(query_ids) != 10:
        raise ValueError("DG25_QUERY_DENOMINATOR_MISMATCH")

    scores = {
        arm_id: _score_arm(
            arm_id=arm_id,
            output=arm_outputs[arm_id],
            groups=groups,
            obligations=obligations,
        )
        for arm_id in (*E1_ARM_ORDER, *E2_ARM_ORDER)
    }
    sequential = _sequential_contributions(scores)
    unique = _full_minus_one_contributions(scores)
    final_policy = _select_final_policy(scores, unique)
    result: dict[str, Any] = {
        "schema": "milai.dg25.e1-e2-effect-score.v0.1",
        "scorer_identity": SCORER_IDENTITY,
        "scorer_contract_digest": expected_contract_digest,
        "combined_all_arm_seal_digest": str(combined_seal["seal_digest"]),
        "independent_authorization_digest": str(authorization["authorization_digest"]),
        "denominators": {"queries": 10, "groups": len(groups), "proofs": len(obligations)},
        "arm_scores": scores,
        "order_conditional_contributions": sequential,
        "full_minus_one_contributions": unique,
        "final_minimal_policy": final_policy,
        "post_score_adaptation": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
    }
    result["score_digest"] = canonical_sha256(result)
    return result


def _validate_authorization(
    authorization: Mapping[str, Any],
    combined_seal: Mapping[str, Any],
) -> None:
    if authorization.get("schema") != "milai.dg25.independent-scoring-authorization.v0.1":
        raise ValueError("DG25_SCORING_AUTHORIZATION_SCHEMA_INVALID")
    if authorization.get("authorized") is not True:
        raise ValueError("DG25_EFFECT_SCORING_NOT_AUTHORIZED")
    if authorization.get("combined_all_arm_seal_digest") != combined_seal.get("seal_digest"):
        raise ValueError("DG25_AUTHORIZATION_SEAL_BINDING_MISMATCH")
    if authorization.get("readiness_bindings_digest") != combined_seal.get(
        "readiness_bindings_digest"
    ):
        raise ValueError("DG25_AUTHORIZATION_READINESS_BINDING_MISMATCH")
    if authorization.get("reader_model_provider_controller_calls") != 0:
        raise ValueError("DG25_FORBIDDEN_CALL_AUTHORIZATION")
    if authorization.get("formal_holdout_authorized") is not False:
        raise ValueError("DG25_FORMAL_HOLDOUT_AUTHORIZATION_INVALID")
    material = dict(authorization)
    observed = material.pop("authorization_digest", None)
    if observed != canonical_sha256(material):
        raise ValueError("DG25_SCORING_AUTHORIZATION_DIGEST_MISMATCH")


def _validate_combined_seal(
    combined_seal: Mapping[str, Any],
    arm_outputs: Mapping[str, Mapping[str, Any]],
    *,
    expected_readiness_bindings: Mapping[str, Any],
) -> None:
    if combined_seal.get("schema") != "milai.dg25.e1-e2-all-arm-seal.v0.2":
        raise ValueError("DG25_ALL_ARM_SEAL_SCHEMA_INVALID")
    material = dict(combined_seal)
    observed = material.pop("seal_digest", None)
    if observed != canonical_sha256(material):
        raise ValueError("DG25_ALL_ARM_SEAL_DIGEST_MISMATCH")
    if combined_seal.get("e1_arm_order") != list(E1_ARM_ORDER):
        raise ValueError("DG25_E1_ARM_ORDER_DRIFT")
    if combined_seal.get("e2_arm_order") != list(E2_ARM_ORDER):
        raise ValueError("DG25_E2_ARM_ORDER_DRIFT")
    if combined_seal.get("all_outputs_sealed_before_label_load") is not True:
        raise ValueError("DG25_LABEL_BEFORE_ALL_ARM_SEAL")
    if combined_seal.get("registry_content_loaded_during_generation") is not False:
        raise ValueError("DG25_REGISTRY_CONTENT_LOADED_DURING_GENERATION")
    if combined_seal.get("scoring_executed_during_generation") is not False:
        raise ValueError("DG25_SCORING_EXECUTED_DURING_GENERATION")
    if combined_seal.get("reader_model_provider_controller_calls") != 0:
        raise ValueError("DG25_FORBIDDEN_GENERATION_CALL")
    if combined_seal.get("formal_holdout_consumed") is not False:
        raise ValueError("DG25_FORMAL_HOLDOUT_CONSUMED")
    if combined_seal.get("automatic_retries") != 0:
        raise ValueError("DG25_AUTOMATIC_RETRY_FORBIDDEN")
    expected_binding_fields = scorer_contract()["required_execution_bindings"]
    if not isinstance(expected_binding_fields, list):
        raise TypeError("DG25_SCORER_BINDING_FIELDS_INVALID")
    if set(expected_readiness_bindings) != set(expected_binding_fields):
        raise ValueError("DG25_EXPECTED_READINESS_BINDING_SCHEMA_MISMATCH")
    if combined_seal.get("readiness_bindings") != dict(expected_readiness_bindings):
        raise ValueError("DG25_COMBINED_SEAL_READINESS_BINDING_MISMATCH")
    if combined_seal.get("readiness_bindings_digest") != canonical_sha256(
        dict(expected_readiness_bindings)
    ):
        raise ValueError("DG25_COMBINED_SEAL_READINESS_BINDING_DIGEST_MISMATCH")
    expected = set(E1_ARM_ORDER) | set(E2_ARM_ORDER)
    if set(arm_outputs) != expected:
        raise ValueError("DG25_ALL_ARM_OUTPUT_SET_MISMATCH")
    identities = combined_seal.get("arm_output_content_digests")
    if not isinstance(identities, Mapping) or set(identities) != expected:
        raise ValueError("DG25_ALL_ARM_OUTPUT_IDENTITY_SET_MISMATCH")
    if combined_seal.get("arm_output_set_digest") != canonical_sha256(dict(identities)):
        raise ValueError("DG25_ALL_ARM_OUTPUT_SET_DIGEST_MISMATCH")
    configs = combined_seal.get("arm_config_digests")
    execution_bindings = combined_seal.get("arm_execution_binding_digests")
    if not isinstance(configs, Mapping) or set(configs) != expected:
        raise ValueError("DG25_ALL_ARM_CONFIG_IDENTITY_SET_MISMATCH")
    if not isinstance(execution_bindings, Mapping) or set(execution_bindings) != expected:
        raise ValueError("DG25_ALL_ARM_EXECUTION_BINDING_SET_MISMATCH")
    e1_configs = {arm_id: configs[arm_id] for arm_id in E1_ARM_ORDER}
    e2_configs = {arm_id: configs[arm_id] for arm_id in E2_ARM_ORDER}
    if canonical_sha256(e1_configs) != expected_readiness_bindings.get(
        "e1_config_set_digest"
    ):
        raise ValueError("DG25_E1_CONFIG_SET_DIGEST_MISMATCH")
    if canonical_sha256(e2_configs) != expected_readiness_bindings.get(
        "e2_config_set_digest"
    ):
        raise ValueError("DG25_E2_CONFIG_SET_DIGEST_MISMATCH")
    for arm_id, output in arm_outputs.items():
        if output.get("schema") != "milai.dg25.label-free-arm-output.v0.2":
            raise ValueError("DG25_ARM_OUTPUT_SCHEMA_INVALID")
        if output.get("arm_id") != arm_id:
            raise ValueError("DG25_ARM_OUTPUT_ID_MISMATCH")
        block = "E1" if arm_id in E1_ARM_ORDER else "E2"
        if output.get("block") != block:
            raise ValueError("DG25_ARM_OUTPUT_BLOCK_MISMATCH")
        if output.get("arm_config_digest") != configs.get(arm_id):
            raise ValueError("DG25_ARM_OUTPUT_CONFIG_DIGEST_MISMATCH")
        output_material = dict(output)
        observed_output_digest = output_material.pop("output_digest", None)
        if observed_output_digest != canonical_sha256(output_material):
            raise ValueError("DG25_ARM_OUTPUT_SELF_DIGEST_MISMATCH")
        if observed_output_digest != identities.get(arm_id):
            raise ValueError("DG25_ARM_OUTPUT_CONTENT_DIGEST_MISMATCH")
        if output.get("registry_content_loaded") is not False:
            raise ValueError("DG25_ARM_OUTPUT_LABEL_BOUNDARY_VIOLATION")
        if output.get("labels_loaded") is not False or output.get("scoring_executed") is not False:
            raise ValueError("DG25_ARM_OUTPUT_SCORE_BOUNDARY_VIOLATION")
        binding = output.get("execution_binding")
        if not isinstance(binding, Mapping):
            raise TypeError("DG25_ARM_EXECUTION_BINDING_REQUIRED")
        binding_material = dict(binding)
        binding_digest = binding_material.pop("execution_binding_digest", None)
        if binding_digest != canonical_sha256(binding_material):
            raise ValueError("DG25_ARM_EXECUTION_BINDING_DIGEST_MISMATCH")
        if binding_digest != execution_bindings.get(arm_id):
            raise ValueError("DG25_ARM_EXECUTION_BINDING_SEAL_MISMATCH")
        _validate_arm_execution_binding(
            arm_id=arm_id,
            block=block,
            binding=binding,
            config_digest=str(configs[arm_id]),
            expected=expected_readiness_bindings,
        )


def _validate_arm_execution_binding(
    *,
    arm_id: str,
    block: str,
    binding: Mapping[str, Any],
    config_digest: str,
    expected: Mapping[str, Any],
) -> None:
    if (
        binding.get("schema") != "milai.dg25.arm-execution-binding.v0.1"
        or binding.get("block") != block
        or binding.get("arm_id") != arm_id
        or binding.get("arm_config_digest") != config_digest
    ):
        raise ValueError("DG25_ARM_EXECUTION_BINDING_HEADER_MISMATCH")
    shared = {
        "execution_delta_manifest_digest": expected["execution_delta_manifest_digest"],
        "all_arm_seal_protocol_digest": expected["all_arm_seal_protocol_digest"],
        "readiness_source_manifest_digest": expected["readiness_source_manifest_digest"],
        "case_order_digest": expected["case_order_digest"],
        "cost_ledger_schema_digest": expected["cost_ledger_schema_digest"],
        "final_k": expected["final_k"],
    }
    if block == "E1":
        shared.update(
            {
                "config_set_digest": expected["e1_config_set_digest"],
                "input_binding_digest": expected["e1_common_pool_binding_digest"],
                "caps_digest": expected["e1_caps_digest"],
            }
        )
        block_identity = binding.get("block_input_identity")
        if not isinstance(block_identity, Mapping) or block_identity.get(
            "e1_action_manifest_digest"
        ) != expected["e1_action_manifest_digest"]:
            raise ValueError("DG25_E1_ACTION_MANIFEST_BINDING_MISMATCH")
    else:
        shared.update(
            {
                "config_set_digest": expected["e2_config_set_digest"],
                "input_binding_digest": expected["e2_common_input_digest"],
                "caps_digest": expected["e2_caps_digest"],
            }
        )
        block_identity = binding.get("block_input_identity")
        if not isinstance(block_identity, Mapping) or block_identity.get(
            "e2_common_input_digest"
        ) != expected["e2_common_input_digest"]:
            raise ValueError("DG25_E2_COMMON_INPUT_BINDING_MISMATCH")
    if any(binding.get(field) != value for field, value in shared.items()):
        raise ValueError("DG25_ARM_PREREGISTERED_EXECUTION_BINDING_MISMATCH")


def _validate_registries(
    gold_registry: Mapping[str, Any],
    proof_registry: Mapping[str, Any],
) -> None:
    if (
        gold_registry.get("schema_version") != "gold-equivalence-registry-v0.1"
        or gold_registry.get("scorer_only") is not True
    ):
        raise ValueError("DG25_GOLD_REGISTRY_INVALID")
    if (
        proof_registry.get("schema_version") != "proof-obligation-registry-v0.1"
        or proof_registry.get("scorer_only") is not True
    ):
        raise ValueError("DG25_PROOF_REGISTRY_INVALID")


def _gold_groups(
    registry: Mapping[str, Any],
) -> dict[tuple[str, str, str], str]:
    result: dict[tuple[str, str, str], str] = {}
    for query in _mapping_sequence(registry.get("queries"), "gold queries"):
        query_id = str(query["query_id"])
        for requirement in _mapping_sequence(query.get("requirements"), "gold requirements"):
            requirement_id = str(requirement["requirement_id"])
            for role in _mapping_sequence(requirement.get("evidence_roles"), "evidence roles"):
                for group in _mapping_sequence(
                    role.get("equivalence_groups"), "equivalence groups"
                ):
                    key = (query_id, requirement_id, str(group["equivalence_group_id"]))
                    result[key] = _canonical_source_ref(str(group["source_turn_ref"]))
    return result


def _proof_obligations(
    registry: Mapping[str, Any],
) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for query in _mapping_sequence(registry.get("queries"), "proof queries"):
        query_id = str(query["query_id"])
        for requirement in _mapping_sequence(query.get("requirements"), "proof requirements"):
            requirement_id = str(requirement["requirement_id"])
            for obligation in _mapping_sequence(requirement.get("obligations"), "obligations"):
                result.add((query_id, requirement_id, str(obligation["obligation_id"])))
    return result


def _score_arm(
    *,
    arm_id: str,
    output: Mapping[str, Any],
    groups: Mapping[tuple[str, str, str], str],
    obligations: set[tuple[str, str, str]],
) -> dict[str, Any]:
    selected_by_requirement: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    proof_status: dict[tuple[str, str, str], str] = {}
    sufficiency: dict[tuple[str, str], str] = {}
    for record in _mapping_sequence(output.get("records"), "arm records"):
        query_id = str(record["query_id"])
        for requirement in _mapping_sequence(record.get("requirements"), "arm requirements"):
            requirement_id = str(requirement["requirement_id"])
            key = (query_id, requirement_id)
            selected_by_requirement[key] = _mapping_sequence(
                requirement.get("selected_occurrences"), "selected occurrences"
            )
            sufficiency[key] = str(requirement.get("sufficiency", "NOT_EVALUATED"))
            for proof in _mapping_sequence(
                requirement.get("proof_obligations"), "arm proof obligations"
            ):
                proof_status[(query_id, requirement_id, str(proof["obligation_id"]))] = str(
                    proof["status"]
                )

    candidate_hits: set[tuple[str, str, str]] = set()
    binding_hits: set[tuple[str, str, str]] = set()
    accepted_match_bindings: set[tuple[str, str, str]] = set()
    all_match_bindings: set[tuple[str, str, str]] = set()
    range_predictions = 0
    correct_range_predictions = 0
    event_identity_by_group: dict[tuple[str, str, str], str] = {}
    for group_key, expected_source in groups.items():
        query_id, requirement_id, _group_id = group_key
        selected = selected_by_requirement.get((query_id, requirement_id), [])
        for item in selected:
            source = _canonical_source_ref(str(item["source_turn_ref"]))
            if item.get("legal") is not True:
                continue
            if str(item.get("binding_status")) == "MATCH":
                all_match_bindings.add((query_id, requirement_id, source))
            if source != expected_source:
                continue
            candidate_hits.add(group_key)
            if str(item.get("binding_status")) == "MATCH":
                binding_hits.add(group_key)
                accepted_match_bindings.add((query_id, requirement_id, source))
            membership = item.get("range_membership")
            if membership is not None:
                range_predictions += 1
                if membership == "IN_RANGE":
                    correct_range_predictions += 1
            event_identity = item.get("event_identity_digest")
            if isinstance(event_identity, str) and event_identity:
                event_identity_by_group[group_key] = event_identity

    proof_hits = {key for key in obligations if proof_status.get(key) == "SATISFIED"}
    wrong_complete = 0
    for key, status in sufficiency.items():
        if status != "COMPLETE":
            continue
        required_groups = {group for group in groups if group[:2] == key}
        required_proofs = {proof for proof in obligations if proof[:2] == key}
        if not required_groups.issubset(binding_hits) or not required_proofs.issubset(proof_hits):
            wrong_complete += 1

    first_loss: Counter[str] = Counter()
    for group in groups:
        if group in binding_hits:
            first_loss["TERMINAL_SURVIVAL"] += 1
        elif group in candidate_hits:
            first_loss["SELECTED_NOT_BOUND"] += 1
        else:
            first_loss["NOT_SELECTED_AT_FIXED_K"] += 1
    ledger = output.get("cost_ledger")
    if not isinstance(ledger, Mapping) or set(ledger) != set(COST_LEDGER_FIELDS):
        raise ValueError("DG25_COST_LEDGER_SCHEMA_MISMATCH")
    if any(ledger[field] is None for field in COST_LEDGER_FIELDS if field != "latency_ms"):
        raise ValueError("DG25_COST_LEDGER_VALUE_MISSING")
    identity_values = list(event_identity_by_group.values())
    distinct_identity_correct = len(identity_values) == len(set(identity_values))
    precision = (
        len(accepted_match_bindings) / len(all_match_bindings) if all_match_bindings else 1.0
    )
    return {
        "arm_id": arm_id,
        "target_requirement_candidate_recall_at_k": len(candidate_hits) / len(groups),
        "candidate_groups": len(candidate_hits),
        "required_evidence_coverage_at_k": len(binding_hits) / len(groups),
        "covered_groups": len(binding_hits),
        "accepted_binding_precision": precision,
        "accepted_binding_count": len(accepted_match_bindings),
        "all_match_binding_count": len(all_match_bindings),
        "proof_obligation_satisfaction_rate": len(proof_hits) / len(obligations),
        "proof_obligations_satisfied": len(proof_hits),
        "range_membership_accuracy": (
            correct_range_predictions / range_predictions if range_predictions else None
        ),
        "range_membership_predictions": range_predictions,
        "distinct_event_identity_accuracy": (
            1.0 if identity_values and distinct_identity_correct else 0.0 if identity_values else None
        ),
        "wrong_complete": wrong_complete,
        "first_loss_distribution": dict(sorted(first_loss.items())),
        "cost_ledger": dict(ledger),
    }


def _sequential_contributions(scores: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for predecessor, arm_id in pairwise(E1_ARM_ORDER[1:6]):
        result.append(_paired_delta(predecessor, arm_id, scores))
    result.append(_paired_delta("R4", "R5_NO_SYNONYM_NORMALIZATION", scores))
    for predecessor, arm_id in pairwise(E2_ARM_ORDER):
        result.append(_paired_delta(predecessor, arm_id, scores))
    return result


def _full_minus_one_contributions(
    scores: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    control = "R5_NO_SYNONYM_NORMALIZATION"
    arms = (
        "R_FINAL_DROP_UNIFIED_PROOF_FIRST",
        "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION",
        "R_FINAL_DROP_ROLE_RESERVATION",
        "R_FINAL_DROP_SOFT_LEXICAL_FEATURES",
    )
    return [_paired_delta(arm_id, control, scores) for arm_id in arms]


def _paired_delta(
    predecessor: str,
    arm_id: str,
    scores: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    before = scores[predecessor]
    after = scores[arm_id]
    return {
        "predecessor": predecessor,
        "arm_id": arm_id,
        "covered_group_delta": int(after["covered_groups"]) - int(before["covered_groups"]),
        "proof_satisfied_delta": int(after["proof_obligations_satisfied"])
        - int(before["proof_obligations_satisfied"]),
        "logical_action_delta": int(after["cost_ledger"]["logical_selected_actions"])
        - int(before["cost_ledger"]["logical_selected_actions"]),
        "replayed_call_delta": int(after["cost_ledger"]["replayed_repository_calls"])
        - int(before["cost_ledger"]["replayed_repository_calls"]),
        "hydrated_delta": int(after["cost_ledger"]["candidates_hydrated"])
        - int(before["cost_ledger"]["candidates_hydrated"]),
        "precision_preserved": float(after["accepted_binding_precision"]) == 1.0,
        "wrong_complete_zero": int(after["wrong_complete"]) == 0,
    }


def _select_final_policy(
    scores: Mapping[str, Mapping[str, Any]],
    unique: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    component_by_drop = {
        "R_FINAL_DROP_UNIFIED_PROOF_FIRST": "UNIFIED_PROOF_FIRST",
        "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION": "OPTIONAL_CHANNEL_UNION",
        "R_FINAL_DROP_ROLE_RESERVATION": "ROLE_RESERVATION",
        "R_FINAL_DROP_SOFT_LEXICAL_FEATURES": "SOFT_LEXICAL_FEATURES",
    }
    retained: list[str] = []
    removed: list[str] = []
    for delta in unique:
        component = component_by_drop[str(delta["predecessor"])]
        matters = (
            int(delta["covered_group_delta"]) > 0
            or int(delta["proof_satisfied_delta"]) > 0
        ) and delta["precision_preserved"] is True and delta["wrong_complete_zero"] is True
        (retained if matters else removed).append(component)
    no_synonym = scores["R5_NO_SYNONYM_NORMALIZATION"]
    with_synonym = scores["R4"]
    synonym_loss = (
        int(no_synonym["covered_groups"]) < int(with_synonym["covered_groups"])
        or int(no_synonym["proof_obligations_satisfied"])
        < int(with_synonym["proof_obligations_satisfied"])
    )
    if synonym_loss:
        retained.append("SYNONYM_NORMALIZATION")
    else:
        removed.append("SYNONYM_NORMALIZATION")
    return {
        "base_arm": "R5_NO_SYNONYM_NORMALIZATION",
        "retained_components": sorted(retained),
        "removed_components": sorted(removed),
        "synonym_generality_parked": synonym_loss,
        "selection_uses_only_preregistered_pairs": True,
        "post_score_adaptation": False,
    }


def _mapping_sequence(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"{label} items must be mappings")
        result.append(item)
    return result


def _canonical_source_ref(value: str) -> str:
    longmem = _LONGMEM_SOURCE_REF.match(value)
    if longmem is not None:
        case_id, session_ordinal, session_id, turn_ordinal = longmem.groups()
        return (
            f"{unquote(case_id)}:s{session_ordinal}:"
            f"{unquote(session_id)}:t{turn_ordinal}"
        )
    if value.startswith("longmemeval://"):
        raise ValueError("DG25_SOURCE_REF_INVALID")
    match = _SOURCE_REF.match(value)
    if match is None:
        raise ValueError("DG25_SOURCE_REF_INVALID")
    return match.group(1)


def canonical_sha256(value: object) -> str:
    """Self-contained canonical digest; importing Runtime here is forbidden."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "COST_LEDGER_FIELDS",
    "E1_ARM_ORDER",
    "E2_ARM_ORDER",
    "SCORER_IDENTITY",
    "score_all_arms",
    "scorer_contract",
]

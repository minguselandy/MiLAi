"""Pure execution-binding and immutable all-arm seal contracts for DG-25."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from milai.domain.requirement_state import canonical_sha256

ArmBlock = Literal["E1", "E2"]

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
COMBINED_SEAL_READINESS_BINDING_FIELDS = (
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
)
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
COMMON_EXECUTION_BINDING_FIELDS = (
    "execution_delta_manifest_digest",
    "all_arm_seal_protocol_digest",
    "readiness_source_manifest_digest",
    "case_order_digest",
    "config_set_digest",
    "input_binding_digest",
    "caps_digest",
    "cost_ledger_schema_digest",
    "final_k",
)


def cost_ledger_schema() -> dict[str, Any]:
    material: dict[str, Any] = {
        "schema": "milai.dg25.cost-ledger-schema.v0.1",
        "fields_in_order": list(COST_LEDGER_FIELDS),
        "latency_ms_disposition_for_matched_replay": "NOT_MEASURED_NULL",
        "physical_repository_calls_for_matched_replay": 0,
        "reader_calls": 0,
    }
    material["cost_ledger_schema_digest"] = canonical_sha256(material)
    return material


def build_label_free_arm_output(
    *,
    block: ArmBlock,
    arm_id: str,
    arm_config_digest: str,
    common_execution_bindings: Mapping[str, Any],
    block_input_identity: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    cost_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a self-identifying output bound to every preregistered identity."""

    _validate_common_bindings(common_execution_bindings)
    if set(cost_ledger) != set(COST_LEDGER_FIELDS):
        raise ValueError("DG25_COST_LEDGER_SCHEMA_MISMATCH")
    if any(
        cost_ledger[field] is None
        for field in COST_LEDGER_FIELDS
        if field != "latency_ms"
    ):
        raise ValueError("DG25_COST_LEDGER_VALUE_MISSING")
    execution_binding: dict[str, Any] = {
        "schema": "milai.dg25.arm-execution-binding.v0.1",
        "block": block,
        "arm_id": arm_id,
        "arm_config_digest": arm_config_digest,
        **dict(common_execution_bindings),
        "block_input_identity": dict(block_input_identity),
    }
    execution_binding["execution_binding_digest"] = canonical_sha256(execution_binding)
    material: dict[str, Any] = {
        "schema": "milai.dg25.label-free-arm-output.v0.2",
        "block": block,
        "arm_id": arm_id,
        "arm_config_digest": arm_config_digest,
        "execution_binding": execution_binding,
        "labels_loaded": False,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
        "records": [dict(item) for item in records],
        "cost_ledger": dict(cost_ledger),
    }
    material["output_digest"] = canonical_sha256(material)
    return material


def validate_label_free_arm_output(
    *,
    output: Mapping[str, Any],
    block: ArmBlock,
    arm_id: str,
    arm_config_digest: str,
    common_execution_bindings: Mapping[str, Any],
    block_input_identity: Mapping[str, Any],
) -> None:
    if output.get("schema") != "milai.dg25.label-free-arm-output.v0.2":
        raise ValueError("DG25_ARM_OUTPUT_SCHEMA_INVALID")
    if (
        output.get("block") != block
        or output.get("arm_id") != arm_id
        or output.get("arm_config_digest") != arm_config_digest
    ):
        raise ValueError("DG25_ARM_OUTPUT_CONFIG_BINDING_MISMATCH")
    for field, expected in {
        "labels_loaded": False,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
    }.items():
        if output.get(field) != expected:
            raise ValueError("DG25_ARM_OUTPUT_BOUNDARY_VIOLATION")
    binding = _mapping(output.get("execution_binding"), "arm execution binding")
    expected_binding: dict[str, Any] = {
        "schema": "milai.dg25.arm-execution-binding.v0.1",
        "block": block,
        "arm_id": arm_id,
        "arm_config_digest": arm_config_digest,
        **dict(common_execution_bindings),
        "block_input_identity": dict(block_input_identity),
    }
    expected_binding["execution_binding_digest"] = canonical_sha256(expected_binding)
    if dict(binding) != expected_binding:
        raise ValueError("DG25_ARM_OUTPUT_EXECUTION_BINDING_MISMATCH")
    ledger = _mapping(output.get("cost_ledger"), "cost ledger")
    if set(ledger) != set(COST_LEDGER_FIELDS):
        raise ValueError("DG25_COST_LEDGER_SCHEMA_MISMATCH")
    material = dict(output)
    observed = material.pop("output_digest", None)
    if observed != canonical_sha256(material):
        raise ValueError("DG25_ARM_OUTPUT_DIGEST_MISMATCH")


def build_block_all_arm_seal(
    *,
    block: ArmBlock,
    arm_outputs: Mapping[str, Mapping[str, Any]],
    arm_order: Sequence[str],
    config_digests: Mapping[str, str],
    common_execution_bindings: Mapping[str, Any],
    block_input_identities: Mapping[str, Mapping[str, Any]],
    generator_source_sha256: str,
    sealer_source_sha256: str,
    runner_source_sha256: str,
    independent_authorization_digest: str,
) -> dict[str, Any]:
    expected_order = E1_ARM_ORDER if block == "E1" else E2_ARM_ORDER
    if list(arm_order) != list(expected_order):
        raise ValueError("DG25_ALL_ARM_ORDER_MISMATCH")
    if list(arm_outputs) != list(expected_order) or list(config_digests) != list(
        expected_order
    ):
        raise ValueError("DG25_ALL_ARM_OUTPUT_SET_OR_ORDER_MISMATCH")
    if set(block_input_identities) != set(expected_order):
        raise ValueError("DG25_ALL_ARM_INPUT_IDENTITY_SET_MISMATCH")
    for arm_id in expected_order:
        validate_label_free_arm_output(
            output=arm_outputs[arm_id],
            block=block,
            arm_id=arm_id,
            arm_config_digest=config_digests[arm_id],
            common_execution_bindings=common_execution_bindings,
            block_input_identity=block_input_identities[arm_id],
        )
    output_digests = {
        arm_id: str(arm_outputs[arm_id]["output_digest"]) for arm_id in expected_order
    }
    schema = (
        "milai.dg25.e1-all-arm-seal.v0.2"
        if block == "E1"
        else "milai.dg25.e2-all-arm-seal.v0.2"
    )
    material: dict[str, Any] = {
        "schema": schema,
        "block": block,
        "arm_order": list(expected_order),
        "arm_config_digests": dict(config_digests),
        "arm_output_content_digests": output_digests,
        "arm_output_set_digest": canonical_sha256(output_digests),
        "common_execution_bindings": dict(common_execution_bindings),
        "block_input_identities": {
            arm_id: dict(block_input_identities[arm_id]) for arm_id in expected_order
        },
        "generator_source_sha256": generator_source_sha256,
        "sealer_source_sha256": sealer_source_sha256,
        "runner_source_sha256": runner_source_sha256,
        "independent_authorization_digest": independent_authorization_digest,
        "all_outputs_sealed_before_label_load": True,
        "registry_content_loaded_during_generation": False,
        "scoring_executed_during_generation": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "automatic_retries": 0,
    }
    material["seal_digest"] = canonical_sha256(material)
    return material


def validate_block_all_arm_seal(
    *,
    seal: Mapping[str, Any],
    block: ArmBlock,
    arm_outputs: Mapping[str, Mapping[str, Any]],
    arm_order: Sequence[str],
    config_digests: Mapping[str, str],
    common_execution_bindings: Mapping[str, Any],
    block_input_identities: Mapping[str, Mapping[str, Any]],
) -> None:
    expected_schema = (
        "milai.dg25.e1-all-arm-seal.v0.2"
        if block == "E1"
        else "milai.dg25.e2-all-arm-seal.v0.2"
    )
    if seal.get("schema") != expected_schema or seal.get("block") != block:
        raise ValueError("DG25_BLOCK_SEAL_SCHEMA_INVALID")
    if seal.get("arm_order") != list(arm_order):
        raise ValueError("DG25_BLOCK_SEAL_ARM_ORDER_DRIFT")
    if seal.get("arm_config_digests") != dict(config_digests):
        raise ValueError("DG25_BLOCK_SEAL_CONFIG_DIGEST_DRIFT")
    if seal.get("common_execution_bindings") != dict(common_execution_bindings):
        raise ValueError("DG25_BLOCK_SEAL_EXECUTION_BINDING_DRIFT")
    if seal.get("block_input_identities") != {
        arm_id: dict(block_input_identities[arm_id]) for arm_id in arm_order
    }:
        raise ValueError("DG25_BLOCK_SEAL_INPUT_BINDING_DRIFT")
    expected_outputs = {
        arm_id: str(arm_outputs[arm_id]["output_digest"]) for arm_id in arm_order
    }
    if seal.get("arm_output_content_digests") != expected_outputs:
        raise ValueError("DG25_BLOCK_SEAL_OUTPUT_DIGEST_DRIFT")
    if seal.get("arm_output_set_digest") != canonical_sha256(expected_outputs):
        raise ValueError("DG25_BLOCK_SEAL_OUTPUT_SET_DIGEST_MISMATCH")
    material = dict(seal)
    observed = material.pop("seal_digest", None)
    if observed != canonical_sha256(material):
        raise ValueError("DG25_BLOCK_SEAL_DIGEST_MISMATCH")


def build_combined_all_arm_seal(
    *,
    e1_seal: Mapping[str, Any],
    e2_seal: Mapping[str, Any],
    arm_outputs: Mapping[str, Mapping[str, Any]],
    readiness_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    expected_order = (*E1_ARM_ORDER, *E2_ARM_ORDER)
    if list(arm_outputs) != list(expected_order):
        raise ValueError("DG25_COMBINED_OUTPUT_SET_OR_ORDER_MISMATCH")
    _validate_combined_readiness_binding_schema(readiness_bindings)
    output_digests = {
        arm_id: str(arm_outputs[arm_id]["output_digest"]) for arm_id in expected_order
    }
    config_digests = {
        arm_id: str(arm_outputs[arm_id]["arm_config_digest"])
        for arm_id in expected_order
    }
    execution_binding_digests = {
        arm_id: str(
            arm_outputs[arm_id]["execution_binding"]["execution_binding_digest"]
        )
        for arm_id in expected_order
    }
    material: dict[str, Any] = {
        "schema": "milai.dg25.e1-e2-all-arm-seal.v0.2",
        "e1_arm_order": list(E1_ARM_ORDER),
        "e2_arm_order": list(E2_ARM_ORDER),
        "e1_all_arm_seal_digest": str(e1_seal["seal_digest"]),
        "e2_all_arm_seal_digest": str(e2_seal["seal_digest"]),
        "readiness_bindings": dict(readiness_bindings),
        "readiness_bindings_digest": canonical_sha256(dict(readiness_bindings)),
        "arm_config_digests": config_digests,
        "arm_execution_binding_digests": execution_binding_digests,
        "arm_output_content_digests": output_digests,
        "arm_output_set_digest": canonical_sha256(output_digests),
        "all_outputs_sealed_before_label_load": True,
        "registry_content_loaded_during_generation": False,
        "scoring_executed_during_generation": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "automatic_retries": 0,
    }
    material["seal_digest"] = canonical_sha256(material)
    return material


def validate_combined_all_arm_seal(
    *,
    seal: Mapping[str, Any],
    e1_seal: Mapping[str, Any],
    e2_seal: Mapping[str, Any],
    arm_outputs: Mapping[str, Mapping[str, Any]],
    readiness_bindings: Mapping[str, Any],
) -> None:
    """Recompute the exact 16-arm combined seal and every safety boundary."""

    expected_order = (*E1_ARM_ORDER, *E2_ARM_ORDER)
    if list(arm_outputs) != list(expected_order):
        raise ValueError("DG25_COMBINED_OUTPUT_SET_OR_ORDER_MISMATCH")
    _validate_combined_readiness_binding_schema(readiness_bindings)
    if seal.get("schema") != "milai.dg25.e1-e2-all-arm-seal.v0.2":
        raise ValueError("DG25_COMBINED_SEAL_SCHEMA_INVALID")
    expected_fields: dict[str, Any] = {
        "e1_arm_order": list(E1_ARM_ORDER),
        "e2_arm_order": list(E2_ARM_ORDER),
        "e1_all_arm_seal_digest": str(e1_seal["seal_digest"]),
        "e2_all_arm_seal_digest": str(e2_seal["seal_digest"]),
        "readiness_bindings": dict(readiness_bindings),
        "readiness_bindings_digest": canonical_sha256(dict(readiness_bindings)),
        "arm_config_digests": {
            arm_id: str(arm_outputs[arm_id]["arm_config_digest"])
            for arm_id in expected_order
        },
        "arm_execution_binding_digests": {
            arm_id: str(
                arm_outputs[arm_id]["execution_binding"]["execution_binding_digest"]
            )
            for arm_id in expected_order
        },
        "arm_output_content_digests": {
            arm_id: str(arm_outputs[arm_id]["output_digest"])
            for arm_id in expected_order
        },
    }
    expected_fields["arm_output_set_digest"] = canonical_sha256(
        expected_fields["arm_output_content_digests"]
    )
    if any(seal.get(key) != value for key, value in expected_fields.items()):
        raise ValueError("DG25_COMBINED_SEAL_BINDING_DRIFT")
    boundaries = {
        "all_outputs_sealed_before_label_load": True,
        "registry_content_loaded_during_generation": False,
        "scoring_executed_during_generation": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "automatic_retries": 0,
    }
    if any(seal.get(key) != value for key, value in boundaries.items()):
        raise ValueError("DG25_COMBINED_SEAL_BOUNDARY_VIOLATION")
    material = dict(seal)
    observed = material.pop("seal_digest", None)
    if observed != canonical_sha256(material):
        raise ValueError("DG25_COMBINED_SEAL_DIGEST_MISMATCH")


def _validate_combined_readiness_binding_schema(
    readiness_bindings: Mapping[str, Any],
) -> None:
    if set(readiness_bindings) != set(COMBINED_SEAL_READINESS_BINDING_FIELDS):
        raise ValueError("DG25_COMBINED_READINESS_BINDING_SCHEMA_MISMATCH")


def _validate_common_bindings(bindings: Mapping[str, Any]) -> None:
    if set(bindings) != set(COMMON_EXECUTION_BINDING_FIELDS):
        raise ValueError("DG25_COMMON_EXECUTION_BINDING_SCHEMA_MISMATCH")
    if bindings.get("final_k") != 8:
        raise ValueError("DG25_FINAL_K_DRIFT")
    for field in COMMON_EXECUTION_BINDING_FIELDS:
        if field == "final_k":
            continue
        value = bindings.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError("DG25_COMMON_EXECUTION_BINDING_DIGEST_INVALID")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


__all__ = [
    "COMBINED_SEAL_READINESS_BINDING_FIELDS",
    "COMMON_EXECUTION_BINDING_FIELDS",
    "COST_LEDGER_FIELDS",
    "E1_ARM_ORDER",
    "E2_ARM_ORDER",
    "build_block_all_arm_seal",
    "build_combined_all_arm_seal",
    "build_label_free_arm_output",
    "cost_ledger_schema",
    "validate_block_all_arm_seal",
    "validate_combined_all_arm_seal",
    "validate_label_free_arm_output",
]

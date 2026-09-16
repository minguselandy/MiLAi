"""Build and validate the label-free DG-25 S4A execution-readiness package."""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from milai.domain.requirement_state import canonical_sha256

from evals.dg25.arm_sealing import (
    E1_ARM_ORDER,
    E2_ARM_ORDER,
    validate_block_all_arm_seal,
    validate_label_free_arm_output,
)
from evals.dg25.routing_ablation import E2ArmConfigV01

S3_READINESS_RUN_ID = "dg25-s3-readiness-20260830-011"
S3A_RUN_ID = "dg25-s3a-e1-label-free-20260830-001"
S4A_OFFICIAL_RUN_ID = "dg25-s4a-e2-label-free-20260830-001"

HISTORICAL_READINESS_ROOT = Path("var/dg25/readiness") / S3_READINESS_RUN_ID
S3A_OUTPUT_ROOT = Path("var/dg25/s3a") / S3A_RUN_ID
S4A_READINESS_ROOT = Path("var/dg25/s4a-readiness")
S4A_OUTPUT_ROOT = Path("var/dg25/s4a")
REVIEW_ROOT = Path("var/dg25/reviews")

FIXED_INPUT_PATHS = {
    "historical_readiness_receipt": HISTORICAL_READINESS_ROOT / "receipt.json",
    "execution_delta_manifest": (
        HISTORICAL_READINESS_ROOT / "execution-delta-manifest.json"
    ),
    "e2_common_input": HISTORICAL_READINESS_ROOT / "e2-common-input.json",
    "all_arm_seal_protocol": (HISTORICAL_READINESS_ROOT / "all-arm-seal-protocol.json"),
    "cost_ledger_schema": HISTORICAL_READINESS_ROOT / "cost-ledger-schema.json",
    "historical_source_manifest": HISTORICAL_READINESS_ROOT / "source-manifest.json",
    "effect_scorer_contract": (
        HISTORICAL_READINESS_ROOT / "effect-scorer-contract.json"
    ),
    "e1_label_free_bundle": S3A_OUTPUT_ROOT / "e1-label-free-arm-outputs.json",
    "e1_all_arm_seal": S3A_OUTPUT_ROOT / "e1-all-arm-seal.json",
    "product_traces": (
        Path("var/dg24/s3/dg24-s3-product-trace-20260829-002")
        / "sealed-product-traces.json"
    ),
    "label_free_inputs": Path("var/dg11/paper/freeze/longmemeval-full-inputs.json"),
    "input_only_manifest": (
        Path("var/dg24/s0/dg24-s0-freeze-20260829-008")
        / "input-only-case-manifest-v0.1.json"
    ),
    "failure_index": Path("var/dg25/failure-index.jsonl"),
}

EXPECTED_IMMUTABLE_IDENTITIES = {
    "historical_readiness_receipt": (
        "d5628ffb571e82794344a059a50734467c6069b6614a84864ed8e77ef74e8ac8",
        4430,
    ),
    "e1_label_free_bundle": (
        "4f52a4837dc6b86edbd10e15a1fda80b3ad4e2e47485064981f0ad8a739d6e77",
        1691874,
    ),
    "e1_all_arm_seal": (
        "7e08857a33f1943dd3a84c6cd4f79dbc795533824efce592bb6709fbc02dfcf6",
        7801,
    ),
    "product_traces": (
        "463e1dae44e8f9239f037f9e5525fc168a4b7f161fe3c54125de49e4266f300d",
        15805002,
    ),
    "label_free_inputs": (
        "7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412",
        257601764,
    ),
    "input_only_manifest": (
        "aadff8787484eb8fb1c8b048134f2ce1225d756d611add75c48a4621de8894bc",
        4927,
    ),
}

HISTORICAL_ARTIFACT_KEYS = {
    "execution_delta_manifest": "execution_delta_manifest",
    "e2_common_input": "e2_common_input",
    "all_arm_seal_protocol": "all_arm_seal_protocol",
    "cost_ledger_schema": "cost_ledger_schema",
    "historical_source_manifest": "source_manifest",
    "effect_scorer_contract": "effect_scorer_contract",
}

S4A_SOURCE_PATHS = (
    "evals/dg14/contracts.py",
    "evals/dg25/arm_sealing.py",
    "evals/dg25/effect_scorer.py",
    "evals/dg25/routing_ablation.py",
    "evals/dg25/s4a_generator.py",
    "evals/dg25/s4a_readiness.py",
    "scripts/run_dg25_s4a.py",
    "scripts/run_dg25_s4a_quality.py",
    "scripts/run_dg25_s4a_readiness.py",
    "tests/test_dg25_s4a.py",
    "runtime/src/milai/application/evidence_semantics.py",
    "runtime/src/milai/application/memory_query.py",
    "runtime/src/milai/domain/requirement_state.py",
    "runtime/src/milai/domain/semantic_query.py",
    "runtime/src/milai/domain/temporal_proof.py",
)

READINESS_ARTIFACT_FILENAMES = {
    "execution_manifest": "execution-manifest.json",
    "source_manifest": "source-manifest.json",
    "stop_contract": "stop-contract.json",
    "validation_report": "readiness-validation-report.json",
}


def build_s4a_readiness_materials(
    *,
    root: Path,
    run_id: str,
    quality_receipt_path: Path,
) -> dict[str, dict[str, Any]]:
    """Build all pre-authorization materials without executing an E2 arm."""

    root = root.resolve()
    identities = {
        key: file_identity(root, root / path) for key, path in FIXED_INPUT_PATHS.items()
    }
    _validate_immutable_identities(identities)
    historical_receipt = read_json(
        root / FIXED_INPUT_PATHS["historical_readiness_receipt"]
    )
    _validate_historical_artifact_bindings(historical_receipt, identities)

    delta = read_json(root / FIXED_INPUT_PATHS["execution_delta_manifest"])
    common_input = read_json(root / FIXED_INPUT_PATHS["e2_common_input"])
    protocol = read_json(root / FIXED_INPUT_PATHS["all_arm_seal_protocol"])
    ledger_schema = read_json(root / FIXED_INPUT_PATHS["cost_ledger_schema"])
    historical_source_manifest = read_json(
        root / FIXED_INPUT_PATHS["historical_source_manifest"]
    )
    scorer_contract = read_json(root / FIXED_INPUT_PATHS["effect_scorer_contract"])
    e1_bundle = read_json(root / FIXED_INPUT_PATHS["e1_label_free_bundle"])
    e1_seal = read_json(root / FIXED_INPUT_PATHS["e1_all_arm_seal"])
    product_traces = read_json(root / FIXED_INPUT_PATHS["product_traces"])
    label_free_inputs = read_json(root / FIXED_INPUT_PATHS["label_free_inputs"])
    input_manifest = read_json(root / FIXED_INPUT_PATHS["input_only_manifest"])

    _validate_historical_contracts(
        delta=delta,
        common_input=common_input,
        protocol=protocol,
        ledger_schema=ledger_schema,
        historical_source_manifest=historical_source_manifest,
        scorer_contract=scorer_contract,
    )
    _validate_label_free_sources(
        product_traces=product_traces,
        label_free_inputs=label_free_inputs,
        input_manifest=input_manifest,
    )
    validate_and_order_e1_bundle(e1_bundle, e1_seal)

    source_manifest = build_s4a_source_manifest(root)
    quality_identity = file_identity(root, quality_receipt_path)
    quality_receipt = read_json(quality_receipt_path)
    _validate_quality_receipt(
        quality_receipt,
        quality_identity=quality_identity,
        source_manifest=source_manifest,
    )

    failure_snapshot = {
        **identities["failure_index"],
        "line_count": _nonempty_line_count(root / FIXED_INPUT_PATHS["failure_index"]),
    }
    common_bindings = derive_common_execution_bindings(
        delta=delta,
        common_input=common_input,
        protocol=protocol,
        ledger_schema=ledger_schema,
        historical_source_manifest=historical_source_manifest,
    )
    (
        combined_seal_readiness_bindings,
        combined_seal_readiness_binding_fields,
    ) = derive_combined_seal_readiness_bindings(
        protocol=protocol,
        scorer_contract=scorer_contract,
    )
    authorization_bindings = derive_authorization_bindings(
        run_id=run_id,
        identities=identities,
        delta=delta,
        common_input=common_input,
        scorer_contract=scorer_contract,
        e1_seal=e1_seal,
        label_free_inputs=label_free_inputs,
        source_manifest=source_manifest,
        quality_identity=quality_identity,
        failure_snapshot=failure_snapshot,
        combined_seal_readiness_bindings=combined_seal_readiness_bindings,
    )
    execution_material: dict[str, Any] = {
        "schema": "milai.dg25.s4a-execution-manifest.v0.1",
        "run_id": run_id,
        "status": "READY_PENDING_FRESH_INDEPENDENT_S4A_AUTHORIZATION",
        "historical_readiness_run_id": S3_READINESS_RUN_ID,
        "consumed_s3a_run_id": S3A_RUN_ID,
        "official_s4a_run_id": S4A_OFFICIAL_RUN_ID,
        "e2_arm_order": list(E2_ARM_ORDER),
        "e2_arm_configs": list(_mapping(delta.get("E2"), "E2 delta")["arm_configs"]),
        "e2_config_digest_map": dict(
            _mapping(delta.get("E2"), "E2 delta")["config_digest_map"]
        ),
        "common_execution_bindings": common_bindings,
        "combined_seal_readiness_binding_fields": (
            combined_seal_readiness_binding_fields
        ),
        "combined_seal_readiness_bindings": combined_seal_readiness_bindings,
        "combined_seal_readiness_bindings_digest": canonical_sha256(
            combined_seal_readiness_bindings
        ),
        "authorization_bindings": authorization_bindings,
        "fixed_input_identities": identities,
        "quality_receipt": quality_identity,
        "failure_index_snapshot": failure_snapshot,
        "source_manifest_digest": source_manifest["source_manifest_digest"],
        "boundaries": _execution_boundaries(),
    }
    execution_material["execution_manifest_digest"] = canonical_sha256(
        execution_material
    )

    stop_material: dict[str, Any] = {
        "schema": "milai.dg25.s4a-stop-contract.v0.1",
        "stage": "S4A_E2_LABEL_FREE",
        "official_s4a_run_id": S4A_OFFICIAL_RUN_ID,
        "expected_authorization_bindings": authorization_bindings,
        "expected_authorization_bindings_digest": canonical_sha256(
            authorization_bindings
        ),
        "combined_seal_readiness_binding_fields": (
            combined_seal_readiness_binding_fields
        ),
        "expected_combined_seal_readiness_bindings": (combined_seal_readiness_bindings),
        "expected_combined_seal_readiness_bindings_digest": canonical_sha256(
            combined_seal_readiness_bindings
        ),
        "pre_generation": {
            **_execution_boundaries(),
            "output_directory_exists": False,
            "e1_all_arm_seal_valid": True,
            "e2_arm_output_count": 0,
            "e2_all_arm_seal_present": False,
            "combined_all_arm_seal_present": False,
        },
        "post_generation": {
            **_execution_boundaries(),
            "e1_all_arm_seal_valid": True,
            "e2_arm_output_count": 5,
            "e2_arm_order_exact": True,
            "e2_output_digests_recomputed": True,
            "e2_execution_bindings_recomputed": True,
            "e2_all_arm_seal_recomputed": True,
            "combined_all_arm_seal_recomputed": True,
            "partial_duplicate_or_reordered_outputs": 0,
        },
    }
    stop_material["stop_contract_digest"] = canonical_sha256(stop_material)

    checks = {
        "immutable_input_identities_exact": True,
        "historical_readiness_artifacts_exact": True,
        "historical_e2_configs_exact": True,
        "e2_common_input_exact": True,
        "e1_bundle_and_seal_recomputed": True,
        "label_free_source_boundaries_pass": True,
        "current_source_manifest_complete": True,
        "generator_filesystem_and_scorer_isolation_pass": source_manifest[
            "source_scan"
        ]["generator_isolated"],
        "runner_scorer_and_registry_isolation_pass": source_manifest["source_scan"][
            "runner_isolated"
        ],
        "combined_seal_scorer_contract_compatible": True,
        "single_use_official_run_id_bound": True,
        "quality_receipt_exact_and_current": True,
        "official_e2_generation_executed": False,
        "combined_seal_created": False,
        "labels_or_registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "candidate_default_enabled": False,
    }
    if not all(value is True or value == 0 for value in checks.values()):
        raise ValueError("DG25_S4A_READINESS_CHECK_FAILED")
    validation_material: dict[str, Any] = {
        "schema": "milai.dg25.s4a-readiness-validation.v0.1",
        "status": "PASS_DG25_S4A_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION",
        "checks": checks,
        "authorization_bindings_digest": canonical_sha256(authorization_bindings),
        "combined_seal_readiness_bindings_digest": canonical_sha256(
            combined_seal_readiness_bindings
        ),
        "execution_manifest_digest": execution_material["execution_manifest_digest"],
        "stop_contract_digest": stop_material["stop_contract_digest"],
    }
    validation_material["validation_digest"] = canonical_sha256(validation_material)

    return {
        "execution_manifest": execution_material,
        "source_manifest": source_manifest,
        "stop_contract": stop_material,
        "validation_report": validation_material,
    }


def build_s4a_source_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    files = [file_identity(root, root / path) for path in S4A_SOURCE_PATHS]
    scan = _source_boundary_scan(root)
    material: dict[str, Any] = {
        "schema": "milai.dg25.s4a-source-manifest.v0.1",
        "fresh": True,
        "files": files,
        "source_set_digest": canonical_sha256(files),
        "source_scan": scan,
        "effect_scorer_source": next(
            item for item in files if item["path"] == "evals/dg25/effect_scorer.py"
        ),
    }
    material["source_manifest_digest"] = canonical_sha256(material)
    return material


def derive_common_execution_bindings(
    *,
    delta: Mapping[str, Any],
    common_input: Mapping[str, Any],
    protocol: Mapping[str, Any],
    ledger_schema: Mapping[str, Any],
    historical_source_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    e2 = _mapping(delta.get("E2"), "E2 delta")
    return {
        "execution_delta_manifest_digest": str(delta["manifest_digest"]),
        "all_arm_seal_protocol_digest": str(protocol["protocol_digest"]),
        "readiness_source_manifest_digest": str(
            historical_source_manifest["source_manifest_digest"]
        ),
        "case_order_digest": str(delta["case_order_digest"]),
        "config_set_digest": str(e2["config_set_digest"]),
        "input_binding_digest": str(common_input["common_input_digest"]),
        "caps_digest": str(e2["caps_digest"]),
        "cost_ledger_schema_digest": str(ledger_schema["cost_ledger_schema_digest"]),
        "final_k": 8,
    }


def derive_combined_seal_readiness_bindings(
    *,
    protocol: Mapping[str, Any],
    scorer_contract: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Resolve the frozen scorer-facing bindings without S4A authorization fields."""

    combined_schema = _mapping(
        protocol.get("combined_seal_schema"), "combined seal schema"
    )
    template = dict(
        _mapping(
            combined_schema.get("readiness_bindings"),
            "combined seal readiness bindings",
        )
    )
    contract = _mapping(scorer_contract.get("contract"), "scorer contract")
    raw_fields = contract.get("required_execution_bindings")
    if not isinstance(raw_fields, Sequence) or isinstance(raw_fields, (str, bytes)):
        raise TypeError("DG25_S4A_SCORER_BINDING_FIELDS_INVALID")
    fields = [str(item) for item in raw_fields]
    if (
        any(not isinstance(item, str) or not item for item in raw_fields)
        or len(fields) != 16
        or len(set(fields)) != len(fields)
        or set(template) != set(fields)
    ):
        raise ValueError("DG25_S4A_COMBINED_BINDING_SCHEMA_MISMATCH")
    if (
        combined_schema.get("schema") != "milai.dg25.e1-e2-all-arm-seal.v0.2"
        or template.get("all_arm_seal_protocol_digest")
        != "BOUND_TO_THIS_PROTOCOL_AFTER_SEAL"
    ):
        raise ValueError("DG25_S4A_COMBINED_BINDING_PROTOCOL_INVALID")

    bindings = dict(template)
    bindings["all_arm_seal_protocol_digest"] = protocol.get("protocol_digest")
    for field, value in bindings.items():
        if field == "all_arm_seal_protocol_digest":
            continue
        if field == "final_k":
            if value != 8:
                raise ValueError("DG25_S4A_COMBINED_BINDING_FINAL_K_DRIFT")
            continue
        if protocol.get(field) != value:
            raise ValueError(f"DG25_S4A_COMBINED_BINDING_VALUE_DRIFT:{field}")
    return bindings, fields


def derive_authorization_bindings(
    *,
    run_id: str,
    identities: Mapping[str, Mapping[str, Any]],
    delta: Mapping[str, Any],
    common_input: Mapping[str, Any],
    scorer_contract: Mapping[str, Any],
    e1_seal: Mapping[str, Any],
    label_free_inputs: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    quality_identity: Mapping[str, Any],
    failure_snapshot: Mapping[str, Any],
    combined_seal_readiness_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    source_files = {
        str(item["path"]): item
        for item in _mapping_sequence(source_manifest.get("files"), "source files")
    }
    e2 = _mapping(delta.get("E2"), "E2 delta")
    return {
        "readiness_run_id": run_id,
        "official_s4a_run_id": S4A_OFFICIAL_RUN_ID,
        "historical_readiness_receipt_sha256": identities[
            "historical_readiness_receipt"
        ]["sha256"],
        "execution_delta_manifest_digest": delta["manifest_digest"],
        "e2_common_input_digest": common_input["common_input_digest"],
        "e2_config_set_digest": e2["config_set_digest"],
        "e2_caps_digest": e2["caps_digest"],
        "e1_bundle_sha256": identities["e1_label_free_bundle"]["sha256"],
        "e1_all_arm_seal_sha256": identities["e1_all_arm_seal"]["sha256"],
        "e1_all_arm_seal_digest": e1_seal["seal_digest"],
        "product_trace_sha256": identities["product_traces"]["sha256"],
        "label_free_input_sha256": identities["label_free_inputs"]["sha256"],
        "label_free_dataset_sha256": label_free_inputs["dataset_sha256"],
        "input_only_manifest_sha256": identities["input_only_manifest"]["sha256"],
        "effect_scorer_contract_digest": _mapping(
            scorer_contract.get("contract"), "scorer contract"
        )["contract_digest"],
        "effect_scorer_source_sha256": source_files["evals/dg25/effect_scorer.py"][
            "sha256"
        ],
        "s4a_source_manifest_digest": source_manifest["source_manifest_digest"],
        "s4a_generator_source_sha256": source_files["evals/dg25/s4a_generator.py"][
            "sha256"
        ],
        "s4a_sealer_source_sha256": source_files["evals/dg25/arm_sealing.py"]["sha256"],
        "s4a_runner_source_sha256": source_files["scripts/run_dg25_s4a.py"]["sha256"],
        "quality_receipt_sha256": quality_identity["sha256"],
        "failure_index_sha256": failure_snapshot["sha256"],
        "failure_index_line_count": failure_snapshot["line_count"],
        "combined_seal_readiness_bindings_digest": canonical_sha256(
            dict(combined_seal_readiness_bindings)
        ),
        "expected_e2_arm_count": 5,
        "expected_combined_arm_count": 16,
    }


def authorization_request(
    *,
    readiness_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    material: dict[str, Any] = {
        "schema": "milai.dg25.s4a-authorization-request.v0.1",
        "scope": "S4A_E2_LABEL_FREE_ALL_5_ARMS_E2_AND_COMBINED_SEALS",
        "readiness_bindings": dict(readiness_bindings),
        "readiness_bindings_digest": canonical_sha256(dict(readiness_bindings)),
        **_authorization_boundaries(),
        "authorized_attempts_requested": 1,
    }
    material["request_digest"] = canonical_sha256(material)
    return material


def validate_readiness_receipt(
    *,
    root: Path,
    readiness_dir: Path,
    receipt: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if (
        receipt.get("schema") != "milai.dg25.s4a-readiness-receipt.v0.1"
        or receipt.get("status")
        != "PASS_DG25_S4A_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION"
    ):
        raise ValueError("DG25_S4A_READINESS_RECEIPT_INVALID")
    artifacts = _mapping(receipt.get("artifacts"), "readiness artifacts")
    if set(artifacts) != set(READINESS_ARTIFACT_FILENAMES):
        raise ValueError("DG25_S4A_READINESS_ARTIFACT_SET_MISMATCH")
    observed: dict[str, dict[str, Any]] = {}
    for key, filename in READINESS_ARTIFACT_FILENAMES.items():
        path = readiness_dir / filename
        identity = file_identity(root, path)
        if dict(_mapping(artifacts.get(key), key)) != identity:
            raise ValueError("DG25_S4A_READINESS_ARTIFACT_IDENTITY_DRIFT")
        observed[key] = identity
    return observed


def file_identity(root: Path, path: Path) -> dict[str, Any]:
    root = root.resolve()
    absolute = path if path.is_absolute() else root / path
    if absolute.is_symlink() or not absolute.is_file():
        raise ValueError(f"DG25_S4A_IDENTITY_NOT_REGULAR_FILE:{absolute}")
    resolved = absolute.resolve(strict=True)
    try:
        logical = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("DG25_S4A_IDENTITY_OUTSIDE_WORKSPACE") from exc
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": logical,
        "sha256": digest.hexdigest(),
        "size": resolved.stat().st_size,
    }


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _validate_immutable_identities(
    identities: Mapping[str, Mapping[str, Any]],
) -> None:
    for key, (sha256, size) in EXPECTED_IMMUTABLE_IDENTITIES.items():
        identity = identities[key]
        if identity.get("sha256") != sha256 or identity.get("size") != size:
            raise ValueError(f"DG25_S4A_IMMUTABLE_INPUT_DRIFT:{key}")


def _validate_historical_artifact_bindings(
    receipt: Mapping[str, Any],
    identities: Mapping[str, Mapping[str, Any]],
) -> None:
    if (
        receipt.get("run_id") != S3_READINESS_RUN_ID
        or receipt.get("status")
        != "PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION"
    ):
        raise ValueError("DG25_S4A_HISTORICAL_READINESS_RECEIPT_INVALID")
    artifacts = _mapping(receipt.get("artifacts"), "historical artifacts")
    for identity_key, artifact_key in HISTORICAL_ARTIFACT_KEYS.items():
        if dict(_mapping(artifacts.get(artifact_key), artifact_key)) != dict(
            identities[identity_key]
        ):
            raise ValueError(
                f"DG25_S4A_HISTORICAL_ARTIFACT_IDENTITY_DRIFT:{artifact_key}"
            )


def _validate_historical_contracts(
    *,
    delta: Mapping[str, Any],
    common_input: Mapping[str, Any],
    protocol: Mapping[str, Any],
    ledger_schema: Mapping[str, Any],
    historical_source_manifest: Mapping[str, Any],
    scorer_contract: Mapping[str, Any],
) -> None:
    for value, digest_key, code in (
        (delta, "manifest_digest", "EXECUTION_DELTA"),
        (common_input, "common_input_digest", "COMMON_INPUT"),
        (protocol, "protocol_digest", "SEAL_PROTOCOL"),
        (ledger_schema, "cost_ledger_schema_digest", "COST_LEDGER"),
        (historical_source_manifest, "source_manifest_digest", "SOURCE_MANIFEST"),
    ):
        material = dict(value)
        observed = material.pop(digest_key, None)
        if observed != canonical_sha256(material):
            raise ValueError(f"DG25_S4A_{code}_DIGEST_MISMATCH")
    contract = dict(_mapping(scorer_contract.get("contract"), "scorer contract"))
    observed_contract_digest = contract.pop("contract_digest", None)
    scorer_seal = dict(scorer_contract)
    observed_seal_digest = scorer_seal.pop("scorer_seal_digest", None)
    if (
        observed_contract_digest != canonical_sha256(contract)
        or observed_seal_digest != canonical_sha256(scorer_seal)
        or scorer_contract.get("registry_content_loaded") is not False
        or scorer_contract.get("effect_scoring_executed") is not False
    ):
        raise ValueError("DG25_S4A_SCORER_CONTRACT_DIGEST_MISMATCH")
    e2 = _mapping(delta.get("E2"), "E2 delta")
    configs = [
        E2ArmConfigV01.model_validate(item)
        for item in _mapping_sequence(e2.get("arm_configs"), "E2 configs")
    ]
    if (
        [item.arm_id for item in configs] != list(E2_ARM_ORDER)
        or e2.get("arm_order") != list(E2_ARM_ORDER)
        or e2.get("config_digest_map")
        != {item.arm_id: item.config_digest for item in configs}
        or e2.get("config_set_digest")
        != canonical_sha256({item.arm_id: item.config_digest for item in configs})
        or any(
            item.common_input_digest != common_input.get("common_input_digest")
            for item in configs
        )
    ):
        raise ValueError("DG25_S4A_E2_CONFIG_CONTRACT_DRIFT")
    caps = _mapping(e2.get("caps"), "E2 caps")
    if (
        caps
        != {"range_scan_max_rows": 2000, "raw_row_count": 973, "requirement_count": 2}
        or e2.get("caps_digest") != canonical_sha256(caps)
        or common_input.get("requirement_count") != 2
        or common_input.get("raw_row_count") != 973
    ):
        raise ValueError("DG25_S4A_E2_DENOMINATOR_OR_CAP_DRIFT")


def _validate_label_free_sources(
    *,
    product_traces: Mapping[str, Any],
    label_free_inputs: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
) -> None:
    execution_counts = _mapping(
        product_traces.get("execution_counts"), "product execution counts"
    )
    forbidden_absent = _mapping(
        input_manifest.get("forbidden_fields_absent"), "manifest forbidden fields"
    )
    if (
        product_traces.get("schema")
        != "milai.dg24.sealed-product-trace-collection.v0.1"
        or product_traces.get("registry_content_loaded") is not False
        or product_traces.get("formal_holdout_consumed") is not False
        or product_traces.get("candidate_default") is not False
        or execution_counts.get("reader_calls") != 0
        or execution_counts.get("generative_provider_calls") != 0
        or execution_counts.get("automatic_retries") != 0
        or label_free_inputs.get("schema") != "milai.dg11.paper-longmemeval-inputs.v1"
        or label_free_inputs.get("partition") != "LME-FULL-500-CHARACTERIZATION"
        or label_free_inputs.get("forbidden_label_fields_present") is not False
        or label_free_inputs.get("label_fields_accessed") is not False
        or label_free_inputs.get("paper_labels_opened") is not False
        or input_manifest.get("schema_version") != "input-only-case-manifest-v0.1"
        or not forbidden_absent
        or any(value is not True for value in forbidden_absent.values())
    ):
        raise ValueError("DG25_S4A_LABEL_FREE_SOURCE_BOUNDARY_INVALID")


def validate_and_order_e1_bundle(
    bundle: Mapping[str, Any],
    seal: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    boundaries = {
        "labels_loaded": False,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "automatic_retries": 0,
    }
    if (
        bundle.get("schema") != "milai.dg25.e1-label-free-all-arm-bundle.v0.1"
        or bundle.get("arm_order") != list(E1_ARM_ORDER)
        or any(bundle.get(key) != value for key, value in boundaries.items())
    ):
        raise ValueError("DG25_S4A_E1_BUNDLE_BOUNDARY_INVALID")
    raw_outputs = _mapping(bundle.get("arm_outputs"), "E1 outputs")
    if set(raw_outputs) != set(E1_ARM_ORDER):
        raise ValueError("DG25_S4A_E1_OUTPUT_SET_DRIFT")
    outputs = {arm_id: _mapping(raw_outputs[arm_id], arm_id) for arm_id in E1_ARM_ORDER}
    first_binding = dict(
        _mapping(outputs[E1_ARM_ORDER[0]]["execution_binding"], "binding")
    )
    for field in (
        "schema",
        "block",
        "arm_id",
        "arm_config_digest",
        "block_input_identity",
        "execution_binding_digest",
    ):
        first_binding.pop(field)
    common_bindings = first_binding
    config_digests = {
        arm_id: str(outputs[arm_id]["arm_config_digest"]) for arm_id in E1_ARM_ORDER
    }
    block_inputs = {
        arm_id: dict(
            _mapping(
                _mapping(outputs[arm_id]["execution_binding"], "binding").get(
                    "block_input_identity"
                ),
                "block input",
            )
        )
        for arm_id in E1_ARM_ORDER
    }
    for arm_id in E1_ARM_ORDER:
        validate_label_free_arm_output(
            output=outputs[arm_id],
            block="E1",
            arm_id=arm_id,
            arm_config_digest=config_digests[arm_id],
            common_execution_bindings=common_bindings,
            block_input_identity=block_inputs[arm_id],
        )
    validate_block_all_arm_seal(
        seal=seal,
        block="E1",
        arm_outputs=outputs,
        arm_order=E1_ARM_ORDER,
        config_digests=config_digests,
        common_execution_bindings=common_bindings,
        block_input_identities=block_inputs,
    )
    return outputs


def _validate_quality_receipt(
    receipt: Mapping[str, Any],
    *,
    quality_identity: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
) -> None:
    if (
        receipt.get("schema") != "milai.dg25.s4a-quality-receipt.v0.1"
        or receipt.get("status") != "PASS_DG25_S4A_QUALITY"
        or receipt.get("automatic_retries") != 0
        or receipt.get("source_files_current_after_gates") is not True
        or receipt.get("source_set_digest") != source_manifest.get("source_set_digest")
        or receipt.get("source_files") != source_manifest.get("files")
        or quality_identity.get("sha256") is None
    ):
        raise ValueError("DG25_S4A_QUALITY_RECEIPT_INVALID_OR_STALE")
    gates = _mapping_sequence(receipt.get("gates"), "quality gates")
    if not gates or any(item.get("exit_code") != 0 for item in gates):
        raise ValueError("DG25_S4A_QUALITY_GATE_NOT_PASS")


def _source_boundary_scan(root: Path) -> dict[str, Any]:
    generator = root / "evals/dg25/s4a_generator.py"
    runner = root / "scripts/run_dg25_s4a.py"
    generator_modules, generator_calls = _ast_surface(generator)
    runner_modules, _runner_calls = _ast_surface(runner)
    forbidden_generator_modules = {
        "evals.dg25.effect_scorer",
        "evals.dg24.gold_registry",
        "evals.dg24.proof_registry",
        "pathlib",
        "os",
        "subprocess",
    }
    forbidden_runner_modules = {
        "evals.dg25.effect_scorer",
        "evals.dg24.gold_registry",
        "evals.dg24.proof_registry",
    }
    generator_isolated = not forbidden_generator_modules.intersection(
        generator_modules
    ) and not {"open", "eval", "exec", "__import__"}.intersection(generator_calls)
    runner_isolated = not forbidden_runner_modules.intersection(runner_modules)
    if not generator_isolated or not runner_isolated:
        raise ValueError("DG25_S4A_SOURCE_ISOLATION_FAILED")
    return {
        "generator_import_modules": sorted(generator_modules),
        "generator_direct_call_names": sorted(generator_calls),
        "generator_isolated": generator_isolated,
        "runner_import_modules": sorted(runner_modules),
        "runner_isolated": runner_isolated,
        "scorer_registry_import_count": 0,
    }


def _ast_surface(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    modules.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    return modules, calls


def _execution_boundaries() -> dict[str, Any]:
    return {
        "labels_loaded": False,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
    }


def _authorization_boundaries() -> dict[str, Any]:
    return {
        "labels_authorized": False,
        "registry_content_authorized": False,
        "scoring_authorized": False,
        "s4b_authorized": False,
        "e3_authorized": False,
        "reader_model_provider_controller_calls_authorized": 0,
        "formal_holdout_authorized": False,
        "candidate_default_authorized": False,
        "automatic_retries": 0,
    }


def _nonempty_line_count(path: Path) -> int:
    return sum(
        bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines()
    )


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


__all__ = [
    "FIXED_INPUT_PATHS",
    "READINESS_ARTIFACT_FILENAMES",
    "REVIEW_ROOT",
    "S4A_OFFICIAL_RUN_ID",
    "S4A_OUTPUT_ROOT",
    "S4A_READINESS_ROOT",
    "S4A_SOURCE_PATHS",
    "authorization_request",
    "build_s4a_readiness_materials",
    "build_s4a_source_manifest",
    "derive_combined_seal_readiness_bindings",
    "derive_common_execution_bindings",
    "file_identity",
    "read_json",
    "validate_and_order_e1_bundle",
    "validate_readiness_receipt",
]

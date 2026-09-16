"""Build DG-25 S4B scoring readiness without opening scorer registries."""

from __future__ import annotations

import ast
import hashlib
import json
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from evals.dg25.arm_sealing import (
    E1_ARM_ORDER,
    E2_ARM_ORDER,
    validate_block_all_arm_seal,
    validate_combined_all_arm_seal,
    validate_label_free_arm_output,
)
from evals.dg25.effect_scorer import canonical_sha256, scorer_contract
from evals.dg25.s4b_scoring import S4B_OFFICIAL_RUN_ID

S4B_READINESS_ROOT = Path("var/dg25/s4b-readiness")
S4B_OUTPUT_ROOT = Path("var/dg25/s4b")
S4B_REVIEW_ROOT = Path("var/dg25/reviews")

FIXED_INPUT_PATHS = {
    "effect_scorer_contract": Path(
        "var/dg25/readiness/dg25-s3-readiness-20260830-011/"
        "effect-scorer-contract.json"
    ),
    "bound_stop_contract": Path(
        "var/dg25/readiness/dg25-s3-readiness-20260830-011/"
        "stop-evaluation-contract.json"
    ),
    "e1_bundle": Path(
        "var/dg25/s3a/dg25-s3a-e1-label-free-20260830-001/"
        "e1-label-free-arm-outputs.json"
    ),
    "e1_seal": Path(
        "var/dg25/s3a/dg25-s3a-e1-label-free-20260830-001/"
        "e1-all-arm-seal.json"
    ),
    "e2_bundle": Path(
        "var/dg25/s4a/dg25-s4a-e2-label-free-20260830-001/"
        "e2-label-free-arm-outputs.json"
    ),
    "e2_seal": Path(
        "var/dg25/s4a/dg25-s4a-e2-label-free-20260830-001/"
        "e2-all-arm-seal.json"
    ),
    "combined_seal": Path(
        "var/dg25/s4a/dg25-s4a-e2-label-free-20260830-001/"
        "e1-e2-all-arm-seal.json"
    ),
    "s4a_generation_receipt": Path(
        "var/dg25/s4a/dg25-s4a-e2-label-free-20260830-001/"
        "generation-receipt.json"
    ),
    "s4a_readiness_receipt": Path(
        "var/dg25/s4a-readiness/dg25-s4a-readiness-20260830-006/receipt.json"
    ),
    "s4a_execution_manifest": Path(
        "var/dg25/s4a-readiness/dg25-s4a-readiness-20260830-006/"
        "execution-manifest.json"
    ),
    "s4a_independent_review": Path(
        "var/dg25/reviews/dg25-s4a-independent-review-20260830-004/review.json"
    ),
    "failure_index": Path("var/dg25/failure-index.jsonl"),
}

EXPECTED_FIXED_IDENTITIES = {
    "effect_scorer_contract": (
        "944dce48205e3103a6f34e7e7183810648b811233e0515885aed8dcbd54584f7",
        6307,
    ),
    "bound_stop_contract": (
        "b6e4a18a033b659ee8a0949d8f4cf0565f9869470024c652bd339eb14b5817c6",
        7970,
    ),
    "e1_bundle": (
        "4f52a4837dc6b86edbd10e15a1fda80b3ad4e2e47485064981f0ad8a739d6e77",
        1691874,
    ),
    "e1_seal": (
        "7e08857a33f1943dd3a84c6cd4f79dbc795533824efce592bb6709fbc02dfcf6",
        7801,
    ),
    "e2_bundle": (
        "82ef53318d2571d8c9c2df250ae99bf5268c0c7a26e5402a0d41e6fbb1f385ce",
        152285,
    ),
    "e2_seal": (
        "dd527f9bbee3c506d39e2f17d120c06a154dfc7f9943270b24d06cd05d21d736",
        5878,
    ),
    "combined_seal": (
        "d2d03ab60e1a76798c60742311b17eef3907f9a24847b0e9340005c8a648bb30",
        6981,
    ),
    "s4a_generation_receipt": (
        "c72d945140fde2bd5736d7cbe1b651fad62d2928356bada4959d397f2802b779",
        1984,
    ),
    "s4a_readiness_receipt": (
        "f948a6167aa25d2420b2335d538600e2f769e47c90b9222a6990c11d81a7afe0",
        6160,
    ),
    "s4a_execution_manifest": (
        "e82b2f7ed994d238a0ba87ab125d9a50a18890d76d75728101a8957c9f28a44d",
        23631,
    ),
    "s4a_independent_review": (
        "ba95c9adb2bf7e9188e3b104fa7579edbfd17f7d3a16988ec6e10498935c0858",
        6077,
    ),
}

HISTORICAL_SCORER_SHA256 = (
    "ee8929e4feb95246a258d49555b7dd8b8ac83872576e7af2f678218d1303a929"
)
HISTORICAL_SCORER_SIZE = 29966
CURRENT_SCORER_SHA256 = (
    "4b429b4fa1b20a2720acb03bd3bda56d21689744539581815a5a32c8d8d3dae4"
)
CURRENT_SCORER_SIZE = 30493
SCORER_CONTRACT_DIGEST = (
    "58e1c1c4dcde34407d110212d358085d24b551caac951f98fe905d1d0b4693d9"
)

S4B_SOURCE_PATHS = (
    "evals/dg25/arm_sealing.py",
    "evals/dg25/effect_scorer.py",
    "evals/dg25/s4b_readiness.py",
    "evals/dg25/s4b_scoring.py",
    "evals/dg25/stop_gate.py",
    "scripts/run_dg25_s4b.py",
    "scripts/run_dg25_s4b_quality.py",
    "scripts/run_dg25_s4b_readiness.py",
    "tests/test_dg25_s4b.py",
)

READINESS_ARTIFACT_FILENAMES = {
    "scorer_source_amendment": "scorer-source-compatibility-amendment.json",
    "execution_manifest": "execution-manifest.json",
    "source_manifest": "source-manifest.json",
    "stop_contract": "stop-contract.json",
    "validation_report": "readiness-validation-report.json",
}

_UNQUOTE_IMPORT = "from urllib.parse import unquote\n"
_LONGMEM_PATTERN = (
    "_LONGMEM_SOURCE_REF = re.compile(\n"
    '    r"^longmemeval://case/([^/]+)/session/(\\d+)/([^/]+)/turn/(\\d+)(?:\\?|$)"\n'
    ")\n"
)
_LONGMEM_FUNCTION_PREFIX = (
    "    longmem = _LONGMEM_SOURCE_REF.match(value)\n"
    "    if longmem is not None:\n"
    "        case_id, session_ordinal, session_id, turn_ordinal = longmem.groups()\n"
    "        return (\n"
    '            f"{unquote(case_id)}:s{session_ordinal}:"\n'
    '            f"{unquote(session_id)}:t{turn_ordinal}"\n'
    "        )\n"
    '    if value.startswith("longmemeval://"):\n'
    '        raise ValueError("DG25_SOURCE_REF_INVALID")\n'
)


def build_s4b_readiness_materials(
    *,
    root: Path,
    run_id: str,
    quality_receipt_path: Path,
) -> dict[str, dict[str, Any]]:
    """Build a pre-label scoring package and its source-binding amendment."""

    root = root.resolve()
    identities = {
        key: file_identity(root, root / path) for key, path in FIXED_INPUT_PATHS.items()
    }
    _validate_fixed_identities(identities)

    scorer_envelope = read_json(root / FIXED_INPUT_PATHS["effect_scorer_contract"])
    bound_stop = read_json(root / FIXED_INPUT_PATHS["bound_stop_contract"])
    e1_bundle = read_json(root / FIXED_INPUT_PATHS["e1_bundle"])
    e1_seal = read_json(root / FIXED_INPUT_PATHS["e1_seal"])
    e2_bundle = read_json(root / FIXED_INPUT_PATHS["e2_bundle"])
    e2_seal = read_json(root / FIXED_INPUT_PATHS["e2_seal"])
    combined_seal = read_json(root / FIXED_INPUT_PATHS["combined_seal"])
    s4a_execution = read_json(root / FIXED_INPUT_PATHS["s4a_execution_manifest"])
    s4a_review = read_json(root / FIXED_INPUT_PATHS["s4a_independent_review"])

    _validate_scorer_and_stop_contracts(scorer_envelope, bound_stop)
    e1_outputs = validate_label_free_bundle(
        bundle=e1_bundle,
        seal=e1_seal,
        block="E1",
        arm_order=E1_ARM_ORDER,
    )
    e2_outputs = validate_label_free_bundle(
        bundle=e2_bundle,
        seal=e2_seal,
        block="E2",
        arm_order=E2_ARM_ORDER,
    )
    all_outputs = {**e1_outputs, **e2_outputs}
    readiness_bindings = _mapping(
        combined_seal.get("readiness_bindings"), "combined readiness bindings"
    )
    validate_combined_all_arm_seal(
        seal=combined_seal,
        e1_seal=e1_seal,
        e2_seal=e2_seal,
        arm_outputs=all_outputs,
        readiness_bindings=readiness_bindings,
    )

    amendment = build_scorer_source_amendment(
        root=root,
        combined_seal=combined_seal,
        scorer_envelope=scorer_envelope,
        s4a_execution=s4a_execution,
        s4a_review=s4a_review,
        identities=identities,
    )
    source_manifest = build_s4b_source_manifest(root)
    quality_identity = file_identity(root, quality_receipt_path)
    quality_receipt = read_json(quality_receipt_path)
    _validate_quality_receipt(
        quality_receipt,
        quality_identity=quality_identity,
        source_manifest=source_manifest,
    )

    registry_references = _registry_references(scorer_envelope)
    registry_observations = {
        key: observe_registry_without_opening(root, reference)
        for key, reference in registry_references.items()
    }
    failure_snapshot = {
        **identities["failure_index"],
        "line_count": _nonempty_line_count(root / FIXED_INPUT_PATHS["failure_index"]),
    }
    authorization_bindings = build_authorization_bindings(
        run_id=run_id,
        identities=identities,
        combined_seal=combined_seal,
        amendment=amendment,
        source_manifest=source_manifest,
        quality_identity=quality_identity,
        failure_snapshot=failure_snapshot,
        registry_references=registry_references,
        bound_stop=bound_stop,
    )
    request = authorization_request(authorization_bindings)

    execution: dict[str, Any] = {
        "schema": "milai.dg25.s4b-execution-manifest.v0.1",
        "run_id": run_id,
        "official_s4b_run_id": S4B_OFFICIAL_RUN_ID,
        "status": "READY_PENDING_FRESH_INDEPENDENT_SCORING_AUTHORIZATION",
        "fixed_input_identities": identities,
        "registry_identity_references": registry_references,
        "registry_pre_authorization_observations": registry_observations,
        "combined_seal_digest": combined_seal["seal_digest"],
        "combined_seal_readiness_bindings": dict(readiness_bindings),
        "combined_seal_readiness_bindings_digest": combined_seal[
            "readiness_bindings_digest"
        ],
        "scorer_source_amendment_digest": amendment["amendment_digest"],
        "source_manifest_digest": source_manifest["source_manifest_digest"],
        "quality_receipt": quality_identity,
        "failure_index_snapshot": failure_snapshot,
        "authorization_bindings": authorization_bindings,
        "authorization_request_digest": request["request_digest"],
        "boundaries": _pre_authorization_boundaries(),
    }
    execution["execution_manifest_digest"] = canonical_sha256(execution)

    base_gate_bindings = {
        **dict(readiness_bindings),
        "e1_all_arm_seal_digest": e1_seal["seal_digest"],
        "e2_all_arm_seal_digest": e2_seal["seal_digest"],
        "combined_all_arm_seal_digest": combined_seal["seal_digest"],
        "independent_scoring_authorization_digest": "PENDING_FRESH_REVIEW",
    }
    stop_contract: dict[str, Any] = {
        "schema": "milai.dg25.s4b-stop-contract.v0.1",
        "official_s4b_run_id": S4B_OFFICIAL_RUN_ID,
        "base_score_gate_bindings": base_gate_bindings,
        "effective_scorer_source": amendment["effective_scorer_source"],
        "scorer_source_amendment_digest": amendment["amendment_digest"],
        "registry_identity_references": registry_references,
        "sequence": [
            "VALIDATE_READINESS_AND_FRESH_AUTHORIZATION",
            "PASS_PRE_SCORE_GATE_WITH_REGISTRIES_UNOPENED",
            "VERIFY_AND_OPEN_TWO_AUTHORIZED_REGISTRIES_ONCE",
            "CALL_FROZEN_EFFECT_SCORER_ONCE",
            "PROJECT_PREREGISTERED_REPORTS",
            "PASS_OR_STOP_POST_SCORE_GATE",
        ],
        "expected_output_files": [
            "joint-score.json",
            "routing-selection-ablation-report.json",
            "component-unique-contribution-report.json",
            "rule-leave-one-out-report.json",
            "temporal-ablation-report.json",
            "final-minimal-policy.json",
            "pre-score-stop-gate.json",
            "post-score-stop-gate.json",
            "receipt.json",
        ],
        "authorized_score_executions": 1,
        "automatic_retries": 0,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_authorized": False,
        "candidate_default": False,
    }
    stop_contract["stop_contract_digest"] = canonical_sha256(stop_contract)

    checks = {
        "fixed_input_identities_exact": True,
        "e1_bundle_and_seal_recomputed": True,
        "e2_bundle_and_seal_recomputed": True,
        "combined_seal_recomputed": True,
        "scorer_contract_digest_exact": True,
        "historical_scorer_source_reconstructed_exact": True,
        "current_scorer_matches_s4a_authorization": True,
        "scorer_delta_limited_to_longmem_canonicalization": True,
        "registry_paths_regular_size_exact_content_unopened": all(
            item["regular_file"] is True
            and item["size_matches_expected"] is True
            and item["content_opened"] is False
            for item in registry_observations.values()
        ),
        "current_source_manifest_complete": True,
        "source_boundary_scan_pass": source_manifest["source_scan"]["passed"],
        "quality_receipt_exact_and_current": True,
        "labels_or_registry_content_loaded": False,
        "effect_scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "candidate_default_enabled": False,
        "automatic_retries": 0,
    }
    zero_checks = {
        "reader_model_provider_controller_calls",
        "automatic_retries",
    }
    false_checks = {
        "labels_or_registry_content_loaded",
        "effect_scoring_executed",
        "formal_holdout_consumed",
        "candidate_default_enabled",
    }
    true_checks = set(checks) - zero_checks - false_checks
    if (
        any(checks[key] is not True for key in true_checks)
        or any(checks[key] is not False for key in false_checks)
        or any(checks[key] != 0 for key in zero_checks)
    ):
        raise ValueError("DG25_S4B_READINESS_CHECK_FAILED")
    validation: dict[str, Any] = {
        "schema": "milai.dg25.s4b-readiness-validation.v0.1",
        "status": (
            "PASS_DG25_S4B_READINESS_PENDING_FRESH_INDEPENDENT_SCORING_AUTHORIZATION"
        ),
        "checks": checks,
        "authorization_bindings_digest": canonical_sha256(authorization_bindings),
        "authorization_request_digest": request["request_digest"],
        "scorer_source_amendment_digest": amendment["amendment_digest"],
        "execution_manifest_digest": execution["execution_manifest_digest"],
        "stop_contract_digest": stop_contract["stop_contract_digest"],
    }
    validation["validation_digest"] = canonical_sha256(validation)
    return {
        "scorer_source_amendment": amendment,
        "execution_manifest": execution,
        "source_manifest": source_manifest,
        "stop_contract": stop_contract,
        "validation_report": validation,
    }


def build_scorer_source_amendment(
    *,
    root: Path,
    combined_seal: Mapping[str, Any],
    scorer_envelope: Mapping[str, Any],
    s4a_execution: Mapping[str, Any],
    s4a_review: Mapping[str, Any],
    identities: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Prove the pre-fix scorer can be reconstructed by one exact allowed delta."""

    scorer_path = root / "evals/dg25/effect_scorer.py"
    current = scorer_path.read_text(encoding="utf-8")
    current_bytes = current.encode("utf-8")
    if (
        hashlib.sha256(current_bytes).hexdigest() != CURRENT_SCORER_SHA256
        or len(current_bytes) != CURRENT_SCORER_SIZE
    ):
        raise ValueError("DG25_S4B_CURRENT_SCORER_SOURCE_DRIFT")
    historical = _reconstruct_historical_scorer(current)
    historical_bytes = historical.encode("utf-8")
    if (
        hashlib.sha256(historical_bytes).hexdigest() != HISTORICAL_SCORER_SHA256
        or len(historical_bytes) != HISTORICAL_SCORER_SIZE
    ):
        raise ValueError("DG25_S4B_HISTORICAL_SCORER_RECONSTRUCTION_MISMATCH")
    if _unaffected_ast(current) != _unaffected_ast(historical):
        raise ValueError("DG25_S4B_SCORER_DELTA_OUTSIDE_ALLOWLIST")

    sealed_bindings = _mapping(
        combined_seal.get("readiness_bindings"), "sealed readiness bindings"
    )
    s4a_authorization = _mapping(
        s4a_execution.get("authorization_bindings"), "S4A authorization bindings"
    )
    review_authorization = _mapping(s4a_review.get("authorization"), "S4A review auth")
    review_bindings = _mapping(
        review_authorization.get("readiness_bindings"), "S4A review bindings"
    )
    envelope_contract = _mapping(scorer_envelope.get("contract"), "scorer contract")
    live_contract = scorer_contract()
    if (
        sealed_bindings.get("effect_scorer_source_sha256")
        != HISTORICAL_SCORER_SHA256
        or s4a_authorization.get("effect_scorer_source_sha256")
        != CURRENT_SCORER_SHA256
        or review_bindings.get("effect_scorer_source_sha256")
        != CURRENT_SCORER_SHA256
        or envelope_contract.get("contract_digest") != SCORER_CONTRACT_DIGEST
        or live_contract.get("contract_digest") != SCORER_CONTRACT_DIGEST
        or sealed_bindings.get("effect_scorer_contract_digest")
        != SCORER_CONTRACT_DIGEST
    ):
        raise ValueError("DG25_S4B_SCORER_SOURCE_OR_CONTRACT_BINDING_INVALID")

    material: dict[str, Any] = {
        "schema": "milai.dg25.scorer-source-compatibility-amendment.v0.1",
        "status": "VALID_LABEL_FREE_SCORER_SOURCE_BINDING_AMENDMENT",
        "base_combined_seal": identities["combined_seal"],
        "base_combined_seal_digest": combined_seal["seal_digest"],
        "base_scorer_source": {
            "path": "evals/dg25/effect_scorer.py",
            "sha256": HISTORICAL_SCORER_SHA256,
            "size": HISTORICAL_SCORER_SIZE,
            "reconstructed_from_effective_source": True,
        },
        "effective_scorer_source": {
            "path": "evals/dg25/effect_scorer.py",
            "sha256": CURRENT_SCORER_SHA256,
            "size": CURRENT_SCORER_SIZE,
        },
        "unchanged_scorer_contract_digest": SCORER_CONTRACT_DIGEST,
        "allowed_delta": {
            "purpose": "CANONICALIZE_LONGMEM_SOURCE_REFS_TO_FROZEN_REGISTRY_FORM",
            "added_import": "urllib.parse.unquote",
            "added_pattern": "_LONGMEM_SOURCE_REF",
            "modified_function": "_canonical_source_ref",
            "other_top_level_ast_delta_count": 0,
            "runtime_repository_reader_model_provider_controller_delta": 0,
        },
        "s4a_generation_authorization_binding": {
            "review": identities["s4a_independent_review"],
            "authorization_digest": review_authorization["authorization_digest"],
            "effective_scorer_source_sha256": review_bindings[
                "effect_scorer_source_sha256"
            ],
        },
        "product_seals_mutated": False,
        "label_or_registry_content_loaded": False,
        "effect_scoring_executed": False,
        "formal_holdout_consumed": False,
        "reader_model_provider_controller_calls": 0,
        "automatic_retries": 0,
        "fresh_independent_scoring_authorization_required": True,
    }
    material["amendment_digest"] = canonical_sha256(material)
    return material


def build_s4b_source_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    files = [file_identity(root, root / path) for path in S4B_SOURCE_PATHS]
    scan = _source_boundary_scan(root)
    material: dict[str, Any] = {
        "schema": "milai.dg25.s4b-source-manifest.v0.1",
        "fresh": True,
        "files": files,
        "source_set_digest": canonical_sha256(files),
        "source_scan": scan,
    }
    material["source_manifest_digest"] = canonical_sha256(material)
    return material


def build_authorization_bindings(
    *,
    run_id: str,
    identities: Mapping[str, Mapping[str, Any]],
    combined_seal: Mapping[str, Any],
    amendment: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    quality_identity: Mapping[str, Any],
    failure_snapshot: Mapping[str, Any],
    registry_references: Mapping[str, Mapping[str, Any]],
    bound_stop: Mapping[str, Any],
) -> dict[str, Any]:
    sources = {
        str(item["path"]): item
        for item in _mapping_sequence(source_manifest.get("files"), "source files")
    }
    return {
        "readiness_run_id": run_id,
        "official_s4b_run_id": S4B_OFFICIAL_RUN_ID,
        "combined_all_arm_seal_digest": combined_seal["seal_digest"],
        "combined_all_arm_seal_sha256": identities["combined_seal"]["sha256"],
        "readiness_bindings_digest": combined_seal["readiness_bindings_digest"],
        "e1_bundle_sha256": identities["e1_bundle"]["sha256"],
        "e1_all_arm_seal_digest": combined_seal["e1_all_arm_seal_digest"],
        "e1_all_arm_seal_sha256": identities["e1_seal"]["sha256"],
        "e2_bundle_sha256": identities["e2_bundle"]["sha256"],
        "e2_all_arm_seal_digest": combined_seal["e2_all_arm_seal_digest"],
        "e2_all_arm_seal_sha256": identities["e2_seal"]["sha256"],
        "scorer_source_amendment_digest": amendment["amendment_digest"],
        "historical_effect_scorer_source_sha256": HISTORICAL_SCORER_SHA256,
        "effect_scorer_source_sha256": CURRENT_SCORER_SHA256,
        "effect_scorer_contract_digest": SCORER_CONTRACT_DIGEST,
        "bound_stop_contract_digest": bound_stop["bound_contract_digest"],
        "gold_registry_path": registry_references["gold_equivalence_registry"]["path"],
        "gold_registry_sha256": registry_references["gold_equivalence_registry"][
            "sha256"
        ],
        "gold_registry_size": registry_references["gold_equivalence_registry"]["size"],
        "proof_registry_path": registry_references["proof_obligation_registry"][
            "path"
        ],
        "proof_registry_sha256": registry_references["proof_obligation_registry"][
            "sha256"
        ],
        "proof_registry_size": registry_references["proof_obligation_registry"][
            "size"
        ],
        "s4b_source_manifest_digest": source_manifest["source_manifest_digest"],
        "s4b_scoring_source_sha256": sources["evals/dg25/s4b_scoring.py"]["sha256"],
        "s4b_runner_source_sha256": sources["scripts/run_dg25_s4b.py"]["sha256"],
        "quality_receipt_sha256": quality_identity["sha256"],
        "failure_index_sha256": failure_snapshot["sha256"],
        "failure_index_line_count": failure_snapshot["line_count"],
        "expected_arm_count": 16,
        "expected_registry_open_count": 2,
        "expected_score_execution_count": 1,
        "automatic_retries": 0,
    }


def authorization_request(bindings: Mapping[str, Any]) -> dict[str, Any]:
    material: dict[str, Any] = {
        "schema": "milai.dg25.s4b-scoring-authorization-request.v0.1",
        "scope": "S4B_JOINT_E1_E2_POST_SEAL_SCORE",
        "official_s4b_run_id": S4B_OFFICIAL_RUN_ID,
        "authorization_bindings": dict(bindings),
        "authorization_bindings_digest": canonical_sha256(dict(bindings)),
        "authorized_attempts_requested": 1,
        "labels_authorized_only_after_pre_score_gate": True,
        "registry_content_authorized_only_after_pre_score_gate": True,
        "scoring_executions_requested": 1,
        "e3_authorized": False,
        "reader_model_provider_controller_calls_authorized": 0,
        "formal_holdout_authorized": False,
        "candidate_default_authorized": False,
        "automatic_retries": 0,
    }
    material["request_digest"] = canonical_sha256(material)
    return material


def validate_label_free_bundle(
    *,
    bundle: Mapping[str, Any],
    seal: Mapping[str, Any],
    block: Literal["E1", "E2"],
    arm_order: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    expected_schema = {
        "E1": "milai.dg25.e1-label-free-all-arm-bundle.v0.1",
        "E2": "milai.dg25.e2-label-free-all-arm-bundle.v0.1",
    }[block]
    if (
        bundle.get("schema") != expected_schema
        or bundle.get("arm_order") != list(arm_order)
        or bundle.get("labels_loaded") is not False
        or bundle.get("registry_content_loaded") is not False
        or bundle.get("scoring_executed") is not False
        or bundle.get("reader_model_provider_controller_calls") != 0
        or bundle.get("automatic_retries") != 0
    ):
        raise ValueError(f"DG25_S4B_{block}_BUNDLE_BOUNDARY_INVALID")
    raw_outputs = _mapping(bundle.get("arm_outputs"), f"{block} outputs")
    if set(raw_outputs) != set(arm_order):
        raise ValueError(f"DG25_S4B_{block}_OUTPUT_SET_MISMATCH")
    outputs = {arm: _mapping(raw_outputs[arm], arm) for arm in arm_order}
    configs = {arm: str(outputs[arm]["arm_config_digest"]) for arm in arm_order}
    block_inputs = {
        arm: dict(
            _mapping(
                _mapping(outputs[arm]["execution_binding"], "binding").get(
                    "block_input_identity"
                ),
                "block input identity",
            )
        )
        for arm in arm_order
    }
    common = dict(_mapping(outputs[arm_order[0]]["execution_binding"], "binding"))
    for field in (
        "schema",
        "block",
        "arm_id",
        "arm_config_digest",
        "block_input_identity",
        "execution_binding_digest",
    ):
        common.pop(field)
    for arm in arm_order:
        validate_label_free_arm_output(
            output=outputs[arm],
            block=block,
            arm_id=arm,
            arm_config_digest=configs[arm],
            common_execution_bindings=common,
            block_input_identity=block_inputs[arm],
        )
    validate_block_all_arm_seal(
        seal=seal,
        block=block,
        arm_outputs=outputs,
        arm_order=arm_order,
        config_digests=configs,
        common_execution_bindings=common,
        block_input_identities=block_inputs,
    )
    return outputs


def observe_registry_without_opening(
    root: Path, reference: Mapping[str, Any]
) -> dict[str, Any]:
    """Use lstat only; content hashing and JSON parsing remain post-authorization."""

    logical = Path(str(reference["path"]))
    if logical.is_absolute() or ".." in logical.parts:
        raise ValueError("DG25_S4B_REGISTRY_PATH_INVALID")
    path = root / logical
    metadata = path.lstat()
    regular = stat.S_ISREG(metadata.st_mode) and not path.is_symlink()
    if not regular or metadata.st_size != int(reference["size"]):
        raise ValueError("DG25_S4B_REGISTRY_PREAUTH_METADATA_MISMATCH")
    return {
        "path": logical.as_posix(),
        "regular_file": regular,
        "observed_size": metadata.st_size,
        "expected_size": int(reference["size"]),
        "size_matches_expected": metadata.st_size == int(reference["size"]),
        "expected_sha256": str(reference["sha256"]),
        "sha256_computed": False,
        "content_opened": False,
    }


def validate_readiness_receipt(
    *, root: Path, readiness_dir: Path, receipt: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    if (
        receipt.get("schema") != "milai.dg25.s4b-readiness-receipt.v0.1"
        or receipt.get("status")
        != "PASS_DG25_S4B_READINESS_PENDING_FRESH_INDEPENDENT_SCORING_AUTHORIZATION"
    ):
        raise ValueError("DG25_S4B_READINESS_RECEIPT_INVALID")
    artifacts = _mapping(receipt.get("artifacts"), "readiness artifacts")
    if set(artifacts) != set(READINESS_ARTIFACT_FILENAMES):
        raise ValueError("DG25_S4B_READINESS_ARTIFACT_SET_MISMATCH")
    result: dict[str, dict[str, Any]] = {}
    for key, filename in READINESS_ARTIFACT_FILENAMES.items():
        identity = file_identity(root, readiness_dir / filename)
        if identity != dict(_mapping(artifacts.get(key), key)):
            raise ValueError("DG25_S4B_READINESS_ARTIFACT_IDENTITY_DRIFT")
        result[key] = identity
    return result


def file_identity(root: Path, path: Path) -> dict[str, Any]:
    root = root.resolve()
    absolute = path if path.is_absolute() else root / path
    if absolute.is_symlink() or not absolute.is_file():
        raise ValueError(f"DG25_S4B_IDENTITY_NOT_REGULAR_FILE:{absolute}")
    resolved = absolute.resolve(strict=True)
    try:
        logical = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("DG25_S4B_IDENTITY_OUTSIDE_WORKSPACE") from exc
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": logical, "sha256": digest.hexdigest(), "size": resolved.stat().st_size}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _reconstruct_historical_scorer(current: str) -> str:
    for snippet in (_UNQUOTE_IMPORT, _LONGMEM_PATTERN, _LONGMEM_FUNCTION_PREFIX):
        if current.count(snippet) != 1:
            raise ValueError("DG25_S4B_SCORER_ALLOWED_DELTA_SHAPE_MISMATCH")
        current = current.replace(snippet, "", 1)
    return current


def _unaffected_ast(source: str) -> str:
    tree = ast.parse(source)
    body: list[ast.stmt] = []
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "urllib.parse"
            and [alias.name for alias in node.names] == ["unquote"]
        ):
            continue
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_LONGMEM_SOURCE_REF"
            for target in node.targets
        ):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == (
            "_canonical_source_ref"
        ):
            continue
        body.append(node)
    return ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False)


def _registry_references(
    scorer_envelope: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    references = _mapping(
        scorer_envelope.get("registry_identity_references"), "registry references"
    )
    expected = {"gold_equivalence_registry", "proof_obligation_registry"}
    if set(references) != expected:
        raise ValueError("DG25_S4B_REGISTRY_REFERENCE_SET_MISMATCH")
    return {key: _mapping(references[key], key) for key in sorted(expected)}


def _validate_fixed_identities(
    identities: Mapping[str, Mapping[str, Any]],
) -> None:
    for key, (expected_sha, expected_size) in EXPECTED_FIXED_IDENTITIES.items():
        identity = identities[key]
        if identity.get("sha256") != expected_sha or identity.get("size") != expected_size:
            raise ValueError(f"DG25_S4B_FIXED_INPUT_DRIFT:{key}")


def _validate_scorer_and_stop_contracts(
    scorer_envelope: Mapping[str, Any], bound_stop: Mapping[str, Any]
) -> None:
    envelope_material = dict(scorer_envelope)
    observed_seal = envelope_material.pop("scorer_seal_digest", None)
    contract = dict(_mapping(scorer_envelope.get("contract"), "scorer contract"))
    observed_contract = contract.pop("contract_digest", None)
    live_contract = scorer_contract()
    stop_contract = _mapping(bound_stop.get("contract"), "stop contract")
    if (
        observed_seal != canonical_sha256(envelope_material)
        or observed_contract != canonical_sha256(contract)
        or observed_contract != SCORER_CONTRACT_DIGEST
        or live_contract.get("contract_digest") != SCORER_CONTRACT_DIGEST
        or bound_stop.get("bound_contract_digest")
        != canonical_sha256(
            {
                key: value
                for key, value in bound_stop.items()
                if key != "bound_contract_digest"
            }
        )
        or stop_contract.get("pre_score_required_bindings") is None
    ):
        raise ValueError("DG25_S4B_SCORER_OR_STOP_CONTRACT_INVALID")


def _validate_quality_receipt(
    receipt: Mapping[str, Any],
    *,
    quality_identity: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
) -> None:
    if (
        receipt.get("schema") != "milai.dg25.s4b-quality-receipt.v0.1"
        or receipt.get("status") != "PASS_DG25_S4B_QUALITY"
        or receipt.get("automatic_retries") != 0
        or receipt.get("source_files_current_after_gates") is not True
        or receipt.get("source_set_digest") != source_manifest.get("source_set_digest")
        or receipt.get("source_files") != source_manifest.get("files")
        or quality_identity.get("sha256") is None
    ):
        raise ValueError("DG25_S4B_QUALITY_RECEIPT_INVALID_OR_STALE")
    gates = _mapping_sequence(receipt.get("gates"), "quality gates")
    if not gates or any(item.get("exit_code") != 0 for item in gates):
        raise ValueError("DG25_S4B_QUALITY_GATE_NOT_PASS")


def _source_boundary_scan(root: Path) -> dict[str, Any]:
    forbidden_modules = (
        "milai.adapters",
        "milai.application",
        "milai.persistence",
        "milai.providers",
        "milai.reader",
    )
    findings: list[str] = []
    for logical in S4B_SOURCE_PATHS:
        path = root / logical
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules = [node.module]
            else:
                modules = []
            for module in modules:
                if module.startswith(forbidden_modules):
                    findings.append(f"{logical}:forbidden-import:{module}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"eval", "exec", "__import__"}
            ):
                findings.append(f"{logical}:dynamic-call:{node.func.id}")
    return {
        "passed": not findings,
        "findings": findings,
        "registry_content_opened_during_scan": False,
        "reader_model_provider_controller_import_count": 0 if not findings else len(findings),
    }


def _pre_authorization_boundaries() -> dict[str, Any]:
    return {
        "labels_loaded": False,
        "registry_content_loaded": False,
        "effect_scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
    }


def _nonempty_line_count(path: Path) -> int:
    return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())


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
    "CURRENT_SCORER_SHA256",
    "FIXED_INPUT_PATHS",
    "READINESS_ARTIFACT_FILENAMES",
    "S4B_OUTPUT_ROOT",
    "S4B_READINESS_ROOT",
    "S4B_REVIEW_ROOT",
    "S4B_SOURCE_PATHS",
    "authorization_request",
    "build_s4b_readiness_materials",
    "build_s4b_source_manifest",
    "build_scorer_source_amendment",
    "file_identity",
    "observe_registry_without_opening",
    "read_json",
    "validate_label_free_bundle",
    "validate_readiness_receipt",
]

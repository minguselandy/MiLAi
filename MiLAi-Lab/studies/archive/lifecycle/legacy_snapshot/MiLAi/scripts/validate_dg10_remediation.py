from __future__ import annotations

import argparse
import json
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import dg10_ai_provenance as ai_provenance
from scripts import dg10_bfcl_scoring as bfcl_scoring
from scripts import dg10_remediation as remediation

ROOT = remediation.ROOT
CANDIDATE = remediation.CANDIDATE
DATE = remediation.DATE
CLAIM_MATRIX = ROOT / "docs/contracts/DG-10-remediation-claim-matrix-candidate.4.yaml"
CLAIM_MATRIX_AMENDMENT = ROOT / (
    "docs/contracts/DG-10-remediation-claim-matrix-amendment-candidate.4.1.yaml"
)
ACCEPTANCE = ROOT / "docs/contracts/DG-10-remediation-acceptance-candidate.4.1.yaml"
ACCEPTANCE_AMENDMENT = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.18.json"
)
PREVIOUS_ACCEPTANCE_AMENDMENT = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.14.json"
)
AI_EXECUTION_PROVENANCE = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.18.json"
)
AI_EXECUTION_AUTHORITY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.18.json"
)
BFCL_CASE_MANIFEST = ROOT / (
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.15-2026-08-22.json"
)
BFCL_EXECUTION_IDENTITY = ROOT / (
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.13-2026-08-22.json"
)
BFCL_WORKER_CLOSURE = ROOT / (
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.13-2026-08-22.json"
)
R2_WORKER_CLOSURE = ROOT / (
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.25-2026-08-22.json"
)
ATTEMPT_SCHEMA = ROOT / "docs/contracts/DG-10-attempt-ledger.schema.json"
TERMINAL_SCHEMA = ROOT / "docs/contracts/DG-10-agent-terminal.schema.json"
BENCHMARK_PROJECT = ROOT / "evals/dg10/pyproject.toml"
BENCHMARK_LOCK = ROOT / "evals/dg10/uv.lock"
PYTHON_VERSION = ROOT / "evals/dg10/.python-version"
DEFAULT_OUTPUT = ROOT / (
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.18-2026-08-22.json"
)
BASELINE_OUTPUT = ROOT / (
    "docs/reports/DG-10-remediation-baseline-candidate.4.3-2026-08-22.json"
)
SOURCE_INVENTORY_OUTPUT = ROOT / (
    "docs/reports/DG-10-remediation-source-inventory-candidate.4-2026-08-22.json"
)
AI_POLICY_OVERRIDE = remediation.AI_POLICY_OVERRIDE

EXPECTED_STAGE_STATES = {
    "NOT_STARTED",
    "AUTHOR_CANDIDATE",
    "REVIEW_REQUIRED",
    "ACCEPTED",
    "REVISE",
    "NO_GO_TERMINAL",
}
EXPECTED_EVIDENCE_CLASSES = {
    "AUTHOR",
    "DETERMINISTIC",
    "HUMAN",
    "INDEPENDENT",
    "AI_INDEPENDENT",
}
EVIDENCE_RECORD_CLASSES = EXPECTED_EVIDENCE_CLASSES
REQUIRED_RECORD_KEYS = {
    "claim_id",
    "stage_id",
    "stage_state",
    "evidence_class",
    "candidate_id",
    "inventory_sha256",
    "required_gates",
    "gate_receipts",
    "allowed",
}


class ValidationError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValidationError(reason)


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValidationError(f"YAML root is not a mapping: {path}")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValidationError(f"JSON root is not an object: {path}")
    return value


def _list_of_strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{label} must be list[str]")
    return value


def _validate_receipt(
    receipt: Mapping[str, Any], *, candidate_id: str, verify_files: bool
) -> str:
    required = {"gate_id", "candidate_id", "path", "sha256"}
    _require(set(receipt) == required, "gate receipt key set is incomplete or unknown")
    _require(
        receipt.get("candidate_id") == candidate_id,
        "cross-candidate receipt splice is forbidden",
    )
    gate_id = receipt.get("gate_id")
    _require(isinstance(gate_id, str) and gate_id, "gate receipt ID is invalid")
    digest = receipt.get("sha256")
    remediation._require_sha256(digest, "gate receipt digest")
    path_value = receipt.get("path")
    _require(isinstance(path_value, str) and path_value, "gate receipt path is invalid")
    if verify_files:
        path = (ROOT / path_value).resolve()
        _require(path.is_relative_to(ROOT), "gate receipt path escapes the repository")
        _require(path.is_file(), "gate receipt file is missing")
        _require(remediation.sha256_file(path) == digest, "gate receipt hash mismatch")
    return gate_id


def _validate_gate_receipt_semantics(
    reference: Mapping[str, Any],
    *,
    expected_gate_id: str,
    expected_stage_id: str,
    expected_inventory_sha256: str,
) -> None:
    path = (ROOT / str(reference["path"])).resolve()
    value = _load_json(path)
    required = {
        "schema",
        "candidate_id",
        "gate_id",
        "stage_id",
        "stage_state",
        "result",
        "evidence_class",
        "source_inventory_sha256",
        "policy_override_sha256",
        "evidence",
    }
    _require(set(value) == required, "gate receipt semantic key set drift")
    _require(value.get("schema") == "milai.dg10.gate-receipt.v1", "gate receipt schema drift")
    _require(value.get("candidate_id") == CANDIDATE, "gate receipt candidate drift")
    _require(value.get("gate_id") == expected_gate_id, "gate receipt ID semantic drift")
    _require(value.get("stage_id") == expected_stage_id, "gate receipt stage semantic drift")
    _require(value.get("stage_state") == "ACCEPTED", "gate receipt stage is not ACCEPTED")
    _require(value.get("result") == "PASS", "gate receipt result is not PASS")
    _require(
        value.get("source_inventory_sha256") == expected_inventory_sha256,
        "gate receipt source inventory drift",
    )
    evidence_class = value.get("evidence_class")
    _require(
        evidence_class in {"DETERMINISTIC", "AI_INDEPENDENT"},
        "gate receipt evidence class is not accepted",
    )
    if evidence_class == "AI_INDEPENDENT":
        _require(AI_POLICY_OVERRIDE.is_file(), "AI policy override is absent")
        _require(
            value.get("policy_override_sha256")
            == remediation.sha256_file(AI_POLICY_OVERRIDE),
            "AI gate receipt policy binding drift",
        )
    else:
        _require(value.get("policy_override_sha256") is None, "deterministic gate claims AI policy")
    evidence = value.get("evidence")
    _require(isinstance(evidence, list) and evidence, "gate receipt evidence is absent")
    seen: set[str] = set()
    for item in evidence:
        _require(
            isinstance(item, Mapping) and set(item) == {"path", "sha256"},
            "gate evidence reference drift",
        )
        relative = item.get("path")
        _require(isinstance(relative, str) and relative and relative not in seen, "gate evidence path invalid")
        seen.add(relative)
        target = (ROOT / relative).resolve()
        _require(
            target.is_relative_to(ROOT) and target.is_file() and not target.is_symlink(),
            "gate evidence file is missing or unsafe",
        )
        remediation._require_sha256(item.get("sha256"), "gate evidence digest")
        _require(remediation.sha256_file(target) == item.get("sha256"), "gate evidence hash drift")


def validate_evidence_record(
    record: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    verify_files: bool = True,
) -> dict[str, Any]:
    _require(set(record) == REQUIRED_RECORD_KEYS, "claim evidence record key set drift")
    claim_id = record.get("claim_id")
    _require(isinstance(claim_id, str) and claim_id in catalog, "unknown claim")
    policy = catalog[claim_id]
    _require(isinstance(policy, Mapping), "claim catalog entry is invalid")
    _require(record.get("stage_id") == policy.get("stage_id"), "unknown or wrong stage")
    _require(record.get("stage_state") in EXPECTED_STAGE_STATES, "unknown stage state")
    _require(
        record.get("evidence_class") in EVIDENCE_RECORD_CLASSES,
        "unknown evidence class",
    )
    candidate_id = record.get("candidate_id")
    _require(isinstance(candidate_id, str) and candidate_id, "candidate ID is invalid")
    remediation._require_sha256(record.get("inventory_sha256"), "inventory digest")
    required_gates = _list_of_strings(record.get("required_gates"), "required_gates")
    _require(len(required_gates) == len(set(required_gates)), "required gate is duplicated")
    catalog_gates = _list_of_strings(policy.get("required_gates"), "catalog gates")
    _require(set(required_gates) == set(catalog_gates), "required gate set drift")
    receipts = record.get("gate_receipts")
    _require(isinstance(receipts, list), "gate_receipts must be a list")
    receipt_gates = [
        _validate_receipt(item, candidate_id=candidate_id, verify_files=verify_files)
        for item in receipts
        if isinstance(item, Mapping)
    ]
    _require(len(receipt_gates) == len(receipts), "gate receipt must be an object")
    _require(len(receipt_gates) == len(set(receipt_gates)), "gate receipt is duplicated")
    _require(set(receipt_gates) == set(required_gates), "missing gate or receipt")
    allowed = record.get("allowed")
    _require(isinstance(allowed, bool), "allowed must be boolean")
    if record.get("stage_state") != "ACCEPTED":
        _require(allowed is False, "unaccepted stage cannot allow a claim")
    if record.get("evidence_class") == "AUTHOR":
        _require(allowed is False, "AUTHOR evidence cannot be acceptance")
    return {
        "claim_id": claim_id,
        "candidate_id": candidate_id,
        "stage_id": record["stage_id"],
        "stage_state": record["stage_state"],
        "evidence_class": record["evidence_class"],
        "receipt_count": len(receipts),
        "allowed": allowed,
    }


def validate_claim_request(
    record: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    quality_outcome: str,
    expected_inventory_sha256: str | None = None,
    verify_files: bool = True,
) -> dict[str, Any]:
    result = validate_evidence_record(record, catalog, verify_files=verify_files)
    _require(result["stage_state"] == "ACCEPTED", "claim stage is not ACCEPTED")
    if result["claim_id"] in {"QUALITY_TARGET_MET", "LOCAL_VLLM_MCP_AGENT_CANDIDATE"}:
        _require(quality_outcome == "TARGET_MET", "quality BELOW_TARGET blocks claim")
    _require(
        result["evidence_class"] == "AI_INDEPENDENT",
        "claim lacks AI-independent acceptance evidence",
    )
    _require(result["allowed"] is True, "claim request is not allowed")
    _require(result["candidate_id"] == CANDIDATE, "claim request is not for the current candidate")
    remediation._require_sha256(expected_inventory_sha256, "expected source inventory")
    _require(
        record.get("inventory_sha256") == expected_inventory_sha256,
        "claim source inventory binding drift",
    )
    _require(verify_files, "claim request cannot skip receipt file verification")
    receipts = record.get("gate_receipts")
    _require(isinstance(receipts, list), "claim gate receipts are absent")
    paths = [item.get("path") for item in receipts if isinstance(item, Mapping)]
    _require(len(paths) == len(set(paths)), "one receipt file cannot satisfy multiple gates")
    for receipt in receipts:
        _require(isinstance(receipt, Mapping), "claim gate receipt is not an object")
        _validate_gate_receipt_semantics(
            receipt,
            expected_gate_id=str(receipt["gate_id"]),
            expected_stage_id=str(record["stage_id"]),
            expected_inventory_sha256=str(expected_inventory_sha256),
        )
    return result


def validate_claim_matrix() -> dict[str, Any]:
    value = _load_yaml(CLAIM_MATRIX)
    amendment = _load_yaml(CLAIM_MATRIX_AMENDMENT)
    _require(
        amendment.get("candidate_id") == CANDIDATE
        and amendment.get("status") == "FROZEN_ACTIVE_POLICY_BINDING_AMENDMENT"
        and amendment.get("parent_claim_matrix")
        == {
            "path": CLAIM_MATRIX.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(CLAIM_MATRIX),
        }
        and amendment.get("active_ai_policy")
        == {
            "path": AI_POLICY_OVERRIDE.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(AI_POLICY_OVERRIDE),
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
        },
        "claim matrix active xhigh amendment drift",
    )
    _require(value.get("schema_version") == "1", "claim matrix schema drift")
    _require(value.get("goal_id") == "DG-10-RM", "claim matrix goal drift")
    _require(value.get("candidate_id") == CANDIDATE, "claim matrix candidate drift")
    _require(
        set(_list_of_strings(value.get("allowed_stage_states"), "allowed_stage_states"))
        == EXPECTED_STAGE_STATES,
        "allowed stage state catalog drift",
    )
    _require(
        set(
            _list_of_strings(
                value.get("allowed_evidence_classes"), "allowed_evidence_classes"
            )
        )
        == EXPECTED_EVIDENCE_CLASSES,
        "allowed evidence class catalog drift",
    )
    catalog = value.get("claim_catalog")
    _require(isinstance(catalog, Mapping), "claim catalog is missing")
    records = value.get("qualified_evidence")
    _require(isinstance(records, list) and records, "qualified evidence is missing")
    results = [
        validate_evidence_record(record, catalog)
        for record in records
        if isinstance(record, Mapping)
    ]
    _require(len(results) == len(records), "qualified evidence record is invalid")
    aggregate = value.get("aggregate_current_status")
    _require(isinstance(aggregate, Mapping), "aggregate status is missing")
    _require(aggregate.get("allowed") is False, "aggregate claim must remain denied")
    _require(
        aggregate.get("full_test_authorized") is False
        and aggregate.get("release_authorized") is False,
        "candidate.4 authorization boundary drift",
    )
    return {
        "path": CLAIM_MATRIX.relative_to(ROOT).as_posix(),
        "sha256": remediation.sha256_file(CLAIM_MATRIX),
        "active_amendment_sha256": remediation.sha256_file(
            CLAIM_MATRIX_AMENDMENT
        ),
        "qualified_evidence_count": len(results),
        "allowed_evidence_count": sum(int(item["allowed"]) for item in results),
        "aggregate_allowed": False,
        "status": "PASS_STAGE_QUALIFIED_NO_ACCEPTANCE",
    }


def validate_acceptance() -> dict[str, Any]:
    value = _load_yaml(ACCEPTANCE)
    amendment = _load_json(ACCEPTANCE_AMENDMENT)
    _require(
        amendment.get("schema") == "milai.dg10.remediation-acceptance-amendment.v1"
        and amendment.get("candidate_id") == CANDIDATE
        and amendment.get("status")
        == "FROZEN_ACTIVE_CONTENT_ADDRESSED_ISOLATED_PYTHON_EXACT_ENV_SIGNED_AI_AUTHORITY"
        and amendment.get("supersedes")
        == {
            "path": PREVIOUS_ACCEPTANCE_AMENDMENT.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(PREVIOUS_ACCEPTANCE_AMENDMENT),
        }
        and amendment.get("reasoning_policy")
        == {
            "path": AI_POLICY_OVERRIDE.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(AI_POLICY_OVERRIDE),
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
        }
        and amendment.get("full_test_execution") == "DENIED_NOT_RUN"
        and amendment.get("release_authorized") is False
        and amendment.get("schema_freeze_authorized") is False,
        "active acceptance amendment drift",
    )
    provenance = amendment.get("ai_execution_provenance")
    _require(
        isinstance(provenance, Mapping)
        and provenance.get("path")
        == AI_EXECUTION_PROVENANCE.relative_to(ROOT).as_posix()
        and provenance.get("sha256")
        == remediation.sha256_file(AI_EXECUTION_PROVENANCE)
        and provenance.get("execution_channel")
        == "ISOLATED_ROOT_CODE_PYTHON_ENV_ED25519_LIVE_CODEX_V3"
        and provenance.get("authority_policy_path")
        == AI_EXECUTION_AUTHORITY.relative_to(ROOT).as_posix()
        and provenance.get("authority_policy_sha256")
        == remediation.sha256_file(AI_EXECUTION_AUTHORITY)
        and provenance.get("caller_selected_attempt_roots") == "DENY"
        and provenance.get("unsigned_v1_v2_or_missing_execution_attestation")
        == "REJECT_FAIL_CLOSED"
        and provenance.get("runtime_signature_and_process_identity_replay_required")
        is True
        and provenance.get("pinned_codex_code_mode_host_required") is True
        and provenance.get("pinned_codex_runtime_resource_closure_required")
        is True
        and provenance.get("codex_and_helper_root_uid_gid_mode_replay_required")
        is True
        and provenance.get("root_owned_static_model_catalog_required") is True
        and provenance.get("model_catalog_hash_command_and_runtime_replay_required")
        is True
        and provenance.get("content_addressed_authority_module_closure_required")
        is True
        and provenance.get("isolated_python_runtime_tree_and_loaded_library_replay_required")
        is True
        and provenance.get("fixed_sys_path_and_no_bytecode_mode_required") is True
        and provenance.get("authority_process_exact_environment_required") is True
        and provenance.get("codex_child_exact_environment_required") is True
        and provenance.get("procfs_environment_equality_required") is True
        and provenance.get("stderr_allowlist")
        == "EMPTY_OR_ONE_EXACT_ASCII_TIMESTAMPED_DIAGNOSTIC_WITH_ONE_LF",
        "protected AI execution provenance amendment drift",
    )
    provenance_contract = _load_json(AI_EXECUTION_PROVENANCE)
    _require(
        provenance_contract.get("status")
        == "SEPARATE_UID_SIGNED_AI_EXECUTION_AUTHORITY_REQUIRED"
        and provenance_contract.get("execution_channel")
        == "ISOLATED_ROOT_CODE_PYTHON_ENV_ED25519_LIVE_CODEX_V3"
        and provenance_contract.get("import_policy", {}).get(
            "caller_selected_attempt_root_allowed"
        )
        is False
        and provenance_contract.get("import_policy", {}).get(
            "unsigned_or_v1_or_v2_execution_attestation_allowed"
        )
        is False
        and provenance_contract.get("import_policy", {}).get(
            "post_hoc_same_uid_attempt_directory_allowed"
        )
        is False
        and provenance_contract.get("import_policy", {}).get("stderr_allowlist")
        == "EMPTY_OR_ONE_EXACT_ASCII_TIMESTAMPED_DIAGNOSTIC_WITH_ONE_LF"
        and provenance_contract.get("import_policy", {}).get(
            "duplicate_or_noncanonical_stderr_action"
        )
        == "REJECT_FAIL_CLOSED"
        and provenance_contract.get("r3_policy", {}).get(
            "generic_r3_accepted_receipt_allowed"
        )
        is False
        and provenance_contract.get("trust_boundary", {}).get(
            "provider_cryptographic_signature_claimed"
        )
        is False
        and provenance_contract.get("trust_boundary", {}).get(
            "equivalently_protected_local_authority_claimed"
        )
        is True
        and provenance_contract.get("trust_boundary", {}).get(
            "workspace_author_can_generate_valid_execution_receipt"
        )
        is False
        and provenance_contract.get("historical_execution_failure", {}).get(
            "remediated_reason_code"
        )
        == "DUPLICATE_KNOWN_MODEL_REFRESH_STDERR_DIAGNOSTIC"
        and "pinned_root_owned_codex_runtime_resource_closure"
        in provenance_contract.get("trust_boundary", {}).get(
            "trusted_components", []
        )
        and "pinned_root_owned_static_codex_model_catalog"
        in provenance_contract.get("trust_boundary", {}).get(
            "trusted_components", []
        )
        and "root_owned_read_only_model_catalog_hash_is_policy_frozen_command_bound_and_replayed"
        in provenance_contract.get("required_runtime_attestations", [])
        and "content_addressed_root_owned_authority_code_closure"
        in provenance_contract.get("trust_boundary", {}).get(
            "trusted_components", []
        )
        and "root_owned_authority_python_distribution_and_virtual_environment"
        in provenance_contract.get("trust_boundary", {}).get(
            "trusted_components", []
        )
        and provenance_contract.get("trust_boundary", {}).get(
            "workspace_module_or_environment_substitution"
        )
        == "REJECT_BEFORE_LAUNCH_OR_SIGNING",
        "protected AI execution provenance contract drift",
    )
    authority_policy = ai_provenance.load_authority_policy(
        AI_EXECUTION_AUTHORITY
    )
    private_key = Path(str(authority_policy["private_key_path"]))
    codex = Path(str(authority_policy["codex_executable_path"]))
    codex_host = Path(str(authority_policy["codex_code_mode_host_path"]))
    codex_catalog = ai_provenance.pinned_model_catalog(authority_policy)
    codex_resources = ai_provenance.pinned_codex_runtime_resources(authority_policy)
    authority_code = ai_provenance.pinned_authority_code(authority_policy)
    authority_python = ai_provenance.pinned_authority_python_runtime(authority_policy)
    authority_runner = Path(str(authority_policy["authority_runner_path"]))
    _require(
        authority_policy["authority_uid"]
        != authority_policy["workspace_author_uid"]
        and authority_policy["authority_gid"]
        != authority_policy["workspace_author_gid"]
        and private_key.is_file()
        and not private_key.is_symlink()
        and private_key.stat().st_uid == authority_policy["authority_uid"]
        and private_key.stat().st_gid == authority_policy["authority_gid"]
        and private_key.stat().st_mode & 0o777 == 0o600
        and codex.is_file()
        and not codex.is_symlink()
        and codex.stat().st_uid == authority_policy["codex_executable_uid"] == 0
        and codex.stat().st_gid == authority_policy["codex_executable_gid"] == 0
        and f"{stat.S_IMODE(codex.stat().st_mode):04o}"
        == authority_policy["codex_executable_mode"]
        == "0555"
        and remediation.sha256_file(codex)
        == authority_policy["codex_executable_sha256"]
        and codex_host == codex.with_name("codex-code-mode-host")
        and codex_host.is_file()
        and not codex_host.is_symlink()
        and codex_host.stat().st_uid
        == authority_policy["codex_code_mode_host_uid"]
        == 0
        and codex_host.stat().st_gid
        == authority_policy["codex_code_mode_host_gid"]
        == 0
        and f"{stat.S_IMODE(codex_host.stat().st_mode):04o}"
        == authority_policy["codex_code_mode_host_mode"]
        == "0555"
        and remediation.sha256_file(codex_host)
        == authority_policy["codex_code_mode_host_sha256"]
        and codex_catalog == codex.with_name("model-catalog.json")
        and codex_catalog.stat().st_uid
        == authority_policy["codex_model_catalog_uid"]
        == 0
        and codex_catalog.stat().st_gid
        == authority_policy["codex_model_catalog_gid"]
        == 0
        and f"{stat.S_IMODE(codex_catalog.stat().st_mode):04o}"
        == authority_policy["codex_model_catalog_mode"]
        == "0444"
        and remediation.sha256_file(codex_catalog)
        == authority_policy["codex_model_catalog_sha256"]
        and set(codex_resources) == set(ai_provenance.CODEX_RESOURCE_PATHS)
        and authority_runner.is_file()
        and not authority_runner.is_symlink()
        and authority_runner.stat().st_uid == 0
        and authority_runner.stat().st_gid == 0
        and authority_runner.stat().st_mode & 0o022 == 0
        and remediation.sha256_file(authority_runner)
        == authority_policy["authority_runner_sha256"]
        and authority_code["root"] == authority_policy["authority_code_root"]
        and authority_code["manifest_sha256"]
        == authority_policy["authority_code_manifest_sha256"]
        and authority_python["isolated_flag"] == 1
        and authority_python["dont_write_bytecode_flag"] == 1
        and authority_python["runtime_roots"]
        == authority_policy["authority_python_runtime_roots"]
        and authority_python["loaded_libraries"]
        == authority_policy["authority_python_loaded_libraries"]
        and all(
            Path(path).is_dir()
            and Path(path).stat().st_uid == authority_policy["authority_uid"]
            and Path(path).stat().st_gid == authority_policy["authority_gid"]
            and Path(path).stat().st_mode & 0o777 == 0o700
            for path in authority_policy["protected_attempt_roots"].values()
        ),
        "separate-UID AI execution authority host boundary drift",
    )
    r1_validation = amendment.get("r1_validation")
    execution_failure = amendment.get("remediates_ai_audit_execution_failure")
    _require(
        isinstance(execution_failure, Mapping)
        and execution_failure.get("attempt_id") == "candidate.4-primary-015"
        and execution_failure.get("historical_status")
        == "INVALID_EXECUTION_REVISE_NO_ACCEPTANCE_EFFECT"
        and execution_failure.get("reason_code")
        == "DUPLICATE_KNOWN_MODEL_REFRESH_STDERR_DIAGNOSTIC",
        "AI audit execution failure remediation drift",
    )
    _require(
        isinstance(r1_validation, Mapping)
        and r1_validation.get("active_scope") == "all"
        and r1_validation.get("active_source_inventory_required") is True
        and r1_validation.get(
            "subordinate_source_root_must_equal_stage_ledger_root"
        )
        is True
        and r1_validation.get("contract_only_scope_for_author_candidate")
        == "DENY",
        "R1 full-source validation amendment drift",
    )
    r2_verification = amendment.get("r2_verification")
    _require(
        isinstance(r2_verification, Mapping)
        and r2_verification.get("upstream_bfcl_tracked_file_count") == 192
        and r2_verification.get(
            "upstream_bfcl_tracked_bytes_must_be_materialized_in_review_bundle"
        )
        is True
        and r2_verification.get(
            "upstream_bfcl_path_size_hash_and_aggregate_replay_required"
        )
        is True
        and r2_verification.get("runtime_wheel_payload_file_count") == 65
        and r2_verification.get("all_runtime_wheel_source_inputs_must_be_materialized")
        is True
        and r2_verification.get(
            "runtime_wheel_payload_and_source_path_and_bytes_equality_required"
        )
        is True,
        "R2 upstream BFCL materialization amendment drift",
    )
    bfcl_preregistration = amendment.get("bfcl_preregistration")
    _require(
        isinstance(bfcl_preregistration, Mapping)
        and bfcl_preregistration.get("active_manifest_path")
        == "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.15-2026-08-22.json"
        and bfcl_preregistration.get("execution_identity_path")
        == "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.13-2026-08-22.json"
        and bfcl_preregistration.get(
            "acceptance_manifest_scoring_execution_identity_paths_must_match"
        )
        is True,
        "BFCL active execution identity alignment drift",
    )
    bfcl_manifest = _load_json(BFCL_CASE_MANIFEST)
    bfcl_execution_identity = _load_json(BFCL_EXECUTION_IDENTITY)
    bfcl_worker_closure = _load_json(BFCL_WORKER_CLOSURE)
    r2_worker_closure = _load_json(R2_WORKER_CLOSURE)
    expected_worker_reference = {
        "path": BFCL_WORKER_CLOSURE.relative_to(ROOT).as_posix(),
        "sha256": remediation.sha256_file(BFCL_WORKER_CLOSURE),
    }
    _require(
        bfcl_scoring.ACTIVE_CASE_MANIFEST == BFCL_CASE_MANIFEST
        and bfcl_scoring.ACTIVE_ACCEPTANCE_CONTRACT == ACCEPTANCE_AMENDMENT
        and bfcl_scoring.ACTIVE_EXECUTION_IDENTITY == BFCL_EXECUTION_IDENTITY
        and bfcl_manifest.get("acceptance_contract")
        == {
            "path": ACCEPTANCE_AMENDMENT.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(ACCEPTANCE_AMENDMENT),
        }
        and bfcl_manifest.get("execution_identity")
        == {
            "path": BFCL_EXECUTION_IDENTITY.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(BFCL_EXECUTION_IDENTITY),
        }
        and bfcl_manifest.get("dependency_closure")
        == {
            "python": expected_worker_reference,
            "javascript": expected_worker_reference,
            "java": expected_worker_reference,
        }
        and bfcl_execution_identity.get("worker_closure")
        == {
            "path": BFCL_WORKER_CLOSURE.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(BFCL_WORKER_CLOSURE),
            "size": BFCL_WORKER_CLOSURE.stat().st_size,
        }
        and bfcl_worker_closure.get("coherent_r2_closure")
        == {
            "path": R2_WORKER_CLOSURE.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(R2_WORKER_CLOSURE),
            "size": R2_WORKER_CLOSURE.stat().st_size,
        }
        and r2_worker_closure.get("status")
        == "R2_AUTHOR_CANDIDATE_DYNAMIC_PASS_REVIEW_REQUIRED"
        and r2_worker_closure.get("verification", {}).get("pytest", {}).get("passed")
        == 281
        and r2_worker_closure.get("verification", {}).get("pytest", {}).get("failed")
        == 0
        and r2_worker_closure.get("verification", {}).get("ruff", {}).get("exit_code")
        == 0,
        "BFCL acceptance/manifest/scoring/execution closure contradiction",
    )
    model_execution = amendment.get("model_call_execution")
    _require(
        isinstance(model_execution, Mapping)
        and model_execution.get(
            "bootstrap_authorization_replayed_at_the_native_transport_before_each_call"
        )
        is True
        and model_execution.get(
            "durable_atomic_per_slot_claim_required_before_provider_io"
        )
        is True
        and model_execution.get(
            "provider_native_id_must_be_journaled_before_semantic_response_validation"
        )
        is True
        and model_execution.get("direct_repeated_and_concurrent_slot_replay")
        == "DENY_BEFORE_NETWORK"
        and model_execution.get("maximum_actual_t2_provider_requests") == 24
        and model_execution.get(
            "every_non_bootstrap_completion_requires_active_accepted_r3"
        )
        is True
        and model_execution.get(
            "openworker_container_requires_host_derived_read_only_post_r3_capability"
        )
        is True
        and model_execution.get(
            "new_completion_literal_outside_the_frozen_boundary_allowlist"
        )
        == "DENY"
        and model_execution.get(
            "post_r3_authority_must_replay_signed_fixed_r3_import"
        )
        is True
        and model_execution.get("caller_minted_or_unsigned_r3_stage_receipt")
        == "DENY",
        "model-call authorization boundary amendment drift",
    )
    stage_state = amendment.get("stage_state")
    test_access = amendment.get("test_access")
    _require(
        isinstance(stage_state, Mapping)
        and stage_state.get("generic_r3_accepted_receipts") == "DENY"
        and stage_state.get("fixed_r3_importer_required") is True
        and stage_state.get("r3_primary_ed25519_authority_signature_required")
        is True
        and stage_state.get("r3_signature_replayed_at_each_post_r3_authorization")
        is True
        and isinstance(test_access, Mapping)
        and test_access.get("separate_uid_ed25519_execution_attestation_required")
        is True
        and test_access.get("isolated_v3_execution_attestation_required") is True
        and test_access.get("authority_owned_fixed_attempt_root_required") is True
        and test_access.get("locally_fabricated_or_v1_v2_attempts")
        == "REJECT_FAIL_CLOSED",
        "R3 or test-access protected importer amendment drift",
    )
    _require(value.get("schema_version") == "1", "acceptance schema drift")
    _require(value.get("goal_id") == "DG-10-RM", "acceptance goal drift")
    _require(value.get("candidate_id") == CANDIDATE, "acceptance candidate drift")
    _require(value.get("test_access_authorized") is False, "test access opened")
    _require(
        value.get("test_labels_or_outputs_opened") is False,
        "test labels or outputs opened",
    )
    track = value.get("track_a")
    _require(isinstance(track, Mapping), "Track A contract missing")
    _require(
        track.get("arms") == ["NO_MEMORY", "NAIVE_RAG", "MILAI_RETRIEVAL"],
        "Track A arm set drift",
    )
    calls = track.get("answer_model_calls_per_case")
    _require(
        isinstance(calls, Mapping) and set(calls.values()) == {1},
        "Track A must use exactly one answer call in every arm",
    )
    _require(
        track.get("memory_target_tokenizer_tokens_max") == 512,
        "memory ceiling drift",
    )
    _require(
        track.get("current_diagnostic_case_count") == 50
        and track.get("disjoint_confirmation_case_count") == 50
        and track.get("required_ability_strata") == ["knowledge_update", "temporal"]
        and track.get("preregistered_case_manifest_required") is True,
        "quality case manifest or denominator drift",
    )
    _require(
        track.get("artificial_marker_allowed") is False
        and track.get("shared_baseline_ranking_allowed") is False,
        "MiLAi retrieval bypass is enabled",
    )
    thresholds = track.get("thresholds")
    _require(isinstance(thresholds, Mapping), "Track A thresholds missing")
    minimums = {
        "normalized_f1_delta_vs_naive_rag_min": 0.0,
        "exact_match_delta_vs_naive_rag_min": 0.0,
        "knowledge_update_f1_delta_min": 0.0,
        "temporal_f1_delta_min": 0.0,
        "recall_at_1_delta_min": 0.0,
        "false_certainty_rate_max": 0.0,
    }
    _require(
        all(thresholds.get(key) == expected for key, expected in minimums.items()),
        "quality threshold was lowered or omitted",
    )
    bfcl = value.get("bfcl")
    _require(isinstance(bfcl, Mapping) and bfcl.get("max_steps") == 20, "BFCL step drift")
    bfcl_thresholds = bfcl.get("thresholds")
    _require(
        isinstance(bfcl_thresholds, Mapping)
        and bfcl_thresholds.get("overall_accuracy_min") == 0.80
        and bfcl_thresholds.get("supported_single_turn_accuracy_min") == 0.85
        and bfcl_thresholds.get("multi_turn_accuracy_min") == 0.50
        and bfcl_thresholds.get("irrelevance_no_call_accuracy_min") == 0.80,
        "BFCL threshold was lowered or omitted",
    )
    _require(
        bfcl.get("dev_case_count") == 216
        and bfcl.get("multi_turn_case_count") == 80
        and bfcl.get("supported_single_turn_case_count") == 122
        and bfcl.get("irrelevance_no_call_case_count") == 24
        and bfcl.get("frozen_case_to_category_manifest_required") is True,
        "BFCL denominator binding drift",
    )
    serving = value.get("serving")
    _require(isinstance(serving, Mapping), "serving contract missing")
    _require(serving.get("percentile_method") == "NEAREST_RANK", "tail method drift")
    _require(
        serving.get("p99_terminal_attempts_per_cell_min") == 100
        and serving.get("p99_below_minimum") == "NOT_ESTIMABLE",
        "p99 sample contract drift",
    )
    _require(
        serving.get("absolute_threshold_state")
        == "CALIBRATION_REQUIRED_BEFORE_ACCEPTANCE_RUN"
        and serving.get("absolute_thresholds") is None,
        "serving threshold calibration boundary drift",
    )
    authorization_rule = value.get("authorization_rule")
    _require(isinstance(authorization_rule, Mapping), "authorization rule missing")
    bootstrap = authorization_rule.get("bootstrap_t2_control_path")
    _require(
        isinstance(bootstrap, Mapping)
        and bootstrap.get("requires_all") == ["DG10-R0", "DG10-R1", "DG10-R2"]
        and bootstrap.get("exact_model_calls") == 24
        and bootstrap.get("test_access_allowed") is False
        and bootstrap.get("all_attempts_preallocated_and_ledgered") is True,
        "T2 bootstrap rule drift",
    )
    tier2 = authorization_rule.get("tier2_review_replacement")
    _require(
        isinstance(tier2, Mapping)
        and tier2.get("evidence_class") == "AI_INDEPENDENT"
        and tier2.get("primary_audit_count") == 2
        and tier2.get("conflict_requires_third_ai_adjudication") is True
        and tier2.get("human_receipt_required") is False,
        "Tier 2 AI replacement rule drift",
    )
    _require(
        tier2.get("model") == "gpt-5.6-sol"
        and tier2.get("reasoning_effort") == "xhigh"
        and value.get("ai_policy_override_sha256")
        == remediation.sha256_file(AI_POLICY_OVERRIDE),
        "active xhigh AI policy binding drift",
    )
    return {
        "path": ACCEPTANCE.relative_to(ROOT).as_posix(),
        "sha256": remediation.sha256_file(ACCEPTANCE),
        "active_amendment_sha256": remediation.sha256_file(ACCEPTANCE_AMENDMENT),
        "track_a_answer_calls_per_arm": dict(calls),
        "memory_token_ceiling": 512,
        "bfcl_max_steps": 20,
        "full_test_authorized": False,
        "status": "PASS_PRE_MODEL_THRESHOLDS_FROZEN_SERVING_CALIBRATION_PENDING",
    }


def validate_schemas() -> dict[str, Any]:
    attempt = _load_json(ATTEMPT_SCHEMA)
    terminal = _load_json(TERMINAL_SCHEMA)
    attempt_required = set(_list_of_strings(attempt.get("required"), "attempt required"))
    terminal_required = set(_list_of_strings(terminal.get("required"), "terminal required"))
    expected_attempt = {
        "attempt_id",
        "parent_attempt_id",
        "candidate_id",
        "phase",
        "arm",
        "case_id",
        "planned_model_calls",
        "planned_mcp_calls",
        "native_request_ids",
        "usage",
        "provider_terminal",
        "mcp_terminal",
        "agent_terminal",
        "parser_terminal",
        "started_at",
        "provider_claimed_at",
        "native_completed_at",
        "mcp_completed_at",
        "finished_at",
        "retention_state",
        "failure_reason_code",
        "external_billed_cost",
        "self_hosted_compute_cost",
        "raw_sidecar_digest",
        "provider_claim_digest",
        "raw_mcp_sidecar_digest",
        "redacted_public_receipt_digest",
    }
    _require(expected_attempt <= attempt_required, "attempt schema required set incomplete")
    expected_terminal = {
        "provider_status",
        "agent_status",
        "parser_status",
        "native_request_count",
        "native_usage_all_attempts",
        "public_result_status",
        "stable_reason_code",
    }
    _require(expected_terminal <= terminal_required, "terminal schema required set incomplete")
    reason_values = set(
        attempt.get("properties", {}).get("failure_reason_code", {}).get("enum", [])
    )
    _require(reason_values == remediation.STABLE_REASON_CODES, "reason code set drift")
    return {
        "attempt_schema_sha256": remediation.sha256_file(ATTEMPT_SCHEMA),
        "terminal_schema_sha256": remediation.sha256_file(TERMINAL_SCHEMA),
        "stable_reason_code_count": len(reason_values),
        "status": "PASS",
    }


def source_inventory_paths() -> list[Path]:
    return [
        remediation.GOALS,
        CLAIM_MATRIX,
        CLAIM_MATRIX_AMENDMENT,
        ACCEPTANCE,
        ACCEPTANCE_AMENDMENT,
        ATTEMPT_SCHEMA,
        TERMINAL_SCHEMA,
        AI_POLICY_OVERRIDE,
        ROOT / "docs/contracts/DG-10-memory-quality-topology-candidate.4.json",
        ROOT / "scripts/dg10_remediation.py",
        Path(__file__).resolve(),
        BENCHMARK_PROJECT,
        BENCHMARK_LOCK,
        PYTHON_VERSION,
        ROOT / "evals/dg10/wheels/milai_runtime-0.1.0-py3-none-any.whl",
        ROOT / "tests/test_dg10_remediation.py",
    ]


def build_source_inventory() -> dict[str, Any]:
    inventory = remediation.canonical_inventory(source_inventory_paths())
    return {
        "schema": "milai.dg10.remediation-source-inventory.v1",
        "candidate_id": CANDIDATE,
        "date": DATE,
        "status": "AUTHOR_CANDIDATE_INVENTORY_BOUND",
        **inventory,
    }


def _active_source_inventory(path: Path) -> dict[str, Any]:
    resolved = path.absolute()
    _require(
        resolved.is_relative_to(ROOT.absolute())
        and not remediation.has_symlink_component(resolved)
        and resolved.is_file(),
        "active candidate source inventory is missing or unsafe",
    )
    value = _load_json(resolved)
    required = {
        "schema",
        "candidate_id",
        "entry_count",
        "canonical_entries_sha256",
        "entries",
    }
    _require(set(value) == required, "active candidate source inventory key set drift")
    _require(
        value.get("schema") == "milai.dg10.candidate-source-inventory.v1"
        and value.get("candidate_id") == CANDIDATE,
        "active candidate source inventory identity drift",
    )
    entries = value.get("entries")
    _require(
        isinstance(entries, list)
        and bool(entries)
        and value.get("entry_count") == len(entries),
        "active candidate source inventory denominator drift",
    )
    paths: list[Path] = []
    previous: str | None = None
    for entry in entries:
        _require(
            isinstance(entry, Mapping)
            and set(entry) == {"path", "sha256", "size"},
            "active candidate source inventory entry drift",
        )
        relative = entry.get("path")
        _require(
            isinstance(relative, str)
            and bool(relative)
            and (previous is None or previous < relative),
            "active candidate source inventory order drift",
        )
        previous = relative
        parsed = PurePosixPath(relative)
        _require(
            not parsed.is_absolute() and ".." not in parsed.parts,
            "active candidate source inventory path unsafe",
        )
        target = (ROOT / parsed).absolute()
        _require(
            target.is_relative_to(ROOT.absolute())
            and not remediation.has_symlink_component(target)
            and target.is_file()
            and target.stat().st_size == entry.get("size")
            and remediation.sha256_file(target) == entry.get("sha256"),
            "active candidate source inventory material drift",
        )
        paths.append(target)
    recomputed = remediation.canonical_inventory(paths)
    _require(
        recomputed["canonical_entries_sha256"]
        == value.get("canonical_entries_sha256"),
        "active candidate source inventory root drift",
    )
    return value


def validate(
    scope: str = "contracts", *, active_source_inventory_path: Path | None = None
) -> dict[str, Any]:
    _require(scope in {"contracts", "all"}, "unknown validation scope")
    baseline = remediation.build_baseline_report()
    report: dict[str, Any] = {
        "schema": "milai.dg10.remediation-contract-validation.v1",
        "candidate_id": CANDIDATE,
        "date": DATE,
        "scope": scope,
        "status": "PASS_AUTHOR_CANDIDATE_REVIEW_REQUIRED",
        "independent_acceptance": False,
        "model_run_authorized": False,
        "R0": {
            "status": baseline["status"],
            "open_blocking_findings": baseline["open_blocking_findings"],
        },
        "R1": {
            "claim_matrix": validate_claim_matrix(),
            "acceptance": validate_acceptance(),
            "schemas": validate_schemas(),
            "status": "AUTHOR_CANDIDATE_REVIEW_REQUIRED",
        },
        "external_provider_gate": "OE-F06_OPEN_PARKED",
        "test_access_authorized": False,
        "full_test_execution": "DENIED_NOT_RUN",
    }
    if scope == "all":
        _require(
            active_source_inventory_path is not None,
            "scope all requires the full active candidate source inventory",
        )
        report["source_inventory"] = _active_source_inventory(
            active_source_inventory_path
        )
    return report


def _write_outputs(
    report: Mapping[str, Any],
    *,
    output: Path | None,
    write_baseline: bool,
    write_inventory: bool,
) -> None:
    if output is not None:
        remediation.atomic_write_new(output.absolute(), remediation.encoded_json(report))
    if write_baseline:
        baseline = remediation.build_baseline_report()
        remediation.atomic_write_new(BASELINE_OUTPUT, remediation.encoded_json(baseline))
    if write_inventory:
        inventory = build_source_inventory()
        remediation.atomic_write_new(
            SOURCE_INVENTORY_OUTPUT, remediation.encoded_json(inventory)
        )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Validate DG-10 remediation contracts")
    parser.add_argument("--scope", choices=("contracts", "all"), default="contracts")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--write-inventory", action="store_true")
    parser.add_argument("--active-source-inventory", type=Path)
    args = parser.parse_args(argv)
    report = validate(
        args.scope, active_source_inventory_path=args.active_source_inventory
    )
    _write_outputs(
        report,
        output=args.output,
        write_baseline=args.write_baseline,
        write_inventory=args.write_inventory,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

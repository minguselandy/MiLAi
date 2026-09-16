from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from scripts import dg10_ai_provenance as provenance
from scripts import dg10_remediation as remediation
from scripts import dg10_stage_ledger as stage_ledger

ROOT = remediation.ROOT
BOOTSTRAP_PHASE = "T2_CONTROL_PATH_SMOKE"
POST_R3_PHASE = "POST_R3_MODEL_RUN"
BOOTSTRAP_MODEL_CALLS = 24
REQUIRED_BOOTSTRAP_STAGES = ("DG10-R0", "DG10-R1", "DG10-R2")
REQUIRED_POST_R3_STAGES = (*REQUIRED_BOOTSTRAP_STAGES, "DG10-R3")
POLICY_OVERRIDE = remediation.AI_POLICY_OVERRIDE
R0_R2_AGGREGATE = ROOT / "docs/reviews/DG-10-r0-r2-ai-audit-candidate.4-2026-08-22.json"
R0_R2_AUDIT_ROOT = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-authority-audits"
)
R0_R2_BUNDLE_ROOT = ROOT.parent / "evidence/dg10-candidate4-xhigh-ai-r0-r2-review"
R3_AUDIT_ROOT = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-r3-authority-audits"
)
R3_BUNDLE_ROOT = ROOT.parent / "evidence/dg10-candidate4-xhigh-ai-r3-review"
R3_AGGREGATE = ROOT / "docs/reviews/DG-10-r3-ai-audit-candidate.4-2026-08-22.json"
R3_STAGE_RECEIPT = ROOT / (
    "docs/reviews/DG-10-dg10-r3-ai-stage-receipt-candidate.4-2026-08-22.json"
)
ACTIVE_IDENTITIES = ROOT / (
    "docs/reports/DG-10-authorization-identities-candidate.4.21-2026-08-22.json"
)
REFERENCE_KEYS = {"path", "sha256"}


class AuthorizationError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AuthorizationError(reason)


def _require_nonfatal_ai_stderr(raw: bytes) -> None:
    _require(
        remediation.ai_audit_stderr_is_nonfatal(raw),
        "AI stderr contains an unclassified error",
    )


def _object(path: Path) -> tuple[dict[str, Any], str]:
    _require(
        path.is_file() and not remediation.has_symlink_component(path),
        f"authorization artifact missing or unsafe: {path}",
    )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthorizationError(f"authorization artifact is invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"authorization artifact is not an object: {path}")
    return value, remediation.sha256_file(path)


def _reference(path: Path) -> dict[str, str]:
    lexical = path.absolute()
    _require(
        lexical.is_relative_to(ROOT.absolute())
        and not remediation.has_symlink_component(lexical),
        "authorization artifact escapes repository or has a symlink component",
    )
    resolved = lexical.resolve()
    _require(
        resolved.is_relative_to(ROOT.resolve()),
        "authorization artifact escapes repository",
    )
    return {
        "path": resolved.relative_to(ROOT).as_posix(),
        "sha256": remediation.sha256_file(resolved),
    }


def _verify_reference(value: object) -> Path:
    _require(isinstance(value, Mapping) and set(value) == REFERENCE_KEYS, "artifact reference drift")
    relative = value.get("path")
    _require(isinstance(relative, str) and relative, "artifact reference path absent")
    parsed = PurePosixPath(relative)
    _require(not parsed.is_absolute() and ".." not in parsed.parts, "artifact reference path unsafe")
    lexical = (ROOT / parsed).absolute()
    _require(
        lexical.is_relative_to(ROOT.absolute())
        and not remediation.has_symlink_component(lexical),
        "artifact reference escapes repository or has a symlink component",
    )
    target = lexical.resolve()
    _require(target.is_relative_to(ROOT.resolve()), "artifact reference escapes repository")
    remediation._require_sha256(value.get("sha256"), "artifact reference")
    _require(target.is_file(), "artifact reference is missing or unsafe")
    observed = remediation.sha256_file(target)
    _require(observed == value.get("sha256"), "artifact reference hash drift")
    return target


def _verify_document_reference(value: object) -> tuple[Path, dict[str, Any]]:
    target = _verify_reference(value)
    document, _digest = _object(target)
    return target, document


def _verify_evidence(value: object) -> list[dict[str, str]]:
    _require(isinstance(value, list) and value, "artifact evidence list absent")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        target = _verify_reference(item)
        relative = target.relative_to(ROOT).as_posix()
        _require(relative not in seen, "artifact evidence reference duplicated")
        seen.add(relative)
        normalized.append({"path": relative, "sha256": remediation.sha256_file(target)})
    return normalized


def _verify_source_inventory(reference: object) -> tuple[dict[str, str], str]:
    target, document = _verify_document_reference(reference)
    required = {
        "schema",
        "candidate_id",
        "entry_count",
        "canonical_entries_sha256",
        "entries",
    }
    _require(set(document) == required, "source inventory key set drift")
    _require(document.get("schema") == "milai.dg10.candidate-source-inventory.v1", "source inventory schema drift")
    _require(document.get("candidate_id") == remediation.CANDIDATE, "source inventory candidate drift")
    entries = document.get("entries")
    _require(isinstance(entries, list) and entries, "source inventory entries absent")
    _require(document.get("entry_count") == len(entries), "source inventory denominator drift")
    normalized_paths: list[Path] = []
    previous_path: str | None = None
    for entry in entries:
        _require(
            isinstance(entry, Mapping) and set(entry) == {"path", "sha256", "size"},
            "source inventory entry drift",
        )
        relative = entry.get("path")
        _require(isinstance(relative, str) and relative, "source inventory path absent")
        parsed_source = PurePosixPath(relative)
        _require(
            not parsed_source.is_absolute()
            and ".." not in parsed_source.parts
            and "\\" not in relative,
            "source inventory path is unsafe",
        )
        _require(previous_path is None or previous_path < relative, "source inventory order or uniqueness drift")
        previous_path = relative
        lexical_source = (ROOT / relative).absolute()
        _require(
            not remediation.has_symlink_component(lexical_source),
            "source inventory material has a symlink component",
        )
        source = lexical_source.resolve()
        _require(
            source.is_relative_to(ROOT.resolve()) and source.is_file(),
            "source inventory material missing or unsafe",
        )
        _require(source.stat().st_size == entry.get("size"), "source inventory size drift")
        _require(remediation.sha256_file(source) == entry.get("sha256"), "source inventory hash drift")
        normalized_paths.append(source)
    recomputed = remediation.canonical_inventory(normalized_paths)["canonical_entries_sha256"]
    _require(recomputed == document.get("canonical_entries_sha256"), "source inventory root drift")
    return _reference(target), str(recomputed)


def _verify_identity_artifact(
    reference: object, *, expected_schema: str
) -> tuple[dict[str, str], str]:
    target, document = _verify_document_reference(reference)
    required = {"schema", "candidate_id", "identity_sha256", "evidence"}
    _require(set(document) == required, "identity artifact key set drift")
    _require(document.get("schema") == expected_schema, "identity artifact schema drift")
    _require(document.get("candidate_id") == remediation.CANDIDATE, "identity artifact candidate drift")
    evidence = _verify_evidence(document.get("evidence"))
    identity = remediation.sha256_bytes(remediation.encoded_json({"evidence": evidence}))
    _require(document.get("identity_sha256") == identity, "identity artifact digest drift")
    return _reference(target), identity


def _verify_identity_receipt(path: Path) -> dict[str, Any]:
    document, _digest = _object(path.resolve())
    required = {
        "schema",
        "candidate_id",
        "source_inventory",
        "environment_identity",
        "model_identity",
        "policy_override",
    }
    _require(set(document) == required, "identity receipt key set drift")
    _require(document.get("schema") == "milai.dg10.authorization-identities.v1", "identity receipt schema drift")
    _require(document.get("candidate_id") == remediation.CANDIDATE, "identity receipt candidate drift")
    source_reference, source_root = _verify_source_inventory(document.get("source_inventory"))
    environment_reference, environment_identity = _verify_identity_artifact(
        document.get("environment_identity"),
        expected_schema="milai.dg10.environment-identity.v1",
    )
    model_reference, model_identity = _verify_identity_artifact(
        document.get("model_identity"),
        expected_schema="milai.dg10.model-identity.v1",
    )
    policy_target, policy_document = _verify_document_reference(document.get("policy_override"))
    _require(policy_target == POLICY_OVERRIDE.resolve(), "authorization policy path drift")
    _require(policy_document.get("candidate_id") == remediation.CANDIDATE, "authorization policy candidate drift")
    _require(
        policy_document.get("status") == "USER_AUTHORIZED_POLICY_OVERRIDE_FROZEN",
        "authorization policy is not frozen",
    )
    return {
        "receipt": _reference(path.resolve()),
        "source_inventory": source_reference,
        "source_inventory_sha256": source_root,
        "environment_identity": environment_reference,
        "environment_identity_sha256": environment_identity,
        "model_identity": model_reference,
        "model_identity_sha256": model_identity,
        "policy_override": _reference(policy_target),
    }


def _verify_stage_receipt(path: Path, *, expected_stage: str, identities: Mapping[str, Any]) -> dict[str, Any]:
    if expected_stage == "DG10-R3":
        _require(
            path.resolve() == R3_STAGE_RECEIPT.resolve(),
            "R3 acceptance is not the fixed R3 AI importer output",
        )
    document, _digest = _object(path.resolve())
    required = {
        "schema",
        "candidate_id",
        "stage_id",
        "stage_state",
        "evidence_class",
        "independent_acceptance",
        "source_inventory_sha256",
        "environment_identity_sha256",
        "model_identity_sha256",
        "policy_override_sha256",
        "open_p0",
        "open_p1",
        "evidence",
    }
    _require(set(document) == required, "stage receipt key set drift")
    _require(document.get("schema") == "milai.dg10.stage-receipt.v1", "stage receipt schema drift")
    _require(document.get("candidate_id") == remediation.CANDIDATE, "stage receipt candidate drift")
    _require(document.get("stage_id") == expected_stage, "stage receipt ID drift")
    _require(document.get("stage_state") == "ACCEPTED", "stage receipt is not ACCEPTED")
    _require(document.get("evidence_class") == "AI_INDEPENDENT", "stage receipt is not AI-independent")
    _require(document.get("independent_acceptance") is True, "stage receipt lacks acceptance")
    _require(document.get("open_p0") == 0 and document.get("open_p1") == 0, "stage receipt has open P0/P1")
    for key in (
        "source_inventory_sha256",
        "environment_identity_sha256",
        "model_identity_sha256",
    ):
        _require(document.get(key) == identities.get(key), f"stage receipt identity drift: {key}")
    _require(
        document.get("policy_override_sha256") == identities["policy_override"]["sha256"],
        "stage receipt policy binding drift",
    )
    evidence = _verify_evidence(document.get("evidence"))
    if expected_stage == "DG10-R3":
        aggregate = _verify_r3_aggregate(R3_AGGREGATE, identities)
        _require(
            aggregate["receipt"] in document["evidence"],
            "R3 stage receipt does not bind the fixed imported aggregate",
        )
    return {
        **_reference(path.resolve()),
        "stage_id": expected_stage,
        "evidence_count": len(evidence),
    }


def _verify_primary_ai_run(
    reference: object,
    *,
    expected_bundle_entries_sha256: str,
    expected_bundle_directory_id: str,
    expected_scope: str = "R0_R2_PRIMARY",
) -> dict[str, str]:
    target, document = _verify_document_reference(reference)
    required = {
        "schema",
        "candidate_id",
        "scope",
        "model",
        "reasoning_effort",
        "cli_version",
        "process_exit_code",
        "provider_thread_id",
        "provider_thread_count",
        "turn_completed_count",
        "error_count",
        "output_schema_validation",
        "boundary_validation",
        "decision",
        "open_p0",
        "open_p1",
        "verdict_sha256",
        "raw_evidence_hashes",
        "raw_evidence",
    }
    _require(set(document) == required, "AI run receipt key set drift")
    expected = {
        "schema": "milai.dg10.ai-review-run-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "scope": expected_scope,
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "process_exit_code": 0,
        "provider_thread_count": 1,
        "turn_completed_count": 1,
        "error_count": 0,
        "output_schema_validation": "PASS",
        "boundary_validation": "PASS",
        "decision": "PASS",
        "open_p0": 0,
        "open_p1": 0,
    }
    for key, value in expected.items():
        _require(document.get(key) == value, f"AI run semantic drift: {key}")
    raw_hashes = document.get("raw_evidence_hashes")
    raw_evidence = document.get("raw_evidence")
    expected_hash_keys = {"prompt", "response_schema", "output", "events", "stderr"}
    expected_evidence_keys = {*expected_hash_keys, "process"}
    _require(
        isinstance(raw_hashes, Mapping) and set(raw_hashes) == expected_hash_keys,
        "AI raw hash set drift",
    )
    _require(
        isinstance(raw_evidence, Mapping) and set(raw_evidence) == expected_evidence_keys,
        "AI raw evidence set drift",
    )
    raw_paths = {key: _verify_reference(value) for key, value in raw_evidence.items()}
    for key in expected_hash_keys:
        _require(
            raw_hashes.get(key) == remediation.sha256_file(raw_paths[key]),
            f"AI raw evidence hash drift: {key}",
        )
    _require_nonfatal_ai_stderr(raw_paths["stderr"].read_bytes())
    process, _digest = _object(raw_paths["process"])
    _require(
        process.get("model") == "gpt-5.6-sol"
        and process.get("scope") == expected_scope
        and process.get("reasoning_effort") == "xhigh"
        and process.get("process_exit_code") == 0
        and process.get("sandbox") == "read-only"
        and process.get("ephemeral") is True
        and process.get("ignore_user_config") is True
        and process.get("ignore_rules") is True,
        "AI process provenance drift",
    )
    _require(
        process.get("bundle_directory_id") == expected_bundle_directory_id,
        "AI process bundle identity drift",
    )
    attempt_id = process.get("attempt_id")
    attempt_prefix = (
        "candidate.4-primary-"
        if expected_scope == "R0_R2_PRIMARY"
        else "candidate.4-r3-primary-"
    )
    _require(
        isinstance(attempt_id, str)
        and attempt_id.startswith(attempt_prefix),
        "AI process attempt identity drift",
    )
    if expected_scope == "R0_R2_PRIMARY":
        bundle_root = R0_R2_BUNDLE_ROOT
        audit_root = R0_R2_AUDIT_ROOT
    elif expected_scope == "R3_PRIMARY":
        bundle_root = R3_BUNDLE_ROOT
        audit_root = R3_AUDIT_ROOT
    else:
        raise AuthorizationError("unsupported protected AI run scope")
    provenance.validate_execution_attestation(
        process.get("execution_attestation"),
        bundle=(bundle_root / expected_bundle_directory_id).resolve(),
        output=(audit_root / attempt_id / "review-output.json").resolve(),
        materialized_runner=ROOT / "scripts/run_dg10_candidate4_ai_audit.py",
        process=process,
    )
    process_bindings = {
        "prompt_sha256": "prompt",
        "response_schema_sha256": "response_schema",
        "output_sha256": "output",
        "events_sha256": "events",
        "stderr_sha256": "stderr",
    }
    for process_key, raw_key in process_bindings.items():
        _require(process.get(process_key) == raw_hashes[raw_key], f"AI process binding drift: {process_key}")
    events: list[dict[str, Any]] = []
    for line in raw_paths["events"].read_bytes().splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuthorizationError("AI event stream contains invalid JSON") from exc
        _require(isinstance(item, dict), "AI event is not an object")
        events.append(item)
    threads = [item.get("thread_id") for item in events if item.get("type") == "thread.started"]
    _require(
        threads == [document.get("provider_thread_id")]
        and sum(item.get("type") == "turn.completed" for item in events) == 1
        and not any(item.get("type") in {"error", "turn.failed"} for item in events),
        "AI provider event provenance drift",
    )
    output, _digest = _object(raw_paths["output"])
    if expected_scope == "R0_R2_PRIMARY":
        output_accepted = (
            output.get("overall_disposition")
            == "ACCEPT_R0_R2_FOR_T2_BOOTSTRAP"
            and output.get("open_p0_count") == 0
            and output.get("open_p1_count") == 0
        )
    else:
        output_accepted = (
            output.get("decision") == "ACCEPT_R3"
            and output.get("open_p0_count") == 0
            and output.get("open_p1_count") == 0
        )
    _require(output_accepted, f"AI raw output does not accept {expected_scope}")
    _require(
        output.get("bundle_entries_sha256") == expected_bundle_entries_sha256,
        "AI raw output bundle digest drift",
    )
    final_messages = [
        item["item"]["text"]
        for item in events
        if item.get("type") == "item.completed"
        and isinstance(item.get("item"), Mapping)
        and item["item"].get("type") == "agent_message"
        and isinstance(item["item"].get("text"), str)
    ]
    _require(bool(final_messages), "AI final event absent")
    try:
        final_output = json.loads(final_messages[-1])
    except json.JSONDecodeError as exc:
        raise AuthorizationError("AI final event is not JSON") from exc
    _require(final_output == output, "AI final event/output mismatch")
    remediation._require_sha256(document.get("verdict_sha256"), "AI semantic verdict")
    return {
        **_reference(target),
        "thread_id": str(document["provider_thread_id"]),
        "verdict_sha256": str(document["verdict_sha256"]),
    }


def _verify_r3_aggregate(path: Path, identities: Mapping[str, Any]) -> dict[str, Any]:
    path = path.resolve()
    _require(path == R3_AGGREGATE.resolve(), "R3 aggregate is not fixed importer output")
    document, _digest = _object(path)
    required = {
        "schema",
        "candidate_id",
        "status",
        "evidence_class",
        "policy_override_sha256",
        "identity_receipt",
        "bundle_receipt",
        "primary_audits",
        "provider_thread_count",
        "semantic_verdict_sha256",
        "open_p0",
        "open_p1",
        "model_run_authorized_by_audit",
        "test_access_authorized",
        "release_authorized",
    }
    _require(set(document) == required, "R3 aggregate key set drift")
    _require(
        document.get("schema") == "milai.dg10.r3-ai-audit.v1"
        and document.get("candidate_id") == remediation.CANDIDATE
        and document.get("status") == "AI_INDEPENDENT_R3_ACCEPTED"
        and document.get("evidence_class") == "AI_INDEPENDENT"
        and document.get("provider_thread_count") == 2
        and document.get("open_p0") == 0
        and document.get("open_p1") == 0
        and document.get("model_run_authorized_by_audit") is False
        and document.get("test_access_authorized") is False
        and document.get("release_authorized") is False,
        "R3 aggregate semantic drift",
    )
    _require(
        document.get("policy_override_sha256")
        == identities["policy_override"]["sha256"]
        and document.get("identity_receipt") == identities["receipt"],
        "R3 aggregate identity or policy drift",
    )
    _bundle_path, bundle_receipt = _verify_document_reference(
        document.get("bundle_receipt")
    )
    _require(
        bundle_receipt.get("candidate_id") == remediation.CANDIDATE
        and bundle_receipt.get("minimum_primary_ai_audits") == 2,
        "R3 review bundle receipt drift",
    )
    remediation._require_sha256(
        bundle_receipt.get("bundle_entries_sha256"), "R3 bundle entries"
    )
    bundle_id = bundle_receipt.get("bundle_directory_id")
    _require(isinstance(bundle_id, str) and bundle_id, "R3 bundle identity absent")
    audits = document.get("primary_audits")
    _require(isinstance(audits, list) and len(audits) == 2, "R3 primary audit denominator drift")
    verified = [
        _verify_primary_ai_run(
            item,
            expected_bundle_entries_sha256=bundle_receipt["bundle_entries_sha256"],
            expected_bundle_directory_id=bundle_id,
            expected_scope="R3_PRIMARY",
        )
        for item in audits
    ]
    _require(len({item["thread_id"] for item in verified}) == 2, "R3 AI threads are not distinct")
    _require(
        len({item["verdict_sha256"] for item in verified}) == 1
        and document.get("semantic_verdict_sha256") == verified[0]["verdict_sha256"],
        "R3 AI semantic verdict drift",
    )
    return {"receipt": _reference(path), "primary_audits": verified}


def _verify_r0_r2_aggregate(path: Path, identities: Mapping[str, Any]) -> dict[str, Any]:
    path = path.resolve()
    _require(path == R0_R2_AGGREGATE.resolve(), "R0-R2 aggregate is not the fixed importer output")
    document, _digest = _object(path)
    required = {
        "schema",
        "candidate_id",
        "status",
        "evidence_class",
        "human_evidence_claimed",
        "policy_override_sha256",
        "identity_receipt",
        "bundle_receipt",
        "primary_audits",
        "provider_thread_count",
        "semantic_verdict_sha256",
        "stage_receipts",
        "stage_ledger_checkpoint",
        "accepted_stages",
        "open_p0",
        "open_p1",
        "model_run_authorized_by_audit",
        "test_access_authorized",
        "release_authorized",
    }
    _require(set(document) == required, "R0-R2 aggregate key set drift")
    _require(
        document.get("schema") == "milai.dg10.r0-r2-ai-audit.v1"
        and document.get("candidate_id") == remediation.CANDIDATE
        and document.get("status")
        == "AI_INDEPENDENT_R0_R2_ACCEPTED_FOR_EXACT_T2_BOOTSTRAP"
        and document.get("evidence_class") == "AI_INDEPENDENT"
        and document.get("human_evidence_claimed") is False
        and document.get("provider_thread_count") == 2
        and document.get("accepted_stages") == list(REQUIRED_BOOTSTRAP_STAGES)
        and document.get("open_p0") == 0
        and document.get("open_p1") == 0
        and document.get("model_run_authorized_by_audit") is False
        and document.get("test_access_authorized") is False
        and document.get("release_authorized") is False,
        "R0-R2 aggregate semantic drift",
    )
    _require(
        document.get("policy_override_sha256") == identities["policy_override"]["sha256"]
        and document.get("identity_receipt") == identities["receipt"],
        "R0-R2 aggregate identity or policy drift",
    )
    bundle_target, bundle_receipt = _verify_document_reference(
        document.get("bundle_receipt")
    )
    _require(
        bundle_receipt.get("schema")
        == "milai.dg10.candidate4-ai-review-bundle-receipt.v1"
        and bundle_receipt.get("candidate_id") == remediation.CANDIDATE
        and bundle_receipt.get("minimum_primary_ai_audits") == 2,
        "R0-R2 review bundle receipt drift",
    )
    remediation._require_sha256(
        bundle_receipt.get("bundle_entries_sha256"), "R0-R2 bundle entries"
    )
    _require(
        isinstance(bundle_receipt.get("bundle_directory_id"), str)
        and bundle_receipt["bundle_directory_id"],
        "R0-R2 bundle directory identity absent",
    )
    audits = document.get("primary_audits")
    _require(isinstance(audits, list) and len(audits) == 2, "R0-R2 primary audit denominator drift")
    verified_audits = [
        _verify_primary_ai_run(
            item,
            expected_bundle_entries_sha256=bundle_receipt[
                "bundle_entries_sha256"
            ],
            expected_bundle_directory_id=bundle_receipt["bundle_directory_id"],
        )
        for item in audits
    ]
    _require(len({item["thread_id"] for item in verified_audits}) == 2, "R0-R2 AI threads are not distinct")
    _require(
        len({item["verdict_sha256"] for item in verified_audits}) == 1
        and document.get("semantic_verdict_sha256") == verified_audits[0]["verdict_sha256"],
        "R0-R2 AI semantic verdict drift",
    )
    stages = document.get("stage_receipts")
    _require(isinstance(stages, list) and len(stages) == 3, "R0-R2 stage receipt denominator drift")
    verified_stages: list[dict[str, Any]] = []
    for stage, reference in zip(REQUIRED_BOOTSTRAP_STAGES, stages, strict=True):
        stage_path = _verify_reference(reference)
        verified_stages.append(
            _verify_stage_receipt(stage_path, expected_stage=stage, identities=identities)
        )
    checkpoint_path = _verify_reference(document.get("stage_ledger_checkpoint"))
    try:
        stage_reconciliation = stage_ledger.verify_checkpoint(
            checkpoint_path,
            required_stages=REQUIRED_BOOTSTRAP_STAGES,
            required_state="ACCEPTED",
        )
    except stage_ledger.StageLedgerError as exc:
        raise AuthorizationError(str(exc)) from exc
    for stage, receipt in zip(REQUIRED_BOOTSTRAP_STAGES, verified_stages, strict=True):
        current = stage_reconciliation["current_entries"][stage]
        _require(current["receipt"] == {key: receipt[key] for key in REFERENCE_KEYS}, "stage ledger receipt binding drift")
        _require(
            current["source_inventory_sha256"] == identities["source_inventory_sha256"],
            "stage ledger source identity drift",
        )
    return {
        "receipt": _reference(path),
        "bundle_receipt": _reference(bundle_target),
        "stage_receipts": verified_stages,
        "stage_ledger_checkpoint": _reference(checkpoint_path),
        "stage_ledger_reconciliation": stage_reconciliation,
        "primary_audits": verified_audits,
    }


def _authorization_digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "authorization_payload_sha256"}
    return remediation.sha256_bytes(remediation.encoded_json(payload))


def _bootstrap_call_slots(
    identities: Mapping[str, Any], aggregate: Mapping[str, Any]
) -> list[str]:
    seed = remediation.sha256_bytes(
        remediation.encoded_json(
            {
                "candidate_id": remediation.CANDIDATE,
                "phase": BOOTSTRAP_PHASE,
                "identity_receipt": identities["receipt"],
                "r0_r2_aggregate": aggregate["receipt"],
                "policy_override": identities["policy_override"],
            }
        )
    )
    return [f"dg10-t2-{seed[:16]}-slot-{index:02d}" for index in range(1, 25)]


def evaluate_first_model_authorization(
    *,
    phase: str,
    planned_model_calls: int,
    r0_r2_aggregate_path: Path | None,
    post_r3_stage_receipt_path: Path | None = None,
    identity_receipt_path: Path | None,
    test_access_requested: bool,
) -> dict[str, Any]:
    _require(phase in {BOOTSTRAP_PHASE, POST_R3_PHASE}, "unknown model authorization phase")
    required_stages = (
        REQUIRED_BOOTSTRAP_STAGES if phase == BOOTSTRAP_PHASE else REQUIRED_POST_R3_STAGES
    )
    reason_codes: list[str] = []
    if phase == BOOTSTRAP_PHASE and planned_model_calls != BOOTSTRAP_MODEL_CALLS:
        reason_codes.append("BOOTSTRAP_CALL_DENOMINATOR_DRIFT")
    if (
        not isinstance(planned_model_calls, int)
        or isinstance(planned_model_calls, bool)
        or planned_model_calls <= 0
    ):
        reason_codes.append("PLANNED_MODEL_CALL_COUNT_INVALID")
    if test_access_requested:
        reason_codes.append("TEST_ACCESS_FORBIDDEN_DURING_MODEL_AUTHORIZATION")
    identities: dict[str, Any] | None = None
    if identity_receipt_path is None:
        reason_codes.append("SOURCE_ENVIRONMENT_MODEL_IDENTITY_RECEIPT_ABSENT")
    else:
        _require(
            identity_receipt_path.resolve() == ACTIVE_IDENTITIES.resolve(),
            "model authorization requires the fixed active identity receipt",
        )
        identities = _verify_identity_receipt(identity_receipt_path)
    aggregate: dict[str, Any] | None = None
    stage_receipts: list[dict[str, Any]] = []
    if r0_r2_aggregate_path is None:
        reason_codes.append("FIXED_R0_R2_IMPORT_AGGREGATE_ABSENT")
    elif identities is not None:
        aggregate = _verify_r0_r2_aggregate(r0_r2_aggregate_path, identities)
        stage_receipts = list(aggregate["stage_receipts"])
    if phase == POST_R3_PHASE:
        if post_r3_stage_receipt_path is None or identities is None:
            reason_codes.append("REQUIRED_R3_STAGE_RECEIPT_ABSENT")
        else:
            stage_receipts.append(
                _verify_stage_receipt(
                    post_r3_stage_receipt_path,
                    expected_stage="DG10-R3",
                    identities=identities,
                )
            )
    call_slots = (
        _bootstrap_call_slots(identities, aggregate)
        if phase == BOOTSTRAP_PHASE
        and identities is not None
        and aggregate is not None
        and not reason_codes
        else []
    )
    result: dict[str, Any] = {
        "schema": "milai.dg10.model-authorization.v2",
        "candidate_id": remediation.CANDIDATE,
        "phase": phase,
        "planned_model_calls": planned_model_calls,
        "test_access_requested": test_access_requested,
        "required_stages": list(required_stages),
        "stage_receipts": stage_receipts,
        "r0_r2_aggregate": aggregate,
        "identities": identities,
        "call_slots": call_slots,
        "call_slot_manifest_sha256": (
            remediation.sha256_bytes(remediation.encoded_json({"call_slots": call_slots}))
            if call_slots
            else None
        ),
        "authorized": not reason_codes,
        "reason_codes": reason_codes,
    }
    result["authorization_payload_sha256"] = _authorization_digest(result)
    return result


def require_first_model_authorization(receipt: Mapping[str, Any]) -> None:
    required = {
        "schema",
        "candidate_id",
        "phase",
        "planned_model_calls",
        "test_access_requested",
        "required_stages",
        "stage_receipts",
        "r0_r2_aggregate",
        "identities",
        "call_slots",
        "call_slot_manifest_sha256",
        "authorized",
        "reason_codes",
        "authorization_payload_sha256",
    }
    _require(set(receipt) == required, "model authorization key set drift")
    _require(receipt.get("schema") == "milai.dg10.model-authorization.v2", "model authorization schema drift")
    _require(receipt.get("candidate_id") == remediation.CANDIDATE, "model authorization candidate drift")
    _require(receipt.get("authorization_payload_sha256") == _authorization_digest(receipt), "model authorization digest drift")
    identities = receipt.get("identities")
    aggregate = receipt.get("r0_r2_aggregate")
    _require(isinstance(identities, Mapping), "model authorization identities absent")
    _require(isinstance(aggregate, Mapping), "model authorization R0-R2 aggregate absent")
    identity_reference = identities.get("receipt")
    _require(isinstance(identity_reference, Mapping), "identity receipt reference absent")
    recomputed = evaluate_first_model_authorization(
        phase=str(receipt.get("phase")),
        planned_model_calls=receipt.get("planned_model_calls"),
        r0_r2_aggregate_path=ROOT / str(aggregate["receipt"]["path"]),
        post_r3_stage_receipt_path=(
            ROOT / str(receipt["stage_receipts"][-1]["path"])
            if receipt.get("phase") == POST_R3_PHASE
            and isinstance(receipt.get("stage_receipts"), list)
            and receipt["stage_receipts"]
            else None
        ),
        identity_receipt_path=ROOT / str(identity_reference["path"]),
        test_access_requested=receipt.get("test_access_requested") is True,
    )
    _require(dict(receipt) == recomputed, "model authorization does not match bound artifacts")
    _require(receipt.get("authorized") is True and receipt.get("reason_codes") == [], "DG-10 model authorization is not satisfied")


def authorized_bootstrap_slots(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    require_first_model_authorization(receipt)
    _require(receipt.get("phase") == BOOTSTRAP_PHASE, "authorization is not for T2 bootstrap")
    slots = receipt.get("call_slots")
    _require(
        isinstance(slots, list)
        and len(slots) == BOOTSTRAP_MODEL_CALLS
        and len(set(slots)) == BOOTSTRAP_MODEL_CALLS,
        "bootstrap call slot manifest drift",
    )
    _require(
        receipt.get("call_slot_manifest_sha256")
        == remediation.sha256_bytes(remediation.encoded_json({"call_slots": slots})),
        "bootstrap call slot digest drift",
    )
    return tuple(str(slot) for slot in slots)

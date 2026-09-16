from __future__ import annotations

import argparse
import json
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_ai_provenance as provenance
from scripts import dg10_remediation as remediation
from scripts import dg10_stage_ledger as stage_ledger
from scripts.build_dg10_candidate4_ai_review_bundle import (
    DEFAULT_OUTPUT_ROOT,
    PARENT_FINDINGS,
)

POLICY = remediation.AI_POLICY_OVERRIDE
DEFAULT_BUNDLE_RECEIPT = ROOT / "docs/reports/DG-10-r0-r2-ai-review-bundle-candidate.4.18-2026-08-22.json"
DEFAULT_IDENTITIES = ROOT / "docs/reports/DG-10-authorization-identities-candidate.4.21-2026-08-22.json"
DEFAULT_OUTPUT_DIRECTORY = ROOT / "docs/reviews"
DEFAULT_AUDIT_ROOT = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-authority-audits"
)
STAGES = ("DG10-R0", "DG10-R1", "DG10-R2")
OUTPUT_KEYS = {
    "schema_version",
    "review_type",
    "authority",
    "candidate_id",
    "model_requested",
    "audit_role",
    "bundle_entries_sha256",
    "closed_set_boundary",
    "manifest_validation",
    "source_inventory_validation",
    "parent_finding_closures",
    "stage_assessments",
    "bootstrap_policy_disposition",
    "findings",
    "open_p0_count",
    "open_p1_count",
    "open_p2_count",
    "overall_disposition",
    "inspected_paths",
    "reproduction_commands",
}


class AuditImportError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AuditImportError(reason)


def _require_nonfatal_ai_stderr(raw: bytes) -> None:
    _require(
        remediation.ai_audit_stderr_is_nonfatal(raw),
        "AI audit stderr contains an unclassified error",
    )


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditImportError(f"invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def _reference(path: Path) -> dict[str, str]:
    path = path.resolve()
    _require(path.is_relative_to(ROOT) and path.is_file() and not path.is_symlink(), "evidence unsafe")
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": remediation.sha256_file(path)}


def _bundle_file(bundle: Path, value: object, manifest_paths: set[str]) -> Path:
    _require(isinstance(value, str) and value, "audit evidence path invalid")
    parsed = PurePosixPath(value)
    _require(not parsed.is_absolute() and ".." not in parsed.parts, "audit evidence path unsafe")
    _require(value in manifest_paths or value == "review-manifest.json", "audit cites unbound path")
    target = (bundle / value).resolve()
    _require(target.is_relative_to(bundle) and target.is_file() and not target.is_symlink(), "audit evidence absent")
    return target


def _verify_bundle(bundle: Path, receipt: Mapping[str, Any]) -> tuple[dict[str, Any], set[str]]:
    bundle = bundle.resolve()
    _require(
        bundle.is_dir()
        and not bundle.is_symlink()
        and bundle.name == receipt.get("bundle_directory_id"),
        "review bundle identity drift",
    )
    manifest = _object(bundle / "review-manifest.json")
    _require(
        manifest.get("schema") == "milai.dg10.candidate4-ai-review-manifest.v1"
        and manifest.get("candidate_id") == remediation.CANDIDATE
        and remediation.sha256_file(bundle / "review-manifest.json") == receipt.get("manifest_sha256"),
        "review manifest identity drift",
    )
    entries = manifest.get("entries")
    _require(isinstance(entries, list) and manifest.get("entry_count") == len(entries), "bundle denominator drift")
    observed: list[dict[str, Any]] = []
    paths: set[str] = set()
    for entry in entries:
        _require(
            isinstance(entry, Mapping)
            and set(entry) == {"path", "source_class", "size", "sha256"},
            "bundle entry schema drift",
        )
        relative = entry.get("path")
        _require(isinstance(relative, str) and relative not in paths, "bundle entry path invalid")
        paths.add(relative)
        target = _bundle_file(bundle, relative, paths)
        row = {
            "path": relative,
            "source_class": entry.get("source_class"),
            "size": target.stat().st_size,
            "sha256": remediation.sha256_file(target),
        }
        _require(row == dict(entry), f"bundle entry drift: {relative}")
        _require(stat.S_IMODE(target.stat().st_mode) == 0o444, "bundle file is writable")
        observed.append(row)
    aggregate = remediation.sha256_bytes(remediation.encoded_json({"entries": observed}))
    _require(
        aggregate == manifest.get("bundle_entries_sha256") == receipt.get("bundle_entries_sha256")
        and len(entries) == receipt.get("entry_count"),
        "bundle aggregate drift",
    )
    return manifest, paths


def _list(value: object, reason: str) -> list[Any]:
    _require(isinstance(value, list), reason)
    return value


def _validate_paths(
    bundle: Path, paths: object, manifest_paths: set[str], *, nonempty: bool
) -> list[str]:
    values = _list(paths, "audit path list invalid")
    _require(not nonempty or bool(values), "audit evidence path list empty")
    _require(len(values) == len(set(values)), "audit evidence path repeats")
    for value in values:
        _bundle_file(bundle, value, manifest_paths)
    return [str(value) for value in values]


def _validate_output(
    value: dict[str, Any],
    *,
    bundle: Path,
    manifest: Mapping[str, Any],
    manifest_paths: set[str],
    manifest_sha256: str,
) -> str:
    _require(set(value) == OUTPUT_KEYS, "AI output key set drift")
    expected = {
        "schema_version": "1.0",
        "review_type": "AI_BLIND_SEMANTIC_AUDIT",
        "authority": "AI_INDEPENDENT_PER_USER_POLICY",
        "candidate_id": remediation.CANDIDATE,
        "model_requested": "gpt-5.6-sol",
        "audit_role": "PRIMARY",
        "bundle_entries_sha256": manifest["bundle_entries_sha256"],
    }
    for key, item in expected.items():
        _require(value.get(key) == item, f"AI output invariant drift: {key}")
    boundary = value.get("closed_set_boundary")
    boundary_keys = {
        "repository_accessed",
        "network_accessed",
        "runtime_or_socket_accessed",
        "external_protected_archive_accessed",
        "materialized_historical_archive_inspected",
        "prior_candidate4_review_read",
        "semantic_scope_compliant",
        "limitations",
    }
    _require(isinstance(boundary, Mapping) and set(boundary) == boundary_keys, "AI boundary schema drift")
    _require(
        boundary.get("repository_accessed") is False
        and boundary.get("network_accessed") is False
        and boundary.get("runtime_or_socket_accessed") is False
        and boundary.get("external_protected_archive_accessed") is False
        and boundary.get("prior_candidate4_review_read") is False
        and boundary.get("semantic_scope_compliant") is True,
        "AI closed-set boundary failed",
    )
    _require(isinstance(boundary.get("limitations"), list), "AI boundary limitations invalid")

    validation = value.get("manifest_validation")
    _require(
        isinstance(validation, Mapping)
        and set(validation)
        == {
            "status",
            "entry_count",
            "bundle_entries_sha256_recomputed",
            "review_manifest_sha256_recomputed",
            "mismatches",
        }
        and validation.get("status") == "PASS"
        and validation.get("entry_count") == manifest["entry_count"]
        and validation.get("bundle_entries_sha256_recomputed") == manifest["bundle_entries_sha256"]
        and validation.get("review_manifest_sha256_recomputed") == manifest_sha256
        and validation.get("mismatches") == [],
        "AI manifest replay failed",
    )
    source = value.get("source_inventory_validation")
    closure = manifest.get("closure")
    _require(
        isinstance(source, Mapping)
        and set(source)
        == {"status", "entry_count", "canonical_entries_sha256_recomputed", "mismatches"}
        and isinstance(closure, Mapping)
        and source.get("status") == "PASS"
        and source.get("entry_count") == closure.get("source_entry_count")
        and source.get("canonical_entries_sha256_recomputed") == closure.get("source_entries_sha256")
        and source.get("mismatches") == [],
        "AI source replay failed",
    )

    closures = _list(value.get("parent_finding_closures"), "parent closure list invalid")
    _require(len(closures) == len(PARENT_FINDINGS), "parent finding closure denominator drift")
    closure_status: dict[str, str] = {}
    for item in closures:
        _require(
            isinstance(item, Mapping)
            and set(item) == {"finding_id", "status", "rationale", "evidence_paths"},
            "parent closure entry drift",
        )
        finding_id = item.get("finding_id")
        _require(
            finding_id in PARENT_FINDINGS and finding_id not in closure_status,
            "parent closure ID invalid",
        )
        _require(item.get("status") in {"CLOSED", "OPEN"}, "parent closure status invalid")
        _require(isinstance(item.get("rationale"), str) and item["rationale"], "parent closure rationale absent")
        _validate_paths(bundle, item.get("evidence_paths"), manifest_paths, nonempty=True)
        closure_status[str(finding_id)] = str(item["status"])

    assessments = value.get("stage_assessments")
    _require(isinstance(assessments, Mapping) and set(assessments) == set(STAGES), "stage set drift")
    decisions: dict[str, str] = {}
    for stage in STAGES:
        item = assessments[stage]
        _require(
            isinstance(item, Mapping)
            and set(item) == {"decision", "rationale", "evidence_paths"}
            and item.get("decision") in {"ACCEPTED", "REVISE"}
            and isinstance(item.get("rationale"), str)
            and bool(item["rationale"]),
            "stage assessment drift",
        )
        _validate_paths(bundle, item.get("evidence_paths"), manifest_paths, nonempty=True)
        decisions[stage] = str(item["decision"])

    findings = _list(value.get("findings"), "AI finding list invalid")
    finding_counts = {"P0": 0, "P1": 0, "P2": 0}
    finding_ids: set[str] = set()
    finding_keys = {
        "finding_id",
        "severity",
        "status",
        "category",
        "title",
        "rationale",
        "evidence_paths",
        "affected_stages",
        "required_action",
    }
    for item in findings:
        _require(isinstance(item, Mapping) and set(item) == finding_keys, "AI finding schema drift")
        finding_id = item.get("finding_id")
        severity = item.get("severity")
        status_value = item.get("status")
        _require(isinstance(finding_id, str) and finding_id and finding_id not in finding_ids, "finding ID invalid")
        finding_ids.add(finding_id)
        _require(severity in {"P0", "P1", "P2", "P3"}, "finding severity invalid")
        _require(status_value in {"OPEN", "CLOSED", "ACCEPTED_RISK"}, "finding status invalid")
        _validate_paths(bundle, item.get("evidence_paths"), manifest_paths, nonempty=True)
        _require(isinstance(item.get("affected_stages"), list), "finding stage list invalid")
        for key in ("category", "title", "rationale", "required_action"):
            _require(isinstance(item.get(key), str) and item[key], f"finding {key} absent")
        if status_value == "OPEN" and severity in finding_counts:
            finding_counts[str(severity)] += 1
    _require(
        value.get("open_p0_count") == finding_counts["P0"]
        and value.get("open_p1_count") == finding_counts["P1"]
        and value.get("open_p2_count") == finding_counts["P2"],
        "AI open finding counts drift",
    )
    for finding_id, status_value in closure_status.items():
        if status_value == "OPEN":
            _require(finding_id in finding_ids, "open parent finding omitted from finding list")
    _validate_paths(bundle, value.get("inspected_paths"), manifest_paths, nonempty=True)
    commands = _list(value.get("reproduction_commands"), "reproduction command list invalid")
    _require(
        all(
            isinstance(command, str)
            and command
            and ".." not in command
            and not any(token in command for token in ("curl ", "wget ", "rm ", "chmod ", "git ", ">"))
            for command in commands
        ),
        "reproduction command violates read-only boundary",
    )

    accepted = value.get("overall_disposition") == "ACCEPT_R0_R2_FOR_T2_BOOTSTRAP"
    if accepted:
        _require(
            boundary.get("materialized_historical_archive_inspected") is True
            and set(decisions.values()) == {"ACCEPTED"}
            and set(closure_status.values()) == {"CLOSED"}
            and value.get("open_p0_count") == 0
            and value.get("open_p1_count") == 0
            and value.get("bootstrap_policy_disposition")
            == "CANDIDATE4_R0_R2_ACCEPTS_EXACT_24_CALL_T2_BOOTSTRAP",
            "AI acceptance conditions are inconsistent",
        )
    else:
        _require(
            value.get("overall_disposition") == "REVISE"
            and value.get("bootstrap_policy_disposition")
            == "REVISE_R0_R2_AND_DO_NOT_AUTHORIZE_ANY_MODEL_CALL",
            "AI revise disposition is inconsistent",
        )
    semantic = {
        "overall": value["overall_disposition"],
        "bootstrap": value["bootstrap_policy_disposition"],
        "stages": decisions,
        "parent_closures": closure_status,
        "open_p0": value["open_p0_count"],
        "open_p1": value["open_p1_count"],
    }
    return remediation.sha256_bytes(remediation.encoded_json(semantic))


def _validate_attempt(
    attempt: Path,
    *,
    bundle: Path,
    manifest: Mapping[str, Any],
    manifest_paths: set[str],
    manifest_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    attempt = attempt.resolve()
    _require(
        attempt.parent == DEFAULT_AUDIT_ROOT.resolve()
        and attempt.name.startswith("candidate.4-primary-"),
        "AI attempt is outside the fixed protected audit root",
    )
    _require(attempt.is_dir() and stat.S_IMODE(attempt.stat().st_mode) == 0o700, "attempt dir unsafe")
    files = {name: attempt / name for name in ("process.json", "review-output.json", "events.jsonl", "stderr.log")}
    _require(
        all(path.is_file() and not path.is_symlink() and stat.S_IMODE(path.stat().st_mode) == 0o600 for path in files.values()),
        "AI attempt file absent or mode drift",
    )
    process = _object(files["process.json"])
    process_keys = {
        "schema",
        "candidate_id",
        "attempt_id",
        "scope",
        "audit_role",
        "model",
        "reasoning_effort",
        "cli_version",
        "process_exit_code",
        "termination_reason",
        "timeout_seconds",
        "bundle_directory_id",
        "prompt_sha256",
        "response_schema_sha256",
        "events_sha256",
        "stderr_sha256",
        "output_sha256",
        "sandbox",
        "ephemeral",
        "ignore_user_config",
        "ignore_rules",
        "execution_attestation",
    }
    _require(set(process) == process_keys, "AI process metadata key set drift")
    expected = {
        "schema": "milai.dg10.ai-audit-process.v1",
        "candidate_id": remediation.CANDIDATE,
        "scope": "R0_R2_PRIMARY",
        "audit_role": "PRIMARY",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "process_exit_code": 0,
        "termination_reason": "COMPLETED",
        "bundle_directory_id": bundle.name,
        "sandbox": "read-only",
        "ephemeral": True,
        "ignore_user_config": True,
        "ignore_rules": True,
    }
    for key, item in expected.items():
        _require(process.get(key) == item, f"AI process invariant drift: {key}")
    _require(isinstance(process.get("cli_version"), str) and process["cli_version"], "AI CLI absent")
    _require(
        isinstance(process.get("timeout_seconds"), int)
        and not isinstance(process["timeout_seconds"], bool)
        and 60 <= process["timeout_seconds"] <= 3600,
        "AI process timeout metadata drift",
    )
    hash_bindings = {
        "prompt_sha256": bundle / "audit-prompt.md",
        "response_schema_sha256": bundle / "audit-response.schema.json",
        "events_sha256": files["events.jsonl"],
        "stderr_sha256": files["stderr.log"],
        "output_sha256": files["review-output.json"],
    }
    for key, path in hash_bindings.items():
        _require(process.get(key) == remediation.sha256_file(path), f"AI raw hash drift: {key}")
    provenance.validate_execution_attestation(
        process.get("execution_attestation"),
        bundle=bundle,
        output=files["review-output.json"],
        materialized_runner=(
            bundle / "current-source/scripts/run_dg10_candidate4_ai_audit.py"
        ),
        process=process,
    )
    _require_nonfatal_ai_stderr(files["stderr.log"].read_bytes())

    events: list[dict[str, Any]] = []
    for raw in files["events.jsonl"].read_bytes().splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuditImportError("AI event stream contains invalid JSON") from exc
        _require(isinstance(event, dict), "AI event is not an object")
        events.append(event)
    threads = [event.get("thread_id") for event in events if event.get("type") == "thread.started"]
    _require(len(threads) == 1 and isinstance(threads[0], str) and threads[0], "AI thread cardinality drift")
    _require(sum(event.get("type") == "turn.completed" for event in events) == 1, "AI completed turn drift")
    _require(
        not any(event.get("type") in {"error", "turn.failed"} for event in events),
        "AI event stream reports failure",
    )
    value = _object(files["review-output.json"])
    final_messages = [
        event["item"]["text"]
        for event in events
        if event.get("type") == "item.completed"
        and isinstance(event.get("item"), Mapping)
        and event["item"].get("type") == "agent_message"
        and isinstance(event["item"].get("text"), str)
    ]
    _require(bool(final_messages), "AI event stream has no agent message")
    try:
        final_value = json.loads(final_messages[-1])
    except json.JSONDecodeError as exc:
        raise AuditImportError("AI final event message is not JSON") from exc
    _require(final_value == value, "AI output differs from final event message")
    semantic_sha256 = _validate_output(
        value,
        bundle=bundle,
        manifest=manifest,
        manifest_paths=manifest_paths,
        manifest_sha256=manifest_sha256,
    )
    raw_hashes = {
        "prompt": process["prompt_sha256"],
        "response_schema": process["response_schema_sha256"],
        "output": process["output_sha256"],
        "events": process["events_sha256"],
        "stderr": process["stderr_sha256"],
    }
    run_receipt = {
        "schema": "milai.dg10.ai-review-run-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "scope": "R0_R2_PRIMARY",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "cli_version": process["cli_version"],
        "process_exit_code": 0,
        "provider_thread_id": threads[0],
        "provider_thread_count": 1,
        "turn_completed_count": 1,
        "error_count": 0,
        "output_schema_validation": "PASS",
        "boundary_validation": "PASS",
        "decision": "PASS" if value["overall_disposition"] == "ACCEPT_R0_R2_FOR_T2_BOOTSTRAP" else "REVISE",
        "open_p0": value["open_p0_count"],
        "open_p1": value["open_p1_count"],
        "verdict_sha256": semantic_sha256,
        "raw_evidence_hashes": raw_hashes,
    }
    return value, run_receipt, semantic_sha256


def _identity_values(identity_receipt: Path) -> dict[str, Any]:
    receipt = _object(identity_receipt)
    _require(
        receipt.get("schema") == "milai.dg10.authorization-identities.v1"
        and receipt.get("candidate_id") == remediation.CANDIDATE,
        "authorization identity receipt drift",
    )
    result: dict[str, Any] = {"identity_receipt": _reference(identity_receipt)}
    for key in ("source_inventory", "environment_identity", "model_identity", "policy_override"):
        reference = receipt.get(key)
        _require(isinstance(reference, Mapping) and set(reference) == {"path", "sha256"}, "identity reference drift")
        target = (ROOT / str(reference["path"])).resolve()
        _require(_reference(target) == dict(reference), "identity reference hash drift")
        document = _object(target)
        if key == "source_inventory":
            result["source_inventory_sha256"] = document.get("canonical_entries_sha256")
        elif key.endswith("_identity"):
            result[f"{key}_sha256"] = document.get("identity_sha256")
        else:
            result["policy_override_sha256"] = reference["sha256"]
    for key in (
        "source_inventory_sha256",
        "environment_identity_sha256",
        "model_identity_sha256",
        "policy_override_sha256",
    ):
        remediation._require_sha256(result.get(key), key)
    return result


def import_audits(
    *,
    bundle: Path,
    bundle_receipt_path: Path,
    identity_receipt_path: Path,
    attempt_paths: Sequence[Path],
    output_directory: Path,
) -> dict[str, Any]:
    _require(len(attempt_paths) == 2, "exactly two primary AI audit attempts required")
    _require(
        bundle_receipt_path.resolve() == DEFAULT_BUNDLE_RECEIPT.resolve()
        and identity_receipt_path.resolve() == DEFAULT_IDENTITIES.resolve(),
        "AI importer requires the fixed active bundle and identity receipts",
    )
    bundle_receipt = _object(bundle_receipt_path.resolve())
    _require(
        bundle_receipt.get("schema") == "milai.dg10.candidate4-ai-review-bundle-receipt.v1"
        and bundle_receipt.get("candidate_id") == remediation.CANDIDATE
        and bundle_receipt.get("minimum_primary_ai_audits") == 2,
        "AI review bundle receipt drift",
    )
    manifest, manifest_paths = _verify_bundle(bundle, bundle_receipt)
    _require(
        bundle.resolve()
        == (DEFAULT_OUTPUT_ROOT / str(bundle_receipt["bundle_directory_id"])).resolve(),
        "AI importer bundle path substitution",
    )
    manifest_sha256 = remediation.sha256_file(bundle.resolve() / "review-manifest.json")
    validated = [
        _validate_attempt(
            path,
            bundle=bundle.resolve(),
            manifest=manifest,
            manifest_paths=manifest_paths,
            manifest_sha256=manifest_sha256,
        )
        for path in attempt_paths
    ]
    outputs = [item[0] for item in validated]
    run_receipts = [item[1] for item in validated]
    semantic_hashes = [item[2] for item in validated]
    _require(
        len({receipt["provider_thread_id"] for receipt in run_receipts}) == 2,
        "primary AI provider threads are not distinct",
    )
    _require(len(set(semantic_hashes)) == 1, "primary AI verdict conflict requires third adjudication")
    _require(
        all(output["overall_disposition"] == "ACCEPT_R0_R2_FOR_T2_BOOTSTRAP" for output in outputs),
        "primary AI audit requires remediation",
    )
    identities = _identity_values(identity_receipt_path.resolve())
    identity_document = _object(identity_receipt_path.resolve())
    source_reference = identity_document.get("source_inventory")
    _require(
        isinstance(source_reference, Mapping),
        "active identity source reference absent",
    )
    source_document = _object((ROOT / str(source_reference["path"])).resolve())
    source_entries = source_document.get("entries")
    _require(isinstance(source_entries, list), "active source inventory entries absent")
    bundle_source_entries = [
        {
            "path": str(entry["path"])[len("current-source/") :],
            "sha256": entry["sha256"],
            "size": entry["size"],
        }
        for entry in manifest["entries"]
        if entry.get("source_class") == "CANDIDATE4_SOURCE"
        and str(entry.get("path", "")).startswith("current-source/")
    ]
    _require(
        bundle_source_entries == source_entries
        and manifest.get("closure", {}).get("source_entries_sha256")
        == identities["source_inventory_sha256"],
        "AI review bundle source closure differs from the active identity",
    )
    _require(
        identities["policy_override_sha256"] == remediation.sha256_file(POLICY),
        "AI policy override binding drift",
    )
    output_directory = output_directory.resolve()
    _require(output_directory.is_relative_to(ROOT), "AI receipt output escapes repository")
    run_paths = [
        output_directory / f"DG-10-r0-r2-ai-primary-{index}-candidate.4-2026-08-22.json"
        for index in (1, 2)
    ]
    stage_paths = {
        stage: output_directory
        / f"DG-10-{stage.lower()}-ai-stage-receipt-candidate.4-2026-08-22.json"
        for stage in STAGES
    }
    aggregate_path = output_directory / "DG-10-r0-r2-ai-audit-candidate.4-2026-08-22.json"
    stage_checkpoint_path = output_directory / (
        "DG-10-r0-r2-stage-ledger-checkpoint-candidate.4-2026-08-22.json"
    )
    raw_directories = [
        output_directory / f"DG-10-r0-r2-ai-primary-{index}-candidate.4-raw-2026-08-22"
        for index in (1, 2)
    ]
    _require(
        not any(
            path.exists()
            for path in [
                *run_paths,
                *stage_paths.values(),
                aggregate_path,
                stage_checkpoint_path,
                *raw_directories,
            ]
        ),
        "refusing to overwrite immutable AI receipt",
    )
    for index, (path, receipt, attempt_path) in enumerate(
        zip(run_paths, run_receipts, attempt_paths, strict=True), start=1
    ):
        raw_sources = {
            "prompt": bundle / "audit-prompt.md",
            "response_schema": bundle / "audit-response.schema.json",
            "output": attempt_path.resolve() / "review-output.json",
            "events": attempt_path.resolve() / "events.jsonl",
            "stderr": attempt_path.resolve() / "stderr.log",
            "process": attempt_path.resolve() / "process.json",
        }
        raw_directory = raw_directories[index - 1]
        raw_evidence: dict[str, dict[str, str]] = {}
        for key, source in raw_sources.items():
            suffix = {
                "prompt": "prompt.md",
                "response_schema": "response.schema.json",
                "output": "output.json",
                "events": "events.jsonl",
                "stderr": "stderr.log",
                "process": "process.json",
            }[key]
            target = raw_directory / suffix
            remediation.atomic_write_new(target, source.read_bytes())
            raw_evidence[key] = _reference(target)
        receipt["raw_evidence"] = raw_evidence
        remediation.atomic_write_new(path, remediation.encoded_json(receipt))
    common_evidence = [
        _reference(bundle_receipt_path.resolve()),
        identities["identity_receipt"],
        _reference(POLICY),
        *[_reference(path) for path in run_paths],
    ]
    stage_specific = {
        "DG10-R0": [
            ROOT / "docs/reports/DG-10-remediation-baseline-candidate.4.3-2026-08-22.json",
            ROOT / "docs/reports/DG-10-r0-archive-replay-candidate.4-2026-08-22.json",
        ],
        "DG10-R1": [
            ROOT / "docs/reports/DG-10-remediation-contract-validation-candidate.4.18-2026-08-22.json",
        ],
        "DG10-R2": [
            ROOT / "docs/reports/DG-10-benchmark-worker-closure-candidate.4.28-2026-08-22.json",
            ROOT / "docs/reports/DG-10-model-probe-candidate.4-2026-08-22.json",
            ROOT / "docs/reports/DG-10-candidate-source-inventory-candidate.4.21-2026-08-22.json",
            ROOT / "docs/reports/DG-10-environment-identity-candidate.4.21-2026-08-22.json",
            ROOT / "docs/reports/DG-10-model-identity-candidate.4.21-2026-08-22.json",
            ROOT / "docs/reports/DG-10-identity-supersession-candidate.4.21-2026-08-22.json",
        ],
    }
    for stage, path in stage_paths.items():
        evidence = [*common_evidence, *[_reference(item) for item in stage_specific[stage]]]
        receipt = {
            "schema": "milai.dg10.stage-receipt.v1",
            "candidate_id": remediation.CANDIDATE,
            "stage_id": stage,
            "stage_state": "ACCEPTED",
            "evidence_class": "AI_INDEPENDENT",
            "independent_acceptance": True,
            "source_inventory_sha256": identities["source_inventory_sha256"],
            "environment_identity_sha256": identities["environment_identity_sha256"],
            "model_identity_sha256": identities["model_identity_sha256"],
            "policy_override_sha256": identities["policy_override_sha256"],
            "open_p0": 0,
            "open_p1": 0,
            "evidence": evidence,
        }
        remediation.atomic_write_new(path, remediation.encoded_json(receipt))
    ledger_before = stage_ledger.reconcile_stage_ledger()
    _require(
        all(
            ledger_before["current_stage_states"].get(stage) == "REVIEW_REQUIRED"
            and ledger_before["current_entries"][stage]["source_inventory_sha256"]
            == identities["source_inventory_sha256"]
            for stage in STAGES
        ),
        "R0-R2 stage ledger is not at the fixed review checkpoint",
    )
    for stage in STAGES:
        stage_ledger.append_stage_state(
            stage_id=stage,
            stage_state="ACCEPTED",
            evidence_class="AI_INDEPENDENT",
            source_inventory_sha256=identities["source_inventory_sha256"],
            receipt_path=stage_paths[stage],
        )
    stage_ledger.write_checkpoint(
        stage_checkpoint_path,
        required_stages=STAGES,
        required_state="ACCEPTED",
    )
    aggregate = {
        "schema": "milai.dg10.r0-r2-ai-audit.v1",
        "candidate_id": remediation.CANDIDATE,
        "status": "AI_INDEPENDENT_R0_R2_ACCEPTED_FOR_EXACT_T2_BOOTSTRAP",
        "evidence_class": "AI_INDEPENDENT",
        "human_evidence_claimed": False,
        "policy_override_sha256": identities["policy_override_sha256"],
        "identity_receipt": identities["identity_receipt"],
        "bundle_receipt": _reference(bundle_receipt_path.resolve()),
        "primary_audits": [_reference(path) for path in run_paths],
        "provider_thread_count": 2,
        "semantic_verdict_sha256": semantic_hashes[0],
        "stage_receipts": [_reference(stage_paths[stage]) for stage in STAGES],
        "stage_ledger_checkpoint": _reference(stage_checkpoint_path),
        "accepted_stages": list(STAGES),
        "open_p0": 0,
        "open_p1": 0,
        "model_run_authorized_by_audit": False,
        "test_access_authorized": False,
        "release_authorized": False,
    }
    remediation.atomic_write_new(aggregate_path, remediation.encoded_json(aggregate))
    return {"aggregate": _reference(aggregate_path), "stage_receipts": aggregate["stage_receipts"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import two candidate.4 primary AI audits")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bundle-receipt", type=Path, default=DEFAULT_BUNDLE_RECEIPT)
    parser.add_argument("--identity-receipt", type=Path, default=DEFAULT_IDENTITIES)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    args = parser.parse_args()
    result = import_audits(
        bundle=args.bundle,
        bundle_receipt_path=args.bundle_receipt,
        identity_receipt_path=args.identity_receipt,
        attempt_paths=args.attempt,
        output_directory=args.output_directory,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

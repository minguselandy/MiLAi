from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

CANDIDATE = "candidate.3"
STAGES = ("DG10-R0", "DG10-R1", "DG10-R2")
SEVERITIES = {"P0", "P1", "P2", "P3"}
FINDING_STATES = {"OPEN", "CLOSED", "ACCEPTED_RISK"}
REQUIRED_POLICY = "REQUIRE_NEW_CANDIDATE_WITH_R0_R2_CONTROL_PATH_BOOTSTRAP_RULE"
BASELINE_ARCHIVE_SHA256 = remediation.EXPECTED_BASELINE_HASHES[remediation.BASELINE_ARCHIVE]
DEFAULT_OUTPUT = ROOT / "docs/reports/DG-10-r0-r2-independent-review-candidate.3-2026-08-22.json"


class BootstrapReviewImportError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise BootstrapReviewImportError(reason)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BootstrapReviewImportError(f"invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value, raw


def _validate_bundle_manifest(
    bundle_directory: Path, manifest: Mapping[str, Any]
) -> tuple[str, dict[str, Mapping[str, Any]]]:
    required = {
        "schema",
        "candidate_id",
        "created_at",
        "review_scope",
        "bundle_entries_sha256",
        "entry_count",
        "entries",
        "boundaries",
    }
    _require(set(manifest) == required, "review manifest key set drift")
    _require(
        manifest.get("schema") == "milai.dg10.bootstrap-review-manifest.v1",
        "review manifest schema drift",
    )
    _require(manifest.get("candidate_id") == CANDIDATE, "review manifest candidate drift")
    entries = manifest.get("entries")
    _require(isinstance(entries, list) and entries, "review manifest entries absent")
    _require(manifest.get("entry_count") == len(entries), "review manifest denominator drift")
    indexed: dict[str, Mapping[str, Any]] = {}
    entry_keys = {"path", "source_path", "size", "sha256"}
    for entry in entries:
        _require(isinstance(entry, Mapping) and set(entry) == entry_keys, "manifest entry drift")
        relative = entry.get("path")
        _require(isinstance(relative, str) and relative, "manifest path absent")
        parsed = PurePosixPath(relative)
        _require(
            not parsed.is_absolute()
            and ".." not in parsed.parts
            and relative not in indexed,
            "manifest path is unsafe or duplicated",
        )
        target = (bundle_directory / relative).resolve()
        _require(
            target.is_relative_to(bundle_directory)
            and target.is_file()
            and not target.is_symlink(),
            "manifest material is missing or unsafe",
        )
        _require(target.stat().st_size == entry.get("size"), "manifest material size drift")
        _require(_sha256(target.read_bytes()) == entry.get("sha256"), "manifest material hash drift")
        indexed[relative] = entry
    canonical = _sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    )
    _require(canonical == manifest.get("bundle_entries_sha256"), "bundle aggregate digest drift")
    _require(bundle_directory.name == f"sha256-{canonical}", "bundle directory identity drift")
    boundaries = manifest.get("boundaries")
    _require(isinstance(boundaries, Mapping), "review manifest boundaries absent")
    required_boundaries = {
        "read_only": True,
        "closed_set_only": True,
        "git_metadata_included": False,
        "environment_files_included": False,
        "raw_sidecars_included": False,
        "runtime_socket_included": False,
        "secrets_included": False,
        "test_labels_or_outputs_included": False,
        "model_calls_authorized_by_bundle": False,
        "codex_acceptance_authority": False,
    }
    _require(dict(boundaries) == required_boundaries, "review manifest boundary drift")
    return canonical, indexed


def _timestamp(value: object, label: str) -> datetime:
    _require(isinstance(value, str), f"{label} is absent")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BootstrapReviewImportError(f"{label} is invalid") from exc
    _require(parsed.tzinfo is not None, f"{label} lacks timezone")
    return parsed


def _validate_authority(
    authority: Mapping[str, Any],
    *,
    reviewer_id_hash: str,
    reviewed_at: datetime,
) -> None:
    required = {
        "schema",
        "reviewer_id_hash",
        "issuer_id_hash",
        "role_separated_from_author",
        "authorized_candidate_id",
        "authorized_stages",
        "valid_from",
        "valid_until",
        "signature_reference_sha256",
    }
    _require(set(authority) == required, "reviewer authority receipt key set drift")
    _require(authority.get("schema") == "milai.dg10.reviewer-authority.v1", "authority schema drift")
    _require(authority.get("reviewer_id_hash") == reviewer_id_hash, "authority reviewer mismatch")
    _require(authority.get("role_separated_from_author") is True, "reviewer is not role-separated")
    _require(authority.get("authorized_candidate_id") == CANDIDATE, "authority candidate mismatch")
    _require(authority.get("authorized_stages") == list(STAGES), "authority stage scope drift")
    for key in ("reviewer_id_hash", "issuer_id_hash", "signature_reference_sha256"):
        remediation._require_sha256(authority.get(key), key)
    valid_from = _timestamp(authority.get("valid_from"), "authority valid_from")
    valid_until = _timestamp(authority.get("valid_until"), "authority valid_until")
    _require(valid_from <= reviewed_at <= valid_until, "review occurred outside authority window")


def _validate_findings(value: object) -> tuple[list[dict[str, Any]], list[str]]:
    _require(isinstance(value, list), "review findings are not an array")
    findings: list[dict[str, Any]] = []
    open_blocking: list[str] = []
    seen: set[str] = set()
    required = {"finding_id", "severity", "status", "title", "evidence_sha256"}
    for item in value:
        _require(isinstance(item, Mapping) and set(item) == required, "finding key set drift")
        finding_id = item.get("finding_id")
        _require(isinstance(finding_id, str) and finding_id and finding_id not in seen, "finding ID invalid")
        seen.add(finding_id)
        severity = item.get("severity")
        status = item.get("status")
        _require(severity in SEVERITIES, "finding severity invalid")
        _require(status in FINDING_STATES, "finding status invalid")
        _require(isinstance(item.get("title"), str) and item.get("title"), "finding title absent")
        remediation._require_sha256(item.get("evidence_sha256"), "finding evidence")
        normalized = dict(item)
        findings.append(normalized)
        if severity in {"P0", "P1"} and status == "OPEN":
            open_blocking.append(str(finding_id))
    return findings, sorted(open_blocking)


def import_review(
    *,
    bundle_directory: Path,
    response_path: Path,
    authority_path: Path,
    transcript_path: Path,
) -> dict[str, Any]:
    bundle_directory = bundle_directory.resolve()
    _require(bundle_directory.is_dir(), "review bundle is absent")
    _require(stat.S_IMODE(bundle_directory.stat().st_mode) == 0o555, "review bundle is not read-only")
    manifest_path = bundle_directory / "review-manifest.json"
    response_schema_path = bundle_directory / "response.schema.json"
    _require(manifest_path.is_file() and response_schema_path.is_file(), "bundle control files absent")
    manifest, manifest_raw = _object(manifest_path)
    bundle_hash, indexed_entries = _validate_bundle_manifest(bundle_directory, manifest)
    _require(
        "archive-manifests/candidate.2-members.json" in indexed_entries,
        "archive member manifest is not bundle-bound",
    )
    response, response_raw = _object(response_path.resolve())
    authority, authority_raw = _object(authority_path.resolve())
    transcript_raw = transcript_path.resolve().read_bytes()
    expected_response_keys = {
        "candidate_id",
        "bundle_entries_sha256",
        "bundle_manifest_sha256",
        "reviewer_id_hash",
        "reviewer_role_separated",
        "reviewer_authority_receipt_sha256",
        "evidence_class",
        "reviewed_at",
        "stage_decisions",
        "archive_replay",
        "bootstrap_policy_disposition",
        "findings",
        "review_transcript_sha256",
    }
    _require(set(response) == expected_response_keys, "review response key set drift")
    _require(response.get("candidate_id") == CANDIDATE, "review candidate mismatch")
    _require(response.get("bundle_entries_sha256") == bundle_hash, "response bundle mismatch")
    _require(response.get("bundle_manifest_sha256") == _sha256(manifest_raw), "manifest digest mismatch")
    reviewer_id = response.get("reviewer_id_hash")
    remediation._require_sha256(reviewer_id, "reviewer identity")
    _require(response.get("reviewer_role_separated") is True, "response lacks role separation")
    _require(response.get("evidence_class") in {"HUMAN", "INDEPENDENT"}, "Codex/author evidence cannot be imported")
    reviewed_at = _timestamp(response.get("reviewed_at"), "reviewed_at")
    _require(
        response.get("reviewer_authority_receipt_sha256") == _sha256(authority_raw),
        "reviewer authority receipt digest mismatch",
    )
    _validate_authority(authority, reviewer_id_hash=str(reviewer_id), reviewed_at=reviewed_at)
    _require(
        response.get("review_transcript_sha256") == _sha256(transcript_raw),
        "review transcript digest mismatch",
    )
    decisions = response.get("stage_decisions")
    _require(isinstance(decisions, Mapping) and set(decisions) == set(STAGES), "stage decision set drift")
    _require(all(value in {"ACCEPTED", "REVISE"} for value in decisions.values()), "stage decision invalid")
    if any(value == "ACCEPTED" for value in decisions.values()):
        raise BootstrapReviewImportError(
            "legacy candidate.3 independent acceptance path is disabled; use candidate.4 AI policy"
        )
    archive = response.get("archive_replay")
    archive_required = {
        "authorized_protected_archive_access",
        "archive_sha256",
        "member_count",
        "safe_member_status",
        "member_manifest_sha256",
        "replay_transcript_sha256",
    }
    _require(isinstance(archive, Mapping) and set(archive) == archive_required, "archive replay key set drift")
    archive_manifest_raw = (bundle_directory / "archive-manifests/candidate.2-members.json").read_bytes()
    if archive.get("authorized_protected_archive_access") is True:
        _require(archive.get("archive_sha256") == BASELINE_ARCHIVE_SHA256, "R0 archive digest mismatch")
        _require(archive.get("member_count") == 201, "R0 archive member denominator drift")
        _require(archive.get("safe_member_status") == "PASS_SAFE_REGULAR_MEMBERS", "R0 archive safety failed")
        _require(archive.get("member_manifest_sha256") == _sha256(archive_manifest_raw), "R0 member manifest mismatch")
        remediation._require_sha256(archive.get("replay_transcript_sha256"), "archive replay transcript")
    else:
        _require(decisions["DG10-R0"] == "REVISE", "R0 acceptance requires archive replay")
    findings, open_blocking = _validate_findings(response.get("findings"))
    policy = response.get("bootstrap_policy_disposition")
    _require(
        policy
        in {
            REQUIRED_POLICY,
            "REVISE_R0_R2_AND_DO_NOT_AUTHORIZE_ANY_MODEL_CALL",
        },
        "bootstrap policy disposition invalid",
    )
    if open_blocking:
        _require(all(value == "REVISE" for value in decisions.values()), "open P0/P1 cannot coexist with acceptance")
    if policy == "REVISE_R0_R2_AND_DO_NOT_AUTHORIZE_ANY_MODEL_CALL":
        _require(all(value == "REVISE" for value in decisions.values()), "no-call policy requires all stages REVISE")
    accepted = [stage for stage in STAGES if decisions[stage] == "ACCEPTED"]
    stage_receipts: list[dict[str, Any]] = []
    all_accepted = accepted == list(STAGES) and not open_blocking
    policy_allows_new_candidate = policy == REQUIRED_POLICY
    return {
        "schema": "milai.dg10.bootstrap-independent-review-import.v1",
        "candidate_id": CANDIDATE,
        "status": (
            "R0_R2_ACCEPTED_NEW_CANDIDATE_POLICY_REQUIRED"
            if all_accepted and policy_allows_new_candidate
            else "REVIEW_REVISE_NO_MODEL_AUTHORIZATION"
        ),
        "independent_acceptance": all_accepted,
        "evidence_class": "INDEPENDENT",
        "bundle_entries_sha256": bundle_hash,
        "bundle_manifest_sha256": _sha256(manifest_raw),
        "review_response_sha256": _sha256(response_raw),
        "reviewer_authority_receipt_sha256": _sha256(authority_raw),
        "review_transcript_sha256": _sha256(transcript_raw),
        "reviewer_id_hash": reviewer_id,
        "accepted_stages": accepted,
        "stage_receipts": stage_receipts,
        "bootstrap_policy_disposition": policy,
        "findings": findings,
        "open_p0_p1": open_blocking,
        "candidate_3_model_run_authorized": False,
        "next_required_action": (
            "CREATE_AND_FREEZE_NEW_CANDIDATE_CONTROL_PATH_BOOTSTRAP_CONTRACT"
            if all_accepted and policy_allows_new_candidate
            else "REMEDIATE_REVIEW_FINDINGS_AND_REPEAT_INDEPENDENT_REVIEW"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import DG-10 independent bootstrap review")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--authority-receipt", type=Path, required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = import_review(
        bundle_directory=args.bundle,
        response_path=args.response,
        authority_path=args.authority_receipt,
        transcript_path=args.transcript,
    )
    remediation.atomic_write_new(args.output.resolve(), remediation.encoded_json(report))
    print(json.dumps({"status": report["status"], "accepted_stages": report["accepted_stages"]}, sort_keys=True))


if __name__ == "__main__":
    main()

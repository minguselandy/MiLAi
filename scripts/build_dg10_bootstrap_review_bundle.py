from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scan_ua_secrets import _secrets

from scripts import dg10_remediation as remediation

DATE = remediation.DATE
CANDIDATE = remediation.CANDIDATE
STATUS_REPORT = ROOT / "docs/reports/DG-10-remediation-engineering-status-candidate.3-2026-08-22.json"
BASELINE_ARCHIVE = remediation.BASELINE_ARCHIVE
DEFAULT_OUTPUT_ROOT = ROOT.parent / "evidence/dg10-remediation-bootstrap-review"
DEFAULT_RECEIPT = ROOT / "docs/reports/DG-10-r0-r2-bootstrap-review-bundle-candidate.3-2026-08-22.json"

EVIDENCE_PATHS = (
    "docs/reports/DG-10-remediation-baseline-candidate.3-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.3.1-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.3.2-2026-08-22.json",
    "docs/reports/DG-10-model-run-authorization-candidate.3-2026-08-22.json",
    "docs/reports/DG-10-memory-fixture-ingest-ledgered-candidate.3-2026-08-22.json",
    "docs/reports/DG-10-memory-fixture-pre-ledger-diagnostics-candidate.3-2026-08-22.json",
    "docs/reports/DG-10-remediation-engineering-status-candidate.3-2026-08-22.json",
    "docs/reports/DG-10-r2-source-worker-binding-candidate.3.1-2026-08-22.json",
    "docs/reviews/DG-10-r0-r2-bootstrap-codex-adversarial-review-candidate.3.md",
    "docs/reviews/DG-10-r0-r2-bootstrap-codex-remediation-recheck-candidate.3.md",
    "scripts/import_dg10_bootstrap_review.py",
    "docs/reports/DG-10-final-completion-audit-candidate.2-2026-08-22.json",
    "docs/reviews/DG-10-sol-final-audit-disposition-candidate.1-2026-08-22.json",
    "dist/DG-10-experiment-results-candidate.2-2026-08-22.receipt.json",
)

REVIEW_PROMPT = """# DG-10 candidate.3 R0-R2 bootstrap independent review

Review only the closed, read-only bundle. Do not access the repository, environment,
Runtime socket, raw sidecars, model output, benchmark labels, or network.

Decide R0, R1, and R2 independently as ACCEPTED or REVISE. Do not accept R3-R8.
Recompute every bundled material SHA-256, the source inventory root, claim/schema
invariants, fresh-install receipt, R2 direct binding, and retained pre-ledger disclosure.

The protected candidate.2 archive bytes are deliberately excluded from this sanitized
bundle. R0 ACCEPTED therefore requires a role-separated human replay with separately
authorized access to the exact archive. Bind that replay to the included member manifest
and fill archive_replay; Codex cannot satisfy this condition.

Also issue a binding policy disposition for the bootstrap cycle:
R3 requires a 24/24 T2 model smoke, while the frozen first-model rule requires R3
ACCEPTED before any model call. Choose exactly one:
  A. REQUIRE_NEW_CANDIDATE_WITH_R0_R2_CONTROL_PATH_BOOTSTRAP_RULE
  B. REVISE_R0_R2_AND_DO_NOT_AUTHORIZE_ANY_MODEL_CALL

Codex output is adversarial evidence only. An ACCEPTED stage decision must be signed
by a role-separated independent human/reviewer authority and hash-bound to this bundle.
Return JSON conforming exactly to response.schema.json. The response is accepted only
through import_dg10_bootstrap_review.py with a separate authority receipt and transcript.
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
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
    ],
    "properties": {
        "candidate_id": {"const": CANDIDATE},
        "bundle_entries_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "bundle_manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "reviewer_id_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "reviewer_role_separated": {"const": True},
        "reviewer_authority_receipt_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "evidence_class": {"enum": ["HUMAN", "INDEPENDENT"]},
        "reviewed_at": {"type": "string", "format": "date-time"},
        "stage_decisions": {
            "type": "object",
            "additionalProperties": False,
            "required": ["DG10-R0", "DG10-R1", "DG10-R2"],
            "properties": {
                stage: {"enum": ["ACCEPTED", "REVISE"]}
                for stage in ("DG10-R0", "DG10-R1", "DG10-R2")
            },
        },
        "archive_replay": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "authorized_protected_archive_access",
                "archive_sha256",
                "member_count",
                "safe_member_status",
                "member_manifest_sha256",
                "replay_transcript_sha256",
            ],
            "properties": {
                "authorized_protected_archive_access": {"const": True},
                "archive_sha256": {"const": "7e1b88267d2c9cd6f819d937ddd1ed5a1f15b5cb5b38b547f8067938f7702166"},
                "member_count": {"const": 201},
                "safe_member_status": {"const": "PASS_SAFE_REGULAR_MEMBERS"},
                "member_manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "replay_transcript_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
        },
        "bootstrap_policy_disposition": {
            "enum": [
                "REQUIRE_NEW_CANDIDATE_WITH_R0_R2_CONTROL_PATH_BOOTSTRAP_RULE",
                "REVISE_R0_R2_AND_DO_NOT_AUTHORIZE_ANY_MODEL_CALL",
            ]
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["finding_id", "severity", "status", "title", "evidence_sha256"],
                "properties": {
                    "finding_id": {"type": "string", "minLength": 1},
                    "severity": {"enum": ["P0", "P1", "P2", "P3"]},
                    "status": {"enum": ["OPEN", "CLOSED", "ACCEPTED_RISK"]},
                    "title": {"type": "string", "minLength": 1},
                    "evidence_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
            },
        },
        "review_transcript_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}


class BootstrapBundleError(remediation.RemediationError):
    pass


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BootstrapBundleError(f"JSON root is not an object: {path}")
    return value


def _archive_member_manifest() -> bytes:
    members: list[dict[str, Any]] = []
    with tarfile.open(BASELINE_ARCHIVE, mode="r:gz") as archive:
        for member in archive.getmembers():
            parsed = PurePosixPath(member.name)
            if (
                not member.isfile()
                or parsed.is_absolute()
                or ".." in parsed.parts
                or "\\" in member.name
            ):
                raise BootstrapBundleError("candidate.2 archive contains an unsafe member")
            handle = archive.extractfile(member)
            if handle is None:
                raise BootstrapBundleError("candidate.2 archive member is unreadable")
            raw = handle.read()
            members.append(
                {
                    "path": member.name,
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    manifest = {
        "schema": "milai.dg10.safe-archive-member-manifest.v1",
        "archive_sha256": remediation.sha256_file(BASELINE_ARCHIVE),
        "member_count": len(members),
        "members": members,
    }
    return _json_bytes(manifest)


def _materials() -> dict[str, tuple[str | None, bytes]]:
    status = _load_object(STATUS_REPORT)
    inventory = status.get("source_inventory")
    entries = inventory.get("entries") if isinstance(inventory, Mapping) else None
    if not isinstance(entries, list) or not entries:
        raise BootstrapBundleError("frozen source inventory is absent")
    materials: dict[str, tuple[str | None, bytes]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise BootstrapBundleError("source inventory entry is invalid")
        relative = str(entry["path"])
        source = (ROOT / relative).resolve()
        if not source.is_relative_to(ROOT) or not source.is_file() or source.is_symlink():
            raise BootstrapBundleError(f"source inventory material is unsafe: {relative}")
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry.get("sha256") or len(raw) != entry.get("size"):
            raise BootstrapBundleError(f"source inventory material drifted: {relative}")
        materials[f"materials/{relative}"] = (relative, raw)
    for relative in EVIDENCE_PATHS:
        source = (ROOT / relative).resolve()
        if not source.is_relative_to(ROOT) or not source.is_file() or source.is_symlink():
            raise BootstrapBundleError(f"evidence material is unsafe: {relative}")
        materials[f"materials/{relative}"] = (relative, source.read_bytes())
    materials["archive-manifests/candidate.2-members.json"] = (
        None,
        _archive_member_manifest(),
    )
    materials["review-prompt.md"] = (None, REVIEW_PROMPT.encode())
    materials["response.schema.json"] = (None, _json_bytes(RESPONSE_SCHEMA))
    return materials


def _validate_destination(value: str) -> None:
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or not parsed.parts
        or ".." in parsed.parts
        or {".git", ".env", "raw-sidecars"}.intersection(parsed.parts)
    ):
        raise BootstrapBundleError(f"unsafe bundle destination: {value}")


def build_bundle(
    *, output_root: Path, secret_source: Path
) -> tuple[Path, dict[str, Any]]:
    materials = _materials()
    secrets = _secrets(secret_source)
    entries: list[dict[str, Any]] = []
    for destination, (source, raw) in sorted(materials.items()):
        _validate_destination(destination)
        if any(secret in raw for secret in secrets):
            raise BootstrapBundleError(f"secret value found in review material: {destination}")
        entries.append(
            {
                "path": destination,
                "source_path": source,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    entries_raw = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    bundle_entries_sha256 = hashlib.sha256(entries_raw).hexdigest()
    manifest = {
        "schema": "milai.dg10.bootstrap-review-manifest.v1",
        "candidate_id": CANDIDATE,
        "created_at": datetime.now(UTC).isoformat(),
        "review_scope": ["DG10-R0", "DG10-R1", "DG10-R2", "BOOTSTRAP_POLICY"],
        "bundle_entries_sha256": bundle_entries_sha256,
        "entry_count": len(entries),
        "entries": entries,
        "boundaries": {
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
        },
    }
    manifest_raw = _json_bytes(manifest)
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_root.chmod(0o700)
    final = output_root / f"sha256-{bundle_entries_sha256}"
    if final.exists():
        raise BootstrapBundleError(f"refusing to overwrite review bundle: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=".dg10-bootstrap-review-", dir=output_root))
    try:
        for destination, (_source, raw) in materials.items():
            target = temporary / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        manifest_path = temporary / "review-manifest.json"
        descriptor = os.open(
            manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(manifest_raw)
            stream.flush()
            os.fsync(stream.fileno())
        for directory in sorted(
            (path for path in temporary.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.chmod(0o555)
        temporary.chmod(0o555)
        os.replace(temporary, final)
    except BaseException:
        if temporary.exists():
            for path in sorted(temporary.rglob("*"), reverse=True):
                if path.is_dir():
                    path.chmod(0o755)
                else:
                    path.chmod(0o644)
            temporary.chmod(0o755)
            shutil.rmtree(temporary)
        raise
    files = [path for path in final.rglob("*") if path.is_file()]
    directories = [path for path in final.rglob("*") if path.is_dir()]
    if any(stat.S_IMODE(path.stat().st_mode) != 0o444 for path in files) or any(
        stat.S_IMODE(path.stat().st_mode) != 0o555 for path in [final, *directories]
    ):
        raise BootstrapBundleError("materialized review bundle is not read-only")
    receipt = {
        "schema": "milai.dg10.bootstrap-review-bundle-receipt.v1",
        "candidate_id": CANDIDATE,
        "date": DATE,
        "status": "R0_R2_AUTHOR_BUNDLE_READY_INDEPENDENT_REVIEW_REQUIRED",
        "independent_acceptance": False,
        "bundle_directory_id": final.name,
        "bundle_path_class": "REPO_EXTERNAL_READ_ONLY_MATERIALIZED_WORKSPACE",
        "bundle_entries_sha256": bundle_entries_sha256,
        "entry_count": len(entries),
        "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "secret_scan": {
            "status": "PASS",
            "secret_value_count": len(secrets),
            "matching_files": [],
        },
        "archive_member_manifest": {
            "status": "PASS_SAFE_REGULAR_MEMBERS",
            "archive_sha256": remediation.sha256_file(BASELINE_ARCHIVE),
            "member_count": 201,
        },
        "filesystem": {
            "file_mode": "0444",
            "directory_mode": "0555",
            "file_count_including_manifest": len(files),
        },
        "boundaries": manifest["boundaries"],
        "provider_requests": 0,
        "test_access_authorized": False,
        "accepted_stages": [],
        "next_required_action": "ROLE_SEPARATED_INDEPENDENT_REVIEWER_REPLAYS_R0_R2_AND_DISPOSES_BOOTSTRAP_POLICY",
    }
    return final, receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Build DG-10 R0-R2 bootstrap review bundle")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--secret-source", type=Path, default=ROOT / "runtime/.env")
    args = parser.parse_args()
    if args.candidate != CANDIDATE:
        raise BootstrapBundleError("candidate identity mismatch")
    bundle, receipt = build_bundle(
        output_root=args.output,
        secret_source=args.secret_source.resolve(),
    )
    remediation.atomic_write_new(args.receipt.resolve(), remediation.encoded_json(receipt))
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "bundle": str(bundle),
                "bundle_entries_sha256": receipt["bundle_entries_sha256"],
                "receipt": str(args.receipt.resolve()),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

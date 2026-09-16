from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import import_dg10_bootstrap_review as review_import


def _raw(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True) + "\n").encode()


def _bundle(tmp_path: Path) -> tuple[Path, bytes]:
    staging = tmp_path / "staging"
    materials = {
        "archive-manifests/candidate.2-members.json": _raw({"member_count": 201}),
        "response.schema.json": _raw({"type": "object"}),
    }
    entries = []
    for relative, raw in sorted(materials.items()):
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        entries.append(
            {
                "path": relative,
                "source_path": None,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    canonical = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    bundle = tmp_path / f"sha256-{canonical}"
    staging.rename(bundle)
    manifest = {
        "schema": "milai.dg10.bootstrap-review-manifest.v1",
        "candidate_id": "candidate.3",
        "created_at": "2026-08-22T00:00:00+00:00",
        "review_scope": ["DG10-R0", "DG10-R1", "DG10-R2", "BOOTSTRAP_POLICY"],
        "bundle_entries_sha256": canonical,
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
    manifest_raw = _raw(manifest)
    (bundle / "review-manifest.json").write_bytes(manifest_raw)
    bundle.chmod(0o555)
    return bundle, manifest_raw


def test_manifest_recomputes_every_material_and_aggregate(tmp_path: Path) -> None:
    bundle, _ = _bundle(tmp_path)
    manifest = json.loads((bundle / "review-manifest.json").read_text())
    canonical, indexed = review_import._validate_bundle_manifest(bundle, manifest)
    assert bundle.name == f"sha256-{canonical}"
    assert set(indexed) == {
        "archive-manifests/candidate.2-members.json",
        "response.schema.json",
    }
    bundle.chmod(0o755)
    target = bundle / "response.schema.json"
    target.write_text("tampered\n")
    with pytest.raises(review_import.BootstrapReviewImportError, match=r"hash drift|size drift"):
        review_import._validate_bundle_manifest(bundle, manifest)


def test_legacy_importer_cannot_mint_accepted_stage_receipts(tmp_path: Path) -> None:
    bundle, manifest_raw = _bundle(tmp_path)
    reviewer_id = "1" * 64
    authority = {
        "schema": "milai.dg10.reviewer-authority.v1",
        "reviewer_id_hash": reviewer_id,
        "issuer_id_hash": "2" * 64,
        "role_separated_from_author": True,
        "authorized_candidate_id": "candidate.3",
        "authorized_stages": ["DG10-R0", "DG10-R1", "DG10-R2"],
        "valid_from": "2026-08-21T00:00:00+00:00",
        "valid_until": "2026-08-23T00:00:00+00:00",
        "signature_reference_sha256": "3" * 64,
    }
    authority_path = tmp_path / "authority.json"
    authority_raw = _raw(authority)
    authority_path.write_bytes(authority_raw)
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_raw = b'{"event":"review"}\n'
    transcript_path.write_bytes(transcript_raw)
    manifest = json.loads(manifest_raw)
    response = {
        "candidate_id": "candidate.3",
        "bundle_entries_sha256": manifest["bundle_entries_sha256"],
        "bundle_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "reviewer_id_hash": reviewer_id,
        "reviewer_role_separated": True,
        "reviewer_authority_receipt_sha256": hashlib.sha256(authority_raw).hexdigest(),
        "evidence_class": "INDEPENDENT",
        "reviewed_at": "2026-08-22T00:00:00+00:00",
        "stage_decisions": {
            "DG10-R0": "ACCEPTED",
            "DG10-R1": "ACCEPTED",
            "DG10-R2": "ACCEPTED",
        },
        "archive_replay": {
            "authorized_protected_archive_access": True,
            "archive_sha256": review_import.BASELINE_ARCHIVE_SHA256,
            "member_count": 201,
            "safe_member_status": "PASS_SAFE_REGULAR_MEMBERS",
            "member_manifest_sha256": "4" * 64,
            "replay_transcript_sha256": "5" * 64,
        },
        "bootstrap_policy_disposition": review_import.REQUIRED_POLICY,
        "findings": [],
        "review_transcript_sha256": hashlib.sha256(transcript_raw).hexdigest(),
    }
    response_path = tmp_path / "response.json"
    response_path.write_bytes(_raw(response))
    try:
        with pytest.raises(review_import.BootstrapReviewImportError, match="disabled"):
            review_import.import_review(
                bundle_directory=bundle,
                response_path=response_path,
                authority_path=authority_path,
                transcript_path=transcript_path,
            )
    finally:
        bundle.chmod(0o755)

"""Materialize a receipt only from an externally pinned independent approval.

This is a preparation step, never a reviewer or a runtime authorization source.
The approving agent's actual record and mechanical replay are separate inputs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def finalize_authority(*, candidate_path, candidate_sha256, mechanical_path,
                       mechanical_sha256, approval_path, approval_sha256):
    from v0222_scoped_cpu_guard import require_cpu_network_guard

    require_cpu_network_guard()
    from v0220_evidence import dependencies
    from v0222_admission_read_scope import AdmissionReadScope
    from v0222_scoped_evidence import _strict_json
    from v0224_static_bundle import canonical_json

    candidate_path, mechanical_path, approval_path = map(
        Path, (candidate_path, mechanical_path, approval_path)
    )
    for path in (candidate_path, mechanical_path, approval_path):
        if not path.is_absolute() or path.resolve() != path or ".." in path.parts:
            raise ValueError("CANONICAL_APPROVAL_INPUT_REQUIRED")
    output = candidate_path.parent.parent / "approved-receipt.json"
    if output.exists() or output.is_symlink():
        raise ValueError("FRESH_APPROVED_RECEIPT_REQUIRED_NO_RETRY")
    with AdmissionReadScope() as scope:
        approval = _strict_json(scope.read_bytes(approval_path, approval_sha256).decode("utf-8"))
        fields = {
            "status", "reviewer", "reviewer_is_not_human", "candidate_sha256",
            "bundle_sha256", "mechanical_sha256", "classification_digest", "files",
        }
        if type(approval) is not dict or set(approval) != fields:
            raise ValueError("EXACT_EXTERNAL_INDEPENDENT_APPROVAL_REQUIRED")
        if (approval["status"] != "INDEPENDENT_R03_AUTHORITY_APPROVAL"
                or approval["reviewer_is_not_human"] is not True
                or type(approval["reviewer"]) is not str
                or not approval["reviewer"].startswith("/root/")):
            raise ValueError("EXPLICIT_DELEGATED_AUTHORITY_APPROVAL_REQUIRED")
        if (approval["candidate_sha256"] != candidate_sha256
                or approval["mechanical_sha256"] != mechanical_sha256):
            raise ValueError("APPROVAL_INPUT_BINDING_MISMATCH")
        pins = approval["files"]
        if type(pins) is not dict or not pins:
            raise ValueError("EXPLICIT_APPROVAL_FILES_REQUIRED")
        required_sources = {str(path) for path in dependencies([Path(__file__).resolve()])}
        if not required_sources <= set(pins):
            raise ValueError("APPROVAL_MISSING_FINALIZER_SOURCE_CLOSURE")
        if (pins.get(str(candidate_path)) != candidate_sha256
                or pins.get(str(mechanical_path)) != mechanical_sha256):
            raise ValueError("APPROVAL_MISSING_ARTIFACT_PINS")
        for name, digest in pins.items():
            if type(name) is not str or not Path(name).is_absolute():
                raise ValueError("ABSOLUTE_APPROVAL_FILE_REQUIRED")
            scope.read_bytes(Path(name), digest)
        candidate = _strict_json(
            scope.read_bytes(candidate_path, candidate_sha256).decode("utf-8")
        )
        mechanical = _strict_json(
            scope.read_bytes(mechanical_path, mechanical_sha256).decode("utf-8")
        )
        receipt_fields = {
            "status", "bundle_sha256", "format_revision", "verifier_files",
            "proof_roots", "fresh_roles", "environment", "classification_digest",
        }
        if (type(candidate) is not dict or set(candidate) != receipt_fields
                or candidate["status"] != "STATIC_BUNDLE_CANDIDATE_NOT_APPROVED"):
            raise ValueError("EXACT_UNAPPROVED_CANDIDATE_REQUIRED")
        if (mechanical["status"] != "MECHANICAL_STATIC_REVALIDATION_COMPLETE_NOT_APPROVAL"
                or mechanical["runtime_authorized"] is not False
                or mechanical["candidate_status"] != candidate["status"]
                or mechanical["proof_roots"] != candidate["proof_roots"]
                or mechanical["files"].get(str(candidate_path)) != candidate_sha256):
            raise ValueError("COMPLETE_MECHANICAL_REPLAY_REQUIRED")
        for field in ("bundle_sha256", "classification_digest"):
            if not approval[field] == candidate[field] == mechanical[field]:
                raise ValueError("APPROVAL_AUTHORITY_BINDING_MISMATCH")
        bundle_path = candidate_path.parent / "static.bundle"
        if pins.get(str(bundle_path)) != candidate["bundle_sha256"]:
            raise ValueError("APPROVAL_MISSING_ACTUAL_BUNDLE_PIN")
        receipt = {**candidate, "status": "INDEPENDENT_STATIC_BUNDLE_APPROVED"}
    payload = canonical_json(receipt)
    with output.open("xb") as stream:
        stream.write(payload)
    if output.read_bytes() != payload:
        raise ValueError("PERSISTED_APPROVED_RECEIPT_DRIFT")
    return {"path": str(output), "sha256": hashlib.sha256(payload).hexdigest(),
            "status": "APPROVED_RECEIPT_MATERIALIZED_NOT_GATE_A"}

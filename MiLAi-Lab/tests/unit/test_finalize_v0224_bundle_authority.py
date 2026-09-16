"""Synthetic externally trusted approval records, no real authority is created."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import finalize_v0224_bundle_authority as finalizer
from v0220_evidence import dependencies
from v0224_static_bundle import canonical_json


def put(path, value):
    raw = value if type(value) is bytes else canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def records(tmp_path, monkeypatch):
    import v0222_scoped_cpu_guard as guard

    monkeypatch.setattr(guard, "_installed", True)
    candidate_path = tmp_path / "sealed/candidate-receipt.json"
    bundle_path = candidate_path.parent / "static.bundle"
    bundle_sha = put(bundle_path, b"synthetic payload: semantic replay tested separately")
    candidate = {
        "status": "STATIC_BUNDLE_CANDIDATE_NOT_APPROVED", "bundle_sha256": bundle_sha,
        "format_revision": "V0224_STATIC_BUNDLE_V1", "verifier_files": {},
        "proof_roots": [], "fresh_roles": {}, "environment": {},
        "classification_digest": hashlib.sha256(b"{}").hexdigest(),
    }
    candidate_sha = put(candidate_path, candidate)
    mechanical_path = tmp_path / "revalidated/mechanical-revalidation.json"
    mechanical = {
        "status": "MECHANICAL_STATIC_REVALIDATION_COMPLETE_NOT_APPROVAL",
        "runtime_authorized": False, "candidate_status": candidate["status"],
        "proof_roots": [], "files": {str(candidate_path): candidate_sha},
        "bundle_sha256": bundle_sha, "classification_digest": candidate["classification_digest"],
    }
    mechanical_sha = put(mechanical_path, mechanical)
    pins = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in dependencies([Path(finalizer.__file__).resolve()])}
    pins.update({str(candidate_path): candidate_sha, str(bundle_path): bundle_sha,
                 str(mechanical_path): mechanical_sha})
    approval = {
        "status": "INDEPENDENT_R03_AUTHORITY_APPROVAL", "reviewer": "/root/synthetic_reviewer",
        "reviewer_is_not_human": True, "candidate_sha256": candidate_sha,
        "bundle_sha256": bundle_sha, "mechanical_sha256": mechanical_sha,
        "classification_digest": candidate["classification_digest"], "files": pins,
    }
    approval_path = tmp_path / "independent-approval.json"
    approval_sha = put(approval_path, approval)
    return {
        "candidate_path": candidate_path, "candidate_sha256": candidate_sha,
        "mechanical_path": mechanical_path, "mechanical_sha256": mechanical_sha,
        "approval_path": approval_path, "approval_sha256": approval_sha,
    }, approval


def test_external_approval_materializes_exact_receipt_once(records):
    kwargs, _ = records
    result = finalizer.finalize_authority(**kwargs)
    output = Path(result["path"])
    receipt = json.loads(output.read_bytes())
    original = json.loads(kwargs["candidate_path"].read_bytes())
    assert receipt == {**original, "status": "INDEPENDENT_STATIC_BUNDLE_APPROVED"}
    assert result["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="NO_RETRY"):
        finalizer.finalize_authority(**kwargs)


@pytest.mark.parametrize("field,value", [
    ("status", "SELF_APPROVED"), ("reviewer_is_not_human", False),
    ("candidate_sha256", "0" * 64), ("mechanical_sha256", "0" * 64),
    ("bundle_sha256", "0" * 64), ("classification_digest", "0" * 64),
])
def test_wrong_approval_binding_refuses_without_output(records, field, value):
    kwargs, approval = records
    approval[field] = value
    kwargs["approval_sha256"] = put(kwargs["approval_path"], approval)
    with pytest.raises(ValueError):
        finalizer.finalize_authority(**kwargs)
    assert not (kwargs["candidate_path"].parent.parent / "approved-receipt.json").exists()


def test_approval_pin_is_external_not_discovered(records):
    kwargs, _ = records
    kwargs["approval_path"].write_bytes(b"{}")
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        finalizer.finalize_authority(**kwargs)


def test_missing_finalizer_source_closure_refuses(records):
    kwargs, approval = records
    del approval["files"][str(Path(finalizer.__file__).resolve())]
    kwargs["approval_sha256"] = put(kwargs["approval_path"], approval)
    with pytest.raises(ValueError, match="SOURCE_CLOSURE"):
        finalizer.finalize_authority(**kwargs)


def test_guard_refusal_precedes_output(records, monkeypatch):
    import v0222_scoped_cpu_guard as guard

    kwargs, _ = records
    monkeypatch.setattr(guard, "_installed", False)
    with pytest.raises(Exception, match="GUARD"):
        finalizer.finalize_authority(**kwargs)

"""Seal evidence gates using explicit synthetic artifacts, with no formal instance."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import seal_v0222_presentation as module
from v0220_evidence import dependencies, read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import encoded


def inputs(tmp_path, monkeypatch):
    root = tmp_path / "SYNTHETIC_NOT_A_FORMAL_INSTANCE"
    marker = tmp_path / "synthetic-marker.json"
    save(marker, {"synthetic": True})
    files = {str(marker): sha(marker)}
    proof_path = tmp_path / "proof.json"
    save(
        proof_path,
        {
            "status": "CURRENT_AUDITOR_FULL_REFERENCE_PASS",
            "mode": "OFFLINE_ONLY_NOT_AUTHORIZATION",
            "P3_requests": 16,
            "P4_requests": 80,
            "P4_chains": 24,
            "model_requests": 0,
            "http_requests": 0,
            "files": files,
            "sources": {
                str(p): sha(p)
                for p in dependencies([module.LAB / "tools/prepare_v0222_presentation.py"])
            },
        },
    )
    engineering_path = tmp_path / "engineering.json"
    # The test replaces executable entry names, not evidence validation itself.
    monkeypatch.setattr(module, "ENTRY_NAMES", ("seal_v0222_presentation.py",))
    monkeypatch.setattr(module, "TEST_NAMES", ("test_v0222_presentation_seal.py",))
    entries = [module.LAB / "tools/seal_v0222_presentation.py", Path(__file__).resolve()]
    save(
        engineering_path,
        {
            "status": "ENGINEERING_CHECKS_PASS",
            "checks": [
                {"command": command, "exit_code": 0}
                for command in sorted(module.ENGINEERING_COMMANDS)
            ],
            "files": {str(p): sha(p) for p in dependencies(entries)},
        },
    )
    boundary = tmp_path / "synthetic-boundary"
    save(
        boundary / "independent-result-review.json",
        {"status": "BOUNDARY_RESULT_REVIEW_PASS", "files": files},
    )
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "BOUNDARY_ROOT", boundary)
    monkeypatch.setattr(module, "HISTORICAL_SOURCES", ())
    monkeypatch.setattr(module, "verify_lineage", lambda: None)
    return root, proof_path, engineering_path


@pytest.mark.parametrize(
    "change",
    [
        "old_engineering",
        "missing_check",
        "nonzero",
        "bool_exit",
        "empty_proof_sources",
        "partial_proof_sources",
        "matrix_count",
        "source_drift",
    ],
)
def test_incomplete_engineering_or_proof_rejected_before_any_seal(tmp_path, monkeypatch, change):
    root, proof, engineering = inputs(tmp_path, monkeypatch)
    path = (
        engineering
        if change in {"old_engineering", "missing_check", "nonzero", "bool_exit"}
        else proof
    )
    value = read(path)
    if change == "old_engineering":
        value["files"] = {str(proof): sha(proof)}
    elif change == "missing_check":
        value["checks"].pop()
    elif change == "nonzero":
        value["checks"][0]["exit_code"] = 1
    elif change == "bool_exit":
        value["checks"][0]["exit_code"] = False
    elif change == "empty_proof_sources":
        value["sources"] = {}
    elif change == "partial_proof_sources":
        value["sources"].pop(str(module.LAB / "tools/v0222_presentation_audit.py"))
    elif change == "matrix_count":
        value["P4_requests"] = 79
    else:
        value["sources"][str(module.LAB / "tools/v0222_presentation_audit.py")] = "0" * 64
    path.write_text(encoded(value))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("MUST_REJECT_BEFORE_AUTHORIZATION_OR_SEAL")

    monkeypatch.setattr(module, "make_authorization", forbidden)
    monkeypatch.setattr(module, "seal", forbidden)
    with pytest.raises(ProviderStop):
        module.prepare(root, proof, engineering)
    assert not root.exists()


def test_complete_synthetic_evidence_reaches_authorization_only_after_all_checks(
    tmp_path, monkeypatch
):
    root, proof, engineering = inputs(tmp_path, monkeypatch)
    marker = "TEST_ONLY_VALIDATION_FINISHED_NO_INSTANCE_CREATED"

    def stop_before_create(*_args, **_kwargs):
        raise RuntimeError(marker)

    monkeypatch.setattr(module, "make_authorization", stop_before_create)
    with pytest.raises(RuntimeError, match=marker):
        module.prepare(root, proof, engineering)
    assert not root.exists()


def test_other_or_existing_root_is_rejected_without_reading_evidence(tmp_path, monkeypatch):
    fixed = tmp_path / "fixed"
    monkeypatch.setattr(module, "ROOT", fixed)
    for root in (tmp_path / "wrong", tmp_path):
        with pytest.raises(ProviderStop, match="ONE_FRESH_FIXED_PRESENTATION_INSTANCE_REQUIRED"):
            module.prepare(root, tmp_path / "missing-proof", tmp_path / "missing-engineering")
    fixed.mkdir()
    with pytest.raises(ProviderStop, match="ONE_FRESH_FIXED_PRESENTATION_INSTANCE_REQUIRED"):
        module.prepare(fixed, tmp_path / "missing-proof", tmp_path / "missing-engineering")

"""Synthetic metadata/orchestration only; real sealer and replay never execute."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import prepare_v0224_bundle_authority as builder


def contract():
    inherited = {f"/synthetic/path-{i}": "a" * 64 for i in range(7113)}
    return {
        "status": "R03_AUTHORITY_PREPARATION_FROZEN",
        "roots": [{"path": "/synthetic/path-0", "sha256": "a" * 64, "purpose": "STATIC_TREE"}],
        "fresh_roles": {},
        "verifier_files": {},
        "files": {},
        "expected_inherited_files": inherited,
        "allowed_extra_files": {},
        "limits": {
            "max_header_bytes": 1000000,
            "max_payload_bytes": 1000000,
            "max_paths": 10000,
            "max_blobs": 10000,
        },
    }


def test_complete_contract_and_missing_source_or_inherited_refusal():
    data = contract()
    assert builder._validate_contract(data, set()).max_paths == 10000
    with pytest.raises(ValueError, match="COMPLETE_PREPARER_SOURCE"):
        builder._validate_contract(data, {"/source"})
    data["expected_inherited_files"].pop("/synthetic/path-1")
    with pytest.raises(ValueError, match="7113"):
        builder._validate_contract(data, set())


@pytest.mark.parametrize(
    "mutation", ["status", "extra", "source_conflict", "role_unpinned", "root_unpinned"]
)
def test_contract_rejects_unfrozen_or_unbound_inputs(mutation):
    data = contract()
    if mutation == "status":
        data["status"] = "DRAFT"
    elif mutation == "extra":
        data["allowed_extra_files"]["/extra"] = "a" * 64
    elif mutation == "source_conflict":
        data["files"]["/synthetic/path-0"] = "b" * 64
    elif mutation == "role_unpinned":
        data["fresh_roles"]["/unknown"] = {"sha256": "a" * 64, "roles": ["MANDATORY"]}
    else:
        data["roots"][0]["path"] = "/unknown"
    with pytest.raises(ValueError):
        builder._validate_contract(data, set())


def test_exact_inherited_coverage_and_only_declared_extra_subset():
    old = {"/old": "a" * 64}
    extra = {"/new": "b" * 64}
    builder._check_observed_coverage(old, old, extra)
    builder._check_observed_coverage({**old, **extra}, old, extra)
    for observed in ({}, {"/old": "b" * 64}, {**old, "/unknown": "b" * 64}):
        with pytest.raises(ValueError):
            builder._check_observed_coverage(observed, old, extra)


@pytest.fixture
def synthetic(monkeypatch, tmp_path):
    import v0220_evidence as evidence
    import v0222_scoped_cpu_guard as guard
    import v0224_bundle_revalidation as replay
    import v0224_static_bundle as sealing

    monkeypatch.setattr(guard, "enable_cpu_network_guard", lambda: None)
    monkeypatch.setattr(evidence, "dependencies", lambda entries: [])
    data = contract()
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(data))
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    calls = []

    def seal(output, *, roots, fresh_roles, limits):
        calls.append("seal")
        output.mkdir()
        package = b"synthetic package, no authority approval"
        candidate = {
            "proof_roots": roots,
            "fresh_roles": fresh_roles,
            "bundle_sha256": hashlib.sha256(package).hexdigest(),
        }
        (output / "static.bundle").write_bytes(package)
        (output / "candidate-receipt.json").write_text(json.dumps(candidate))
        (output / "seal-observation.json").write_text(
            json.dumps({"observed_files": data["expected_inherited_files"]})
        )
        return candidate

    def revalidate(output, **kwargs):
        calls.append("revalidate")
        output.mkdir()
        result = {"status": "MECHANICAL_STATIC_REVALIDATION_COMPLETE_NOT_APPROVAL"}
        (output / "mechanical-revalidation.json").write_text(json.dumps(result))
        return result

    monkeypatch.setattr(sealing, "seal_static_bundle", seal)
    monkeypatch.setattr(replay, "revalidate_candidate", revalidate)
    return path, pin, calls


def test_success_only_ready_never_approved_and_no_retry(synthetic):
    path, pin, calls = synthetic
    result = builder.prepare_authority(path, pin)
    assert calls == ["seal", "revalidate"]
    assert result["status"] == "READY_FOR_INDEPENDENT_AUTHORITY_REVIEW"
    assert result["runtime_authorized"] is False
    assert result["expected_inherited_paths"] == 7113
    assert result["external_scope_stats"]["closing_reads"] > 0
    assert len(result["generated_files"]) == 4
    terminal = json.loads((path.parent / "authority-v1/authority-helper-terminal.json").read_text())
    assert terminal["phases"][-1]["phase"] == "report"
    with pytest.raises(ValueError, match="NO_RETRY"):
        builder.prepare_authority(path, pin)


def test_wrong_contract_pin_records_failure_before_seal(synthetic):
    path, _pin, calls = synthetic
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        builder.prepare_authority(path, "0" * 64)
    assert calls == []
    failure = json.loads((path.parent / "authority-v1/authority-failure.json").read_text())
    assert failure["phase"] == "external_contract"
    assert not (path.parent / "authority-v1/authority-prepared.json").exists()


def test_mechanical_failure_preserves_primary_and_no_ready(synthetic, monkeypatch):
    import v0224_bundle_revalidation as replay

    path, pin, _calls = synthetic
    primary = RuntimeError("mechanical-original")

    def fail(*a, **kw):
        raise primary

    monkeypatch.setattr(replay, "revalidate_candidate", fail)
    with pytest.raises(RuntimeError) as raised:
        builder.prepare_authority(path, pin)
    assert raised.value is primary
    failure = json.loads((path.parent / "authority-v1/authority-failure.json").read_text())
    assert failure["phase"] == "mechanical_revalidation"
    assert not (path.parent / "authority-v1/authority-prepared.json").exists()


def test_local_budget_stops_before_next_phase_without_claiming_parent_wall(synthetic, monkeypatch):
    path, pin, calls = synthetic
    stamps = iter([1, 300_000_000_002, 300_000_000_003])
    monkeypatch.setattr(builder.time, "monotonic_ns", lambda: next(stamps))
    with pytest.raises(ValueError, match="PARENT_BOUND_STILL_REQUIRED"):
        builder.prepare_authority(path, pin)
    assert calls == []
    assert not (path.parent / "authority-v1/authority-prepared.json").exists()


def test_persisted_candidate_drift_is_not_revalidated(synthetic, monkeypatch):
    import v0224_static_bundle as sealing

    path, pin, calls = synthetic
    original = sealing.seal_static_bundle

    def changed(output, **kwargs):
        candidate = original(output, **kwargs)
        raw = dict(candidate)
        raw["proof_roots"] = []
        (output / "candidate-receipt.json").write_text(json.dumps(raw))
        return candidate

    monkeypatch.setattr(sealing, "seal_static_bundle", changed)
    with pytest.raises(ValueError, match="PERSISTED_SEAL_CANDIDATE_DRIFT"):
        builder.prepare_authority(path, pin)
    assert calls == ["seal"]


def test_persisted_mechanical_drift_is_not_ready(synthetic, monkeypatch):
    import v0224_bundle_revalidation as replay

    path, pin, calls = synthetic
    original = replay.revalidate_candidate

    def changed(output, **kwargs):
        result = original(output, **kwargs)
        (output / "mechanical-revalidation.json").write_text(
            json.dumps({**result, "extra": "drift"})
        )
        return result

    monkeypatch.setattr(replay, "revalidate_candidate", changed)
    with pytest.raises(ValueError, match="PERSISTED_MECHANICAL_REVALIDATION_DRIFT"):
        builder.prepare_authority(path, pin)
    assert calls == ["seal", "revalidate"]
    assert not (path.parent / "authority-v1/authority-prepared.json").exists()

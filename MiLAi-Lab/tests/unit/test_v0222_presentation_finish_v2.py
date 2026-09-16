"""Parent orchestration with real SQL/FSM/scopes, explicitly synthetic audit.

These tests do not exercise the raw HTTP/World auditor or actual child exits.
Those are separate adapter/integration obligations. No HTTP is performed.
"""

import copy
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0222_presentation_batch_v2 import known, put, reservation
from test_v0222_presentation_batch_v2 import setup as core_setup
from test_v0222_presentation_gates_v2 import install_review_prerequisites

import v0222_presentation_finish_v2 as module
from v0220_provider_hardened import ProviderStop, usage_state
from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope


@pytest.fixture
def setup(tmp_path, monkeypatch):
    batch, clock, pid, scopes, anchor = core_setup.__wrapped__(tmp_path, monkeypatch)
    batch.__class__ = module.Batch
    for i, spec in enumerate(batch.plan["P3"]):
        spec["variant"] = "full" if i % 2 == 0 else "finish"
    # Explicit synthetic preparations, not a real authorization or source proof.
    required = install_review_prerequisites(batch, anchor)
    review = {
        "status": "G_AUTH_SCOPE_REVIEW_PASS",
        "root": str(batch.root),
        "binding_sha256": batch.binding_sha,
        "review_is_not_user_consent": True,
        "files": required,
    }
    review_path = batch.root / "scope_review.json"
    put(review_path, review)
    with batch.transaction() as db:
        db.execute("DELETE FROM artifacts WHERE name='scope_review'")
    batch.freeze_artifact("scope_review", review_path)
    batch.launch_once("P3")

    def synthetic_audit(episode, rows, events):
        # Acquiring an independent writer proves the baseline SQL context was
        # released before independent auditing. It performs no mutation.
        with sqlite3.connect(batch.path, timeout=0.1) as probe:
            probe.execute("BEGIN IMMEDIATE")
            probe.rollback()
        keys = {
            e["request_id"] for e in events if e["event"] == "RESERVED" and e["session"] == episode
        }
        files = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (batch.root / "episodes" / episode).rglob("*")
            if p.is_file()
            and p.suffix in {".json", ".jsonl"}
            and p.name != "independent-audit.json"
        }
        for path in (
            batch.claim_marker_path(episode),
            batch.root / "live-launch-P3.json",
            batch.root / "exits" / (episode + ".json"),
        ):
            files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "status": "PASS",
            "id": episode,
            "stage": "P3",
            "pid": rows["episode_row"]["pid"],
            "cost": usage_state([e for e in events if e["request_id"] in keys]),
            "checks": {"synthetic_only": True},
            "files": files,
        }

    monkeypatch.setattr(batch, "_audit", synthetic_audit)
    return batch, clock, pid, scopes, anchor


def worker_done(setup, index=0):
    batch, _, pid, _, _ = setup
    episode, key = f"P3-{index:02}", f"req-{index:02}"
    pid[0] = 201 + index
    batch.claim(episode)
    batch.reserve_request(episode, reservation(key, episode))
    batch.dispatch_started(episode, key)
    batch.settle_event(episode, {"event": "RESPONSE_RECEIVED", "request_id": key})
    batch.settle_event(episode, known(key))
    put(
        batch.root / "episodes" / episode / "worker-result.json", {"pid": pid[0], "synthetic": True}
    )
    put(
        batch.root / "exits" / (episode + ".json"),
        {"pid": pid[0], "parent_pid": 101, "returncode": 0, "timed_out": False, "seconds": 0.5},
    )
    pid[0] = 101
    return episode


def audit_row(batch, episode):
    with batch.transaction() as db:
        return db.execute("SELECT * FROM artifacts WHERE name=?", (episode + "_audit",)).fetchone()


def test_finish_after_close_binds_external_evidence_without_pinning_live_ledger(setup, monkeypatch):
    batch, _, _, scopes, _ = setup
    episode = worker_done(setup)
    original = AdmissionReadScope.read_bytes

    def no_live_pin(scope, path, expected_sha256):
        assert path != batch._ledger(episode)
        return original(scope, path, expected_sha256)

    monkeypatch.setattr(AdmissionReadScope, "read_bytes", no_live_pin)
    audit = batch.finish(episode)
    assert audit["status"] == "PASS" and audit_row(batch, episode) is not None
    row = next(r for r in batch.snapshot()["episodes"] if r["id"] == episode)
    assert row["status"] == "PASS"
    assert str(batch.claim_marker_path(episode)) in audit["files"]
    assert str(batch.root / "exits" / (episode + ".json")) in audit["files"]
    assert scopes[-1].status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
    assert batch.snapshot()["cost"]["known_raw_tokens"] == 13


def test_worker_cannot_finish_itself(setup):
    batch, _, pid, _, _ = setup
    episode = worker_done(setup)
    pid[0] = 201
    with pytest.raises(ProviderStop, match="NO_OWNED"):
        batch.finish(episode)
    assert audit_row(batch, episode) is None


@pytest.mark.parametrize("change", ["status", "id", "stage", "pid"])
def test_invalid_audit_header_never_accepted(setup, monkeypatch, change):
    batch = setup[0]
    episode = worker_done(setup)
    original = batch._audit

    def invalid(*args):
        value = original(*args)
        value[change] = "INVALID"
        return value

    monkeypatch.setattr(batch, "_audit", invalid)
    with pytest.raises(ProviderStop, match="FULL_ACCEPTANCE"):
        batch.finish(episode)
    assert audit_row(batch, episode) is None


@pytest.mark.parametrize(
    "change", ["sql", "stop", "raw", "extra_raw", "claim", "source", "expired"]
)
def test_changes_during_audit_fail_closed(setup, monkeypatch, change):
    batch, clock, _, _, anchor = setup
    episode = worker_done(setup)
    original = batch._audit

    def changed(*args):
        audit = original(*args)
        if change == "sql":
            with batch.transaction() as db:
                db.execute("INSERT INTO meta VALUES ('unexpected','change')")
        elif change == "stop":
            batch.stop("MID_AUDIT_STOP")
        elif change == "raw":
            put(batch.root / "episodes" / episode / "worker-result.json", {"changed": True})
        elif change == "extra_raw":
            put(batch.root / "episodes" / episode / "extra.json", {"unbound": True})
        elif change == "claim":
            put(batch.claim_marker_path(episode), {"changed": True})
        elif change == "source":
            put(anchor, {"changed": True})
        else:
            clock[0] += 301
        return audit

    monkeypatch.setattr(batch, "_audit", changed)
    with pytest.raises((ProviderStop, AdmissionReadError)):
        batch.finish(episode)
    assert audit_row(batch, episode) is None
    state = batch.snapshot()
    assert state["stop"] == "MID_AUDIT_STOP" if change == "stop" else state["stop"] is not None
    assert next(r for r in state["episodes"] if r["id"] == episode)["status"] == "FAIL"


@pytest.mark.parametrize("after", ["close", "last_raw_recheck"])
def test_deadline_after_close_or_last_file_hash_cannot_commit_pass(setup, monkeypatch, after):
    batch, clock, _, _, _ = setup
    episode = worker_done(setup)
    if after == "close":
        original = AdmissionReadScope._close

        def close(self, body_error=None):
            original(self, body_error)
            clock[0] += 301

        monkeypatch.setattr(AdmissionReadScope, "_close", close)
    else:
        original = batch._verify_episode_files
        calls = []

        def verify(*args):
            original(*args)
            calls.append(None)
            if len(calls) == 2:
                clock[0] += 301

        monkeypatch.setattr(batch, "_verify_episode_files", verify)
    with pytest.raises(ProviderStop):
        batch.finish(episode)
    assert audit_row(batch, episode) is None
    assert (batch.root / "episodes" / episode / "independent-audit.json").exists()
    assert next(r for r in batch.snapshot()["episodes"] if r["id"] == episode)["status"] == "FAIL"


def complete_synthetic_matrix(setup):
    batch = setup[0]
    for index in range(16):
        batch.finish(worker_done(setup, index))
    return batch


def test_nested_audit_namesake_added_after_close_is_not_hidden(setup, monkeypatch):
    batch = setup[0]
    episode = worker_done(setup)
    original = AdmissionReadScope._close

    def close(scope, body_error=None):
        original(scope, body_error)
        put(
            batch.root / "episodes" / episode / "nested" / "independent-audit.json",
            {"unbound": True},
        )

    monkeypatch.setattr(AdmissionReadScope, "_close", close)
    with pytest.raises(ProviderStop, match="EXACT_RAW_EPISODE"):
        batch.finish(episode)
    assert audit_row(batch, episode) is None


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_final_p4_file_check_rejects_new_unbound_world_sidecar(setup, suffix):
    # File-set component only: not a P4 claim, Session execution or raw audit.
    batch = setup[0]
    episode = "P4-00"
    world = batch.root / "worlds" / (episode + ".sqlite")
    paths = [
        world,
        batch.claim_marker_path(episode),
        batch.root / "exits" / (episode + ".json"),
        batch.root / "live-launch-P4.json",
    ]
    files = {str(path): put(path, {"synthetic_file_check": True}) for path in paths}
    batch._verify_episode_files(episode, {"files": files})
    Path(str(world) + suffix).write_bytes(b"UNBOUND_SIDECAR")
    with pytest.raises(ProviderStop, match="SIDECARS"):
        batch._verify_episode_files(episode, {"files": files})


def test_complete_p3_gate_reaudits_every_position_and_freezes_once(setup, monkeypatch):
    batch = complete_synthetic_matrix(setup)
    original, seen = batch._audit, []

    def audited(episode, rows, events):
        seen.append(episode)
        assert rows["episode_row"]["status"] == "PASS"
        return original(episode, rows, events)

    monkeypatch.setattr(batch, "_audit", audited)
    path = batch.root / "P3-gate.json"
    gate = batch.freeze_p3_gate(path)
    assert seen == [s["id"] for s in batch.plan["P3"]]
    assert gate["full_passed"] == gate["finish_passed"] == 8
    with batch.transaction() as db:
        row = dict(db.execute("SELECT * FROM artifacts WHERE name='P3_gate'").fetchone())
    assert json.loads(path.read_bytes()) == gate
    assert json.loads(row["dependencies"]) == gate["files"]
    assert batch.snapshot()["cost"]["requests"] == 16
    with pytest.raises(ProviderStop, match="ALREADY_FROZEN"):
        batch.freeze_p3_gate(path)


def test_p3_gate_does_not_offset_unrun_positions(setup):
    batch = setup[0]
    batch.finish(worker_done(setup))
    with pytest.raises(ProviderStop, match="16_ACTUAL_PASS"):
        batch.p3_gate()


@pytest.mark.parametrize(
    "change", ["changed_audit", "phase_expired", "wrong_parent", "wrong_matrix", "forged_file"]
)
def test_complete_count_alone_cannot_mint_p3_gate(setup, monkeypatch, change):
    batch = complete_synthetic_matrix(setup)
    _, clock, pid, _, _ = setup
    path = batch.root / "P3-gate.json"
    if change == "changed_audit":
        original = batch._audit

        def altered(*args):
            result = copy.deepcopy(original(*args))
            result["checks"]["new"] = True
            return result

        monkeypatch.setattr(batch, "_audit", altered)
    elif change == "phase_expired":
        clock[0] += 1801  # No RUNNING rows remain; stage still must be checked.
    elif change == "wrong_parent":
        pid[0] = 999
    elif change == "wrong_matrix":
        batch.plan["P3"][0]["variant"] = "finish"
    else:
        put(path, {"status": "G_P3_PASS", "forged": True})
    with pytest.raises(ProviderStop):
        batch.freeze_p3_gate(path)
    with batch.transaction() as db:
        assert db.execute("SELECT 1 FROM artifacts WHERE name='P3_gate'").fetchone() is None

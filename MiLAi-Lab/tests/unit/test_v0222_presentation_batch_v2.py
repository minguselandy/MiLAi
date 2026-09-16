"""Synthetic dynamic coordinator checks; not a sealed Batch or cold-worker proof.

Static authorization is an explicit local fixture that reads a real pinned
anchor into each scope. Full lineage/authorization integration is tested
separately; no network or actual GPU/device operations are performed.
"""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_presentation_batch_v2 as module
from v0220_provider_hardened import ProviderStop
from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    batch = object.__new__(module.Batch)
    batch.root, batch.path = tmp_path, tmp_path / "batch.sqlite"
    batch.binding_sha = "b" * 64
    batch.auth = {"issued_unix": 900.0, "expires_unix": 10000.0}
    batch.plan = {
        stage: [{"id": f"{stage}-{i:02}", "stage": stage} for i in range(count)]
        for stage, count in (("P3", 16), ("P4", 24))
    }
    anchor = tmp_path / "anchor.json"
    digest = put(anchor, {"synthetic": True})
    observed_scopes, clock, pid = [], [1000.0], [101]

    def authorize(stage, scope):
        assert stage in {"PREP", "P3", "P4"}
        scope.read_json(anchor, digest)
        observed_scopes.append(scope)
        return copy.deepcopy(batch.auth), copy.deepcopy(batch.plan)

    monkeypatch.setattr(batch, "_authorize", authorize)
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    monkeypatch.setattr(module.os, "getpid", lambda: pid[0])
    batch.initialize()
    for name, status in [
        ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
        ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
        ("P3_preflight", "G_PREFLIGHT_PASS"),
        ("P4_preflight", "G_PREFLIGHT_PASS"),
        ("P3_references", "SYNTHETIC"),
        ("P4_references", "SYNTHETIC"),
        ("P4_resolved_specs", "SYNTHETIC"),
    ]:
        path = tmp_path / (name + ".json")
        files = {str(anchor): digest}
        sha = put(path, {"status": status, "files": files})
        with batch.transaction() as db:
            db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?)", (name, str(path), sha, json.dumps(files))
            )
    for stage in batch.plan:
        for spec in batch.plan[stage]:
            batch._ledger(spec["id"]).parent.mkdir(parents=True, exist_ok=True)
    return batch, clock, pid, observed_scopes, anchor


def claimed(setup):
    batch, clock, pid, scopes, anchor = setup
    batch.launch_once("P3")
    pid[0] = 201
    batch.claim("P3-00")
    return batch, clock, pid, scopes, anchor


def reservation(key="req", episode="P3-00"):
    return {
        "event": "RESERVED",
        "request_id": key,
        "session": episode,
        "prompt_tokens": 10,
        "output_cap": 4096,
        "raw_upper_bound": 4106,
        "payload_sha256": "a" * 64,
        "cumulative_raw_cap": None,
    }


def known(key="req", prompt=10, completion=3):
    return {
        "event": "USAGE_KNOWN",
        "request_id": key,
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


def dispatch(batch):
    batch.reserve_request("P3-00", reservation())
    batch.dispatch_started("P3-00", "req")
    return batch.http_admit("P3-00", inflight=True)


def test_separate_http_scopes_close_before_return(setup):
    batch, _, _, scopes, _ = claimed(setup)
    first = batch.http_admit("P3-00")
    assert scopes[-1].status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
    second = batch.http_admit("P3-00")
    assert first == second
    assert scopes[-1] is not scopes[-2]
    assert all(s.stats["first_reads"] == s.stats["closing_reads"] > 0 for s in scopes)
    # Returned admission did not retain an open SQLite writer transaction.
    with batch.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_reserve_dispatch_settlement_separate_from_admission(setup):
    batch, _, _, _, _ = claimed(setup)
    dispatch(batch)
    batch.settle_event("P3-00", {"event": "RESPONSE_RECEIVED", "request_id": "req"})
    batch.settle_event("P3-00", known())
    assert batch.admit("P3-00")["status"] == "RUNNING"
    state = batch.snapshot()
    assert state["stop"] is None and state["cost"]["known_raw_tokens"] == 13
    with batch.transaction() as db:
        batch._mirrors(db)


def test_late_usage_survives_stop_and_expiry_without_revival(setup):
    batch, clock, _, scopes, _ = claimed(setup)
    dispatch(batch)
    batch.stop("ORIGINAL_STOP")
    clock[0] = 20000
    count = len(scopes)
    batch.settle_event("P3-00", {"event": "RESPONSE_RECEIVED", "request_id": "req"})
    batch.settle_event("P3-00", known())
    assert len(scopes) == count  # No expired static authorization prerequisite for accounting.
    state = batch.snapshot()
    assert state["stop"] == "ORIGINAL_STOP"
    assert state["episodes"][0]["status"] == "FAIL"
    assert state["cost"]["known_raw_tokens"] == 13
    with pytest.raises(ProviderStop):
        batch.http_admit("P3-00")
    assert batch.snapshot()["stop"] == "ORIGINAL_STOP"


@pytest.mark.parametrize("prompt,completion", [(11, 3), (10, 4097)])
def test_real_overbound_usage_is_charged_and_atomically_stops(setup, prompt, completion):
    batch, *_ = claimed(setup)
    dispatch(batch)
    batch.settle_event("P3-00", {"event": "RESPONSE_RECEIVED", "request_id": "req"})
    batch.settle_event("P3-00", known(prompt=prompt, completion=completion))
    state = batch.snapshot()
    assert state["stop"] == "BOUND_VIOLATION"
    assert state["cost"]["known_raw_tokens"] == prompt + completion
    assert len(state["cost"]["violations"]) == 1
    assert state["episodes"][0]["status"] == "FAIL"
    with batch.transaction() as db:
        batch._mirrors(db)


def test_unknown_not_automatically_reconciled(setup):
    batch, *_ = claimed(setup)
    dispatch(batch)
    batch.settle_event("P3-00", {"event": "USAGE_UNKNOWN", "request_id": "req"})
    with pytest.raises(ProviderStop, match="CORRUPT_USAGE_LEDGER"):
        batch.settle_event("P3-00", known())
    state = batch.snapshot()
    assert state["stop"] == "USAGE_UNKNOWN"
    assert state["cost"]["actual_total_raw_tokens"] is None
    assert state["cost"]["known_raw_tokens"] == 0


@pytest.mark.parametrize("kind", ["RESERVED", "DISPATCH_STARTED", "FAKE"])
def test_settlement_cannot_create_send_and_invalid_event_stops(setup, kind):
    batch, *_ = claimed(setup)
    with pytest.raises(ProviderStop, match="SETTLEMENT_EVENT_ONLY"):
        batch.settle_event("P3-00", {"event": kind, "request_id": "req"})
    assert batch.snapshot()["stop"] == "SETTLEMENT_EVENT_ONLY"
    assert batch.snapshot()["cost"]["requests"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("output_cap", 4095),
        ("output_cap", True),
        ("cumulative_raw_cap", 999999),
        ("session", "P4-00"),
    ],
)
def test_bad_reservation_stops_without_recording(setup, field, value):
    batch, *_ = claimed(setup)
    event = reservation()
    event[field] = value
    with pytest.raises(ProviderStop, match="FROZEN_REQUEST_RESERVATION_REQUIRED"):
        batch.reserve_request("P3-00", event)
    assert batch.snapshot()["stop"] == "FROZEN_REQUEST_RESERVATION_REQUIRED"
    assert batch.snapshot()["cost"]["requests"] == 0


@pytest.mark.parametrize(
    "mutation", ["stop", "owner", "deadline", "phase", "claim", "anchor", "binding"]
)
def test_changes_between_http_calls_fail_stop(setup, mutation):
    batch, clock, _, _, anchor = claimed(setup)
    batch.http_admit("P3-00")
    if mutation == "stop":
        batch.stop("EXTERNAL_STOP")
    elif mutation == "anchor":
        put(anchor, {"changed": True})
    elif mutation == "claim":
        put(batch.claim_marker_path("P3-00"), {"fake": True})
    else:
        with batch.transaction() as db:
            if mutation == "owner":
                db.execute("UPDATE episodes SET pid=888 WHERE id='P3-00'")
            elif mutation == "deadline":
                db.execute("UPDATE episodes SET deadline=? WHERE id='P3-00'", (clock[0] + 9999,))
            elif mutation == "phase":
                db.execute("UPDATE meta SET value='999999' WHERE key='P3_deadline'")
            else:
                db.execute("UPDATE meta SET value='wrong' WHERE key='binding'")
    with pytest.raises((ProviderStop, AdmissionReadError)):
        batch.http_admit("P3-00")
    if mutation != "binding":
        assert batch.snapshot()["stop"] is not None
    # Binding drift cannot authorize a write to the now-unowned coordinator.


def test_closing_hash_time_exhaustion_prevents_return(setup, monkeypatch):
    batch, clock, _, scopes, _ = claimed(setup)
    original = AdmissionReadScope._close

    def close(self, body_error=None):
        original(self, body_error)
        clock[0] += 301

    monkeypatch.setattr(AdmissionReadScope, "_close", close)
    with pytest.raises(ProviderStop, match="EPISODE_DEADLINE"):
        batch.http_admit("P3-00")
    assert scopes[-1].status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
    assert batch.snapshot()["stop"] == "EPISODE_DEADLINE"


def test_claim_deadline_also_rechecked_after_close(setup, monkeypatch):
    batch, clock, pid, _, _ = setup
    batch.launch_once("P3")
    pid[0] = 201
    original = AdmissionReadScope._close

    def close(self, body_error=None):
        original(self, body_error)
        clock[0] += 301

    monkeypatch.setattr(AdmissionReadScope, "_close", close)
    with pytest.raises(ProviderStop, match="EPISODE_DEADLINE"):
        batch.claim("P3-00")
    state = batch.snapshot()
    assert state["stop"] == "EPISODE_DEADLINE"
    assert state["episodes"][0]["status"] == "PENDING"  # Original claim SQL rolled back.
    assert batch.claim_marker_path("P3-00").exists()  # Failed evidence is retained.


def test_pending_reservation_not_permission_for_second_reserve(setup):
    batch, *_ = claimed(setup)
    batch.reserve_request("P3-00", reservation())
    with pytest.raises(ProviderStop, match="UNKNOWN_OR_INVALID"):
        batch.reserve_request("P3-00", reservation("second"))
    assert batch.snapshot()["cost"]["requests"] == 1


def test_mirror_drift_stops_before_any_new_event(setup):
    batch, *_ = claimed(setup)
    batch.reserve_request("P3-00", reservation())
    batch._ledger("P3-00").write_bytes(b"")
    with pytest.raises(ProviderStop, match="DIVERGED"):
        batch.dispatch_started("P3-00", "req")
    assert batch.snapshot()["cost"]["requests"] == 1
    with batch.transaction() as db:
        assert len(batch.events(db)) == 1


def test_dispatch_cannot_be_added_after_stop(setup):
    batch, *_ = claimed(setup)
    batch.reserve_request("P3-00", reservation())
    batch.stop("ORIGINAL_STOP")
    with pytest.raises(ProviderStop, match="BATCH_STOPPED"):
        batch.dispatch_started("P3-00", "req")
    with batch.transaction() as db:
        assert len(batch.events(db)) == 1
    assert batch.snapshot()["stop"] == "ORIGINAL_STOP"


def test_caught_semantic_error_poison_closes_then_stops_outside_sql_lock(setup, monkeypatch):
    batch, _, _, scopes, _ = claimed(setup)
    original = batch._check_journal

    def check(db, scope, **kwargs):
        state = original(db, scope, **kwargs)
        try:
            scope.read_json(batch.root / "anchor.json", "0" * 64)
        except AdmissionReadError:
            assert scope.status == "POISONED"
        return state

    monkeypatch.setattr(batch, "_check_journal", check)
    with pytest.raises(AdmissionReadError):
        batch.http_admit("P3-00")
    assert scopes[-1].status == "CLOSED_FAILED"
    state = batch.snapshot()  # A nested writer stop would have failed with a lock error.
    assert state["stop"] is not None and state["episodes"][0]["status"] == "FAIL"


@pytest.mark.parametrize("target", ["sql_map", "file_map", "artifact_path"])
def test_mutable_ledger_never_enters_frozen_artifact_scope(setup, target):
    batch, *_ = claimed(setup)
    ledger = batch._ledger("P3-00")
    sha = put(ledger, {"not": "a valid event"})
    artifact = batch.root / "injected.json"
    dependencies = {str(ledger): sha} if target == "sql_map" else {}
    body = {"files": {str(ledger): sha}} if target == "file_map" else {"synthetic": True}
    artifact_sha = put(artifact, body)
    if target == "artifact_path":
        artifact, artifact_sha = ledger, sha
    with batch.transaction() as db:
        db.execute(
            "INSERT INTO artifacts VALUES (?,?,?,?)",
            ("injected", str(artifact), artifact_sha, json.dumps(dependencies)),
        )
        with pytest.raises(ProviderStop, match="DYNAMIC_JOURNAL"):
            with AdmissionReadScope() as scope:
                with pytest.raises(ProviderStop, match="DYNAMIC_JOURNAL"):
                    batch._artifact(db, "injected", scope)
                assert scope.status == "POISONED"
                assert scope.stats["first_reads"] == (1 if target == "file_map" else 0)


def test_second_claim_same_pid_and_p4_without_gate_rejected(setup):
    batch, _, pid, _, _ = claimed(setup)
    with pytest.raises(ProviderStop, match="SINGLE_ACTIVE"):
        batch.claim("P3-01")
    assert batch.snapshot()["stop"] == "SINGLE_ACTIVE_EPISODE_ONLY"
    pid[0] = 101
    with pytest.raises(ProviderStop):
        batch.launch_once("P4")


def test_p4_requires_new_full_gate(setup):
    batch, *_ = setup
    with pytest.raises(ProviderStop, match="FROZEN_ARTIFACT_REQUIRED"):
        batch.launch_once("P4")
    assert batch.snapshot()["stop"] == "FROZEN_ARTIFACT_REQUIRED"


def test_second_reservation_and_other_owner_settlement_rejected(setup):
    batch, _, pid, _, _ = claimed(setup)
    dispatch(batch)
    pid[0] = 999
    with pytest.raises(ProviderStop, match="NOT_OWNED"):
        batch.settle_event("P3-00", {"event": "RESPONSE_RECEIVED", "request_id": "req"})
    assert batch.snapshot()["cost"]["actual_total_raw_tokens"] is None


def test_new_root_cannot_open_old_instance():
    with pytest.raises(ProviderStop, match="FIXED_CANONICAL"):
        module.Batch(module.PRESENTATION_ROOT, module.PRESENTATION_BINDING)


@pytest.mark.parametrize("issued,expires", [(1, float("inf")), (True, 10), (10, 10), (1, 129602)])
def test_authorization_window_is_not_extended(issued, expires):
    with pytest.raises(ProviderStop, match="FINITE_36_HOUR"):
        module.make_authorization(module.ROOT, issued=issued, expires=expires, history={})

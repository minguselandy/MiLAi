"""Synthetic boundary negatives, never historical/K1 fixtures or real HTTP.

Static authorization or audit seams are stated in inherited fixture docstrings.
World effects use an independently created public synthetic Lab World. Dynamic
paths are unchanged by the tree candidate; running both contexts checks absence
of interference, not a claim that every dynamic check itself traverses a tree.
The rollback characterization deliberately reports a preexisting missing promise.
"""

import copy
import json
import sqlite3
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import adapter as adapter_fixture
from test_v0220_action_adapter import put as action
from test_v0222_presentation_batch_v2 import claimed, dispatch, known, put, reservation
from test_v0222_presentation_batch_v2 import setup as core_fixture
from test_v0222_presentation_batch_v2_controls import control as control_fixture
from test_v0222_presentation_finish_v2 import audit_row, worker_done
from test_v0222_presentation_finish_v2 import setup as finish_fixture
from test_v0222_presentation_gates_v2 import candidate, rows
from test_v0222_presentation_gates_v2 import setup as gate_fixture

import v0222_presentation_batch_v2 as core
from v0218_world import digest
from v0220_intent_audit import effects
from v0220_provider_hardened import ProviderStop
from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope


@pytest.fixture(params=["original", "candidate"], autouse=True)
def implementation(request, record_property):
    record_property("implementation", request.param)
    if request.param == "candidate":
        from v0223_tree_readonly_candidate import installed_candidate

        context = installed_candidate()
    else:
        context = nullcontext()
    with context:
        yield request.param


@pytest.mark.parametrize("edge", ["sql_only", "file_only"])
def test_mandatory_existing_edge_omission_rejected(tmp_path, monkeypatch, edge):
    setup = gate_fixture.__wrapped__(tmp_path, monkeypatch)
    batch = setup[0]
    path, value = candidate(setup)
    leaf = batch.root / (
        "P3_references-scope-sql-only.json" if edge == "sql_only" else "anchor.json"
    )
    assert leaf.is_file()  # Remove the binding edge; do not remove its target file.
    del value["files"][str(leaf)]
    put(path, value)
    with pytest.raises(ProviderStop, match="SCOPE_REVIEW_MUST_COVER_CURRENT_COMPLETE_PREPARATION"):
        batch.freeze_artifact("scope_review", path)
    assert leaf.is_file() and not rows(batch)
    assert batch.snapshot()["stop"]


@pytest.mark.parametrize("member", ["authorization.json", "authorization-source.json"])
@pytest.mark.parametrize("boundary", ["between_admissions", "during_close"])
def test_grant_bytes_fresh_at_original_control_boundaries(tmp_path, monkeypatch, member, boundary):
    control = control_fixture.__wrapped__(tmp_path, monkeypatch)
    batch = core.Batch(control["root"], control["digest"])
    path = control["root"] / member
    if boundary == "between_admissions":
        put(path, {"changed": True})
        expected = "INITIAL_CONTENT_HASH_MISMATCH"
    else:
        close = AdmissionReadScope._close

        def mutate(scope, body_error=None):
            put(path, {"changed": True})
            return close(scope, body_error)

        monkeypatch.setattr(AdmissionReadScope, "_close", mutate)
        expected = "CLOSING_CONTENT_OR_PATH_IDENTITY_MISMATCH"
    with pytest.raises(AdmissionReadError, match=expected):
        batch.authorize("PREP")
    assert not batch.path.exists()  # Constructor/authorize has no dynamic owner boundary.


@pytest.mark.parametrize("change", ["stop", "owner", "phase"])
def test_active_authority_drift_prevents_next_operation(tmp_path, monkeypatch, change):
    setup = claimed(core_fixture.__wrapped__(tmp_path, monkeypatch))
    batch = setup[0]
    batch.http_admit("P3-00")  # Pure local admission, never transport.
    if change == "stop":
        batch.stop("EXTERNAL_STOP")
    else:
        with batch.transaction() as db:
            if change == "owner":
                db.execute("UPDATE episodes SET pid=999 WHERE id='P3-00'")
            else:
                db.execute("UPDATE meta SET value='1' WHERE key='P3_deadline'")
    expected = {
        "stop": "BATCH_STOPPED_NO_RETRY",
        "owner": "CLAIM_OWNER_OR_EPISODE_DEADLINE_DRIFT",
        "phase": "PHASE_DEADLINE_DRIFT",
    }[change]
    with pytest.raises(ProviderStop, match=expected):
        batch.http_admit("P3-00")
    with batch.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert batch.snapshot()["stop"]


def test_post_close_expiry_prevents_body_write_commit(tmp_path, monkeypatch):
    batch, clock, *_ = core_fixture.__wrapped__(tmp_path, monkeypatch)
    original_close = AdmissionReadScope._close

    def expires_after_close(scope, body_error=None):
        result = original_close(scope, body_error)
        clock[0] = batch.auth["expires_unix"]
        return result

    monkeypatch.setattr(AdmissionReadScope, "_close", expires_after_close)
    with pytest.raises(ProviderStop, match="AUTHORIZATION_EXPIRED"):
        with batch._operation("PREP") as (db, _, _state):
            db.execute("INSERT INTO meta VALUES ('MUST_ROLL_BACK','body')")
    with batch.transaction() as db:
        assert db.execute("SELECT value FROM meta WHERE key='MUST_ROLL_BACK'").fetchone() is None


@pytest.mark.parametrize("mutation", ["insert", "delete", "reorder", "mirror"])
def test_current_event_mutation_blocks_new_dispatch(
    tmp_path, monkeypatch, mutation, record_property
):
    batch, *_ = claimed(core_fixture.__wrapped__(tmp_path, monkeypatch))
    dispatch(batch)
    with batch.transaction() as db:
        before = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if mutation == "insert":
            db.execute(
                "INSERT INTO events(event) VALUES (?)",
                (json.dumps({"event": "DISPATCH_STARTED", "request_id": "unreserved"}),),
            )
        elif mutation == "delete":
            db.execute("DELETE FROM events WHERE seq=(SELECT MIN(seq) FROM events)")
        elif mutation == "reorder":
            values = db.execute("SELECT seq,event FROM events ORDER BY seq").fetchall()
            db.execute("UPDATE events SET event=? WHERE seq=?", (values[1][1], values[0][0]))
            db.execute("UPDATE events SET event=? WHERE seq=?", (values[0][1], values[1][0]))
    if mutation == "mirror":
        batch._ledger("P3-00").write_text("")
    with pytest.raises(ProviderStop) as caught:
        batch.http_admit("P3-00", inflight=True)
    record_property("first_cause", str(caught.value))
    with batch.transaction() as db:
        count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == before + (1 if mutation == "insert" else -1 if mutation == "delete" else 0)


def test_old_unknown_preserved_and_new_unknown_blocks(tmp_path, monkeypatch):
    control = control_fixture.__wrapped__(tmp_path / "control", monkeypatch)
    batch = core.Batch(control["root"], control["digest"])
    before = copy.deepcopy(batch.auth["accepted_unknown"])
    assert before and batch.authorize("PREP")["accepted_unknown"] == before
    runtime = claimed(core_fixture.__wrapped__(tmp_path / "runtime", monkeypatch))[0]
    dispatch(runtime)
    runtime.settle_event("P3-00", {"event": "USAGE_UNKNOWN", "request_id": "req"})
    # Settlement itself records stop; this earlier rule is the next first cause.
    assert runtime.snapshot()["stop"]
    with pytest.raises(ProviderStop, match="BATCH_STOPPED_NO_RETRY"):
        runtime.http_admit("P3-00")
    cost = runtime.snapshot()["cost"]
    assert cost["actual_total_raw_tokens"] is None and cost["unresolved_reservations"]
    assert batch.auth["accepted_unknown"] == before


def test_body_close_stop_firstcause_and_sql_rollback(tmp_path, monkeypatch):
    batch, _, _, _, anchor = core_fixture.__wrapped__(tmp_path, monkeypatch)
    primary = RuntimeError("PRIMARY_BODY_FAILURE")

    def stop_failure(reason):
        raise OSError("SECONDARY_STOP_FAILURE_TEST")

    monkeypatch.setattr(batch, "stop", stop_failure)
    with pytest.raises(RuntimeError) as caught:
        with batch._operation("PREP") as (db, _, _state):
            db.execute("INSERT INTO meta VALUES ('MUST_ROLL_BACK','body')")
            put(anchor, {"changed_after_first_read": True})
            raise primary
    assert caught.value is primary
    assert any("closing failure" in note for note in primary.__notes__)
    assert any("SECONDARY_STOP_FAILURE" in note for note in primary.__notes__)
    with batch.transaction() as db:
        assert db.execute("SELECT value FROM meta WHERE key='MUST_ROLL_BACK'").fetchone() is None


@pytest.mark.parametrize("cleanup", ["rollback", "close", "rollback_and_close"])
def test_rollback_failure_exposes_existing_primary_preservation_gap(
    tmp_path, monkeypatch, record_property, cleanup
):
    """Characterize missing original guarantee, NOT an A2 rollback PASS."""
    batch = core_fixture.__wrapped__(tmp_path, monkeypatch)[0]
    connect = sqlite3.connect
    primary, rollback = RuntimeError("PRIMARY_BODY_FAILURE"), OSError("ROLLBACK_FAILURE")
    close_error = OSError("CLOSE_FAILURE")

    class Connection:
        def __init__(self, db):
            object.__setattr__(self, "db", db)

        def __getattr__(self, key):
            return getattr(self.db, key)

        def __setattr__(self, key, value):
            setattr(self.db, key, value)

        def rollback(self):
            if cleanup in {"rollback", "rollback_and_close"}:
                raise rollback
            return self.db.rollback()

        def close(self):
            self.db.close()
            if cleanup in {"close", "rollback_and_close"}:
                raise close_error

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: Connection(connect(*a, **kw)))
    with pytest.raises(OSError) as caught:
        with batch.transaction() as db:
            db.execute("INSERT INTO meta VALUES ('MUST_ROLL_BACK','body')")
            raise primary
    expected = rollback if cleanup == "rollback" else close_error
    assert caught.value is expected
    chain = []
    current = caught.value
    while current is not None:
        chain.append(str(current))
        current = current.__context__
    assert chain == (
        ["ROLLBACK_FAILURE", "PRIMARY_BODY_FAILURE"]
        if cleanup == "rollback"
        else ["CLOSE_FAILURE", "PRIMARY_BODY_FAILURE"]
        if cleanup == "close"
        else ["CLOSE_FAILURE", "ROLLBACK_FAILURE", "PRIMARY_BODY_FAILURE"]
    )
    record_property("actual_exception_chain", json.dumps(chain))
    with connect(batch.path) as db:
        assert db.execute("SELECT value FROM meta WHERE key='MUST_ROLL_BACK'").fetchone() is None
    record_property("existing_guarantee", "PREEXISTING_A2_GAP_CLEANUP_REPLACES_PRIMARY")


def effect_case(tmp_path):
    adapter = adapter_fixture.__wrapped__(tmp_path)
    initial = adapter.world.snapshot()
    first = adapter.execute(action(), operation_id="synthetic:01")
    turns = [
        {"turn": 1, "action": action(), "response": first},
        {
            "turn": 2,
            "action": {"action": "read", "arguments": {"resource": "records"}},
            "response": adapter.read("records"),
        },
        {
            "turn": 3,
            "action": {"action": "finish", "arguments": {"message": "done"}},
            "response": {"status": "SESSION_FINISHED"},
        },
    ]
    final_hash = digest(adapter.world.snapshot())
    for turn in turns:
        turn["before_sha256"] = digest(initial) if turn["turn"] == 1 else final_hash
        turn["after_sha256"] = final_hash
    spec = {
        "id": "synthetic",
        "scope": "owned",
        "initial_state_sha256": digest(initial),
        "actions": [action()],
    }
    return adapter, spec, initial, turns


def test_duplicate_receipt_cannot_count_as_second_effect(tmp_path):
    adapter, spec, initial, turns = effect_case(tmp_path)
    before = adapter.world.snapshot()
    assert effects(spec, initial, before, adapter.world.ledger(), turns)["status"] == "PASS"
    assert adapter.execute(action(), operation_id="synthetic:01") == turns[0]["response"]
    repeated = [turns[0], {**turns[0], "turn": 2}, *turns[1:]]
    verdict = effects(spec, initial, adapter.world.snapshot(), adapter.world.ledger(), repeated)
    assert verdict["status"] == "FAIL"
    assert adapter.world.snapshot() == before and len(adapter.world.ledger()) == 1


def test_parent_rejects_child_pass_when_independent_world_differs(tmp_path, monkeypatch):
    setup = finish_fixture.__wrapped__(tmp_path / "parent", monkeypatch)
    batch = setup[0]
    episode = worker_done(setup)
    adapter, spec, initial, turns = effect_case(tmp_path / "world")
    assert (
        effects(spec, initial, adapter.world.snapshot(), adapter.world.ledger(), turns)["status"]
        == "PASS"
    )
    adapter.world.publish(event_id="external-change", current={"authorized": False})
    original_audit = batch._audit

    def independent_world_audit(*args):
        header = original_audit(*args)
        actual = effects(spec, initial, adapter.world.snapshot(), adapter.world.ledger(), turns)
        return {**header, "status": actual["status"], "checks": actual["checks"]}

    monkeypatch.setattr(batch, "_audit", independent_world_audit)
    with pytest.raises(ProviderStop, match="FULL_ACCEPTANCE_AUDIT_NOT_PASS"):
        batch.finish(episode)
    assert audit_row(batch, episode) is None
    assert next(r for r in batch.snapshot()["episodes"] if r["id"] == episode)["status"] == "FAIL"


def test_late_usage_charged_without_reviving_stopped_execution(tmp_path, monkeypatch):
    batch, clock, *_ = claimed(core_fixture.__wrapped__(tmp_path, monkeypatch))
    dispatch(batch)
    batch.stop("ORIGINAL_STOP")
    clock[0] = batch.auth["expires_unix"] + 1
    batch.settle_event("P3-00", {"event": "RESPONSE_RECEIVED", "request_id": "req"})
    batch.settle_event("P3-00", known())
    with pytest.raises(ProviderStop):
        batch.reserve_request("P3-00", reservation("second"))
    state = batch.snapshot()
    assert state["stop"] == "ORIGINAL_STOP" and state["cost"]["known_raw_tokens"] == 13

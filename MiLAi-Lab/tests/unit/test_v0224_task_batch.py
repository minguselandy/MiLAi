"""Small D1/D2 SQLite/FSM and World tests; no model or real fixture."""

import copy
import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public

import v0224_task_batch as m
from v0218_world import World
from v0220_action_adapter import ActionAdapter
from v0220_session import SessionContract
from v0222_admission_read_scope import AdmissionReadScope


def plan(stage="D2"):
    spec = {
        "id": "task-one",
        "stage": stage,
        "scope": "owned",
        "profile": "NATURAL_NO_CARRY",
        "arm": "N0-exec",
        "max_generations": 16,
        "public_source": {"path": "/public.json", "sha256": "a" * 64},
        "initial_state_sha256": "a" * 64,
        "root": "public-root",
        "variant": "stable",
    }
    if stage == "D1":
        spec.update(profile="RECOVERY_ORACLE", arm="ORACLE", max_generations=5, intent={}, event={})
    return {"revision": m.REVISION, "http_identity": copy.deepcopy(m.IDENTITY), stage: [spec]}


@pytest.mark.parametrize("stage", ["D1", "D2"])
def test_bounded_stage_plan_and_no_private_actor_fields(stage):
    value = plan(stage)
    m.validate_plan(value, stage)
    value[stage][0]["checker_private_file"] = "/gold"
    with pytest.raises(m.ProviderStop, match="PRIVATE_CHECKER"):
        m.validate_plan(value, stage)


def test_natural_cannot_gain_oracle_intent_or_more_generations():
    for field, value in [("intent", {}), ("max_generations", 17), ("arm", "ORACLE")]:
        data = plan()
        data["D2"][0][field] = value
        with pytest.raises(m.ProviderStop):
            m.validate_plan(data, "D2")


def test_original_transaction_settlement_and_owner_methods_reused():
    assert m.Batch.transaction is m.corrected_transaction
    for name in (
        "_owned",
        "_append_mirrored",
        "dispatch_started",
        "settle_event",
        "admit",
        "http_admit",
    ):
        assert getattr(m.Batch, name) is getattr(m.OriginalCore, name)
    assert m.Batch.stop is m.JournalPrimitives.stop
    assert "retained" not in Path(m.__file__).read_text().split("from v0224_")[-1].split("\n")[0]


class PhysicalScope(AdmissionReadScope):
    @contextmanager
    def physical_reads(self):
        yield self


@pytest.fixture
def owned(tmp_path, monkeypatch):
    batch = object.__new__(m.Batch)
    batch.root = tmp_path
    batch.path = tmp_path / "batch.sqlite"
    batch.binding_sha = "a" * 64
    batch.stage = "D2"
    batch.plan = plan()
    batch.auth = {"expires_unix": 100000.0, "episode_wall_seconds": 3600, "cap": 16}
    pid = {"value": 10001}
    monkeypatch.setattr(m.os, "getpid", lambda: pid["value"])
    monkeypatch.setattr(m.time, "time", lambda: 1000.0)
    monkeypatch.setattr(batch, "_new_scope", lambda: PhysicalScope())
    monkeypatch.setattr(batch, "_authorize", lambda stage, scope: (batch.auth, batch.plan))
    batch.initialize()
    batch.launch_once("D2")
    pid["value"] = 10002
    batch.claim("task-one")
    (tmp_path / "episodes/task-one/provider").mkdir(parents=True)
    return batch, pid


def reserve():
    return {
        "event": "RESERVED",
        "request_id": "r1",
        "unix": 1000.0,
        "session": "task-one",
        "prompt_tokens": 10,
        "output_cap": 4096,
        "raw_upper_bound": 4106,
        "cumulative_raw_cap": None,
        "payload_sha256": "a" * 64,
    }


def complete_usage(batch, unknown=False, bad_usage=False):
    batch.reserve_request("task-one", reserve())
    batch.dispatch_started("task-one", "r1")
    batch.http_admit("task-one", inflight=True)
    batch.settle_event("task-one", {"event": "RESPONSE_RECEIVED", "request_id": "r1"})
    if unknown:
        batch.settle_event("task-one", {"event": "USAGE_UNKNOWN", "request_id": "r1"})
    else:
        batch.settle_event(
            "task-one",
            {
                "event": "USAGE_KNOWN",
                "request_id": "r1",
                "usage": {
                    "prompt_tokens": 11 if bad_usage else 10,
                    "completion_tokens": 1,
                    "total_tokens": 12 if bad_usage else 11,
                },
            },
        )


def test_actual_mirrored_fsm_and_execution_counts(owned):
    batch, _ = owned
    complete_usage(batch)
    assert batch.admit("task-one")["pid"] == 10002
    assert batch.snapshot()["cost"]["requests"] == 1
    with batch.transaction() as db:
        assert len(batch.events(db)) == 4
        assert batch._check_journal(db)["new_generation_allowed"]


@pytest.mark.parametrize("kind", ["unknown", "bound", "mirror"])
def test_current_unknown_bound_or_mirror_failure_stops_new_work(owned, kind):
    batch, _ = owned
    complete_usage(batch, unknown=kind == "unknown", bad_usage=kind == "bound")
    if kind == "mirror":
        batch._ledger("task-one").write_text("")
    with pytest.raises(m.ProviderStop):
        batch.admit("task-one")
    with batch.transaction() as db:
        assert db.execute("SELECT value FROM meta WHERE key='stop'").fetchone()
        assert db.execute("SELECT status FROM episodes").fetchone()[0] == "FAIL"


def test_foreign_worker_cannot_admit(owned):
    batch, pid = owned
    pid["value"] = 10003
    with pytest.raises(m.ProviderStop, match="OWNED"):
        batch.admit("task-one")


def test_duplicate_claim_or_launch_cannot_restart(owned):
    batch, pid = owned
    pid["value"] = 10001
    with pytest.raises(m.ProviderStop):
        batch.launch_once("D2")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_parent_finish_checks_world_and_known_usage_without_gold(owned, monkeypatch):
    batch, pid = owned
    complete_usage(batch)
    world = World.create(batch.root / "worlds/task-one.sqlite", "owned", public())
    ActionAdapter(world, SessionContract.from_public(world.snapshot()))
    directory = batch.root / "episodes/task-one"
    files = {
        str(directory / "final-world.json"): save(directory / "final-world.json", world.snapshot()),
        str(directory / "final-ledger.json"): save(directory / "final-ledger.json", world.ledger()),
    }
    save(
        directory / "worker-result.json",
        {
            "pid": 10002,
            "execution_status": "EXECUTION_COMPLETE",
            "unresolved_operations": [],
            "task_correct": False,
            "files": files,
        },
    )
    exit_path = batch.root / "exits/task-one.json"
    pin = save(exit_path, {"pid": 10002, "parent_pid": 10001, "returncode": 0, "timed_out": False})
    pid["value"] = 10001
    monkeypatch.setattr(m.os, "kill", lambda *args: (_ for _ in ()).throw(ProcessLookupError()))
    result = batch.finish("task-one", exit_path, pin)
    assert (
        result["status"] == "EXECUTION_COMPLETE" and result["task_correctness"] == "NOT_EVALUATED"
    )
    assert batch.snapshot()["episodes"][0]["status"] == "EXECUTION_COMPLETE"


def test_r04_scope_factory_is_original_and_no_process_cache():
    import inspect

    assert "BundleReadScope(**self._static_authority.scope_arguments())" in inspect.getsource(
        m.Batch._new_scope
    )


def test_deadline_expiry_is_not_execution_completion(owned, monkeypatch):
    batch, _ = owned
    monkeypatch.setattr(m.time, "time", lambda: 4600.0)
    with pytest.raises(m.ProviderStop, match="TASK_EPISODE_DEADLINE"):
        batch.admit("task-one")


def test_primary_is_preserved_when_stop_also_fails(owned, monkeypatch):
    batch, _ = owned
    primary = RuntimeError("original body")

    def broken_stop(reason):
        raise ValueError("secondary stop")

    monkeypatch.setattr(batch, "stop", broken_stop)
    with pytest.raises(RuntimeError) as caught:
        with batch._operation("D2"):
            raise primary
    assert caught.value is primary
    assert any("SECONDARY_STOP_FAILURE" in note for note in primary.__notes__)


def test_only_fixed_task_roots_and_d1_d2_stage(tmp_path):
    with pytest.raises(m.ProviderStop, match="EXACT_D1_D2_STAGE"):
        m.validate_plan(plan(), "P4")
    authority = object.__new__(m.StaticAuthority)
    with pytest.raises(m.ProviderStop, match="FIXED_FRESH_TASK_ROOT"):
        m.Batch(tmp_path / "taskv1-d2", "a" * 64, static_authority=authority)

"""Real unchanged Session initialization after a synthetic scoped P4 claim.

Authorization and stage readiness are explicit fixtures, not P3/P4 admission.
SQL, claim evidence, read scopes, Session, and isolated World are real. PID and
wall clock are simulated; no cold-process or complete stage claim is made.
"""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public

import v0222_presentation_batch_v2 as module
from v0218_world import World
from v0220_provider_hardened import ProviderStop
from v0220_session import Session


@pytest.fixture
def fresh_claim(tmp_path, monkeypatch):
    batch = object.__new__(module.Batch)
    batch.root, batch.path = tmp_path, tmp_path / "batch.sqlite"
    batch.binding_sha = "b" * 64
    batch.auth = {"issued_unix": 900.0, "expires_unix": 10000.0}
    batch.plan = {
        stage: [{"id": f"{stage}-{i:02}", "stage": stage} for i in range(count)]
        for stage, count in (("P3", 16), ("P4", 24))
    }
    anchor = tmp_path / "synthetic-anchor.json"
    anchor.write_bytes(b'{"synthetic_static_authorization":true}')
    anchor_sha = hashlib.sha256(anchor.read_bytes()).hexdigest()
    pid = [101]

    def authorize(stage, scope):
        assert stage in {"PREP", "P3", "P4"}
        scope.read_json(anchor, anchor_sha)
        return copy.deepcopy(batch.auth), copy.deepcopy(batch.plan)

    monkeypatch.setattr(batch, "_authorize", authorize)
    # This test isolates claim -> Session layout; it does not bypass any gate
    # in production or claim that a real P3 gate has been established.
    monkeypatch.setattr(batch, "_ready", lambda db, stage, scope: None)
    monkeypatch.setattr(module.time, "time", lambda: 1000.0)
    monkeypatch.setattr(module.os, "getpid", lambda: pid[0])
    batch.initialize()
    batch.launch_once("P4")
    pid[0] = 201
    assert not (tmp_path / "episodes" / "P4-00").exists()
    batch.claim("P4-00")
    return batch


def make_session(batch):
    episode = "P4-00"
    world = World.create(batch.root / "worlds" / (episode + ".sqlite"), "synthetic", public())
    return Session(
        world,
        batch.root / "episodes" / episode,
        episode_id=episode,
        profile="INTENT_ORACLE",
        arm="ORACLE",
        intent={"instruction": "Synthetic initialization only; no inference or write."},
        validate_binding=lambda: batch.admit(episode),
    )


def test_claim_leaves_session_directory_fresh(fresh_claim):
    batch = fresh_claim
    was_fresh = not (batch.root / "episodes" / "P4-00").exists()
    marker = batch.root / "claims" / "P4-00.json"
    host = make_session(batch)
    assert was_fresh
    before = marker.read_bytes()
    batch.admit("P4-00")
    assert marker.read_bytes() == before
    assert host.directory.is_dir()
    assert (host.directory / "session-binding.json").is_file()
    assert host.world.snapshot()["version"] == 0
    assert host.world.ledger() == []
    assert len(host.observations) == 6
    assert batch.snapshot()["cost"]["requests"] == 0
    row = next(r for r in batch.snapshot()["episodes"] if r["id"] == "P4-00")
    assert row["status"] == "RUNNING"
    with batch.transaction() as db:
        claim = dict(db.execute("SELECT * FROM claims").fetchone())
    assert json.loads(before) == {**claim, "binding_sha256": batch.binding_sha}


@pytest.mark.parametrize("mutation", ["missing", "tampered"])
def test_external_claim_rechecked_before_session_initialization(fresh_claim, mutation):
    batch = fresh_claim
    marker = batch.root / "claims" / "P4-00.json"
    if mutation == "missing":
        marker.rename(marker.with_suffix(".retained"))
    else:
        marker.write_text('{"tampered":true}')
    with pytest.raises((FileNotFoundError, ProviderStop)):
        make_session(batch)
    assert not (batch.root / "episodes" / "P4-00").exists()
    assert batch.snapshot()["stop"] is not None
    assert batch.snapshot()["cost"]["requests"] == 0


def test_preexisting_episode_evidence_still_rejected_and_retained(fresh_claim):
    batch = fresh_claim
    directory = batch.root / "episodes" / "P4-00"
    directory.mkdir(parents=True, exist_ok=True)
    retained = directory / "claim.json"
    retained.write_bytes(b'{"historical_evidence":"must not delete or migrate"}')
    before = retained.read_bytes()
    external = batch.root / "claims" / "P4-00.json"
    external_before = external.read_bytes()
    with pytest.raises(FileExistsError):
        make_session(batch)
    assert retained.read_bytes() == before
    assert external.read_bytes() == external_before
    assert not (directory / "session-binding.json").exists()


@pytest.mark.parametrize("episode", ["../P4-00", "/absolute/P4-00", "P4-00/child", "", 1])
def test_claim_marker_path_rejects_noncanonical_ids(fresh_claim, episode):
    with pytest.raises(ProviderStop, match="CANONICAL_EPISODE_ID_REQUIRED"):
        fresh_claim.claim_marker_path(episode)


def test_claim_marker_path_requires_frozen_episode(fresh_claim):
    with pytest.raises(ProviderStop, match="EPISODE_OUTSIDE_FROZEN_PLAN"):
        fresh_claim.claim_marker_path("not-in-plan")


def test_claim_marker_path_is_separate_from_session(fresh_claim):
    assert fresh_claim.claim_marker_path("P4-00") == fresh_claim.root / "claims" / "P4-00.json"

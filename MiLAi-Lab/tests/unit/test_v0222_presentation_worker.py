"""Offline worker integration: real original Session/SQLite, Mock HTTP only."""

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0222_presentation_provider import (
    FINISH,
    READBACK,
    FixtureBatch,
    environment,
    mocked,
)

import v0222_presentation_transport as transport_module
import v0222_presentation_worker as worker
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop, usage_state
from v0222_presentation_provider import FullProvider
from v0222_presentation_references import prepare_p3, prepare_p4


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("MOCK_HTTP_ONLY")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(
        transport_module, "historical_usage_presentation", lambda _: {"sources": []}
    )


def setup(tmp_path, monkeypatch, stage="P3", *, writes=2, variant="full", outputs=None):
    batch = FixtureBatch(tmp_path / "batch", stage, writes=writes, variant=variant)
    directory = batch.root / "references"
    if stage == "P3":
        batch.refs = prepare_p3(directory, batch.value, environment(), lambda: None)
        wanted = [batch.value["expected"]]
    else:
        batch.refs, prepared = prepare_p4(directory, batch.value, environment(), lambda: None)
        batch.value = prepared["spec"]
        wanted = [*batch.value["actions"], READBACK, FINISH]
        cases = tmp_path / "cases"
        save(cases / batch.value["root"] / "public-initial.json", environment())
        monkeypatch.setattr(worker, "CASES", cases)
    batch.claim = lambda episode: batch.admit(episode)
    monkeypatch.setattr(worker, "Batch", lambda *_: batch)
    calls = []

    def provider(root, **kwargs):
        return FullProvider(
            root, **kwargs, transport=mocked(wanted if outputs is None else outputs, calls)
        )

    monkeypatch.setattr(worker, "FullProvider", provider)
    return batch, calls


@pytest.mark.parametrize("variant", ["full", "finish"])
def test_p3_validate_only_never_constructs_world(tmp_path, monkeypatch, variant):
    batch, calls = setup(tmp_path, monkeypatch, variant=variant)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("P3_NO_WORLD_OR_SESSION")

    monkeypatch.setattr(worker.World, "create", forbidden)
    monkeypatch.setattr(worker, "Session", forbidden)
    result = worker.run(batch.root, "TEST_ONLY", batch.episode)
    assert result["status"] == "VALIDATE_ONLY_PASS" and batch.stopped is None
    assert result["business_dispatches"] == result["notebook_writes"] == 0
    assert not (batch.root / "worlds").exists()
    assert read(batch.root / "episodes" / batch.episode / "worker-result.json") == result
    assert usage_state(batch.events)["requests"] == 1 and len(calls) == 4


@pytest.mark.parametrize("writes", [1, 2])
def test_p4_original_session_finishes_only_local_exact_chain(tmp_path, monkeypatch, writes):
    batch, _ = setup(tmp_path, monkeypatch, "P4", writes=writes)
    result = worker.run(batch.root, "TEST_ONLY", batch.episode)
    directory = batch.root / "episodes" / batch.episode
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT" and batch.stopped is None
    assert result["completed_turns"] == writes + 2 and result["unresolved_operations"] == []
    assert len(read(directory / "final-ledger.json")) == writes
    assert read(directory / "initial-world.json")["records"] == {}
    assert usage_state(batch.events)["requests"] == writes + 2


@pytest.mark.parametrize("failure", ["claim", "provider", "verify", "close", "worker_save"])
def test_worker_errors_lock_before_failure_escapes(tmp_path, monkeypatch, failure):
    batch, calls = setup(tmp_path, monkeypatch)

    def fail(*_args, **_kwargs):
        raise OSError("TEST_FAILURE")

    if failure == "claim":
        monkeypatch.setattr(batch, "claim", fail)
    elif failure == "provider":
        monkeypatch.setattr(worker, "FullProvider", fail)
    elif failure in {"verify", "close"}:
        monkeypatch.setattr(FullProvider, failure, fail)
    else:

        def save_failure(path, value):
            if path.name == "worker-result.json":
                raise OSError("TEST_FAILURE")
            save(path, value)

        monkeypatch.setattr(worker, "save", save_failure)
    with pytest.raises(OSError):
        worker.run(batch.root, "TEST_ONLY", batch.episode)
    assert batch.stopped == "OSError"
    assert not (batch.root / "episodes" / batch.episode / "worker-result.json").exists()
    if failure in {"claim", "provider", "verify"}:
        assert not calls


@pytest.mark.parametrize("failure", ["world", "session", "initial_save", "final_save", "rejected"])
def test_p4_constructor_session_and_evidence_failures_permanently_stop(
    tmp_path, monkeypatch, failure
):
    batch, _ = setup(
        tmp_path, monkeypatch, "P4", outputs=[FINISH] if failure == "rejected" else None
    )

    def fail(*_args, **_kwargs):
        raise OSError("TEST_FAILURE")

    if failure == "world":
        monkeypatch.setattr(worker.World, "create", fail)
    elif failure == "session":
        monkeypatch.setattr(worker, "Session", fail)
    elif failure.endswith("save"):

        def save_failure(path, value):
            if path.name == (
                "initial-world.json" if failure == "initial_save" else "final-world.json"
            ):
                raise OSError("TEST_FAILURE")
            save(path, value)

        monkeypatch.setattr(worker, "save", save_failure)
    with pytest.raises((OSError, ProviderStop)):
        worker.run(batch.root, "TEST_ONLY", batch.episode)
    assert batch.stopped
    assert not (batch.root / "episodes" / batch.episode / "worker-result.json").exists()


def test_failed_batch_construction_can_only_lock_exact_bound_existing_root(tmp_path, monkeypatch):
    root = tmp_path / "authorized"
    save(root / "execution-binding.json", {"TEST_ONLY": True})
    binding = sha(root / "execution-binding.json")
    stopped = []

    class FailedBatch:
        def __init__(self, *_):
            raise ProviderStop("FROZEN_SOURCE_DRIFT")

        def stop(self, reason):
            stopped.append((self.path, self.binding_sha, reason))

    monkeypatch.setattr(worker, "ROOT", root)
    monkeypatch.setattr(worker, "Batch", FailedBatch)
    with pytest.raises(ProviderStop, match="FROZEN_SOURCE_DRIFT"):
        worker.run(root, binding, "p3-01")
    assert stopped == [(root / "batch.sqlite", binding, "FROZEN_SOURCE_DRIFT")]
    worker.stop_batch(tmp_path / "other", binding, None, OSError())
    worker.stop_batch(root, "wrong_binding", None, OSError())
    assert len(stopped) == 1

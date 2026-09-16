"""New worker/HTTP/Provider and original Session/audit, synthetic coordinator.

No actual HTTP, model, device or cold worker process is used by these tests.
Core claim/SQL gates and process lifetime have separate tests; this fixture is
not a full frozen admission or an actual 16+24 execution matrix.
"""

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0222_presentation_provider import FINISH, READBACK, mocked
from test_v0222_presentation_provider_v2 import adapted_fixture

import v0222_presentation_worker_v2 as worker
from v0220_evidence import read, save
from v0220_provider_hardened import ProviderStop, usage_state
from v0222_presentation_audit import audit_episode
from v0222_presentation_provider_v2 import FullProvider


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("NEW_WORKER_TEST_MUST_NOT_USE_NETWORK")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def setup(tmp_path, monkeypatch, stage="P3", *, variant="full", writes=1, outputs=None):
    batch = adapted_fixture(tmp_path, monkeypatch, stage, variant=variant, writes=writes)
    calls = []
    batch.claim_marker_path = lambda episode: batch.root / "claims" / (episode + ".json")

    def claim(episode):
        batch.admit(episode)
        save(batch.claim_marker_path(episode), {"synthetic_claim": True})

    batch.claim = claim
    monkeypatch.setattr(worker, "Batch", lambda *_: batch)
    monkeypatch.setattr(worker, "CASES", tmp_path / "cases")
    wanted = (
        [batch.value["expected"]] if stage == "P3" else [*batch.value["actions"], READBACK, FINISH]
    )

    def provider(root, **kwargs):
        return FullProvider(
            root, **kwargs, transport=mocked(wanted if outputs is None else outputs, calls)
        )

    monkeypatch.setattr(worker, "FullProvider", provider)
    return batch, calls


@pytest.mark.parametrize(
    "stage,variant,writes",
    [("P3", "full", 1), ("P3", "finish", 1), ("P4", "full", 1), ("P4", "full", 2)],
)
def test_new_worker_original_raw_audit_and_session(tmp_path, monkeypatch, stage, variant, writes):
    batch, calls = setup(tmp_path, monkeypatch, stage, variant=variant, writes=writes)
    if stage == "P3":

        def forbidden(*_args, **_kwargs):
            raise AssertionError("P3_CANNOT_CREATE_SESSION_OR_WORLD")

        monkeypatch.setattr(worker, "Session", forbidden)
        monkeypatch.setattr(worker.World, "create", forbidden)
    result = worker.run(batch.root, "TEST_ONLY", batch.episode)
    assert result["status"] == (
        "VALIDATE_ONLY_PASS" if stage == "P3" else "SESSION_FINISHED_NOT_TASK_VERDICT"
    )
    assert read(batch.root / "episodes" / batch.episode / "worker-result.json") == result
    assert batch.claim_marker_path(batch.episode).is_file()
    audit = audit_episode(batch, batch.episode)
    assert audit["status"] == "PASS", audit["checks"]
    count = 1 if stage == "P3" else writes + 2
    assert audit["cost"]["requests"] == count
    assert len([path for path, _ in calls if path == "/v1/chat/completions"]) == count
    if stage == "P3":
        assert result["business_dispatches"] == result["notebook_writes"] == 0
        assert not (batch.root / "worlds").exists()
    else:
        directory = batch.root / "episodes" / batch.episode
        assert read(directory / "initial-world.json")["version"] == 0
        assert read(directory / "final-world.json")["version"] == writes
        assert len(read(directory / "final-ledger.json")) == writes
        assert result["unresolved_operations"] == []


@pytest.mark.parametrize("failure", ["claim", "provider", "verify", "close", "worker_save"])
def test_worker_failure_stops_before_escaping_and_never_reports_success(
    tmp_path, monkeypatch, failure
):
    batch, calls = setup(tmp_path, monkeypatch)

    def fail(*_args, **_kwargs):
        raise OSError("PRIMARY_WORKER_FAILURE")

    if failure == "claim":
        monkeypatch.setattr(batch, "claim", fail)
    elif failure == "provider":
        monkeypatch.setattr(worker, "FullProvider", fail)
    elif failure in {"verify", "close"}:
        monkeypatch.setattr(FullProvider, failure, fail)
    else:

        def fail_save(path, value):
            if path.name == "worker-result.json":
                fail()
            save(path, value)

        monkeypatch.setattr(worker, "save", fail_save)
    with pytest.raises(OSError, match="PRIMARY_WORKER_FAILURE"):
        worker.run(batch.root, "TEST_ONLY", batch.episode)
    assert batch.stopped == "OSError"
    assert not (batch.root / "episodes" / batch.episode / "worker-result.json").exists()
    if failure in {"claim", "provider", "verify"}:
        assert not calls


def test_original_error_survives_stop_and_close_failures(tmp_path, monkeypatch):
    batch, _ = setup(tmp_path, monkeypatch)
    original = ProviderStop("PRIMARY_VERIFY_FAILURE")

    class FailingProvider:
        def verify(self):
            raise original

        def close(self):
            raise OSError("secondary close")

    def failing_stop(_reason):
        raise OSError("secondary stop")

    monkeypatch.setattr(worker, "FullProvider", lambda *_args, **_kwargs: FailingProvider())
    monkeypatch.setattr(batch, "stop", failing_stop)
    with pytest.raises(ProviderStop) as caught:
        worker.run(batch.root, "TEST_ONLY", batch.episode)
    assert caught.value is original
    assert "SECONDARY_STOP_FAILURE: OSError" in original.__notes__
    assert "SECONDARY_PROVIDER_CLOSE_FAILURE: OSError" in original.__notes__


def test_p4_early_finish_is_not_promoted_to_worker_success(tmp_path, monkeypatch):
    batch, calls = setup(tmp_path, monkeypatch, "P4", outputs=[FINISH])
    with pytest.raises(ProviderStop, match="PRESENTATION_SESSION_NOT_CLEANLY_FINISHED"):
        worker.run(batch.root, "TEST_ONLY", batch.episode)
    assert batch.stopped == "FINISH_BEFORE_INTENT_AND_PUBLIC_READBACK"
    assert usage_state(batch.events)["known_raw_tokens"] == 120
    assert len([path for path, _ in calls if path == "/v1/chat/completions"]) == 1
    assert not (batch.root / "episodes" / batch.episode / "worker-result.json").exists()


def test_fallback_stop_does_not_touch_other_roots(tmp_path, monkeypatch):
    def forbidden(*_args):
        raise AssertionError("FOREIGN_ROOT_MUST_NOT_BE_READ")

    monkeypatch.setattr(worker, "sha", forbidden)
    failure = ProviderStop("ORIGINAL")
    worker.stop_batch(tmp_path / "foreign", "binding", None, failure)
    assert not hasattr(failure, "__notes__")

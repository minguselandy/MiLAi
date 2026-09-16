"""Plan read-only checks and synthetic preparation-control tests; no HTTP.

These do not prove real new-instance admission or a full cold execution matrix.
The complete original materializer remains unchanged; full integration is separate.
"""

import copy
import socket
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import prepare_v0222_presentation_v2 as module
from v0218_world import digest
from v0220_evidence import read
from v0220_provider_hardened import ProviderStop
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_audit import initial_for


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CPU_OFFLINE_ONLY")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def test_exact_pinned_previous_matrix_new_ids_scopes_and_derived_hashes():
    old = read(module.PRESENTATION_ROOT / "manifest.json")["contract"]
    with AdmissionReadScope() as scope:
        plan = module.episode_specs(scope)
    assert scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
    assert len(plan["P3"]) == 16 and len(plan["P4"]) == 24
    ids, scopes = set(), set()
    for stage in ("P3", "P4"):
        for before, after in zip(old[stage], plan[stage], strict=True):
            ignored = {"id", "scope"} | ({"initial_state_sha256"} if stage == "P4" else set())
            assert {k: v for k, v in before.items() if k not in ignored} == {
                k: v for k, v in after.items() if k not in ignored
            }
            assert before["id"] != after["id"] and before["scope"] != after["scope"]
            if stage == "P4":
                assert digest(initial_for(after)) == after["initial_state_sha256"]
                assert before["initial_state_sha256"] != after["initial_state_sha256"]
            ids.add(after["id"])
            scopes.add(after["scope"])
    assert len(ids) == len(scopes) == 40


def synthetic_batch(tmp_path, *, stop_fails=False):
    events = []

    @contextmanager
    def operation(stage):
        events.append(("open", stage))
        try:
            yield (None, None, None)
        finally:
            events.append(("closed", stage))

    def stop(reason):
        events.append(("stop", reason))
        if stop_fails:
            raise OSError("SYNTHETIC_STOP_FAILURE")

    batch = SimpleNamespace(
        root=tmp_path,
        plan={"P3": [{"id": "p3"}], "P4": []},
        _operation=operation,
        stop=stop,
        freeze_artifact=lambda *args: events.append(("freeze", args)),
        spec=lambda episode: {"id": episode},
    )
    return batch, events


def test_facade_closes_each_guard_before_materializer_work(tmp_path, monkeypatch):
    batch, events = synthetic_batch(tmp_path)
    original = copy.deepcopy(batch.plan)

    def materialize(view):
        for _ in range(2):
            view.authorize("PREP")
            assert events[-1] == ("closed", "PREP")
        assert view.root == batch.root and view.spec("p3") == {"id": "p3"}
        view.plan["P3"].clear()
        view.freeze_artifact("P_full_preparation", tmp_path / "prepared.json", "PASS")
        return {"status": "SYNTHETIC_MATERIALIZER_RESULT"}

    monkeypatch.setattr(module, "original_materialize", materialize)
    result = module.materialize_references(batch)
    assert result["status"] == "SYNTHETIC_MATERIALIZER_RESULT"
    assert batch.plan == original
    assert len([e for e in events if e[0] == "open"]) == 2
    assert not [e for e in events if e[0] == "stop"]


@pytest.mark.parametrize("stage", ["P3", "P4", "UNKNOWN"])
def test_preparation_facade_never_admits_a_model_stage(tmp_path, stage):
    batch, events = synthetic_batch(tmp_path)
    with pytest.raises(ProviderStop, match="CANNOT_AUTHORIZE_MODEL_STAGE"):
        module._PreparationView(batch).authorize(stage)
    assert not events


@pytest.mark.parametrize("stop_fails", [False, True])
@pytest.mark.parametrize("before_old_try", [False, True])
def test_primary_materialization_failure_survives_secondary_stop(
    tmp_path, monkeypatch, stop_fails, before_old_try
):
    batch, events = synthetic_batch(tmp_path, stop_fails=stop_fails)
    primary = ValueError("SYNTHETIC_PRIMARY")

    def materialize(view):
        if not before_old_try:
            view.stop("ValueError")
        raise primary

    monkeypatch.setattr(module, "original_materialize", materialize)
    with pytest.raises(ValueError, match="SYNTHETIC_PRIMARY") as caught:
        module.materialize_references(batch)
    assert caught.value is primary and events[-1] == ("stop", "ValueError")
    notes = getattr(primary, "__notes__", [])
    assert bool(notes) is stop_fails
    if stop_fails:
        assert all("SECONDARY_PREPARATION_STOP_FAILURE: OSError" == note for note in notes)


def test_duplicate_reference_directory_is_preserved_and_stopped(tmp_path):
    batch, events = synthetic_batch(tmp_path)
    directory = tmp_path / "full-reference"
    directory.mkdir()
    with pytest.raises(FileExistsError):
        module.materialize_references(batch)
    assert directory.exists() and events[-1] == ("stop", "FileExistsError")
    assert not list(directory.iterdir())


def test_batch_constructor_failure_is_preserved(tmp_path, monkeypatch):
    failure = ProviderStop("SYNTHETIC_CONSTRUCTOR_FAILURE")
    stopped = []

    def constructor(*args):
        raise failure

    monkeypatch.setattr(module, "Batch", constructor)
    monkeypatch.setattr(module, "stop_batch", lambda *args: stopped.append(args))
    with pytest.raises(ProviderStop) as caught:
        module.prepare(tmp_path, "synthetic")
    assert caught.value is failure
    assert stopped == [(tmp_path, "synthetic", None, failure)]

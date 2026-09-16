"""New transport/Provider plus original Session/raw auditor with fixture authority.

The fixture mirrors the new event API explicitly, but is not a scoped Batch or
an authorization gate. No network is allowed. Real-core transport accounting is
tested separately; these tests preserve the complete acceptance/effect path.
"""

import builtins
import copy
import os
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0222_presentation_audit import prepared
from test_v0222_presentation_provider import FINISH, READBACK, environment, mocked

from v02_local_provider import append_event, read_events
from v0218_world import World
from v0220_evidence import read, save
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_session import Session
from v0222_presentation_audit import audit_episode
from v0222_presentation_provider import FullProvider as OriginalAcceptance
from v0222_presentation_provider_v2 import FullProvider


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("NEW_PROVIDER_TEST_MUST_NOT_USE_NETWORK")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def adapted_fixture(tmp_path, monkeypatch, stage, *, variant="full", writes=1):
    batch, _ = prepared(tmp_path, monkeypatch, stage, variant=variant, writes=writes)
    ledger = batch.root / "episodes" / batch.episode / "provider/provider-ledger-v2.jsonl"

    def mirror(episode, event):
        batch.record(episode, copy.deepcopy(event))
        append_event(ledger, event)

    batch.reserve_request = mirror
    batch.dispatch_started = lambda episode, key: mirror(
        episode, {"event": "DISPATCH_STARTED", "request_id": key}
    )
    batch.settle_event = mirror
    return batch


def execute(batch, outputs, calls):
    directory = batch.root / "episodes" / batch.episode
    world = host = None
    if batch.value["stage"] == "P4":
        world = World.create(
            batch.root / "worlds" / (batch.episode + ".sqlite"), batch.value["scope"], environment()
        )
        host = Session(
            world,
            directory,
            episode_id=batch.episode,
            profile="INTENT_ORACLE",
            arm="ORACLE",
            intent=batch.value["intent"],
            validate_binding=lambda: batch.admit(batch.episode),
        )
        save(directory / "initial-world.json", world.snapshot())
    provider = FullProvider(
        directory / "provider",
        batch=batch,
        episode=batch.episode,
        world=world,
        transport=mocked(outputs, calls),
    )
    if host is None:
        try:
            provider.verify()
            raw = provider.generate(batch.episode, read(Path(batch.refs[0]["canonical"])))
        finally:
            provider.close()
        result = {"status": "VALIDATE_ONLY_PASS", "raw": raw, "business_dispatches": 0}
    else:
        result = host.run(provider, deadline=provider.provider.deadline)
        save(directory / "final-world.json", world.snapshot())
        save(directory / "final-ledger.json", world.ledger())
        result["unresolved_operations"] = host.adapter.journal.unresolved()
    save(directory / "worker-result.json", {**result, "pid": os.getpid()})
    return provider, world, result


def test_original_acceptance_methods_are_reused_without_replacement():
    for name in (
        "_wire_preflight",
        "verify",
        "_check_world",
        "_admit_request",
        "_operation_reply",
        "_verify_new_reply",
        "generate",
        "close",
    ):
        assert getattr(FullProvider, name) is getattr(OriginalAcceptance, name)


@pytest.mark.parametrize(
    "stage,variant,writes",
    [("P3", "full", 1), ("P3", "finish", 1), ("P4", "full", 1), ("P4", "full", 2)],
)
def test_new_transport_and_original_full_audit_session_effects(
    tmp_path, monkeypatch, stage, variant, writes
):
    batch = adapted_fixture(tmp_path, monkeypatch, stage, variant=variant, writes=writes)
    outputs = (
        [batch.value["expected"]] if stage == "P3" else [*batch.value["actions"], READBACK, FINISH]
    )
    calls = []
    provider, world, result = execute(batch, outputs, calls)
    audit = audit_episode(batch, batch.episode)
    assert audit["status"] == "PASS", audit["checks"]
    count = 1 if stage == "P3" else writes + 2
    assert audit["cost"]["requests"] == count
    assert len(batch.events) == 4 * count
    assert read_events(provider.provider.ledger) == batch.events
    assert usage_state(batch.events)["known_raw_tokens"] == 120 * count
    assert len([p for p, _ in calls if p == "/v1/chat/completions"]) == count
    assert provider.closed and not batch.stopped
    if stage == "P4":
        assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
        assert world.snapshot()["version"] == writes
        assert len(world.ledger()) == writes
    else:
        assert world is None and result["business_dispatches"] == 0


@pytest.mark.parametrize(
    "change", ["wrong_target", "invalid_full_schema", "float_cas", "early_finish"]
)
def test_new_transport_never_releases_invalid_or_wrong_intent(tmp_path, monkeypatch, change):
    stage = "P4" if change == "early_finish" else "P3"
    batch = adapted_fixture(tmp_path, monkeypatch, stage)
    output = copy.deepcopy(batch.value["expected"])
    if change == "wrong_target":
        output["arguments"]["object_id"] = "right"
    elif change == "invalid_full_schema":
        output["arguments"]["data"]["text"] = "   "
    elif change == "float_cas":
        output["arguments"]["expected_version"] = 0.0
    else:
        output = FINISH
    calls = []
    if stage == "P4":
        _, _, result = execute(batch, [output], calls)
        assert result["status"] == "FAIL_CLOSED"
    else:
        with pytest.raises((ProviderStop, ValueError)):
            execute(batch, [output], calls)
    assert batch.stopped
    assert len([p for p, _ in calls if p == "/v1/chat/completions"]) == 1
    assert usage_state(batch.events)["known_raw_tokens"] == 120
    assert not list((batch.root / "episodes").rglob("contract-*-validation.json"))
    if stage == "P4":
        world = World(batch.root / "worlds" / (batch.episode + ".sqlite"), batch.value["scope"])
        assert world.snapshot()["version"] == 0
        assert world.ledger() == []


def test_secondary_stop_failure_does_not_replace_original_error():
    class FailingStop:
        def stop(self, reason):
            raise OSError("synthetic stop evidence failure")

    provider = object.__new__(FullProvider)
    provider.batch = FailingStop()
    original = ProviderStop("PRIMARY_ACCEPTANCE_FAILURE")
    provider._stop(original)
    assert provider.stopped
    assert str(original) == "PRIMARY_ACCEPTANCE_FAILURE"
    assert original.__notes__ == ["SECONDARY_STOP_FAILURE: OSError"]


def test_transport_import_failure_is_stopped_at_constructor(tmp_path, monkeypatch):
    original_import, stops = builtins.__import__, []

    def unavailable(name, *args, **kwargs):
        if name == "v0222_presentation_transport_v2":
            raise ImportError("synthetic transport import failure")
        return original_import(name, *args, **kwargs)

    class Batch:
        def stop(self, reason):
            stops.append(reason)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(ImportError, match="synthetic transport"):
        FullProvider(tmp_path / "provider", batch=Batch(), episode="synthetic")
    assert stops == ["ImportError"]
    assert not (tmp_path / "provider").exists()

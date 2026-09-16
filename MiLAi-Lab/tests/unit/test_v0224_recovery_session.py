"""Genuine World publication/CAS recovery, with no model efficacy claim."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put
from test_v0220_session import FakeProvider, finish

from v0218_world import World
from v0224_recovery_session import RecoverySession


@pytest.mark.parametrize("changed", [False, True])
def test_publication_causes_real_rejection_and_public_recovery(tmp_path, changed):
    world = World.create(tmp_path / "world.sqlite", "owned", public())
    host = RecoverySession(
        world,
        tmp_path / "session",
        episode_id="recovery",
        profile="RECOVERY_ORACLE",
        arm="ORACLE",
        intent={"instruction": "Write only while the current public premise permits it."},
        event={"event_id": "fixed-publication", "current": {"authorized": not changed}},
        validate_binding=lambda: None,
    )
    actions = [put(), {"action": "read", "arguments": {"resource": "current"}}]
    if not changed:
        actions.extend([put(version=1), {"action": "read", "arguments": {"resource": "records"}}])
    actions.append(finish())
    provider = FakeProvider(actions)
    result = host.run(provider, deadline=time.monotonic() + 30)
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
    assert result["expected_error_exercised"] and result["expected_rejection_turn"] == 1
    assert result["note_writes"] == 0
    first = host.rows[0]["response"]
    assert first["code"] == "VERSION_CONFLICT"
    assert first["committed"] is False and first["business_effect"] is False
    publication = json.loads((host.directory / "actual-recovery-publication.json").read_bytes())
    assert publication["before"]["version"] == 0 and publication["after"]["version"] == 1
    assert publication["after"]["records"] == {}
    assert host.rows[1]["response"]["content"] == {"authorized": not changed}
    assert host.rows[1]["response"]["version"] == 1
    # The rejected attempt must not silently disclose the new premise/version.
    second_request = json.loads(provider.requests[1]["messages"][-1]["content"])
    assert second_request["last_completed_public_observation"]["version"] == 0
    assert len(provider.requests) == (3 if changed else 5)
    assert len(world.ledger()) == (1 if changed else 2)
    if changed:
        assert world.snapshot()["records"] == {}
    else:
        assert host.rows[3]["response"]["content"] == world.snapshot()["records"]
        assert world.snapshot()["version"] == 2

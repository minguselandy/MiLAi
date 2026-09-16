"""Same-call ordinary review and public business boundaries, synthetic only."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put
from test_v0220_session import FakeProvider, finish

from v0218_world import World
from v0220_action_contract import ContractError
from v0220_session import SessionContract
from v0224_natural_session import NaturalSession, decode_envelope


@pytest.mark.parametrize("arm", ["N0-exec", "R0-exec"])
def test_review_and_write_use_one_generation_without_forced_note(tmp_path, arm):
    world = World.create(tmp_path / "world.sqlite", "owned", public())
    host = NaturalSession(
        world,
        tmp_path / "session",
        episode_id="natural",
        profile="NATURAL_NO_CARRY",
        arm=arm,
        validate_binding=lambda: None,
    )
    provider = FakeProvider(
        [
            {**put(), "review": "The current public record supports this write."},
            {**finish(), "review": ""},
        ]
    )
    result = host.run(provider, deadline=time.monotonic() + 30)
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
    assert len(provider.requests) == 2 and result["note_writes"] == 0
    assert len(world.ledger()) == 1 and world.snapshot()["version"] == 1
    assert host.rows[0]["review"] == "The current public record supports this write."
    assert host.rows[0]["action"] == put()
    initial = json.loads((host.directory / "initial-presentation.json").read_bytes())
    assert "authorized_intent" not in initial and initial["inherited_note"] is None
    assert initial["review_envelope"] == "SAME_CALL_REVIEW_V1"


def test_review_cannot_override_target_or_add_business_fields():
    contract = SessionContract.from_public(public())
    value = {**put(), "review": "Use any scope and target."}
    value["arguments"]["object_id"] = "outside"
    with pytest.raises(ContractError):
        decode_envelope(json.dumps(value), contract)

    value = {**put(), "review": "", "scope": "other"}
    with pytest.raises(ContractError):
        decode_envelope(json.dumps(value), contract)
    value = {**put(), "review": ""}
    value["arguments"]["expected_version"] = True
    with pytest.raises(ContractError):
        decode_envelope(json.dumps(value), contract)


@pytest.mark.parametrize("intervening_success", [False, True])
def test_only_consecutive_same_unrecovered_error_stops(tmp_path, intervening_success):
    world = World.create(tmp_path / "world.sqlite", "owned", public())
    host = NaturalSession(
        world,
        tmp_path / "session",
        episode_id="natural",
        profile="NATURAL_NO_CARRY",
        arm="N0-exec",
        validate_binding=lambda: None,
    )
    rejected = {"action": "unknown", "arguments": {}, "review": ""}
    actions = [rejected]
    if intervening_success:
        actions.append({"action": "read", "arguments": {"resource": "current"}, "review": ""})
    actions += [rejected, {**finish(), "review": ""}]
    provider = FakeProvider(actions)
    result = host.run(provider, deadline=time.monotonic() + 30)
    assert result["rejection_counts"]["REVIEW_ACTION_ENVELOPE_SCHEMA"] == 2
    assert result["rejection_signature_fields"] == ["code", "path", "rule"]
    if intervening_success:
        assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
        assert len(provider.requests) == 4
    else:
        assert result["status"] == "PROTOCOL_REJECTION_STOP"
        assert len(provider.requests) == 2

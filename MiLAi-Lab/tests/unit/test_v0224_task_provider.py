"""Real D11/Transport/Host plumbing with local HTTP-shaped responses only."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put
from test_v0220_session import finish

import v0224_live_http as wire
from v02_local_provider import append_event, read_events
from v0218_world import World
from v0220_provider_hardened import usage_state
from v0222_presentation_batch_v2 import IDENTITY
from v0222_scoped_cpu_mock import _scripted_transport
from v0224_natural_session import NaturalSession
from v0224_task_provider import TaskProvider


class SyntheticBatch:
    def __init__(self, root):
        self.root = root
        self.plan = {"http_identity": IDENTITY}
        self.auth = {"historical": {"sources": []}}
        self.rows, self.stopped = [], False

    def admit(self, episode):
        assert not self.stopped
        return {"stage": "D2", "cap": 16, "deadline": time.time() + 30}

    def http_admit(self, episode, **kwargs):
        return self.admit(episode)

    def event(self, episode, value):
        self.rows.append(value)
        usage_state(self.rows)
        append_event(self.root / "episodes" / episode / "provider/provider-ledger-v2.jsonl", value)

    def reserve_request(self, episode, value):
        self.event(episode, value)

    def dispatch_started(self, episode, request_id):
        self.event(episode, {"event": "DISPATCH_STARTED", "request_id": request_id})

    def settle_event(self, episode, value):
        self.event(episode, value)

    def stop(self, reason):
        self.stopped = True


@pytest.mark.parametrize("invalid_first", [False, True])
def test_same_call_review_through_d11_metering_and_original_host(
    tmp_path, monkeypatch, invalid_first
):
    batch = SyntheticBatch(tmp_path)
    action = put("right")  # Publicly legal choice; there is no expected-target gate.
    action["arguments"]["data"]["amount"] = 19.75
    actions = [
        (
            {**action, "review": "Brief ordinary review."}
            if not invalid_first
            else {"action": "unknown", "arguments": {}, "review": ""}
        ),
        {**finish(), "review": ""},
    ]
    transport = _scripted_transport(IDENTITY, tuple(json.dumps(v) for v in actions))
    monkeypatch.setattr(wire.httpx, "HTTPTransport", lambda **kwargs: transport)
    world = World.create(tmp_path / "world.sqlite", "owned", public())
    directory = tmp_path / "episodes/natural"
    host = NaturalSession(
        world,
        directory,
        episode_id="natural",
        profile="NATURAL_NO_CARRY",
        arm="R0-exec",
        validate_binding=lambda: batch.admit("natural"),
    )
    provider = TaskProvider(directory / "provider", batch=batch, episode="natural")
    result = host.run(provider, deadline=time.monotonic() + 30)
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
    assert not batch.stopped
    events = read_events(directory / "provider/provider-ledger-v2.jsonl")
    assert events == batch.rows and usage_state(events)["requests"] == 2
    assert usage_state(events)["new_generation_allowed"]
    if invalid_first:
        assert host.rows[0]["response"]["status"] == "ACTION_REJECTED"
        assert world.snapshot()["records"] == {}
    else:
        assert world.snapshot()["records"]["right"]["amount"] == 19.75
        assert host.rows[0]["review"] == "Brief ordinary review."

"""Offline Host protocol tests; fake transport never counts as presentation evidence."""

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0218_host as host
from prepare_v0218 import scheduling
from v02_local_provider import append_event
from v0218_world import World, digest


@pytest.mark.parametrize(
    "action,arguments",
    [
        (
            "put_record",
            {
                "object_id": "fixture",
                "expected_version": 0,
                "data": {"confirmed": True, "amount": 12.5, "reason": "not cancelled"},
            },
        ),
        ("save_note", {"note": '逐字保留\n"quoted"'}),
        (
            "request_clarification",
            {
                "object_id": "fixture",
                "expected_version": 2,
                "data": {"question": "Which revision is current?"},
            },
        ),
    ],
)
def test_generic_argument_codec_preserves_types_and_exact_text(action, arguments):
    raw = json.dumps({"action": action, "arguments_json": json.dumps(arguments)})
    assert host.decode_action(raw) == {"action": action, **arguments}


@pytest.mark.parametrize(
    "value",
    [
        {"action": "read"},
        {"action": "read", "arguments_json": {}},
        {"action": "read", "arguments_json": "[]"},
        {"action": "read", "arguments_json": '{"action":"finish"}'},
        {"action": "read", "arguments_json": '{"future_events":true}'},
        {"action": "unknown", "arguments_json": "{}"},
    ],
)
def test_argument_codec_rejects_malformed_or_undeclared_fields(value):
    with pytest.raises(ValueError):
        host.decode_action(json.dumps(value))


@pytest.mark.parametrize("arm", ["N0", "N1", "N2"])
@pytest.mark.parametrize("has_note", [True, False])
def test_visible_schema_error_feedback_and_next_dispatch_sources(
    tmp_path, monkeypatch, arm, has_note, invalid_json=None
):
    world = World.create(tmp_path / "world.sqlite", "scope", scheduling()["public"])
    captured = []
    actions = [
        {"action": "put_record", "object_id": "C03"},
        {"action": "read", "resource": "current"},
        {"action": "finish", "message": "unfinished"},
    ]

    class FakeProvider:
        def __init__(self, directory, **_kwargs):
            self.ledger = directory / "provider-ledger.jsonl"

        def verify(self):
            return {"test_double": True}

        def generate(self, _session, body):
            captured.append(body)
            key = str(len(captured))
            append_event(
                self.ledger,
                {
                    "event": "RESERVED",
                    "request_id": key,
                    "session": "offline",
                    "payload_sha256": digest(body),
                },
            )
            append_event(
                self.ledger,
                {
                    "event": "SETTLED",
                    "request_id": key,
                    "input_tokens": 1,
                    "output_tokens": 1,
                },
            )
            if len(captured) == 1 and invalid_json is not None:
                return invalid_json
            action = actions[len(captured) - 1]
            return json.dumps(
                {
                    "action": action["action"],
                    "arguments_json": json.dumps(
                        {k: v for k, v in action.items() if k != "action"}
                    ),
                }
            )

        def close(self):
            pass

    @contextmanager
    def fake_observer(*_args, **_kwargs):
        yield lambda *_: None

    note = {"content": "Old free note", "content_digest": "test-only-digest"}
    monkeypatch.setattr(host, "Provider", FakeProvider)
    monkeypatch.setattr(host, "observer", fake_observer)
    monkeypatch.setattr(host, "read_note", lambda *_: note)
    config = {
        "world": str(world.path),
        "world_scope": "scope",
        "memory_scope": "scope",
        "output": str(tmp_path / "episode"),
        "owned": str(tmp_path),
        "seconds": 30,
        "generation_cap": 3,
        "root": "offline",
        "episode_id": "offline",
        "arm": arm,
        "variant": "stable",
        "phase": "B",
        "note_commit": note if arm in ("N1", "N2") and has_note else None,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    result = host.run(config_path)
    assert result["status"] == "FINISHED"
    assert result["agent_note_writes"] == 0 and result["inherited_messages"] == 0
    initial = json.loads(captured[0]["messages"][1]["content"])
    assert initial["action_schema"] == host.SCHEMA
    assert initial["saved_working_note"] == (
        note["content"] if arm in ("N1", "N2") and has_note else None
    )
    for body in captured:
        assert body["messages"][0]["content"] == host.SYSTEM + (
            "\n" + host.REMINDER if arm == "N2" else ""
        )
    assert result["actions"][0]["tool_result"]["status"] == "ACTION_REJECTED"
    assert world.snapshot()["records"] == {}
    receipts = json.loads((tmp_path / "episode/dispatch-receipts.json").read_text())["requests"]
    assert not receipts[1]["source_receipts_in_context"]
    assert receipts[2]["source_receipts_in_context"][0]["resource"] == "current"
    assert captured[-1]["response_format"]["json_schema"]["schema"]["properties"]["action"][
        "enum"
    ] == ["finish"]

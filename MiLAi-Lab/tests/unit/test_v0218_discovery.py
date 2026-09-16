"""Candidate policy changes no world facts, free calls, common A or default behavior."""

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0218_host as common
import v0218_policy_host as policy
from prepare_v0218 import scheduling
from run_v0218 import episode_plan
from v02_local_provider import append_event
from v0218_world import World, digest


def test_discovery_two_roots_two_candidates_shared_A_and_equal_opportunities():
    plan = episode_plan([{"root": "one"}, {"root": "two"}], ("N1", "C1", "C2"))
    assert len(plan) == 14 and sum(r["phase"] == "A" for r in plan) == 2
    assert len({r["id"] for r in plan}) == 14
    assert {r["arm"] for r in plan if r["phase"] == "A"} == {"A"}
    for root in ("one", "two"):
        for variant in ("stable", "superseded"):
            assert {r["arm"] for r in plan if r["root"] == root and r["variant"] == variant} == {
                "N1",
                "C1",
                "C2",
            }
    assert policy.system_for("N1") == common.SYSTEM
    assert policy.system_for("C2") == policy.system_for("C1") + "\n" + policy.CHECKPOINT


@pytest.mark.parametrize("arm", ["N1", "C1", "C2"])
@pytest.mark.parametrize("has_note", [False, True])
def test_policy_actual_host_payload_preserves_note_sources_and_budget(
    tmp_path, monkeypatch, arm, has_note
):
    captured = []
    world = World.create(tmp_path / "world.sqlite", "scope", scheduling()["public"])
    note = {"content": "Exact old free text / 旧笔记", "content_digest": "offline-only"}

    class Provider:
        def __init__(self, directory, **kwargs):
            assert kwargs["max_requests"] == 2
            self.ledger = directory / "provider-ledger.jsonl"

        def verify(self):
            pass

        def close(self):
            pass

        def generate(self, session, body):
            captured.append(body)
            key = str(len(captured))
            append_event(
                self.ledger,
                {
                    "event": "RESERVED",
                    "request_id": key,
                    "session": session,
                    "payload_sha256": digest(body),
                },
            )
            append_event(
                self.ledger,
                {"event": "SETTLED", "request_id": key, "input_tokens": 1, "output_tokens": 1},
            )
            return json.dumps(
                {
                    "action": "read" if len(captured) == 1 else "finish",
                    "arguments_json": '{"resource":"current"}'
                    if len(captured) == 1
                    else '{"message":"done"}',
                }
            )

    @contextmanager
    def observer(*_args, **_kwargs):
        yield lambda *_: pytest.fail("No implicit memory calls allowed")

    monkeypatch.setattr(common, "Provider", Provider)
    monkeypatch.setattr(common, "observer", observer)
    monkeypatch.setattr(common, "read_note", lambda *_: note)
    config = {
        "world": str(world.path),
        "world_scope": "scope",
        "memory_scope": "scope",
        "output": str(tmp_path / "episode"),
        "owned": str(tmp_path),
        "seconds": 30,
        "generation_cap": 2,
        "root": "offline",
        "episode_id": "offline",
        "arm": arm,
        "variant": "stable",
        "phase": "B",
        "note_commit": note if has_note else None,
        "policy": arm,
        "policy_system": policy.system_for(arm),
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    before = common.SYSTEM
    outcome = policy.run(path)
    assert common.SYSTEM == before
    assert outcome["accounting"]["requests"] == 2
    assert outcome["agent_note_writes"] == 0 and outcome["inherited_messages"] == 0
    assert world.snapshot()["records"] == {}
    assert len(captured) == 2
    for body in captured:
        assert body["messages"][0]["content"] == policy.system_for(arm)
        initial = json.loads(body["messages"][1]["content"])
        assert initial["saved_working_note"] == (note["content"] if has_note else None)
        assert initial["task"] == world.read("task")
        assert initial["tools"] == common.TOOLS
    assert (
        json.loads(captured[1]["messages"][-2]["content"])["tool_result"]["content"]
        == world.snapshot()["current"]
    )
    assert captured[1]["response_format"]["json_schema"]["schema"]["properties"]["action"][
        "enum"
    ] == ["finish"]
    if arm == "N1":
        # Same actual messages as the original Host, not merely a claimed no-op policy.
        original = list(captured)
        captured.clear()
        config["output"] = str(tmp_path / "original")
        config.pop("policy")
        config.pop("policy_system")
        path.write_text(json.dumps(config))
        common.run(path)
        assert captured == original


@pytest.mark.parametrize("change", ["A", "mismatch", "unknown", "prompt"])
def test_policy_rejects_undeclared_or_A_intervention(tmp_path, monkeypatch, change):
    config = {"phase": "B", "arm": "C1", "policy": "C1", "policy_system": policy.system_for("C1")}
    if change == "A":
        config["phase"] = "A"
    elif change == "mismatch":
        config["arm"] = "C2"
    elif change == "unknown":
        config.update(arm="CUSTOM", policy="CUSTOM")
    else:
        config["policy_system"] += " arbitrary override"
    monkeypatch.setattr(common, "run", lambda *_: pytest.fail("Must reject before common Host"))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises((ValueError, KeyError)):
        policy.run(path)


def test_wrapper_restores_system_on_common_failure(tmp_path, monkeypatch):
    before = common.SYSTEM

    def fail(_):
        raise RuntimeError("offline fault")

    monkeypatch.setattr(common, "run", fail)
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {"phase": "B", "arm": "C1", "policy": "C1", "policy_system": policy.system_for("C1")}
        )
    )
    with pytest.raises(RuntimeError):
        policy.run(path)
    assert common.SYSTEM == before

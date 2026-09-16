"""Exact old R1 wording, same five public reads, no N0 inherited Note."""

import copy
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0218_host as common
from v02_local_provider import append_event
from v0218_e2_host import REVIEW
from v0218_policy_host import AUDIT, BASE_SYSTEM
from v0218_world import World, digest
from v0219_host import PUBLIC_PREFETCH, configured, run, system_for, validate


def config(arm):
    value = {"arm": arm, "phase": "A" if arm == "A" else "B",
             "policy_system": system_for(arm), "note_commit": None}
    if arm != "A":
        value["public_prefetch"] = list(PUBLIC_PREFETCH)
    return value


def test_exact_system_no_weakened_review():
    assert system_for("R1") == BASE_SYSTEM + "\n" + AUDIT + "\n" + REVIEW
    assert system_for("N0") == system_for("N1") == system_for("A") == BASE_SYSTEM
    for arm in ("N2", "C1", "C2", "P1"):
        with pytest.raises(ValueError):
            system_for(arm)


def test_each_arm_full_pending_current_history_without_mutation(tmp_path):
    world = World.create(tmp_path / "world.sqlite", "scope", {
        "task": {}, "policy": {"ordinary": "public"}, "current": {"full": "source"},
        "objects": ["item"],
    })
    world.act(operation_id="question", expected_version=0, action="request_clarification",
              object_id="item", data={"question": "Genuine unresolved fact?"})
    before = digest(world.snapshot())
    old_system, old_prefetch = common.SYSTEM, copy.deepcopy(common.PUBLIC_PREFETCH)
    results = []
    for arm in ("N0", "N1", "R1"):
        with configured(config(arm)):
            common.validate_prefetch(config(arm))
            receipt = common.prefetch(world)
            responses = [r["response"] for r in receipt["reads"]]
            assert [r["resource"] for r in responses] == PUBLIC_PREFETCH
            assert responses[-1]["content"] == {"item": "Genuine unresolved fact?"}
            assert all(r["content_sha256"] == digest(r["content"]) for r in responses)
            results.append(responses)
        assert common.SYSTEM == old_system and common.PUBLIC_PREFETCH == old_prefetch
    assert results[0] == results[1] == results[2]
    assert before == digest(world.snapshot())


def test_context_restores_on_failure():
    old = (common.SYSTEM, common.PUBLIC_PREFETCH)
    with pytest.raises(RuntimeError), configured(config("R1")):
        raise RuntimeError("injected")
    assert (common.SYSTEM, common.PUBLIC_PREFETCH) == old


@pytest.mark.parametrize("arm,patch", [
    ("N0", {"note_commit": {"content": "old"}}),
    ("R1", {"public_prefetch": PUBLIC_PREFETCH[:-1]}),
    ("N1", {"public_prefetch": list(reversed(PUBLIC_PREFETCH))}),
    ("R1", {"policy_system": "Think again"}),
    ("A", {"public_prefetch": PUBLIC_PREFETCH}),
    ("A", {"note_commit": {"content": "ideal note"}}),
    ("A", {"phase": "B"}),
])
def test_profile_deviations_rejected(arm, patch):
    with pytest.raises(ValueError):
        validate({**config(arm), **patch})


@pytest.mark.parametrize("has_note", [False, True])
def test_actual_host_assembly_all_baselines_with_offline_provider(tmp_path, monkeypatch, has_note):
    """Real common loop/SQLite reads; fake Provider and memory, not a P-chain claim."""
    world = World.create(tmp_path / "dispatch.sqlite", "scope", {
        "task": {"request": "synthetic business task"}, "policy": {"full": "rules"},
        "current": {"full": "SOURCE_CANARY"}, "objects": ["item"],
    })
    world.act(operation_id="question", expected_version=0, action="request_clarification",
              object_id="item", data={"question": "PENDING_CANARY"})
    original = digest(world.snapshot())
    captured = []
    note = {"content": "Unconstrained ordinary old note", "content_digest": "offline-fixture"}

    class Provider:
        def __init__(self, directory, **kwargs):
            assert kwargs["max_requests"] == 2
            self.ledger = directory / "provider-ledger.jsonl"
            self.index = 0

        def verify(self):
            pass

        def close(self):
            pass

        def generate(self, session, body):
            captured.append(copy.deepcopy(body))
            self.index += 1
            key = str(self.index)
            append_event(self.ledger, {"event": "RESERVED", "request_id": key,
                "session": session, "payload_sha256": digest(body)})
            append_event(self.ledger, {"event": "SETTLED", "request_id": key,
                "input_tokens": 1, "output_tokens": 1})
            return json.dumps({"action": "read" if self.index == 1 else "finish",
                "arguments_json": '{"resource":"pending"}' if self.index == 1
                else '{"message":"handoff, no business mutation"}'})

    @contextmanager
    def observer(*_args, **_kwargs):
        yield lambda *_: pytest.fail("No implicit Note mutation permitted")

    monkeypatch.setattr(common, "Provider", Provider)
    monkeypatch.setattr(common, "observer", observer)
    monkeypatch.setattr(common, "read_note", lambda *_: note)
    same_sources = []
    for arm in ("N0", "N1", "R1"):
        captured.clear()
        value = {**config(arm), "world": str(world.path), "world_scope": "scope",
            "memory_scope": "scope", "owned": str(tmp_path), "output": str(tmp_path / arm),
            "seconds": 30, "generation_cap": 2, "root": "synthetic", "episode_id": arm,
            "variant": "stable", "note_commit": note if has_note and arm != "N0" else None}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(value))
        outcome = run(path)
        assert outcome["status"] == "FINISHED" and outcome["agent_note_writes"] == 0
        assert len(captured) == 2 and outcome["accounting"]["requests"] == 2
        assert digest(world.snapshot()) == original
        for body in captured:
            assert body["messages"][0]["content"] == system_for(arm)
            initial = json.loads(body["messages"][1]["content"])
            assert initial["saved_working_note"] == (
                note["content"] if has_note and arm != "N0" else None)
            assert initial["tools"] == common.TOOLS
            for index, resource in enumerate(PUBLIC_PREFETCH):
                sent = json.loads(body["messages"][index + 2]["content"])["tool_result"]
                assert sent == world.read(resource)
        same_sources.append(captured[0]["messages"][2:7])
        assert captured[-1]["response_format"]["json_schema"]["schema"]["properties"][
            "action"]["enum"] == ["finish"]
        receipt = json.loads((tmp_path / arm / "dispatch-receipts.json").read_text())
        assert len(receipt["requests"][0]["source_receipts_in_context"]) == 5
        assert len(receipt["requests"][1]["source_receipts_in_context"]) == 6
    assert same_sources[0] == same_sources[1] == same_sources[2]

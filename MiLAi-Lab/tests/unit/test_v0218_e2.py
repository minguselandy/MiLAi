"""Actual shared-host payload and full public-prefetch boundary tests (offline model)."""

import copy
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0218_e2_host as policy
import v0218_host as common
from audit_v0218_e2 import audit_prefetch
from prepare_v0218 import scheduling
from run_v0218_e2 import validate_plan
from v02_local_provider import append_event
from v0218_policy_host import system_for as e1_system
from v0218_world import World, WorldError, digest


def test_e2_fixed_matrix_and_original_policies():
    plan = json.loads((Path(__file__).parents[2] / "configs/v0218-e2-controls.json").read_text())
    episodes = validate_plan(plan)
    assert len(episodes) == len({e["id"] for e in episodes}) == 32
    assert sum(e["phase"] == "A" for e in episodes) == 2
    for arm in ("N1", "C1", "C2"):
        assert policy.system_for(arm) == e1_system(arm)


@pytest.mark.parametrize(
    "fault",
    [
        "arms",
        "variants",
        "public_prefetch",
        "max_requests",
        "raw_token_cap",
        "new_compatibility_requests",
        "roots",
    ],
)
def test_e2_rejects_undeclared_allocations(fault):
    plan = json.loads((Path(__file__).parents[2] / "configs/v0218-e2-controls.json").read_text())
    plan[fault] = [] if isinstance(plan[fault], list) else 1
    with pytest.raises(AssertionError):
        validate_plan(plan)


@pytest.mark.parametrize(
    "phase,resources",
    [
        ("A", common.PUBLIC_PREFETCH),
        ("B", ["current"]),
        ("B", ["current", "policy", "records", "gold"]),
        ("B", None),
    ],
)
def test_reject_private_partial_or_A_prefetch(phase, resources):
    with pytest.raises(ValueError):
        common.validate_prefetch({"phase": phase, "public_prefetch": resources})


def test_prefetch_exact_real_public_reads_scope_and_no_mutation(tmp_path):
    world = World.create(tmp_path / "world.sqlite", "scope", scheduling()["public"])
    before = world.snapshot()
    receipt = common.prefetch(world)
    assert world.snapshot() == before and world.ledger() == []
    messages = audit_prefetch(receipt, before)
    assert len(messages) == 4
    for index, resource in enumerate(common.PUBLIC_PREFETCH):
        assert json.loads(messages[index]["content"])["tool_result"] == world.read(resource)
    with pytest.raises(WorldError, match="SCOPE_DENIED"):
        common.prefetch(World(world.path, "different-scope"))
    for fault in ("content", "scope", "version", "missing"):
        corrupted = copy.deepcopy(receipt)
        if fault == "scope":
            corrupted["scope"] = "different-scope"
        elif fault == "missing":
            corrupted["reads"].pop()
        else:
            corrupted["reads"][0]["response"][fault] = "changed"
        with pytest.raises(AssertionError):
            audit_prefetch(corrupted, before)


@pytest.mark.parametrize("has_note", [False, True])
def test_all_five_actual_payloads_same_full_information_budget_and_no_implicit_save(
    tmp_path, monkeypatch, has_note
):
    captured = []
    world = World.create(tmp_path / "world.sqlite", "scope", scheduling()["public"])
    note = {"content": "Exact ordinary old note / 普通旧笔记", "content_digest": "offline"}

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
            captured.append(body)
            self.index += 1
            key = str(self.index)
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
                    "action": "read" if self.index == 1 else "finish",
                    "arguments_json": '{"resource":"current"}'
                    if self.index == 1
                    else '{"message":"done"}',
                }
            )

    @contextmanager
    def observer(*_args, **_kwargs):
        yield lambda *_: pytest.fail("No implicit memory calls")

    monkeypatch.setattr(common, "Provider", Provider)
    monkeypatch.setattr(common, "observer", observer)
    monkeypatch.setattr(common, "read_note", lambda *_: note)
    same = None
    for arm in policy.POLICIES:
        captured.clear()
        config = {
            "world": str(world.path),
            "world_scope": "scope",
            "memory_scope": "scope",
            "owned": str(tmp_path),
            "output": str(tmp_path / arm),
            "seconds": 30,
            "generation_cap": 2,
            "root": "offline",
            "episode_id": "offline",
            "phase": "B",
            "variant": "stable",
            "arm": arm,
            "policy": arm,
            "policy_system": policy.system_for(arm),
            "public_prefetch": common.PUBLIC_PREFETCH,
            "note_commit": note if has_note else None,
        }
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))
        original_system = common.SYSTEM
        outcome = policy.run(path)
        assert common.SYSTEM == original_system
        assert outcome["status"] == "FINISHED" and outcome["agent_note_writes"] == 0
        assert outcome["accounting"]["requests"] == 2 and world.snapshot()["records"] == {}
        assert len(captured) == 2
        for body in captured:
            assert body["messages"][0]["content"] == policy.system_for(arm)
            initial = json.loads(body["messages"][1]["content"])
            assert initial["saved_working_note"] == (note["content"] if has_note else None)
            assert initial["tools"] == common.TOOLS
            for index, resource in enumerate(common.PUBLIC_PREFETCH):
                assert json.loads(body["messages"][2 + index]["content"])["tool_result"] == (
                    world.read(resource)
                )
        assert captured[1]["response_format"]["json_schema"]["schema"]["properties"]["action"][
            "enum"
        ] == ["finish"]
        stripped = [{**body, "messages": body["messages"][1:]} for body in captured]
        if same is not None:
            assert same == stripped
        same = stripped
        receipts = json.loads((tmp_path / arm / "dispatch-receipts.json").read_text())
        assert len(receipts["requests"][0]["source_receipts_in_context"]) == 4
        assert len(receipts["requests"][1]["source_receipts_in_context"]) == 5

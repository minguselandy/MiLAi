"""Offline no-carry Host effects and fail-closed boundaries, never model efficacy."""

import copy
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put

from v0218_e2_host import system_for as old_policy
from v0218_world import World, digest
from v0220_evidence import read, seal, sha, validate
from v0220_session import Session, check_public, system_for


class FakeProvider:
    def __init__(self, actions, hook=None):
        self.actions = iter(actions)
        self.requests, self.verifies, self.closed = [], 0, False
        self.hook = hook

    def verify(self):
        self.verifies += 1

    def generate(self, session, body):
        self.requests.append(copy.deepcopy(body))
        if self.hook:
            self.hook(len(self.requests))
        value = next(self.actions)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    def close(self):
        self.closed = True


def finish():
    return {"action": "finish", "arguments": {"message": "Reported work; no implicit effect."}}


def session(tmp_path, **kwargs):
    world = World.create(tmp_path / "world.sqlite", "owned", public())
    arguments = {
        "episode_id": "synthetic",
        "profile": "INTENT_ORACLE",
        "arm": "ORACLE",
        "intent": {"instruction": "Synthetic known intent, not natural business evaluation."},
        "validate_binding": lambda: None,
        **kwargs,
    }
    return Session(world, tmp_path / "session", **arguments)


def run(host, provider):
    return host.run(provider, deadline=time.monotonic() + 30)


def test_complete_short_chain_actual_effect_readback_and_no_head_rebase(tmp_path):
    host = session(tmp_path)
    provider = FakeProvider(
        [put(), put("right", 1), {"action": "read", "arguments": {"resource": "records"}}, finish()]
    )
    result = run(host, provider)
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
    assert result["task_outcome"] == "NOT_EVALUATED" and len(provider.requests) == 4
    assert provider.closed and provider.verifies == 1
    assert len(host.world.ledger()) == 2 and host.world.snapshot()["version"] == 2
    assert host.rows[2]["response"]["content"] == host.world.snapshot()["records"]
    assert host.rows[-1]["before_sha256"] == host.rows[-1]["after_sha256"]
    assert read(host.directory / "intent-01.json") == put()
    expected_versions = [0, 1, 2, 2]
    for request, expected in zip(provider.requests, expected_versions, strict=True):
        disclosure = json.loads(request["messages"][-1]["content"])
        assert disclosure["last_completed_public_observation"]["version"] == expected
    assert len(provider.requests[-1]["response_format"]["json_schema"]["schema"]["anyOf"]) == 1


def test_actual_world_head_change_is_not_silently_disclosed_or_bound(tmp_path):
    host = session(tmp_path)

    def concurrent_change(turn):
        if turn == 1:
            host.world.publish(event_id="fixed-event", current={"authorized": True})

    provider = FakeProvider([put(), finish()], hook=concurrent_change)
    result = run(host, provider)
    assert result["status"] == "PROTOCOL_REJECTION_STOP"
    assert result["code"] == "VERSION_CONFLICT" and len(provider.requests) == 1
    assert host.rows[0]["action"]["arguments"]["expected_version"] == 0
    assert host.world.snapshot()["records"] == {}
    assert host.last_observation["version"] == 0  # Error head is not a public premise read.


def test_note_finish_and_clarification_have_distinct_real_effects(tmp_path):
    host = session(tmp_path, profile="NATURAL_NO_CARRY", arm="R0-exec", intent=None)
    before = digest(host.world.snapshot())
    note = {"action": "save_note", "arguments": {"note": "本会话复核,未宣称写入业务。"}}
    nr = host.dispatch(note, 1)
    assert nr["note_saved"] and not nr["business_effect"] and not nr["committed"]
    assert nr["version_domain"] == "SESSION" and digest(host.world.snapshot()) == before
    assert read(host.directory / "note-01.json")["content"] == note["arguments"]["note"]
    clarification = {
        "action": "request_clarification",
        "arguments": {"object_id": "left", "expected_version": 0, "data": {"question": "授权?"}},
    }
    cr = host.dispatch(clarification, 2)
    assert cr["committed"] and cr["business_effect"] and cr["version_domain"] == "WORLD"
    assert host.world.snapshot()["pending"] == {"left": "授权?"}
    assert host.world.snapshot()["records"] == {}
    end = host.dispatch(finish(), 3)
    assert not end["committed"] and end["task_outcome"] == "NOT_EVALUATED"
    with pytest.raises(ValueError, match="SESSION_STOPPED"):
        host.dispatch(put(version=1), 4)
    assert len(host.world.ledger()) == 1


def test_original_r1_policy_preserved_and_no_carry_notes(tmp_path):
    host = session(tmp_path, profile="NATURAL_NO_CARRY", arm="R0-exec", intent=None)
    assert system_for("NATURAL_NO_CARRY", "R0-exec").startswith(old_policy("R1") + "\n")
    initial = read(host.directory / "initial-presentation.json")
    assert initial["inherited_note"] is None and "authorized_intent" not in initial
    assert [r["resource"] for r in initial["observations"]] == [
        "task",
        "current",
        "policy",
        "records",
        "history",
        "pending",
    ]
    assert all(r["version"] == 0 for r in initial["observations"])
    assert len(host.world.ledger()) == 0


@pytest.mark.parametrize("carrier", ["intent", "arm", "profile"])
def test_oracle_material_cannot_be_rebound_as_natural_input(tmp_path, carrier):
    args = {"profile": "NATURAL_NO_CARRY", "arm": "N0-exec", "intent": None}
    args[carrier] = {"instruction": "oracle"} if carrier == "intent" else "ORACLE"
    with pytest.raises(ValueError):
        session(tmp_path, **args)
    assert not (tmp_path / "session").exists()


@pytest.mark.parametrize("mutation", ["scope", "arm", "episode", "contract"])
def test_runtime_cross_arm_scope_and_contract_drift_fails_before_provider(tmp_path, mutation):
    host = session(tmp_path)
    if mutation == "scope":
        host.world.scope = "other"
    elif mutation == "arm":
        host.arm = "N0-exec"
    elif mutation == "episode":
        host.episode_id = "other"
    else:
        host.contract.read_schemas["left"]["properties"]["text"]["maxLength"] = 10
    provider = FakeProvider([finish()])
    result = run(host, provider)
    assert result["status"] == "FAIL_CLOSED" and provider.verifies == 0
    assert provider.requests == [] and provider.closed


@pytest.mark.parametrize("value", [{"gold": "private"}, {"text": "XX秘密-canaryYY"}])
def test_private_keys_and_string_canaries_fail_closed_without_echo(value):
    with pytest.raises(ValueError, match=r"^PUBLIC_ISOLATION_FAILURE$"):
        check_public(value, ("秘密-canary",))


def test_canary_in_public_source_blocks_initial_presentation(tmp_path):
    p = public()
    p["policy"]["text"] = "DO_NOT_LEAK_PRIVATE_CANARY"
    world = World.create(tmp_path / "world.sqlite", "owned", p)
    with pytest.raises(ValueError, match=r"^PUBLIC_ISOLATION_FAILURE$"):
        Session(
            world,
            tmp_path / "session",
            episode_id="id",
            profile="INTENT_ORACLE",
            arm="ORACLE",
            intent={"instruction": "public"},
            forbidden_literals=("DO_NOT_LEAK_PRIVATE_CANARY",),
            validate_binding=lambda: None,
        )
    assert not (tmp_path / "session").exists() and world.ledger() == []


@pytest.mark.parametrize("committed", [False, True])
def test_unknown_commit_stops_next_generation_and_new_session(tmp_path, committed):
    host = session(tmp_path)
    original = host.world.act

    def lost(**kwargs):
        if committed:
            original(**kwargs)
        raise OSError("PRIVATE_ERROR_MUST_NOT_BE_LOGGED")

    host.world.act = lost
    provider = FakeProvider([put(), put("right", 1)])
    result = run(host, provider)
    assert result["status"] == "COMMIT_UNKNOWN_STOP" and len(provider.requests) == 1
    assert len(host.world.ledger()) == int(committed)
    assert host.rows[0]["response"]["committed"] is None
    with pytest.raises(ValueError, match="UNRESOLVED_COMMIT"):
        Session(
            host.world,
            tmp_path / "restart",
            episode_id="restart",
            profile="INTENT_ORACLE",
            arm="ORACLE",
            intent={"instruction": "public"},
            validate_binding=lambda: None,
        )
    assert not (tmp_path / "restart").exists()


def test_provider_exception_never_retries_or_echoes_private_body(tmp_path):
    host = session(tmp_path)
    provider = FakeProvider([OSError("PRIVATE_ERROR_MUST_NOT_BE_LOGGED"), finish()])
    result = run(host, provider)
    assert result["status"] == "FAIL_CLOSED" and len(provider.requests) == 1
    assert "PRIVATE_ERROR" not in json.dumps(result) and host.world.ledger() == []


def test_known_intent_first_malformed_output_stops_batch_candidate(tmp_path):
    host = session(tmp_path)
    provider = FakeProvider(['{"action":"read","arguments_json":"{}"}', finish()])
    result = run(host, provider)
    assert result["status"] == "PROTOCOL_REJECTION_STOP" and len(provider.requests) == 1
    assert not host.rows[0]["dispatch_attempted"] and host.world.ledger() == []


def test_natural_same_category_recurrence_stops_across_episodes(tmp_path):
    host = session(
        tmp_path,
        profile="NATURAL_NO_CARRY",
        arm="N0-exec",
        intent=None,
        prior_rejection_counts={"INVALID_JSON": 1},
    )
    provider = FakeProvider(["invalid", finish()])
    result = run(host, provider)
    assert result["status"] == "PROTOCOL_REJECTION_STOP"
    assert len(provider.requests) == 1 and result["rejection_counts"]["INVALID_JSON"] == 2


def test_natural_one_rejection_can_recover_without_extra_opportunities(tmp_path):
    host = session(tmp_path, profile="NATURAL_NO_CARRY", arm="N0-exec", intent=None)
    provider = FakeProvider(["invalid", put(), finish()])
    result = run(host, provider)
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
    assert len(provider.requests) == 3 and len(host.world.ledger()) == 1
    assert result["rejection_counts"] == {"INVALID_JSON": 1}


@pytest.mark.parametrize("target", ["input", "source", "manifest"])
def test_sealed_input_source_manifest_drift_stops_without_provider(tmp_path, target):
    # Corrupt only test-owned copied source/config, never a sealed live implementation.
    from v0220_evidence import LAB

    fixture = tmp_path / "input.json"
    fixture.write_text('{"arm":"ORACLE"}')
    root = tmp_path / "seal"
    seal(root, entries=[LAB / "tools/v0220_session.py"], inputs=[fixture], contract={"test": True})
    expected = sha(root / "manifest.json")
    host = session(tmp_path, validate_binding=lambda: validate(root, manifest_sha256=expected))
    if target == "input":
        fixture.write_text('{"arm":"other"}')
    elif target == "source":
        (root / "executed-source/tools/v0220_session.py").write_text("# tampered test copy")
    else:
        (root / "manifest.json").write_text("{}")
    provider = FakeProvider([finish()])
    result = run(host, provider)
    assert result["status"] == "FAIL_CLOSED" and provider.verifies == 0
    assert provider.requests == [] and host.world.ledger() == []

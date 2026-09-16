"""Independent literal expectations for actual adapted business state, no model calls."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_v0218 import claim, scheduling
from v0218_checker import evaluate
from v0218_world import World, WorldError, digest


def booking(day, hour, *, mode="in_person", room="301", interviewer="A"):
    return {
        "start": f"2026-03-{day}T{hour}:00:00+08:00",
        "end": f"2026-03-{day}T{hour}:30:00+08:00",
        "mode": mode,
        "room": room,
        "interviewer": interviewer,
        "confirmed": True,
    }


def put(world, target, data, operation="write"):
    return world.act(
        operation_id=operation,
        expected_version=world.snapshot()["version"],
        action="put_record",
        object_id=target,
        data=data,
    )


def populated(tmp_path, spec=None):
    spec = spec or scheduling()
    world = World.create(tmp_path / "world.sqlite", "scope-a", spec["public"])
    if spec["family"] == "scheduling":
        put(world, "C03", booking("25", "09"), "a")
        put(world, "C04", booking("26", "13"), "b")
    else:
        put(
            world,
            "FLT-DLY-0315",
            {
                "decision": "approved",
                "amount_cny": 400,
                "delay_minutes": 167,
                "reason": "weather",
                "basis_revision": "official-v1",
            },
        )
    return world


def test_real_write_reopen_and_multiple_legal_schedules(tmp_path):
    world = populated(tmp_path)
    assert evaluate(World(world.path, "scope-a").snapshot())["status"] == "PASS"
    put(world, "C03", booking("25", "10", room="302", interviewer="B"), "alternate")
    assert evaluate(world.snapshot())["status"] == "PASS"
    assert len(world.ledger()) == 3


def test_declaration_without_business_action_never_passes(tmp_path):
    world = World.create(tmp_path / "empty.sqlite", "scope", scheduling()["public"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    assert not world.ledger()


@pytest.mark.parametrize("factory", [scheduling, claim])
@pytest.mark.parametrize("value", [False, 1, "approved", ["confirmed"]])
@pytest.mark.parametrize("unresolved", [False, True])
def test_checker_rejects_malformed_record_without_crashing(tmp_path, factory, value, unresolved):
    spec = factory()
    state = populated(tmp_path, spec).snapshot()
    target = state["objects"][0]
    state["records"][target] = value
    if unresolved:
        collection = "candidates" if spec["family"] == "scheduling" else "claims"
        state["current"][collection][target]["status"] = "unresolved"
    result = evaluate(state)
    assert result["status"] == "FAIL"
    assert f"{target}:RECORD_TYPE" in result["errors"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("start", ""),
        ("end", ""),
        ("start", "2026-03-25T09:00:00"),
        ("start", "2026-03-25T09:00:00+00:00"),
        ("end", "2026-03-25T09:00:00+08:00"),
        ("mode", "not in_person"),
        ("mode", "in_person or online"),
        ("mode", "previously in_person; now unknown"),
        ("confirmed", "true"),
        ("confirmed", False),
        ("room", "999"),
        ("interviewer", "OTHER"),
    ],
)
def test_schedule_wrong_partial_negated_or_ambiguous_fields(tmp_path, field, value):
    world = populated(tmp_path)
    bad = booking("25", "09")
    bad[field] = value
    put(world, "C03", bad, "bad")
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_missing_required_field_wrong_target_and_snapshot_mutation(tmp_path):
    world = populated(tmp_path)
    state = world.snapshot()
    state["records"]["C03"].pop("start")
    assert evaluate(state)["status"] == "FAIL"
    state = world.snapshot()
    state["records"]["C03"]["object_id"] = "C04"
    assert evaluate(state)["status"] == "FAIL"
    with pytest.raises(WorldError, match="OBJECT_SCOPE"):
        put(world, "OTHER", booking("25", "09"), "outside")


def test_pair_clone_stability_update_and_recovery(tmp_path):
    original = populated(tmp_path)
    before = digest(original.snapshot())
    stable = original.clone(tmp_path / "stable.sqlite", "stable")
    changed = original.clone(tmp_path / "changed.sqlite", "changed")
    assert {k: v for k, v in stable.snapshot().items() if k != "scope"} == {
        k: v for k, v in changed.snapshot().items() if k != "scope"
    }
    event = scheduling()["variants"]["superseded"]
    receipt = changed.publish(event_id="frozen-1", current=event)
    assert changed.publish(event_id="frozen-1", current=event)["version"] == receipt["version"]
    assert evaluate(stable.snapshot())["status"] == "PASS"
    assert evaluate(changed.snapshot())["status"] == "FAIL"
    # Current business facts are normally readable; scripted recovery really changes the DB.
    assert changed.read("current")["content"]["candidates"]["C03"]["modes"] == ["online"]
    put(changed, "C03", booking("25", "09", mode="online", room="online"), "repair-c03")
    assert evaluate(changed.snapshot())["status"] == "FAIL"  # partial repair must not pass
    put(changed, "C04", booking("26", "10"), "repair-c04")
    assert evaluate(changed.snapshot())["status"] == "PASS"
    assert digest(original.snapshot()) == before
    assert evaluate(changed.ledger()[0]["snapshot"])["status"] == "FAIL"  # old partial A retained


def test_unresolved_allows_specific_suspend_but_sufficient_does_not(tmp_path):
    world = populated(tmp_path)
    world.publish(event_id="pending", current=scheduling()["variants"]["unresolved"])
    put(world, "C03", booking("25", "09", mode="online", room="online"), "c03")
    world.act(
        operation_id="ask",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="C04",
        data={"question": "Confirm C04 availability?"},
    )
    assert evaluate(world.snapshot())["status"] == "FAIL"  # an old confirmation is still active
    put(world, "C04", {"confirmed": False}, "unconfirm")
    world.act(
        operation_id="ask2",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="C04",
        data={"question": "Confirm C04 availability?"},
    )
    assert evaluate(world.snapshot())["status"] == "PASS"
    world.publish(event_id="resolved", current=scheduling()["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_overlap_and_noncausal_order_and_object_renaming(tmp_path):
    spec = scheduling()
    spec["public"]["current"]["candidates"]["C04"]["windows"] = copy.deepcopy(
        spec["public"]["current"]["candidates"]["C03"]["windows"]
    )
    world = World.create(tmp_path / "world.sqlite", "scope", spec["public"])
    put(world, "C03", booking("25", "09"), "one")
    put(world, "C04", booking("25", "09"), "two")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    put(world, "C04", booking("25", "10"), "three")
    state = world.snapshot()
    assert evaluate(state)["status"] == "PASS"
    state["objects"].reverse()
    state["current"]["unrelated_notice"] = "Another department changed its meeting."
    assert evaluate(state)["status"] == "PASS"
    state = json.loads(json.dumps(state).replace("C03", "Renamed-X").replace("C04", "Renamed-Y"))
    assert evaluate(state)["status"] == "PASS"


def test_scope_cas_and_idempotency_do_not_mutate_on_rejection(tmp_path):
    world = populated(tmp_path)
    before = digest(world.snapshot())
    with pytest.raises(WorldError, match="SCOPE_DENIED"):
        World(world.path, "wrong-scope").read("current")
    with pytest.raises(WorldError, match="SCOPE_DENIED"):
        World(world.path, "wrong-scope").clone(tmp_path / "leaked.sqlite", "new")
    assert not (tmp_path / "leaked.sqlite").exists()
    with pytest.raises(WorldError, match="VERSION_CONFLICT"):
        world.act(
            operation_id="stale", expected_version=0, action="put_record", object_id="C03", data={}
        )
    assert digest(world.snapshot()) == before
    request = {
        "operation_id": "repeat",
        "expected_version": world.snapshot()["version"],
        "action": "put_record",
        "object_id": "C03",
        "data": booking("25", "11"),
    }
    first = world.act(**request)
    assert world.act(**request) == first
    request["data"] = booking("25", "10")
    with pytest.raises(WorldError, match="REUSE_CONFLICT"):
        world.act(**request)


def test_future_private_and_identity_fields_fail_closed(tmp_path):
    world = populated(tmp_path)
    for resource in ("gold", "future_events", "checker", "../other"):
        with pytest.raises(WorldError, match="NOT_PUBLIC"):
            world.read(resource)
    for data in ({"nested": {"gold_answer": "CANARY"}}, {"future_events": "CANARY"}):
        with pytest.raises(ValueError, match="PRIVATE"):
            put(world, "C03", data, "poison")
    with pytest.raises(WorldError, match="IDENTITY"):
        put(world, "C03", {"object_id": "C04"}, "spoof")
    assert "CANARY" not in json.dumps(world.snapshot())


def test_claim_literal_amount_revision_update_and_recovery(tmp_path):
    world = populated(tmp_path, claim())
    assert evaluate(world.snapshot())["status"] == "PASS"  # 167 minutes => 2 full hours => 400
    world.publish(event_id="new-official", current=claim()["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    put(
        world,
        "FLT-DLY-0315",
        {
            "decision": "rejected",
            "amount_cny": 0,
            "delay_minutes": 167,
            "reason": "operational_rotation",
            "basis_revision": "official-v2",
        },
        "repair",
    )
    assert evaluate(world.snapshot())["status"] == "PASS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_cny", "400"),
        ("amount_cny", 0),
        ("delay_minutes", True),
        ("delay_minutes", 300),
        ("reason", "not weather"),
        ("reason", "weather or operational_rotation"),
        ("reason", "old weather, now unknown"),
        ("basis_revision", "unverified"),
        ("decision", "pending"),
    ],
)
def test_claim_type_unit_negation_and_partial_false_positives(tmp_path, field, value):
    world = populated(tmp_path, claim())
    state = world.snapshot()
    state["records"]["FLT-DLY-0315"][field] = value
    assert evaluate(state)["status"] == "FAIL"


def test_repeated_construction_has_identical_initial_state(tmp_path):
    public = scheduling()["public"]
    first = World.create(tmp_path / "first.sqlite", "same", public)
    second = World.create(tmp_path / "second.sqlite", "same", public)
    assert digest(first.snapshot()) == digest(second.snapshot())

"""Independent literal release-control fixtures for the third original task lineage."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_v0218_expansion import release_control
from v0218_checker import evaluate
from v0218_world import World, WorldError


def initial_record():
    return {
        "deployed_version": "v2.1",
        "required_version": "v3.0",
        "deadline": "2026-03-31",
        "planned_review_at": "2026-03-30T14:00:00+08:00",
        "release_authorized": False,
        "distribution": ["advisor"],
        "basis_revision": "deployment-v1",
    }


def revised_record():
    return {
        "deployed_version": "v3.0",
        "required_version": "v3.0",
        "deadline": "2026-03-28",
        "planned_review_at": "2026-03-27T10:00:00+08:00",
        "release_authorized": True,
        "distribution": ["advisor", "internal_quality"],
        "basis_revision": "deployment-v2",
    }


def put(world, data, operation="write"):
    return world.act(
        operation_id=operation,
        expected_version=world.snapshot()["version"],
        action="put_record",
        object_id="enterprise-midterm",
        data=data,
    )


def populated(tmp_path):
    world = World.create(tmp_path / "world.sqlite", "release", release_control()["public"])
    put(world, initial_record(), "initial")
    assert evaluate(world.snapshot())["status"] == "PASS"
    return world


def test_stable_and_irrelevant_keep_same_actual_record(tmp_path):
    world = populated(tmp_path)
    for variant in ("stable", "irrelevant"):
        branch = world.clone(tmp_path / f"{variant}.sqlite", variant)
        branch.publish(event_id=variant, current=release_control()["variants"][variant])
        assert evaluate(branch.snapshot())["status"] == "PASS"
    assert World(world.path, "release").snapshot()["version"] == 1


def test_new_verified_deployment_and_deadline_require_actual_revision(tmp_path):
    world = populated(tmp_path)
    world.publish(event_id="changed", current=release_control()["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    first = put(world, revised_record(), "repair")
    assert evaluate(World(world.path, "release").snapshot())["status"] == "PASS"
    again = world.act(
        operation_id="repair",
        expected_version=2,
        action="put_record",
        object_id="enterprise-midterm",
        data=revised_record(),
    )
    assert first == again and world.snapshot()["version"] == 3
    alternate = revised_record()
    alternate.update(planned_review_at="2026-03-25T09:00:00+08:00", distribution=["advisor"])
    put(world, alternate, "alternate")
    assert evaluate(world.snapshot())["status"] == "PASS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("deployed_version", "not v2.1"),
        ("deployed_version", 2.1),
        ("required_version", "v2.1"),
        ("basis_revision", "deployment-v0"),
        ("deadline", "2026-03-28"),
        ("deadline", None),
        ("release_authorized", True),
        ("release_authorized", "false"),
        ("release_authorized", 0),
        ("distribution", "advisor"),
        ("distribution", []),
        ("distribution", ["advisor", "enterprise_contact"]),
        ("distribution", ["advisor", {}]),
        ("planned_review_at", "2026-04-01T09:00:00+08:00"),
        ("planned_review_at", "2026-03-18T08:00:00+08:00"),
        ("planned_review_at", "2026-03-25T09:00:00"),
        ("planned_review_at", "2026-03-25T09:00:00+00:00"),
    ],
)
def test_semantically_wrong_actual_write_fails_checker(tmp_path, field, value):
    world = populated(tmp_path)
    row = initial_record()
    row[field] = value
    put(world, row, "mutant")
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_missing_partial_wrong_object_and_forged_private_truth(tmp_path):
    world = populated(tmp_path)
    for field in initial_record():
        state = world.snapshot()
        del state["records"]["enterprise-midterm"][field]
        assert evaluate(state)["status"] == "FAIL"
    state = world.snapshot()
    state["records"]["enterprise-midterm"]["object_id"] = "another-project"
    assert evaluate(state)["status"] == "FAIL"
    with pytest.raises(ValueError, match="PRIVATE"):
        put(world, {**initial_record(), "gold": "CANARY"}, "leak")
    with pytest.raises(WorldError, match="SCOPE"):
        World(world.path, "other").read("current")


def test_unresolved_then_resolved_cannot_remain_suspended(tmp_path):
    world = populated(tmp_path)
    world.publish(event_id="pending", current=release_control()["variants"]["unresolved"])
    pending = revised_record()
    pending.update(
        deployed_version=None, release_authorized=False, basis_revision="deployment-review-pending"
    )
    put(world, pending, "withhold")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    world.act(
        operation_id="clarify",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="enterprise-midterm",
        data={"question": "Please verify the actual deployed version for this milestone."},
    )
    assert evaluate(world.snapshot())["status"] == "PASS"
    world.publish(event_id="resolved", current=release_control()["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    put(world, revised_record(), "complete")
    assert evaluate(world.snapshot())["status"] == "PASS"


def test_renaming_and_recipient_order_do_not_change_validity(tmp_path):
    world = populated(tmp_path)
    original = world.snapshot()
    renamed = copy.deepcopy(original)
    renamed["objects"] = ["renamed-milestone"]
    renamed["current"]["deployments"]["renamed-milestone"] = renamed["current"]["deployments"].pop(
        "enterprise-midterm"
    )
    renamed["records"]["renamed-milestone"] = renamed["records"].pop("enterprise-midterm")
    renamed["records"]["renamed-milestone"]["object_id"] = "renamed-milestone"
    renamed["records"]["renamed-milestone"]["distribution"] = ["internal_quality", "advisor"]
    assert evaluate(renamed)["status"] == evaluate(original)["status"] == "PASS"

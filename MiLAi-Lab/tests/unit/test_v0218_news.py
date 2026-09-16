"""Independent expected register outputs for authority, roles, conflicts and source visibility."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_v0218_news import newsroom
from v0218_checker import evaluate
from v0218_world import World


def records():
    return {
        field: {
            "incident": "park-fire",
            "field": field,
            "value": value,
            "status": "confirmed",
            "source_ids": [source],
            "basis_edition": 1,
        }
        for field, value, source in [
            ("fire_start", "2026-03-18T14:28:00+08:00", "briefing-start"),
            ("alarm_received", "2026-03-18T14:35:00+08:00", "briefing-alarm"),
            ("casualty_count", 2, "health-count-1"),
            ("casualty_status", "under_observation", "health-status-1"),
        ]
    }


def put(world, target, row, operation="put"):
    return world.act(
        operation_id=f"{operation}-{target}",
        expected_version=world.snapshot()["version"],
        action="put_record",
        object_id=target,
        data=row,
    )


def populated(tmp_path):
    spec = newsroom()
    world = World.create(tmp_path / "news.sqlite", "news", spec["public"])
    for field, row in records().items():
        put(world, field, row)
    assert evaluate(world.snapshot())["status"] == "PASS"
    return world, spec


@pytest.mark.parametrize("variant", ["stable", "irrelevant", "helpful"])
def test_valid_work_survives_display_and_non_authoritative_updates(tmp_path, variant):
    world, spec = populated(tmp_path)
    world.publish(event_id=variant, current=spec["variants"][variant])
    assert evaluate(world.snapshot())["status"] == "PASS"
    if variant == "helpful":
        assert not world.snapshot()["current"]["claims"]
        for arm in ("N0", "N1"):
            cold = world.clone(tmp_path / f"{arm}.sqlite", arm)
            assert cold.snapshot()["history"] == world.snapshot()["history"]
            assert evaluate(cold.snapshot())["status"] == "PASS"


def test_update_revises_treatment_not_time_roles(tmp_path):
    world, spec = populated(tmp_path)
    world.publish(event_id="evening", current=spec["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    for field, value in (("casualty_count", 2), ("casualty_status", "discharged")):
        put(
            world,
            field,
            {
                **records()[field],
                "value": value,
                "basis_edition": 2,
                "source_ids": [f"health-{field}-2"],
            },
            "revise",
        )
    assert evaluate(world.snapshot())["status"] == "PASS"
    for field in ("fire_start", "alarm_received"):
        assert world.snapshot()["records"][field]["value"] == records()[field]["value"]


def test_conflict_requires_null_and_real_verification_not_arbitrary_latest(tmp_path):
    world, spec = populated(tmp_path)
    world.publish(event_id="conflict", current=spec["variants"]["unresolved"])
    for field in ("casualty_count", "casualty_status"):
        put(
            world,
            field,
            {
                **records()[field],
                "value": None,
                "status": "conflicting",
                "basis_edition": 2,
                "source_ids": [f"health-{field}-2", f"health-{field}-2-conflict"],
            },
            "withhold",
        )
    assert evaluate(world.snapshot())["status"] == "FAIL"
    for field in ("casualty_count", "casualty_status"):
        world.act(
            operation_id="verify-" + field,
            expected_version=world.snapshot()["version"],
            action="request_clarification",
            object_id=field,
            data={"question": "Resolve the two health authority edition-2 claims for " + field},
        )
    assert evaluate(world.snapshot())["status"] == "PASS"
    # Same cited competing evidence cannot justify a confirmed number without a new source.
    state = world.snapshot()
    state["records"]["casualty_count"]["value"] = 2
    assert evaluate(state)["status"] == "FAIL"


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("fire_start", "value", "2026-03-18T14:35:00+08:00"),
        ("fire_start", "value", "2026-03-18T14:28:00Z"),
        ("fire_start", "value", "2026-03-18T14:28:00"),
        ("fire_start", "value", "not 14:28"),
        ("fire_start", "value", ["14:28", "14:20"]),
        ("casualty_count", "value", 6),
        ("casualty_count", "value", "2"),
        ("casualty_count", "value", 2.0),
        ("casualty_count", "value", True),
        ("casualty_count", "value", -2),
        ("casualty_count", "source_ids", ["witness-count"]),
        ("casualty_count", "source_ids", ["health-count-1", "witness-count"]),
        ("casualty_count", "source_ids", ["health-count-1", "health-count-1"]),
        ("casualty_count", "source_ids", "health-count-1"),
        ("casualty_count", "source_ids", [{}]),
        ("casualty_count", "basis_edition", True),
        ("casualty_count", "basis_edition", "1"),
        ("casualty_count", "incident", "other-fire"),
        ("casualty_count", "field", "fire_start"),
        ("casualty_status", "value", "not under_observation"),
        ("casualty_status", "status", "conflicting"),
    ],
)
def test_typed_attributed_execution_not_keyword_or_declaration(tmp_path, target, field, value):
    world, _ = populated(tmp_path)
    row = records()[target]
    row[field] = value
    put(world, target, row, "bad")
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_partial_records_false_completion_and_needless_clarification(tmp_path):
    world, _ = populated(tmp_path)
    state = world.snapshot()
    state["records"].pop("alarm_received")
    assert evaluate(state)["status"] == "FAIL"
    for field in records()["fire_start"]:
        state = world.snapshot()
        del state["records"]["fire_start"][field]
        assert evaluate(state)["status"] == "FAIL"
    world.act(
        operation_id="unnecessary",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="fire_start",
        data={"question": "Can we trust the known briefing?"},
    )
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_reordering_and_consistent_object_renaming_are_semantically_invariant(tmp_path):
    world, _ = populated(tmp_path)
    state = world.snapshot()
    state["current"]["claims"].reverse()
    assert evaluate(state)["status"] == "PASS"
    state["objects"][0] = "ignition_time"
    state["policy"]["fields"]["ignition_time"] = state["policy"]["fields"].pop("fire_start")
    row = state["records"].pop("fire_start")
    row.update(object_id="ignition_time", field="ignition_time")
    state["records"]["ignition_time"] = row
    for claim in state["current"]["claims"]:
        if claim["field"] == "fire_start":
            claim["field"] = "ignition_time"
    assert evaluate(state)["status"] == "PASS"


def test_missing_changed_archive_and_injected_current_claims_fail_closed(tmp_path):
    world, spec = populated(tmp_path)
    world.publish(event_id="archive", current=spec["variants"]["helpful"])
    base = world.snapshot()
    for mutation in ("missing", "hash", "current"):
        state = copy.deepcopy(base)
        if mutation == "missing":
            state["history"] = []
        elif mutation == "hash":
            state["current"]["archive_content_sha256"] = "0" * 64
        else:
            state["current"]["claims"] = spec["public"]["current"]["claims"]
        assert evaluate(state)["status"] == "FAIL"

"""Complete fictional allocation, source flags, real headcount changes and tied legal ranks."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from check_v0218_expansion import capacity_fixtures
from prepare_v0218_capacity import capacity_review
from v0218_checker import evaluate
from v0218_world import World


def put(world, target, row, operation):
    world.act(
        operation_id=operation + target,
        expected_version=world.snapshot()["version"],
        action="put_record",
        object_id=target,
        data=row,
    )


def populated(tmp_path):
    spec = capacity_review()
    initial, revised, pending, _ = capacity_fixtures()
    world = World.create(tmp_path / "capacity.sqlite", "capacity", spec["public"])
    for target, row in initial.items():
        put(world, target, row, "initial")
    assert evaluate(world.snapshot())["status"] == "PASS"
    return world, spec, revised, pending


def test_headcount_change_requires_both_artifacts_and_current_source_signals(tmp_path):
    world, spec, revised, _ = populated(tmp_path)
    world.publish(event_id="capacity-cut", current=spec["variants"]["superseded"])
    put(world, "ats", revised["ats"], "partial")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    put(world, "summary", revised["summary"], "complete")
    assert evaluate(world.snapshot())["status"] == "PASS"
    assert {
        row["candidate_id"] for row in revised["ats"]["rows"] if row["recommendation"] == "convert"
    } == {"I01", "I02", "I04"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("score", "14.3"),
        ("score", True),
        ("score", float("nan")),
        ("score", 15.0),
        ("rank", "1"),
        ("rank", True),
        ("rank", 1.0),
        ("rank", 2),
        ("rank", 6),
        ("recommendation", "hold"),
        ("recommendation", "not convert"),
        ("reason", "capacity"),
        ("flags", ["invented"]),
        ("flags", "none"),
        ("flags", [{}]),
        ("candidate_id", "OTHER"),
    ],
)
def test_complete_typed_ranking_not_keywords_or_duplicate_positions(tmp_path, field, value):
    world, _, _, _ = populated(tmp_path)
    state = world.snapshot()
    state["records"]["ats"]["rows"][0][field] = value
    assert evaluate(state)["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "headcount", "flag", "schema"])
def test_all_candidates_current_capacity_and_unfavorable_flags_are_required(tmp_path, mutation):
    world, _, _, _ = populated(tmp_path)
    state = world.snapshot()
    row = state["records"]["summary"]
    if mutation == "missing":
        row["rows"].pop()
    elif mutation == "duplicate":
        row["rows"][2] = copy.deepcopy(row["rows"][1])
    elif mutation == "headcount":
        row["headcount"] = "4"
    elif mutation == "flag":
        row["rows"][2]["flags"] = []
    else:
        del row["rows"][2]["reason"]
    assert evaluate(state)["status"] == "FAIL"


def test_unknown_capacity_does_not_erase_known_ranking_or_threshold(tmp_path):
    world, spec, _, pending = populated(tmp_path)
    world.publish(event_id="unknown", current=spec["variants"]["unresolved"])
    for target, row in pending.items():
        put(world, target, row, "withhold")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    world.act(
        operation_id="clarify",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="summary",
        data={"question": "Please confirm the current allocated headcount for this batch."},
    )
    assert evaluate(world.snapshot())["status"] == "PASS"
    state = world.snapshot()
    state["records"]["ats"]["rows"][4]["recommendation"] = "hold"
    assert evaluate(state)["status"] == "FAIL"


@pytest.mark.parametrize("reverse_tie", [False, True])
def test_ties_allow_multiple_orders_but_both_artifacts_must_agree(tmp_path, reverse_tie):
    world, _, _, _ = populated(tmp_path)
    state = world.snapshot()
    state["current"]["candidates"]["I02"]["performance"] = 4.6  # 13.0, ties I04
    for target in ("ats", "summary"):
        state["records"][target]["rows"][1]["score"] = 13.0
        if reverse_tie:
            state["records"][target]["rows"][1]["rank"] = 2
            state["records"][target]["rows"][3]["rank"] = 3
    assert evaluate(state)["status"] == "PASS"
    rows = state["records"]["ats"]["rows"]
    rows[1]["rank"], rows[3]["rank"] = rows[3]["rank"], rows[1]["rank"]
    assert evaluate(state)["status"] == "FAIL"


def test_record_order_irrelevant_team_and_artifact_rename_invariance(tmp_path):
    world, spec, _, _ = populated(tmp_path)
    world.publish(event_id="other-team", current=spec["variants"]["irrelevant"])
    state = world.snapshot()
    state["records"]["ats"]["rows"].reverse()
    assert evaluate(state)["status"] == "PASS"
    state["objects"][0] = "renamed-ats"
    state["records"]["renamed-ats"] = state["records"].pop("ats")
    state["records"]["renamed-ats"]["object_id"] = "renamed-ats"
    assert evaluate(state)["status"] == "PASS"


def test_missing_artifact_fields_and_needless_pause_fail(tmp_path):
    world, _, _, _ = populated(tmp_path)
    for field in ("rows", "headcount", "basis_revision"):
        state = world.snapshot()
        del state["records"]["ats"][field]
        assert evaluate(state)["status"] == "FAIL"
    world.act(
        operation_id="needless",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="summary",
        data={"question": "Should we apply this already approved capacity?"},
    )
    assert evaluate(world.snapshot())["status"] == "FAIL"

"""Full multi-artifact checks using independently specified replay fixtures, not source outputs."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from check_v0218_expansion import product_review_fixtures
from prepare_v0218_product_review import product_review
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
    spec = product_review()
    initial, revised, pending, _ = product_review_fixtures()
    assert initial["summary"]["counts"] == {"phase1": 2, "phase2": 1, "existing": 1, "pending": 0}
    assert revised["summary"]["counts"] == {"phase1": 3, "phase2": 0, "existing": 1, "pending": 0}
    world = World.create(tmp_path / "review.sqlite", "review", spec["public"])
    for target, row in initial.items():
        put(world, target, row, "initial")
    assert evaluate(world.snapshot())["status"] == "PASS"
    return world, spec, revised, pending


@pytest.mark.parametrize("omitted", ["feature_spec", "backlog", "timeline", "summary"])
def test_single_unsynchronized_artifact_prevents_full_success(tmp_path, omitted):
    world, spec, revised, _ = populated(tmp_path)
    world.publish(event_id="authorized-change", current=spec["variants"]["superseded"])
    for target, row in revised.items():
        if target != omitted:
            put(world, target, row, "partial")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    put(world, omitted, revised[omitted], "complete")
    assert evaluate(world.snapshot())["status"] == "PASS"


@pytest.mark.parametrize("artifact", ["feature_spec", "backlog", "timeline"])
@pytest.mark.parametrize("mutation", ["missing", "old", "negation", "phase", "type", "foreign"])
def test_each_replica_requires_full_correct_feature_relations(tmp_path, artifact, mutation):
    world, _, _, _ = populated(tmp_path)
    row = copy.deepcopy(world.snapshot()["records"][artifact])
    if mutation == "missing":
        row["features"].pop("F-204")
    elif mutation == "old":
        row["features"]["F-204"]["status"] = "launched"
    elif mutation == "negation":
        row["features"]["F-203"]["priority"] = "not P2"
    elif mutation == "phase":
        row["features"]["F-204"]["phase"] = "phase1"
    elif mutation == "type":
        row["features"]["F-203"]["priority"] = ["P2", "P1"]
    else:
        row["features"]["F-OTHER"] = row["features"]["F-203"]
    row.pop("object_id")
    put(world, artifact, row, "bad")
    assert evaluate(world.snapshot())["status"] == "FAIL"


@pytest.mark.parametrize("value", [4, "2", True, 2.0, None])
def test_summary_counts_are_typed_and_exclude_existing_features(tmp_path, value):
    world, _, _, _ = populated(tmp_path)
    state = world.snapshot()
    state["records"]["summary"]["counts"]["phase1"] = value
    assert evaluate(state)["status"] == "FAIL"


def test_pending_decision_preserves_known_features_and_requires_real_question(tmp_path):
    world, spec, _, pending = populated(tmp_path)
    world.publish(event_id="pending", current=spec["variants"]["unresolved"])
    for target, row in pending.items():
        put(world, target, row, "pending")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    world.act(
        operation_id="clarify",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="backlog",
        data={"question": "Please resolve the approved phase/priority for F-203."},
    )
    assert evaluate(world.snapshot())["status"] == "PASS"


def test_irrelevant_notice_and_dictionary_order_do_not_change_work(tmp_path):
    world, spec, _, _ = populated(tmp_path)
    world.publish(event_id="team-building", current=spec["variants"]["irrelevant"])
    state = world.snapshot()
    for target in ("feature_spec", "backlog", "timeline"):
        state["records"][target]["features"] = dict(
            reversed(state["records"][target]["features"].items())
        )
    assert evaluate(state)["status"] == "PASS"
    state["records"]["summary"]["total"] = "4"
    assert evaluate(state)["status"] == "FAIL"


def test_artifact_scope_rename_and_needless_clarification(tmp_path):
    world, _, _, _ = populated(tmp_path)
    state = world.snapshot()
    state["objects"][0] = "renamed-spec"
    state["policy"]["artifact_roles"]["renamed-spec"] = state["policy"]["artifact_roles"].pop(
        "feature_spec"
    )
    state["records"]["renamed-spec"] = state["records"].pop("feature_spec")
    state["records"]["renamed-spec"]["object_id"] = "renamed-spec"
    assert evaluate(state)["status"] == "PASS"
    world.act(
        operation_id="needless",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="backlog",
        data={"question": "Should we follow the approved phase decision?"},
    )
    assert evaluate(world.snapshot())["status"] == "FAIL"

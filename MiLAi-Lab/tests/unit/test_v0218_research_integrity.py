"""Raw-sample statistics, selected-vs-best runs, and complete adverse-result reporting."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from check_v0218_expansion import research_integrity_fixtures
from prepare_v0218_research_integrity import research_integrity
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
    spec = research_integrity()
    initial, revised, pending, _ = research_integrity_fixtures()
    world = World.create(tmp_path / "research.sqlite", "research", spec["public"])
    for target, row in initial.items():
        put(world, target, row, "initial")
    assert evaluate(world.snapshot())["status"] == "PASS"
    return world, spec, revised, pending


@pytest.mark.parametrize(
    "field,value",
    [
        ("mean", 74.8),
        ("mean", 75.1),
        ("mean", "74.73"),
        ("mean", [74.73, 74.8]),
        ("mean", float("nan")),
        ("sample_std", 0.33),
        ("sample_std", 0),
        ("paper_value", 75.1),
        ("best_sample_value", 74.8),
        ("paper_seed", 7),
        ("paper_seed", "42"),
        ("seed_count", True),
        ("seed_count", 3.0),
        ("seed_count", 2),
    ],
)
def test_distinct_statistics_not_best_seed_or_population_std(tmp_path, field, value):
    world, _, _, _ = populated(tmp_path)
    state = world.snapshot()
    state["records"]["seed_statistics"][field] = value
    assert evaluate(state)["status"] == "FAIL"


def test_tuned_values_preserve_all_metrics_and_adverse_signed_gaps(tmp_path):
    world, spec, revised, _ = populated(tmp_path)
    world.publish(event_id="tuned", current=spec["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    put(world, "backbone_comparison", revised["backbone_comparison"], "update")
    assert evaluate(world.snapshot())["status"] == "PASS"
    assert revised["backbone_comparison"]["rows"][2]["gap"] == -8.3


@pytest.mark.parametrize(
    "mutation",
    ["omit_bad", "duplicate", "metric", "sign", "pilot", "type", "foreign", "missing_field"],
)
def test_complete_reporting_not_partial_keywords(tmp_path, mutation):
    world, spec, revised, _ = populated(tmp_path)
    world.publish(event_id="tuned", current=spec["variants"]["superseded"])
    row = copy.deepcopy(revised["backbone_comparison"])
    if mutation == "omit_bad":
        row["rows"].pop(2)
    elif mutation == "duplicate":
        row["rows"][2] = copy.deepcopy(row["rows"][0])
    elif mutation == "metric":
        row["rows"][2]["metric"] = "Accuracy"
    elif mutation == "sign":
        row["rows"][2]["gap"] = 8.3
    elif mutation == "pilot":
        row["rows"][0].update(value=70.2, gap=-4.6, run_basis="pilot")
    elif mutation == "type":
        row["rows"][2]["value"] = "58.9"
    elif mutation == "foreign":
        row["rows"][2]["dataset"] = "OTHER"
    else:
        del row["rows"][2]["reference_value"]
    put(world, "backbone_comparison", row, "bad")
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_pending_single_result_does_not_erase_other_known_results(tmp_path):
    world, spec, _, pending = populated(tmp_path)
    world.publish(event_id="pending", current=spec["variants"]["unresolved"])
    put(world, "backbone_comparison", pending["backbone_comparison"], "withhold")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    world.act(
        operation_id="clarify",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="backbone_comparison",
        data={"question": "Please verify the pending tuned RefCOCO F1 result."},
    )
    assert evaluate(world.snapshot())["status"] == "PASS"
    state = world.snapshot()
    state["records"]["backbone_comparison"]["rows"][2]["value"] = 58.9
    assert evaluate(state)["status"] == "FAIL"


def test_seed_order_and_unrelated_paper_do_not_change_statistics(tmp_path):
    world, spec, _, _ = populated(tmp_path)
    world.publish(event_id="other", current=spec["variants"]["irrelevant"])
    state = world.snapshot()
    state["current"]["seed_results"].reverse()
    assert evaluate(state)["status"] == "PASS"
    state["objects"][0] = "renamed-stats"
    state["policy"]["statistics_object"] = "renamed-stats"
    state["records"]["renamed-stats"] = state["records"].pop("seed_statistics")
    state["records"]["renamed-stats"]["object_id"] = "renamed-stats"
    assert evaluate(state)["status"] == "PASS"


def test_missing_statistics_fields_and_needless_pause_fail(tmp_path):
    world, _, _, _ = populated(tmp_path)
    for field in (
        "mean",
        "sample_std",
        "paper_seed",
        "paper_value",
        "best_sample_value",
        "seed_count",
    ):
        state = world.snapshot()
        del state["records"]["seed_statistics"][field]
        assert evaluate(state)["status"] == "FAIL"
    world.act(
        operation_id="needless",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="seed_statistics",
        data={"question": "Should we use these known three seeds?"},
    )
    assert evaluate(world.snapshot())["status"] == "FAIL"

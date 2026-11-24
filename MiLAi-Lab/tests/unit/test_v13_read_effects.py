"""A material increase can have a lower continuation cost; missing rewards stay masked."""

import importlib
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    return importlib.import_module("report_memory_control_v13_read_effects")


def test_expensive_subset_uses_total_cost_and_observed_native_quality(monkeypatch):
    m = module(monkeypatch)
    base = dict(
        source="src",
        native_group="g",
        first_packet_differs=True,
        first_ranges_differ=True,
        terminal_wire_differs=False,
        independent_terminal_responses=False,
        immediate_tokens_delta=100,
    )
    measured = [
        dict(base, quality_delta=q, future_cost_delta=f, total_cost_delta=c)
        for q, f, c in ((0.0, -100, 0.0), (-0.1, -30, 70.0), (None, 10, 110.0), (0.2, None, None))
    ]
    summary = m.summarize_levels(measured, {"src": Counter(roots=4), "no_pairs": Counter(roots=2)})
    assert summary["src"]["expensive_without_quality_gain_all"] == m.rate(1, 2)
    assert summary["src"]["no_quality_gain_given_higher_total_cost"] == m.rate(1, 1)
    assert summary["src"]["missing_quality"] == summary["src"]["missing_future_cost"] == 1
    assert summary["no_pairs"]["first_packet_difference"]["rate"] is None


def test_partial_or_unavailable_interval_does_not_complete_bridge(monkeypatch):
    m = module(monkeypatch)
    obj = SimpleNamespace(id=5, body="abcdef")
    pool = SimpleNamespace(by_ref={"s": obj}, objects={5: obj})

    def span(a, b):
        return dict(source_ref="s", source_revision=1, start=a, end=b)

    item = dict(
        visibility="visible",
        body_delivered=True,
        source_ranges=[span(0, 6)],
        unavailable_source_ranges=[span(2, 4)],
    )
    env = SimpleNamespace(pool=pool, ops=SimpleNamespace(opened={0: item}))
    assert m.ranges(env) == [(5, 0, 2), (5, 4, 6)]
    assert not m.full_objects(m.ranges(env), pool, {5})
    env.ops.opened[1] = {**item, "source_ranges": [span(2, 4)], "unavailable_source_ranges": []}
    assert m.full_objects(m.ranges(env), pool, {5}) == {5}


def test_settlement_uses_current_targets_and_six_matched_cpu_deployments(tmp_path, monkeypatch):
    import json

    import pytest

    m = module(monkeypatch)
    driver = importlib.import_module("settle_memory_control_v13_round")

    def save(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj))

    cohort = {
        "role": "dev",
        "v13_role": "curve",
        "material_budget": 2048,
        "dataset_run_id": "r",
        "tasks": [1, 2],
        "dataset_path": str(tmp_path / "db"),
    }
    save(tmp_path / "rosters/curve-2048.json", cohort)
    points = {}
    paths = {}
    for method in (*driver.METHODS, "rule", "gte-batch8"):
        path = tmp_path / "eval" / method
        arm = {"name": method, "environment": "qrag_milai_v13"}
        save(
            path / "protocol.json",
            {"population": cohort, "comparison": {"reader": "frozen"}, "arm": arm},
        )
        save(path / "run.json", {"status": "COMPLETED"})
        paths[method] = path
        if method in driver.METHODS:
            points[method] = dict(cohort=cohort, deployment={"arm": arm})
    dirs = []
    for method, sampler in (("PQ-U", "uniform"), ("PQ-A", "structured")):
        path = tmp_path / "collection" / f"{method}-12000"
        prev = tmp_path / "weights" / f"{method}-6000"
        save(
            driver.point_path(tmp_path, method, 11, 6000),
            dict(deployment={"arm": {"checkpoint": str(prev)}}),
        )
        save(
            path / "round.json",
            dict(
                continuation_mode="full_episode",
                continuation_policy_id=str(prev),
                dataset_run="r",
                material_budget=2048,
                round=2,
                seed=11,
                sampler=sampler,
            ),
        )
        save(path / "progress.json", dict(state="complete", feedback_calls=6000))
        points[method]["acquisition_paths"] = ["warm", f"{method}-six", str(path)]
        dirs.append(path)
    points["DQ"]["acquisition_paths"] = points["PQ-U"]["acquisition_paths"]
    seen = []

    def invoke(argv, *, check, env):
        seen.append(argv)
        assert check and env["CUDA_VISIBLE_DEVICES"] == ""
        assert [v for i, v in enumerate(argv) if i and argv[i - 1] == "--collection"] == list(
            map(str, dirs)
        )
        arms = [Path(v) for i, v in enumerate(argv) if i and argv[i - 1] == "--arm"]
        assert set(arms) == set(paths.values())
        out = Path(argv[argv.index("--output") + 1])
        save(
            out,
            dict(
                dataset_run="r",
                new_reader_requests=0,
                collections=[
                    dict(
                        source_directory=str(d),
                        continuation=m.read_json(d / "round.json")["continuation_policy_id"],
                        data_role="train",
                        root_count=1,
                        by_source={},
                        observations=[],
                    )
                    for d in dirs
                ],
                dev=[dict(run=str(a), total_registered_tasks=2) for a in arms],
            ),
        )

    monkeypatch.setattr(driver.subprocess, "run", invoke)
    result = driver.settle_read_effects(tmp_path, 11, 12000, points, paths)
    assert result["train_level_effects"]["DQ"]["same_outcomes_as"] == "PQ-U"
    assert result["train_level_effects"]["QR"]["status"] == "unmeasured_single_online_trajectory"
    assert len(result["native_dev_bridge_effects"]) == 6
    cfg = m.read_json(dirs[1] / "round.json")
    cfg["continuation_policy_id"] = str(tmp_path / "other-policy")
    save(dirs[1] / "round.json", cfg)
    with pytest.raises(ValueError, match="own continuation"):
        driver.settle_read_effects(tmp_path, 11, 12000, points, paths)
    assert len(seen) == 1


def test_budget_witness_preserves_unknown_and_tracks_exact_tasks(monkeypatch):
    import pytest

    module(monkeypatch)
    m = importlib.import_module("diagnose_memory_control_v13_recall")
    base = dict(
        source="s",
        group="g",
        annotation_status="text",
        complete_annotation_sets=1,
        host_ready=True,
        reachable=True,
        material_tokens=123,
    )
    low = [
        dict(base, task=1, delivered=True),
        dict(base, task=2, delivered=False),
        dict(base, task=3, delivered=None, complete_annotation_sets=0, annotation_status="missing"),
    ]
    high = [dict(low[0], delivered=False), dict(low[1], delivered=True), low[2]]
    summary = m.coverage_summary(low)
    assert summary["registered_tasks"] == 3 and summary["tasks_with_complete_annotation"] == 2
    assert summary["complete_sets_delivered_tasks"] == 1 and summary["delivered_over_known"] == 0.5
    assert summary["material_tokens_all_ready"]["total"] == 369
    changes = m.budget_changes({512: low, 1024: high, 2048: high})
    assert changes["512_to_1024"]["s"] == {
        "retained": 0,
        "gained": 1,
        "lost": 1,
        "neither": 0,
        "unknown_or_unannotated": 1,
    }
    assert changes["1024_to_2048"]["s"]["lost"] == changes["1024_to_2048"]["s"]["gained"] == 0
    with pytest.raises(ValueError, match="Mismatched task"):
        m.budget_changes({512: low, 1024: list(reversed(high))})

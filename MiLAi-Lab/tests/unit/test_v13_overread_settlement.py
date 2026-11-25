"""Exercise the read-only 6k comparison with synthetic checkpoints and an in-process scorer."""

import json
from collections import Counter
from pathlib import Path

import pytest


def test_settlement_reuses_bound_readouts_and_rejects_a_different_acquisition(
    tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    import memory_control_v13_overread as tool

    root = tmp_path
    roster = {"role": "dev", "dataset_run_id": "fixture"}
    tool.write_json(root / "rosters/curve-2048.json", roster)
    support = {
        "source": {
            axis: Counter(negative=1, tie=1, pairs=1, flips=0) for axis in ("quality", "utility")
        }
    }
    monkeypatch.setattr(
        tool,
        "capture_inputs",
        lambda _: ({"registration": {"dataset_run_id": "fixture"}, "roots": []}, support),
    )
    monkeypatch.setattr(tool, "load_host_cost_scale", lambda *a, **kw: (tool.SCALE, None))
    monkeypatch.setattr(tool, "require_same_host_cost_scale", lambda *a: None)
    warm = root / "warm-11"
    uniform = root / "collection/a11-PQ-U-6000"
    for stage, source, count in ((0, warm, 2000), (1, uniform, 4000)):
        tool.write_json(
            source / "round.json",
            dict(
                sampler="uniform",
                dataset_run="fixture",
                seed=11,
                round=stage,
                continuation_policy_id=tool.TARGET,
                material_budget=2048,
                utility_lambda=tool.PENALTY,
                exclude_roots_from=[str(warm)] if stage else [],
            ),
        )
        tool.write_json(source / "progress.json", dict(state="complete", feedback_calls=count))

    def score(checkpoint, stage):
        stats = {}
        for stem in ("", "_utility"):
            for mode in ("original", "swapped"):
                stats[mode + stem + "_two_action_regret"] = dict(n=2, mean=0.25)
                stats[mode + stem + "_read_on_profitable_stop"] = dict(n=1, mean=1.0)
        return dict(
            checkpoint=str(checkpoint),
            fit_target=[stage, tool.TARGET],
            matched_continuation=True,
            measured_continuation=tool.TARGET,
            cost_scale=tool.SCALE,
            utility_lambda=tool.PENALTY,
            sources={"source": stats},
            overread_utility_error={
                "source": {
                    m: {
                        "n": 1,
                        "mean": {
                            "net_gain_error": 0.5,
                            "quality_gain_error": 0.3,
                            "cost_underestimate_contribution": 0.2,
                        },
                    }
                    for m in ("original", "swapped")
                }
            },
        )

    points, warm_scores = {}, {}
    origin = root / "s1/checkpoint"
    origin.mkdir(parents=True)
    for method, obj in tool.OBJECTIVES.items():
        parent = origin
        for stage, source in enumerate((warm, uniform)):
            ck = root / f"{obj}-{stage}/checkpoint"
            ck.mkdir(parents=True)
            (ck / "control.pt").touch()
            identity = {"id": f"fixture-{obj}-{stage}"}
            contract = dict(
                seed=11,
                supervision_mode=obj,
                probe=False,
                cost_scale=tool.SCALE,
                target=[stage, tool.TARGET],
                input=str([source / "packs"]),
                scale_source=None,
                parent=str(parent),
            )
            tool.write_json(
                ck.parent / "run.json",
                dict(
                    status="completed",
                    reload_scores_equal=True,
                    fit_identity=identity,
                    optimizer_updates=3,
                    contract=contract,
                ),
            )
            tool.write_json(
                ck / "fit_completion.json",
                dict(fit_identity=identity, summary={"optimizer_updates": 3}),
            )
            if stage == 0:
                warm_scores[obj] = score(ck, stage)
                tool.write_json(root / f"evidence-diagnostic/warm-11-{obj}.json", warm_scores[obj])
            else:
                arm = {"checkpoint": str(ck)}
                dev = root / f"evaluation-{method}"
                tool.write_json(dev / "protocol.json", {"arm": arm, "population": roster})
                tool.write_json(dev / "run.json", {"status": "COMPLETED"})
                points[method] = dict(
                    method=method,
                    fit_seed=11,
                    acquisition_seed=11,
                    cohort=roster,
                    usage={"exposure": 6000},
                    acquisition_paths=[str(warm), str(uniform)],
                    deployment=dict(path=str(dev), arm=arm),
                )
            parent = ck
    before = tool.summarize_scores(warm_scores, support)
    tool.write_json(root / "evidence-diagnostic/warm-11-direct-vs-paired.json", dict(axes=before))
    calls = []

    def fake_score(directory, checkpoint, path):
        calls.append(checkpoint)
        tool.write_json(path, score(checkpoint, 1))

    monkeypatch.setattr(tool, "cpu_score", fake_score)
    result = tool.settle_overread(root, 11, points)
    assert len(calls) == 2
    assert (
        json.loads(result.read_text())["change_6k_minus_2k"]["utility"]["original"]["paired"][
            "overread"
        ]["numerator"]
        == 0
    )
    assert tool.settle_overread(root, 11, points) == result and len(calls) == 2
    cached = result.parent / "direct.json.gz"
    row = tool.read_gzip(cached)
    row["score"]["overread_utility_error"] = {}
    tool.write_gzip(cached, row)
    assert tool.settle_overread(root, 11, points) == result and len(calls) == 3
    points["DQ"]["acquisition_paths"] = [str(uniform)]
    with pytest.raises(ValueError, match="closed 6k"):
        tool.settle_overread(root, 11, points)
    assert len(calls) == 3

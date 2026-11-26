"""Exercise S4 dispatch and accounting with synthetic files and no model or Reader."""

from __future__ import annotations

import gzip
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def dump(path, value):
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def driver(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    return importlib.import_module("run_memory_control_v13_rounds")


def setup_args(root, seed=29):
    return SimpleNamespace(
        root=root,
        weights=root / "weights",
        s1=root / "s1",
        curve=root / "curve.json",
        dataset=root / "data",
        warm=root / f"warm-{seed}",
        acquisition_seed=seed,
        fit_seed=11,
        until=12000,
        acquisition_repeat=True,
        frozen_data=False,
        refit_only=False,
        refit_method=None,
        recipe={
            "warm_feedback_calls": 2000,
            "feedback_checkpoints": [6000, 12000, 24000],
            "cost_scale_report": "unit.json",
            "environment": {"gamma": 1.0},
            "observation": "legal",
            "memory_budget_tokens": 2048,
            "utility_lambda": 0.05,
            "eligible_pool_window": 8,
        },
    )


def make_primary(driver, args, monkeypatch):
    from milai_lab.methods import control_cost_scale

    monkeypatch.setattr(
        control_cost_scale, "load_host_cost_scale", lambda *a, **kw: (3.0, {"scale": 3.0})
    )
    monkeypatch.setattr(control_cost_scale, "require_same_host_cost_scale", lambda p, c: None)
    args.s1.mkdir(parents=True)
    (args.s1 / "control.pt").touch()
    cohort = {"role": "dev", "v13_role": "curve", "material_budget": 2048, "tasks": [1, 2]}
    dump(args.curve, cohort)
    dump(
        args.root / "fits/a11-f11-warm-paired/run.json",
        {"contract": {"parent": str(args.s1), "scale_source": {"scale": 3.0}}},
    )
    dump(args.root / "fits/a11-f11-recipe.json", args.recipe)
    dump(args.root / "warm-11/round.json", {"dataset_run": "ds", "reader": "reader"})
    common = args.root / "common-pool"
    common.touch()
    for point in (6000, 12000):
        checkpoints = {}
        for method in ("PQ-U", "PQ-A"):
            data = args.root / "collection" / (method + "-6000")
            dump(data / "mechanism-pool.json", {"common_pool": str(common)})
            readout = args.root / "primary-readouts" / f"{method}-{point}"
            dump(readout / "run.json", {"status": "COMPLETED"})
            saved = args.root / "primary-points" / f"{method}-{point}.json"
            dump(
                saved,
                {
                    "method": method,
                    "usage": {"exposure": point},
                    "fit_seed": 11,
                    "acquisition_seed": 11,
                    "cohort": cohort,
                    "acquisition_paths": [str(args.root / "warm-11"), str(data)],
                    "deployment": {"path": str(readout)},
                },
            )
            checkpoints[method] = str(saved)
        dump(
            args.root / f"dev-review-a11-{point}.json",
            {
                "phase": "fixed_pool_mechanism" if point == 6000 else "natural_policy_iteration",
                "acquisition_seed": 11,
                "fitting_seed": 11,
                "cumulative_feedback_per_learning_arm": point,
                "checkpoints": checkpoints,
                "quality_contrasts": {
                    "PQ-A vs PQ-U": {
                        "quality_delta_points": -0.5 if point == 6000 else 0.4,
                        "quality_interval_95": [-1.1, 1.3],
                        "difference_range_given_unobserved": [-0.6, 0.5],
                        "source_strata": {},
                    }
                },
            },
        )


def test_repeat_uses_one_new_warm_two_arms_shared_pi0_and_distinct_online_policies(
    tmp_path, driver, monkeypatch
):
    args = setup_args(tmp_path)
    make_primary(driver, args, monkeypatch)
    collected = []
    fits = []
    evals = []
    points = []
    budgets = []
    contrasts = []

    mechanism = args.root / "mechanism-a29-f11-6000.json"
    common_pool = args.warm / "mechanism-pool-2901.json.gz"

    def collect(a, directory, calls, stage, mode, prior=None, sampler=None, shared=None):
        if stage == 2:
            review = driver.json_file(mechanism)
            assert review["later_collection_already_registered"] is False
            assert review["active_minus_uniform"] == {"quality_delta_points": -1.25}
        collected.append((directory, calls, stage, mode, prior, sampler, shared))
        dump(
            directory / "round.json",
            dict(
                dataset_run="ds",
                reader="reader",
                environment=a.recipe["environment"],
                material_budget=2048,
                observation="legal",
                seed=a.acquisition_seed,
                round=stage,
                sampler=mode,
                continuation_policy_id=str(prior) if prior else "pi0-fixedcontext-4",
                sampling_checkpoint=str(sampler) if sampler else None,
            ),
        )
        if stage == 1:
            if not common_pool.is_file():
                with gzip.open(common_pool, "wt") as stream:
                    json.dump({"dataset_run": "ds", "seed": 2901, "available": {}}, stream)
            dump(directory / "mechanism-pool.json", {"common_pool": str(common_pool)})

    def fit(a, name, data, parent, objective, scale):
        fits.append((name, data, parent, objective))
        directory = a.weights / name
        dump(
            directory / "run.json",
            dict(
                status="completed",
                contract={
                    "parent": str(parent),
                    "supervision_mode": objective,
                },
            ),
        )
        return directory / "checkpoint"

    def publish_point(point):
        points.append(point)
        dump(
            point.output,
            dict(
                method=point.method,
                cohort=driver.json_file(args.curve),
                acquisition_seed=point.acquisition_seed,
                fit_seed=point.fit_seed,
                acquisition_paths=list(map(str, point.rollouts)),
                fit_paths=list(map(str, point.fits)),
                usage={"exposure": point.calls},
                deployment={"path": str(point.evaluation)},
            ),
        )

    def contrast(active, uniform, repeats):
        assert Path(active["path"]).name == "a29-f11-PQ-A-6000"
        assert Path(uniform["path"]).name == "a29-f11-PQ-U-6000"
        contrasts.append(repeats)
        return {"quality_delta_points": -1.25}

    monkeypatch.setattr(driver, "collect", collect)
    monkeypatch.setattr(driver, "fit", fit)
    monkeypatch.setattr(driver, "exposure", lambda _: 2000)
    monkeypatch.setattr(driver, "evaluate", lambda a, n, c: evals.append(n))
    monkeypatch.setattr(driver, "repeat_accounting", lambda a, r, n: budgets.append(n))
    import report_memory_control_v13_curves

    monkeypatch.setattr(report_memory_control_v13_curves, "point", publish_point)
    monkeypatch.setattr("report_memory_control_v13_deployment.paired_dev_contrast", contrast)
    driver.round_matrix(args)
    assert [v[1] for v in collected] == [2000, 4000, 4000, 6000, 6000]
    assert [v[3] for v in collected] == [
        "uniform",
        "uniform",
        "structured",
        "uniform",
        "structured",
    ]
    assert collected[0][0] == tmp_path / "warm-29" and all(
        x[4:] == (None, None, None) for x in collected[:2]
    )
    assert (
        collected[2][4] is None
        and collected[2][5] == args.weights / "a29-f11-warm-paired/checkpoint"
    )
    assert collected[2][6] == collected[1][0]
    assert collected[3][4] == args.weights / "a29-f11-PQ-U-6000/checkpoint"
    assert collected[4][4] == collected[4][5] == args.weights / "a29-f11-PQ-A-6000/checkpoint"
    assert len(fits) == 5 and all(x[3] == "paired" for x in fits)
    assert len(evals) == len(points) == 4 and budgets == [6000, 12000]
    review = driver.json_file(mechanism)
    assert (review["acquisition_seed"], review["fit_seed"]) == (29, 11)
    assert review["common_pool"] == str(common_pool)
    assert review["common_warm"] == str(args.warm)
    assert review["additional_reader_calls"] == 0 and contrasts == [5000]
    registration = driver.json_file(tmp_path / "repeats/a29-f11-registration.json")
    assert registration["evaluated_evidence"]["6000"]["quality_delta_points"] < 0


@pytest.mark.parametrize(
    "change",
    [
        {"acquisition_seed": 11},
        {"fit_seed": 29},
        {"until": 24000},
        {"frozen_data": True},
        {"refit_only": True},
    ],
)
def test_invalid_repeat_fails_before_any_collection(tmp_path, driver, change):
    args = setup_args(tmp_path)
    for k, v in change.items():
        setattr(args, k, v)
    with pytest.raises(ValueError, match="Independent acquisition repeats"):
        driver.register_acquisition_repeat(args)


def test_combined_budget_counts_shared_warm_once_and_preserves_eval_separation(tmp_path, driver):
    for i, seed in enumerate((29, 47)):
        args = setup_args(tmp_path, seed)
        rollouts = {}
        pos = i * 22000
        dirs = [tmp_path / f"warm-{seed}"] + [
            tmp_path / f"{seed}-{x}" for x in ("U-6", "A-6", "U-12", "A-12")
        ]
        for folder, n in zip(dirs, (2000, 4000, 4000, 6000, 6000), strict=True):
            rec = folder / "receipts"
            rec.mkdir(parents=True)
            with gzip.open(rec / "synthetic-aggregate.json.gz", "wt") as f:
                json.dump(
                    dict(
                        actual_requests=n,
                        feedback_exposure=n,
                        ledger_before=pos,
                        ledger_after=pos + n,
                    ),
                    f,
                )
            pos += n
        rollouts = {"PQ-U": [dirs[0], dirs[1], dirs[3]], "PQ-A": [dirs[0], dirs[2], dirs[4]]}
        driver.repeat_accounting(args, rollouts, 12000)
    combined = driver.json_file(tmp_path / "repeats/acquisition-29-47-accounting.json")
    assert combined["arm_exposure"] == 48000 and combined["known_unique_new_requests"] == 44000
    assert combined["evaluation_charged_separately"]


def test_stage_zero_collect_dispatches_seed_specific_uniform_without_prior(
    tmp_path, driver, monkeypatch
):
    args = setup_args(tmp_path, 47)
    commands = []
    monkeypatch.setattr(driver, "run", lambda *v: commands.append(v))
    monkeypatch.setattr(driver, "exposure", lambda _: 2000)
    driver.collect(args, args.warm, 2000, 0, "uniform")
    (argv,) = commands
    assert argv[0] == "control_policy_iteration"
    for key, value in (
        ("--output", args.warm),
        ("--seed", 47),
        ("--round", 0),
        ("--window", 1),
        ("--calls", 2000),
    ):
        assert argv[argv.index(key) + 1] == value
    assert not {
        "--pool-seed",
        "--reuse-from",
        "--sampler-checkpoint",
        "--continuation-checkpoint",
        "--exclude-roots-from",
    }.intersection(argv)


def test_mismatched_mechanism_pool_fails_before_dispatch(tmp_path, driver, monkeypatch):
    args = setup_args(tmp_path)
    make_primary(driver, args, monkeypatch)
    other = tmp_path / "different-pool"
    other.touch()
    dump(tmp_path / "collection/PQ-A-6000/mechanism-pool.json", {"common_pool": str(other)})
    monkeypatch.setattr(
        driver, "collect", lambda *a: pytest.fail("paid acquisition before evidence")
    )
    with pytest.raises(ValueError, match="same frozen TRAIN pool"):
        driver.round_matrix(args)

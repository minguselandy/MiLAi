"""Frozen-data fitting cannot dispatch a new label or accidentally train another acquisition arm."""

from __future__ import annotations

import gzip
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_curve_billing_separates_shared_imported_and_unpriced_feedback(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    feedback = importlib.import_module("report_memory_control_v13_feedback")
    (tmp_path / "receipts").mkdir()
    (tmp_path / "round.json").write_text(
        json.dumps(dict(round=0, sampler="uniform", continuation_policy_id="pi0"))
    )

    def record(name, actual, start, source):
        item = dict(
            receipt_id=name,
            actual_requests=actual,
            feedback_exposure=1 if actual is None else max(actual, 1),
            ledger_before=start,
            ledger_after=start + (actual or 0),
            status="scored",
            costs=dict(reader_usage_source=source, reader_input_tokens=100, reader_output_tokens=3),
        )
        with gzip.open(tmp_path / "receipts" / (name + ".json.gz"), "wt") as f:
            json.dump(item, f)

    record("paid", 1, 10, "provider")
    record("imported", 0, 11, "provider")
    shared = feedback.report([tmp_path, tmp_path])
    assert shared["total_feedback_exposure"] == 4
    assert shared["newly_billed_usage"] == dict(
        billed_reader_calls=1,
        billed_reader_input_tokens=100,
        billed_reader_output_tokens=3,
        billed_reader_tokens=103,
    )
    record("local_estimate", 1, 11, "local_tokenizer")
    unpriced = feedback.report([tmp_path])["newly_billed_usage"]
    assert unpriced["billed_reader_calls"] == 2 and unpriced["billed_reader_tokens"] is None
    record("local_estimate", 2, 11, "provider")
    retried = feedback.report([tmp_path])["newly_billed_usage"]
    assert retried["billed_reader_calls"] == 3 and retried["billed_reader_tokens"] is None
    record("unknown", None, 13, None)
    assert feedback.report([tmp_path])["newly_billed_usage"]["billed_reader_calls"] is None


def test_curve_gpu_hours_preserve_interrupted_windows_as_lower_bounds(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    curves = importlib.import_module("report_memory_control_v13_curves")
    fit, rollout = tmp_path / "fit", tmp_path / "rollout"
    (fit / "fit-windows").mkdir(parents=True)
    (rollout / "compute").mkdir(parents=True)
    (fit / "fit-windows/fit.json").write_text(
        json.dumps(
            dict(
                state="returned",
                device_count=1,
                wall_seconds=3600,
                earlier_unmetered_fit=False,
                scope="single_gpu_fit_process_lifetime",
            )
        )
    )
    (rollout / "round.json").write_text(
        json.dumps(
            dict(
                sampling_checkpoint="warm",
                continuation_policy_id="pi0-fixedcontext-4",
            )
        )
    )
    unfinished = rollout / "compute/first.json"
    unfinished.write_text(
        json.dumps(
            dict(
                controller_devices=["cuda:0"],
                controller_gpu_residency_hours=0.25,
                complete_invocation=False,
            )
        )
    )
    (rollout / "compute/second.json").write_text(
        json.dumps(
            dict(
                controller_devices=["cuda:0"],
                controller_gpu_residency_hours=0.5,
                complete_invocation=True,
            )
        )
    )
    legacy = tmp_path / "point.json"
    legacy.write_text(
        json.dumps(
            dict(
                usage={"acquisition_and_fit_gpu_hours": 1.75},
                acquisition_paths=[str(rollout)],
                fit_paths=[str(fit)],
            )
        )
    )
    usage = curves.read_curve_point(legacy)["usage"]
    assert usage["observed_acquisition_and_fit_gpu_hours"] == 1.75
    assert usage["acquisition_and_fit_gpu_hours"] is None
    assert usage["fit_job_window_gpu_hours"] == 1
    unfinished.write_text(
        json.dumps(
            dict(
                controller_devices=["cpu"],
                controller_gpu_residency_hours=0,
                complete_invocation=False,
            )
        )
    )
    assert curves.value_gpu_usage([rollout], [fit])["acquisition_and_fit_gpu_hours"] == 1.5
    update = dict(controller_gpu_residency_hours=2, earlier_incomplete_compute_invocations=1)
    assert curves.qr_gpu_usage(update)["acquisition_and_fit_gpu_hours"] is None
    assert curves.qr_gpu_usage(update)["observed_acquisition_and_fit_gpu_hours"] == 2
    update["earlier_incomplete_compute_invocations"] = 0
    assert curves.qr_gpu_usage(update)["acquisition_and_fit_gpu_hours"] == 2


def test_single_active_arm_frozen_refit_does_not_require_uniform_online_data(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    driver = importlib.import_module("run_memory_control_v13_rounds")
    args = SimpleNamespace(
        root=tmp_path,
        weights=tmp_path / "weights",
        s1=tmp_path / "s1/checkpoint",
        acquisition_seed=11,
        fit_seed=29,
        refit_method=["PQ-A"],
        frozen_data=True,
        refit_only=True,
        until=12,
        curve=tmp_path / "roster.json",
        recipe=dict(
            warm_feedback_calls=2,
            feedback_checkpoints=[6, 12],
            environment={"gamma": 1},
            observation="legal",
            memory_budget_tokens=30,
        ),
    )
    args.curve.write_text(json.dumps({"material_budget": 30}))
    warm = tmp_path / "warm-11"
    (warm / "packs").mkdir(parents=True)
    (warm / "round.json").write_text(
        json.dumps(
            dict(
                environment={"gamma": 1}, observation="legal", material_budget=30, sampler="uniform"
            )
        )
    )
    with gzip.open(warm / "packs/root.json.gz", "wt") as f:
        json.dump({"outcomes": [{"future_cost_observed": True, "future_cost": 77}]}, f)
    paid = {warm: 2}
    for stage, (point, n) in enumerate(((6, 4), (12, 6)), 1):
        pool = tmp_path / "collection" / f"a11-PQ-A-{point}"
        pool.mkdir(parents=True)
        (pool / "round.json").write_text(
            json.dumps(dict(sampler="structured", round=stage, seed=11))
        )
        paid[pool] = n
    fits = []

    def fit(a, name, data, parent, objective, scale):
        fits.append((data, parent, objective, scale))
        return a.weights / name / "checkpoint"

    monkeypatch.setattr(driver, "fit", fit)
    monkeypatch.setattr(driver, "exposure", lambda p: paid[p])
    monkeypatch.setattr(driver, "collect", lambda *args: pytest.fail("frozen repeat collected"))
    monkeypatch.setattr(driver, "evaluate", lambda *args: pytest.fail("fit-only issued readout"))
    driver.round_matrix(args)
    assert [f[0].name for f in fits] == ["warm-11", "a11-PQ-A-6", "a11-PQ-A-12"]
    assert [f[1].parent.name for f in fits] == ["s1", "a11-f29-warm-paired", "a11-f29-PQ-A-6"]
    assert {(f[2], f[3]) for f in fits} == {("paired", 77)}


def test_common_pool_comparison_closes_before_on_policy_collection(tmp_path, monkeypatch):
    from milai_lab.datasets.memory_control_report import write_json

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    driver = importlib.import_module("run_memory_control_v13_rounds")
    curves = importlib.import_module("report_memory_control_v13_curves")
    deploy = importlib.import_module("report_memory_control_v13_deployment")
    warm = tmp_path / "warm-11"
    common = warm / "common-pool.json"
    curve = tmp_path / "curve.json"
    measured = tmp_path / "mechanism-a11-f11-6.json"
    recipe = dict(
        environment={"gamma": 1},
        observation="legal",
        memory_budget_tokens=30,
        warm_feedback_calls=2,
        feedback_checkpoints=[6, 12],
    )
    args = SimpleNamespace(
        root=tmp_path,
        s1=tmp_path / "s1/checkpoint",
        weights=tmp_path / "weights",
        curve=curve,
        recipe=recipe,
        fit_seed=11,
        acquisition_seed=11,
        until=12,
        refit_method=None,
        refit_only=False,
        frozen_data=False,
    )
    write_json(common, {"tasks": [1, 2]})
    write_json(curve, {"material_budget": 30})
    write_json(
        warm / "round.json",
        dict(
            environment=recipe["environment"],
            observation="legal",
            material_budget=30,
            sampler="uniform",
        ),
    )
    (warm / "packs").mkdir()
    with gzip.open(warm / "packs/root.json.gz", "wt") as stream:
        json.dump({"outcomes": [{"future_cost_observed": True, "future_cost": 10}]}, stream)
    monkeypatch.setattr(driver, "exposure", lambda _: 2)
    monkeypatch.setattr(driver, "evaluate", lambda *a: None)

    def collect(args, path, calls, stage, mode, prior, sampler, shared):
        if stage == 2:
            assert driver.json_file(measured)["active_minus_uniform"] == {
                "quality_delta_points": -2
            }
        write_json(
            path / "round.json",
            dict(
                round=stage,
                sampler=mode,
                sampling_checkpoint=str(sampler) if sampler else None,
                continuation_policy_id=str(prior) if prior else "pi0-fixedcontext-4",
            ),
        )
        write_json(path / "mechanism-pool.json", {"common_pool": str(common)})

    def fit(args, name, data, parent, objective, scale):
        directory = args.weights / name
        write_json(
            directory / "run.json",
            dict(status="completed", contract=dict(parent=str(parent), supervision_mode=objective)),
        )
        return directory / "checkpoint"

    def save_point(record):
        write_json(
            record.output,
            dict(
                method=record.method,
                cohort=driver.json_file(curve),
                acquisition_paths=list(map(str, record.rollouts)),
                fit_paths=list(map(str, record.fits)),
                fit_seed=record.fit_seed,
                acquisition_seed=record.acquisition_seed,
                usage={"exposure": record.calls},
                deployment={"path": str(record.evaluation)},
            ),
        )

    monkeypatch.setattr(driver, "collect", collect)
    monkeypatch.setattr(driver, "fit", fit)
    monkeypatch.setattr(curves, "point", save_point)
    monkeypatch.setattr(deploy, "paired_dev_contrast", lambda a, b, n: {"quality_delta_points": -2})
    driver.round_matrix(args)
    result = driver.json_file(measured)
    assert result["later_collection_already_registered"] is False
    assert result["common_pool"] == str(common) and result["additional_reader_calls"] == 0
    assert (tmp_path / "collection/a11-PQ-A-12/round.json").is_file()


def test_reader_cost_rejects_two_new_claims_on_the_same_ledger_slot(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    tool = importlib.import_module("report_memory_control_v13_project_cost")

    def packet(name, actual_requests):
        folder = tmp_path / name / "receipts"
        folder.mkdir(parents=True)
        with gzip.open(folder / "test.json.gz", "wt") as f:
            json.dump(
                dict(
                    actual_requests=actual_requests,
                    ledger_before=9,
                    ledger_after=10,
                    status="scored",
                    measurement_reused_from="origin",
                    costs={},
                    reader_result={"response": {"id": "same-provider-response"}},
                ),
                f,
            )

    packet("original", 1)
    packet("reuse", 0)
    result = tool.aggregate(tmp_path)
    assert result["totals"]["settled_new_requests"] == 1
    assert result["totals"]["reused_results"] == 1
    packet("misbound", 1)
    with pytest.raises(ValueError, match="claimed twice"):
        tool.aggregate(tmp_path)


def test_training_only_shortlist_and_group_capped_refit_roster(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    tool = importlib.import_module("repeat_memory_control_v13_finalists")
    methods = {"DQ": 25.0, "PQ-U": 27.0, "PQ-A": 26.0, "rule": 25.5, "gte": 26.25, "QR": 27.5}
    parent = dict(
        role="dev",
        v13_role="tune",
        tasks=[
            {"dataset": s, "native_group": str(g), "task_id": 100 * j + 2 * g + i}
            for j, s in enumerate(("musique_full", "qasper", "personamem_v2"))
            for g in range(6)
            for i in range(2)
        ],
    )
    paths = {}
    for k in methods:
        paths[k] = tmp_path / k
        paths[k].mkdir()
        (paths[k] / "protocol.json").write_text(
            json.dumps(dict(population=parent, comparison={"reader": "fixed"}))
        )
    monkeypatch.setattr(tool, "roster", lambda root, seed: paths)

    def family(paths):
        name = paths[0].name
        return dict(
            arms=[dict(name=name, policy=name)],
            backbone="gte" if name not in {"rule", "QR"} else name,
            selection_score=methods[name],
        )

    monkeypatch.setattr(tool, "validate_dev_family", family)
    selection, _ = tool.freeze(tmp_path, 11)
    assert (selection["final"], selection["same_backbone"], selection["practical"]) == (
        "PQ-U",
        "gte",
        "QR",
    )
    subset = tool.whole_group_roster(parent, 19, 20261125, tmp_path / "parent.json")
    assert 0 < len(subset["tasks"]) <= 19 and len(subset["task_counts"]) == 3
    admitted = {(t["dataset"], t["native_group"]) for t in subset["tasks"]}
    assert subset["tasks"] == [
        t for t in parent["tasks"] if (t["dataset"], t["native_group"]) in admitted
    ]


def test_finite_observed_utility_includes_future_and_known_immediate_cost(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    tool = importlib.import_module("diagnose_memory_control_v13_evidence")
    labels = dict(
        handoff=dict(
            reader_quality=0.70,
            future_cost=100.0,
            immediate_cost=0.0,
            quality_observed=True,
            future_cost_observed=True,
        ),
        read=dict(
            reader_quality=0.74,
            future_cost=120.0,
            immediate_cost=80.0,
            quality_observed=True,
            future_cost_observed=True,
        ),
    )
    gains = tool.native_deltas(labels, "read", 0.05, 100.0)
    assert gains["quality"] == pytest.approx(0.04)
    assert gains["utility"] == pytest.approx(-0.01)
    labels["read"].update(future_cost=None, future_cost_observed=False)
    assert tool.native_deltas(labels, "read", 0.05, 100.0) == {"quality": pytest.approx(0.04)}
    assert tool.native_deltas(labels, "read", 0.0, 100.0)["utility"] == pytest.approx(0.04)
    labels["handoff"]["quality_observed"] = False
    assert tool.native_deltas(labels, "read", 0.05, 100.0) == {}


def test_sampling_signal_counts_regret_mass_and_common_direction_errors(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    tool = importlib.import_module("diagnose_memory_control_v13_evidence")
    observed = {"source": "qasper", "native_group": "paper"}
    flagged = dict(
        observed,
        numerator=0.2,
        finite_pair_regret=0.1,
        native_net_gap=-0.1,
        head_net_gaps=[-0.2, -0.1, 0.3, 0.4],
    )
    missed = dict(
        observed,
        numerator=0.0,
        finite_pair_regret=0.9,
        native_net_gap=-0.9,
        head_net_gaps=[0.2, 0.3, 0.4, 0.4],
    )
    report = tool.summarize_sampling_signal([flagged, missed])
    assert report["native_groups"] == 1 and report["positive_regret_states"] == 2
    assert (
        report["flagged_positive_regret_states"] == report["unflagged_errors_all_heads_wrong"] == 1
    )
    assert report["fraction_of_regret_flagged"] == pytest.approx(0.1)
    assert tool.summarize_sampling_signal([])["fraction_of_regret_flagged"] is None


def test_projections_require_unchanged_seed_and_whole_source_groups():
    from milai_lab.scorers.memory_control_episode_metrics import select_dev_records

    tasks = [dict(dataset="musique_full", native_group="g", task_id=i) for i in (1, 2)]
    pop = dict(
        role="dev",
        v13_role="tune",
        dataset_run_id="run",
        material_budget=2048,
        seed=11,
        tasks=tasks,
    )
    protocol = {"population": pop}
    packets = {1: {}, 2: {}}
    with pytest.raises(ValueError, match="whole native groups"):
        select_dev_records(protocol, packets, dict(pop, v13_role="curve", tasks=tasks[:1]))
    with pytest.raises(ValueError, match="Reader seed"):
        select_dev_records(protocol, packets, dict(pop, seed=12))
    bound, subset = select_dev_records(protocol, packets, dict(pop, v13_role="curve"))
    assert bound["population"]["v13_role"] == "curve" and subset == packets


def test_same_wire_repeat_requires_separate_actual_responses(tmp_path, monkeypatch):
    from milai_lab.scorers import memory_control_episode_metrics as metrics

    task = dict(dataset="qasper", native_group="paper", task_id=1)
    pop = dict(role="dev", v13_role="curve", tasks=[task], dataset_run_id="release", seed=11)
    proto = dict(arm={"policy": "fixed"}, comparison={}, population=pop)
    original, repeat = tmp_path / "first", tmp_path / "second"
    records = {}
    for path in (original, repeat):
        path.mkdir()
        (path / "protocol.json").write_text(json.dumps(proto))
        (path / "run.json").write_text(json.dumps({"status": "COMPLETED"}))
        records[path] = {
            **task,
            "reader_wire": {"seed": 11},
            "costs": {"reader_request_attempted": True},
            "reader_result": {"response": {"id": "replayed-response"}},
        }
    monkeypatch.setattr(metrics, "input_result", lambda p: (proto, {1: records[p]}))
    with pytest.raises(ValueError, match="distinct measured provider replies"):
        metrics.same_wire_dev_repeat(original, repeat, pop, repeats=5, seed=1)
    records[repeat]["reader_result"]["response"]["id"] = "another-response"
    records[repeat]["reader_wire"]["seed"] = 12
    with pytest.raises(ValueError, match="Reader input or decoding seed changed"):
        metrics.same_wire_dev_repeat(original, repeat, pop, repeats=5, seed=1)


def test_selected_repeats_keep_fit_and_acquisition_randomness_separate(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    tool = importlib.import_module("repeat_memory_control_v13_finalists")
    methods = ("PQ-A", "DQ", "QR")
    original = {k: tmp_path / "tune" / k for k in methods}
    arms = {
        k: dict(
            arms=[
                dict(
                    name=k,
                    seed=11,
                    policy="pretrained_checkpoint",
                    checkpoint=f"/original/{k}",
                    utility_lambda=0.1,
                )
            ]
        )
        for k in methods
    }
    selected = dict(final="PQ-A", same_backbone="DQ", practical="QR", families=arms)
    monkeypatch.setattr(tool, "freeze", lambda root, seed: (selected, original))
    calls = []
    monkeypatch.setattr(tool, "invoke", lambda script, *args: calls.append((script, list(args))))
    stages = []
    monkeypatch.setattr(tool, "mechanism_readouts", lambda *args: stages.append("mechanism"))

    def pop(*args):
        stages.append("allocate")
        return tmp_path / "s4/repeat-population.json"

    monkeypatch.setattr(tool, "repeat_population", pop)
    monkeypatch.setattr(
        tool, "evidence_fit", lambda root, init, seed: root / f"seed-{seed}" / "checkpoint"
    )
    seen = []

    def validate(paths, *, final, tune_subset):
        seen.append((len(paths), final))
        assert tune_subset == {"role": "dev"}

    monkeypatch.setattr(tool, "validate_dev_family", validate)
    (tmp_path / "s4").mkdir()
    (tmp_path / "s4/repeat-population.json").write_text('{"role":"dev"}')
    args = SimpleNamespace(
        root=tmp_path,
        weights=tmp_path / "weights",
        acquisition_seed=11,
        s1=tmp_path / "s1/checkpoint",
        dataset=tmp_path / "dataset",
    )
    spec = tool.repeat(args)
    assert stages == ["mechanism", "allocate"]
    fits = [argv for script, argv in calls if script == "run_memory_control_v13_rounds.py"]
    for seed, argv in zip((29, 47), fits, strict=True):
        assert "--frozen-data" in argv and "--refit-only" in argv
        assert (
            argv[argv.index("--acquisition-seed") + 1] == 11
            and argv[argv.index("--fit-seed") + 1] == seed
        )
        assert argv[argv.index("--s1") + 1] == tmp_path / f"seed-{seed}" / "checkpoint"
        assert [argv[i + 1] for i, x in enumerate(argv) if x == "--refit-method"] == ["PQ-A", "DQ"]
    evaluations = [
        argv for script, argv in calls if script == "run_memory_control_v13_evaluation.py"
    ]
    assert len(evaluations) == 4
    for argv in evaluations:
        arm = json.loads(Path(argv[argv.index("--arm") + 1]).read_text())
        assert arm["utility_lambda"] == 0.1 and arm["seed"] in (29, 47)
        assert argv[argv.index("--population") + 1] == tmp_path / "s4/repeat-population.json"
    assert spec["same_backbone"] == ["DQ"] and spec["practical"] == ["QR"]
    assert sorted(seen) == [(1, False), (3, False), (3, True)]

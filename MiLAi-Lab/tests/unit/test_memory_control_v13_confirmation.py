"""The V13 two-comparison family keeps missing infrastructure cost distinct from token counts."""

from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def native_fixture(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    tool = importlib.import_module("confirm_memory_control_v13")
    arms = [{"name": f"fit-{k}", "seed": k} for k in (11, 29, 47)]
    peer = {"name": "fixed"}
    tasks = []
    for source in tool.SOURCES:
        for group in ("a", "b"):
            for _ in range(2 if source == "musique_full" else 1):
                tasks.append({"dataset": source, "native_group": group, "task_id": len(tasks)})
    pop = {
        "role": "confirm",
        "confirmation_primary_comparisons": 2,
        "tasks": tasks,
        "arms": [*arms, peer],
        "confirmation_seeds": [11, 29, 47],
        "quality_noninferiority_points": 1.0,
        "reader_input_savings_floor": 0.15,
        "material_budget": 2048,
        "bootstrap_repeats": 160,
    }
    reg = {
        "final": "F",
        "families": {"F": {"arms": arms}, "B": {"arms": [peer]}},
        "peers": {"same_backbone": "B", "practical": "B"},
        "cost_field": "total_local_gpu_seconds",
        "cost_unit": "local_gpu_seconds",
        "family_one_sided_alpha": 0.025,
        "analysis_seed": 9,
        "max_reader_calls": 32,
        "run_directories": {a["name"]: a["name"] for a in pop["arms"]},
    }
    tool.save(tmp_path / "registration.json", reg)
    tool.save(tmp_path / "population.json", pop)
    for arm in pop["arms"]:
        good = arm != peer
        run = tmp_path / arm["name"]
        (run / "episodes").mkdir(parents=True)
        proto = {"arm": arm, "population": pop, "readout_schedule": "inline", "comparison": {}}
        tool.save(run / "protocol.json", proto)
        tool.save(run / "run.json", {"status": "COMPLETED"})
        window = {
            "reader_requests_this_invocation": len(tasks),
            "policy_load_ms_this_invocation": 0,
        }
        (run / "windows.jsonl").write_text(json.dumps(window) + "\n")
        for t in tasks:
            value = float(good)
            grade = {
                "accuracy": value,
                "answer_f1": value,
                "answer_em": value,
                "support_f1": value,
                "sufficiency_correct": True,
                "gold_answerable": t["task_id"] % 2 == 0,
            }
            tool.save(
                run / "episodes" / f"{t['task_id']}.json",
                {
                    **t,
                    "status": "scored",
                    "grade": {"native_metrics": grade},
                    "costs": {
                        "reader_input_tokens": 10 if good else 200,
                        "episode_live_readout_ms": 1,
                        "reader_request_attempted": True,
                    },
                },
            )
    return tool, pop, arms, peer


def test_real_packet_readout_two_comparisons(tmp_path, native_fixture):
    tool, pop, _, peer = native_fixture
    args = SimpleNamespace(registration=tmp_path, runs=tmp_path, output=tmp_path / "result.json")
    tool.readout(args)
    initial = tool.read(args.output)
    assert initial["findings"] == {"same_backbone": "supported", "practical": "unidentified"}
    assert initial["measured_total_cost"] is None
    assert initial["unique_reader_calls"] == 32
    for a in pop["arms"]:
        run = tmp_path / a["name"]
        proto = tool.read(run / "protocol.json")
        proto["comparison"]["total_cost"] = {
            "unit": "local_gpu_seconds",
            "includes": tool.COMPONENTS,
            "measurement_protocol": "measured_fixture",
        }
        tool.save(run / "protocol.json", proto)
        for f in (run / "episodes").glob("*.json"):
            row = tool.read(f)
            row["costs"]["total_local_gpu_seconds"] = 3.0 if a != peer else 4.0
            tool.save(f, row)
    tool.readout(args)
    measured = tool.read(args.output)
    assert measured["measured_total_cost"]["interval_95"] == pytest.approx([0.25, 0.25])
    assert measured["findings"]["practical"] == "supported"
    lost = tmp_path / "fit-29" / "episodes" / "0.json"
    row = tool.read(lost)
    row.pop("grade")
    row["status"] = "reader_error"
    tool.save(lost, row)
    tool.readout(args)
    failed = tool.read(args.output)
    assert not failed["native_contrasts"]["practical"]["paired_quality_complete"]
    assert failed["findings"]["practical"] == "unidentified"
    assert failed["observed_resources_by_arm"]["fit-29"]["status"]["reader_error"] == 1


def test_final_fit_seed_must_match_its_checkpoint(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    tool = importlib.import_module("confirm_memory_control_v13")
    ckpt = tmp_path / "model" / "checkpoint"
    ckpt.mkdir(parents=True)
    (ckpt / "control.pt").touch()
    tool.save(ckpt.parent / "run.json", {"contract": {"seed": 29, "fitted_groups": ["qasper/p"]}})
    run = tmp_path / "placed-dev"
    run.mkdir()
    tool.save(run / "run.json", {"status": "COMPLETED"})
    tool.save(
        run / "protocol.json",
        {
            "population": {"role": "dev", "v13_role": "tune", "material_budget": 2048},
            "arm": {
                "policy": "pretrained_checkpoint",
                "environment": "qrag_milai_v13",
                "checkpoint": str(ckpt),
                "seed": 11,
            },
        },
    )
    with pytest.raises(ValueError, match="Fit seed"):
        tool.validate_dev_family([run, run, run], final=True)


def fresh_fixture(tool, tmp_path, pop):
    fresh = tmp_path / "fresh.sqlite"
    with sqlite3.connect(fresh) as db:
        db.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE experiment_tasks(
                id INTEGER, dataset TEXT, native_group TEXT, experiment_role TEXT);
            CREATE TABLE experiment_groups(
                dataset TEXT, native_group TEXT, eligible_fresh_confirmation INTEGER);
            CREATE TABLE anomalies(task_id INTEGER,dataset TEXT,reason TEXT);
        """)
        for key, val in {
            "confirmation_only": True,
            "derivation": {"revision": {}},
            "control_release": {"declared": True},
            "run_id": "test-fresh",
        }.items():
            db.execute("INSERT INTO metadata VALUES(?,?)", (key, json.dumps(val)))
        groups = set()
        for t in pop["tasks"]:
            group = "fresh-" + t["native_group"]
            db.execute(
                "INSERT INTO experiment_tasks VALUES(?,?,?,'confirm')",
                (t["task_id"], t["dataset"], group),
            )
            groups.add((t["dataset"], group))
        db.executemany("INSERT INTO experiment_groups VALUES(?,?,1)", groups)
    role, packet = tmp_path / "role.json", tmp_path / "packet.json"
    tool.save(role, {"eligible_groups": {s: 2 for s in tool.SOURCES}, "run_id": "test-fresh"})
    tool.save(
        packet,
        {
            "reader_calls": 0,
            "fitting_states": 0,
            "cold_prepare_sources": tool.SOURCES,
            "current_release_group_overlap": {s: 0 for s in tool.SOURCES},
            "physical_native_outcome_overlap": {s: 0 for s in tool.SOURCES},
            "dataset_run_id": "test-fresh",
        },
    )
    return fresh, role, packet


def test_register_three_fits_and_one_shared_control(tmp_path, native_fixture):
    tool, pop, arms, peer = native_fixture
    fresh, role, packet = fresh_fixture(tool, tmp_path, pop)
    backbone = str(tmp_path / "base")
    runs = {}
    for arm in [*arms, peer]:
        run = tmp_path / arm["name"]
        cfg = tool.read(run / "protocol.json")
        cfg["population"] = dict(pop, role="dev", v13_role="tune")
        cfg["arm"].update(
            environment="qrag_milai_v13", observation_protocol="semantic_nav_delta_v2"
        )
        if arm != peer:
            ckpt = tmp_path / ("weights-" + arm["name"]) / "checkpoint"
            ckpt.mkdir(parents=True)
            (ckpt / "control.pt").touch()
            tool.save(ckpt / "controller.json", {"backbone": backbone})
            contract = {
                "seed": arm["seed"],
                "fitted_groups": ["qasper/train"],
                "supervision_mode": "paired",
                "observation_protocol": "semantic_nav_delta_v2",
                "input": "frozen",
                "effective_batch": 32,
                "epochs": 3,
                "lr": 1e-5,
                "pair_weight": 0.2,
            }
            tool.save(ckpt.parent / "run.json", {"contract": contract})
            cfg["arm"].update(policy="pretrained_checkpoint", checkpoint=str(ckpt))
            runs.setdefault("F", []).append(str(run))
        else:
            cfg["arm"].update(policy="gte_relevance", backbone=backbone)
            runs["B"] = [str(run)]
        tool.save(run / "protocol.json", cfg)
    selection = tmp_path / "selection.json"
    tool.save(
        selection, {"final": "F", "families": runs, "same_backbone": ["B"], "practical": ["B"]}
    )
    args = SimpleNamespace(
        selection=selection,
        data=fresh,
        role_audit=role,
        packet_audit=packet,
        seed=11,
        reader_cap=32,
        quality_mde=1.0,
        draws=2,
        power_repeats=160,
        bootstrap_repeats=160,
        cost_unit="local_gpu_seconds",
        output=tmp_path / "frozen",
    )
    tool.register(args)
    result = tool.read(args.output / "registration.json")
    assert result["reserved_first_calls"] == 32
    assert result["comparison_first_slots"] == {"same_backbone": 32, "practical": 32}
    assert not result["dev_total_cost_available"]
    assert (
        result["capacity_power_grid"][-1]["projections"]["same_backbone"][
            "superiority_power_at_mde"
        ]
        == 1
    )
    assert len(tool.read(args.output / "population.json")["arms"]) == 4
    assert not any(args.output.rglob("episodes"))
    # Two comparisons share the fixed baseline. An exposed MuSiQue pair consumes both members.
    prior = tmp_path / "already-used"
    prior.mkdir()
    member = next(
        t
        for t in tool.read(args.output / "population.json")["tasks"]
        if t["dataset"] == "musique_full"
    )
    tool.save(prior / "protocol.json", {"population": {"role": "confirm", "tasks": [member]}})
    tool.save(prior / "run.json", {"status": "COMPLETED"})
    args.prior_run = [prior]
    args.reader_cap = None
    args.output = tmp_path / "inventory-frozen"
    tool.register(args)
    derived = tool.read(args.output / "registration.json")
    assert derived["max_reader_calls"] == 4 * (8 - 2)
    assert derived["reader_cap_source"] == "remaining_fresh_tasks_times_unique_deployments"
    assert derived["reserved_first_calls"] <= derived["max_reader_calls"]


def test_actual_cost_weights_the_registered_workload(native_fixture):
    tool, pop, _, _ = native_fixture
    # Mu accounts for four of eight tasks but only one of three source means.
    base = {t["task_id"]: 4.0 for t in pop["tasks"]}
    policy = {t["task_id"]: 2.0 if t["dataset"] == "musique_full" else 4.0 for t in pop["tasks"]}
    stats = tool.measured_savings(pop, [policy], [base], 100, 1)
    assert stats["policy_total_mean_across_fits"] == 24.0
    assert stats["baseline_total_mean_across_fits"] == 32.0
    assert stats["savings"] == pytest.approx(0.25)
    assert stats["equal_source_weighted_savings_sensitivity"] == pytest.approx(1 / 6)


def test_restart_preserves_scored_and_does_not_reissue_unknown_dispatch(tmp_path):
    from milai_lab.runners.memory_control_episode import _prepare_episode_batch

    tasks = [{"dataset": "qasper", "native_group": "fixture", "task_id": i} for i in (1, 2)]
    for row, status in zip(tasks, ("scored", "dispatching"), strict=True):
        (tmp_path / f"{row['task_id']}.json").write_text(json.dumps({**row, "status": status}))
    ready, counts, _, prepared = _prepare_episode_batch(
        None, None, {"tasks": tasks}, {}, tmp_path, device="cpu", limit=None
    )
    assert not ready and prepared == 0 and counts == {"scored": 1, "reader_interrupted": 1}
    assert json.loads((tmp_path / "2.json").read_text())["status"] == "reader_interrupted"


def test_seed11_selection_and_seed_spread_use_their_registered_rosters(tmp_path, monkeypatch):
    """Full-menu selection cannot inherit the enriched/depleted fit-repeat slice scores."""
    import milai_lab.runners.memory_control_confirmation as planning

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    tool = importlib.import_module("confirm_memory_control_v13")
    rows = []
    for source in tool.SOURCES:
        for group in ("a", "b", "outside"):
            for _ in range(2 if source == "musique_full" else 1):
                rows.append({"task_id": len(rows), "dataset": source, "native_group": group})
    full = {
        "tasks": rows,
        "protocol": "fixture",
        "role": "dev",
        "v13_role": "tune",
        "dataset_run_id": "fixture",
        "seed": 42,
        "primary_quality": "macro",
        "material_budget": 2048,
        "predeclared_unevaluable_tasks": {},
    }
    fullfile = tmp_path / "tune.json"
    tool.save(fullfile, full)
    child = {
        **full,
        "subset_kind": "frozen_fit_repeat",
        "parent_tune_roster": str(fullfile),
        "selection_seed": 913,
        "tasks": [r for r in rows if r["native_group"] != "outside"],
    }
    childfile = tmp_path / "repeat.json"
    tool.save(childfile, child)
    _, scope = tool.tune_support(tmp_path / "method.json", {"tune_subset": "repeat.json"})
    assert scope == child and tool.full_tune_parent(scope) == full
    results = []
    for label, seed, q in (("F", 11, 0.6), ("F", 29, 0.4), ("F", 47, 0.2), ("B", None, 0.5)):
        run = tmp_path / f"{label}-{seed}"
        (run / "episodes").mkdir(parents=True)
        pop = full if seed in (11, None) else child
        arm = {
            "policy": "gte_relevance",
            "backbone": str(tmp_path / "base"),
            "environment": "qrag_milai_v13",
            "name": run.name,
            "observation_protocol": "semantic_nav_delta_v2",
        }
        if seed is not None:
            ckpt = tmp_path / f"weights-{seed}" / "checkpoint"
            ckpt.mkdir(parents=True)
            (ckpt / "control.pt").touch()
            tool.save(ckpt / "controller.json", {"backbone": str(tmp_path / "base")})
            tool.save(
                ckpt.parent / "run.json",
                {
                    "contract": {
                        "seed": seed,
                        "fitted_groups": ["qasper/training"],
                        "supervision_mode": "paired",
                        "observation_protocol": "semantic_nav_delta_v2",
                        "input": "same-frozen-pack",
                        "effective_batch": 32,
                        "epochs": 3,
                        "lr": 1e-5,
                        "pair_weight": 0.2,
                    }
                },
            )
            arm.update(policy="pretrained_checkpoint", checkpoint=str(ckpt), seed=seed)
            results.append(run)
        meter = {
            "unit": "local_gpu_seconds",
            "includes": tool.COMPONENTS,
            "measurement_protocol": "fixture",
        }
        tool.save(
            run / "protocol.json",
            {"population": pop, "arm": arm, "comparison": {"total_cost": meter}},
        )
        tool.save(run / "run.json", {"status": "COMPLETED"})
        (run / "windows.jsonl").write_text(
            json.dumps(
                {
                    "reader_requests_this_invocation": len(pop["tasks"]),
                    "policy_load_ms_this_invocation": 0,
                }
            )
            + "\n"
        )
        for r in pop["tasks"]:
            quality = float(label == "F") if r["native_group"] == "outside" else q
            measured = {
                "reader_input_tokens": 7,
                "episode_live_readout_ms": 1,
                "reader_request_attempted": True,
            }
            if r["native_group"] != "outside":
                measured["total_local_gpu_seconds"] = 2.0 if label == "F" else 3.0
            tool.save(
                run / "episodes" / f"{r['task_id']}.json",
                {
                    **r,
                    "status": "scored",
                    "costs": measured,
                    "grade": {
                        "native_metrics": {
                            "accuracy": quality,
                            "answer_f1": quality,
                            "answer_em": quality,
                            "support_f1": quality,
                            "sufficiency_correct": True,
                            "gold_answerable": r["task_id"] % 2 == 0,
                        }
                    },
                },
            )
    base = tmp_path / "B-None"
    family = tool.validate_dev_family(results, final=True, tune_subset=scope)
    assert family["selection_score"] == pytest.approx(100 * (0.6 + 0.6 + 1) / 3)
    assert [v[0] for v in family["quality_bounds_points"]] == pytest.approx([60, 40, 20])
    assert [v["registered_tasks"] for v in family["common_fit_support"]] == [8, 8, 8]
    assert [v["input_tasks"] for v in family["common_fit_support"]] == [12, 8, 8]
    assert family["fit_seed_sensitivity"]["quality_points_sample_sd_if_observed"] == pytest.approx(
        20.0
    )
    assert family["fit_seed_sensitivity"]["cost_totals_across_fits"]["reader_input_tokens"][
        "range_if_complete"
    ] == [56, 56]
    assert tool.cost_data([base], "total_local_gpu_seconds") is None
    assert tool.cost_data([base], "total_local_gpu_seconds", dev_roster=child) is not None
    cap = {
        "dataset_run_id": "dummy",
        "seed": 11,
        "target_tasks": 8,
        "selected_groups": {
            s: [{"native_group": g, "tasks": 2 if s == "musique_full" else 1} for g in ("a", "b")]
            for s in tool.SOURCES
        },
    }
    power = planning.plan_confirmation_power(
        cap,
        results,
        base,
        draws=2,
        repeats=160,
        analysis_seed=11,
        primary_comparisons=2,
        holm_plan=True,
        tune_subset=childfile,
        cost_field="total_local_gpu_seconds",
    )
    assert power["projected_dev_tasks"] == 8 and power["projection_reader_requests"] == 0
    assert power["source_groups_used"] == {s: 2 for s in tool.SOURCES}
    assert power["conservative_dev_design"]["seed_quality_delta_points"] == pytest.approx(
        [10, -10, -30]
    )
    fresh, role, packet = fresh_fixture(tool, tmp_path, child)
    selection = tmp_path / "selection.json"
    tool.save(
        selection,
        {
            "final": "F",
            "families": {"F": list(map(str, results)), "B": [str(base)]},
            "same_backbone": ["B"],
            "practical": ["B"],
            "tune_subset": str(childfile),
        },
    )
    args = SimpleNamespace(
        selection=selection,
        data=fresh,
        role_audit=role,
        packet_audit=packet,
        seed=11,
        reader_cap=32,
        quality_mde=1.0,
        draws=2,
        power_repeats=160,
        bootstrap_repeats=160,
        cost_unit="local_gpu_seconds",
        output=tmp_path / "subset-registration",
    )
    tool.register(args)
    registered = tool.read(args.output / "registration.json")
    assert registered["fit_repeat_tasks"] == 8
    assert registered["dev_total_cost_available"]
    assert registered["families"]["F"]["selection_basis"]["tasks"] == 12
    assert registered["families"]["F"]["selection_score"] == pytest.approx(
        family["selection_score"]
    )
    assert registered["capacity_power_grid"][-1]["projections"]["practical"][
        "dev_groups_available"
    ] == {s: 2 for s in tool.SOURCES}
    invalid = {**child, "tasks": child["tasks"][1:]}
    with pytest.raises(ValueError, match="whole native groups"):
        planning.power_dev_records(base, invalid)
    original = tool.read(results[0] / "protocol.json")
    tool.save(results[0] / "protocol.json", {**original, "population": child})
    with pytest.raises(ValueError, match="full parent TUNE"):
        tool.validate_dev_family(results, final=True, tune_subset=scope)


@pytest.mark.parametrize(
    ("role", "v13_role"), [("dev", "calibration"), ("confirm", "confirm_fresh")]
)
def test_power_rejects_wrong_role_before_opening_packets(tmp_path, monkeypatch, role, v13_role):
    import milai_lab.runners.memory_control_confirmation as planning

    (tmp_path / "protocol.json").write_text(
        json.dumps({"population": {"role": role, "v13_role": v13_role}})
    )
    monkeypatch.setattr(
        planning, "input_result", lambda *_: pytest.fail("opened out-of-role records")
    )
    with pytest.raises(ValueError, match="natural TUNE"):
        planning.power_dev_records(tmp_path, {"role": "dev", "v13_role": "tune"})

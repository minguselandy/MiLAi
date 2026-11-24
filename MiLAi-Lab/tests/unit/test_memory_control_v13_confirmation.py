"""The V13 two-comparison family keeps missing infrastructure cost distinct from token counts."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_real_packet_readout_two_comparisons(tmp_path, monkeypatch):
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

"""Frozen-data fitting cannot dispatch a new label or accidentally train another acquisition arm."""

from __future__ import annotations

import gzip
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


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

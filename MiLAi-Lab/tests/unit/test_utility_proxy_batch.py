import json
import sys
from pathlib import Path

import pytest

from milai_lab.methods.bundle_adoption_proxy import select_bundles

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_utility_proxy_batch as batch


def fixture_inputs():
    allocation = json.loads(batch.ALLOCATION.read_text())
    tasks = []
    for domain, positions in allocation["domains"].items():
        for pos in positions:
            rows = []
            if (domain, pos["id"]) == ("os_interaction", "428"):
                rows = [
                    {
                        "bundle_id": str(n),
                        "source_task": "source",
                        "accepted": n,
                        "rejected": 1 - n,
                        "context": str(n),
                        "versions": [{"id": n}],
                    }
                    for n in range(2)
                ]
            tasks.append(
                {
                    "domain": domain,
                    "id": pos["id"],
                    "candidates": rows,
                    "selection": select_bundles(rows),
                    "query_sha256": "a" * 64,
                    "cached_query_available": bool(rows),
                }
            )
    return {"tasks": tasks}, allocation


def test_plan_keeps_allocation_and_repeat_order_and_unknown_use():
    inputs, allocation = fixture_inputs()
    plan = batch.freeze_plan(inputs, allocation)
    assert len(plan) == 64
    assert len({x["attempt_id"] for x in plan}) == 64
    assert sum(x["mechanism_eligible"] for x in plan) == 4
    for n, pair in enumerate(allocation["schedule"]):
        assert [x["arm"] for x in plan[2 * n : 2 * n + 2]] == pair["arms"]
        assert all(x["observable_use"] == "UNKNOWN" for x in plan[2 * n : 2 * n + 2])


def test_selection_or_denominator_drift_rejected():
    inputs, allocation = fixture_inputs()
    inputs["tasks"][0]["selection"]["UTILITY"] = "invented"
    with pytest.raises(ValueError, match="SELECTION_RECOMPUTATION"):
        batch.freeze_plan(inputs, allocation)
    inputs["tasks"].pop()
    with pytest.raises(ValueError, match="POSITION_COUNT"):
        batch.freeze_plan(inputs, allocation)


def test_admission_mismatch_precedes_any_environment_or_model_call(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "ROOT", tmp_path)
    (tmp_path / "admission.json").write_text("{}")
    with pytest.raises(ValueError, match="ADMISSION_SHA_MISMATCH"):
        batch.verify_admission("b" * 64)


def test_started_marker_prevents_replay_or_budget_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "ROOT", tmp_path)
    monkeypatch.setattr(batch, "verify_admission", lambda _: ({}, []))
    (tmp_path / "started.json").write_text("original batch")
    with pytest.raises(FileExistsError):
        batch.run("a" * 64)
    assert (tmp_path / "started.json").read_text() == "original batch"
    assert not (tmp_path / "budget.sqlite").exists()

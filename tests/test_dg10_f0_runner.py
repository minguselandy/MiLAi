from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_dg10_f0


def _catalog(profile: str) -> dict[str, object]:
    names = sorted(run_dg10_f0.EXPECTED_CATALOGS[profile])
    return {
        "protocol_version": "2026-07-28",
        "tools": names,
        "catalog": [
            {
                "name": name,
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
            for name in names
        ],
    }


@pytest.mark.parametrize("profile", sorted(run_dg10_f0.EXPECTED_CATALOGS))
def test_validate_catalog_accepts_exact_closed_profile(profile: str) -> None:
    run_dg10_f0._validate_catalog(profile, _catalog(profile))


def test_validate_catalog_rejects_open_or_escalated_schema() -> None:
    payload = _catalog("reader-lite")
    payload["catalog"][0]["inputSchema"]["additionalProperties"] = True  # type: ignore[index]
    with pytest.raises(run_dg10_f0.F0Error, match="schema is not closed"):
        run_dg10_f0._validate_catalog("reader-lite", payload)

    payload = _catalog("reader-lite")
    payload["tools"] = ["milai_recall", "milai_evidence_revoke"]
    with pytest.raises(run_dg10_f0.F0Error, match="tool catalog drift"):
        run_dg10_f0._validate_catalog("reader-lite", payload)


def test_record_run_uses_only_converged_development_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_dg10_f0, "CURRENT_STATE", tmp_path / "current-state.json")
    monkeypatch.setattr(run_dg10_f0, "EXPERIMENTS", tmp_path / "experiments.jsonl")
    result = {
        "run_id": "f0-package-test0001",
        "status": "PASS",
        "cases": {"F0-01": "PASS", "F0-02": "PASS"},
    }
    experiment = {
        "experiment_id": "exp-f0-package-test0001",
        "rm_id": "RM-02",
        "rm_ids": ["RM-02"],
    }
    run_dg10_f0._record_run(result, experiment)

    state = json.loads(run_dg10_f0.CURRENT_STATE.read_text(encoding="utf-8"))
    assert set(state["rm"]) == {f"RM-{index:02d}" for index in range(16)}
    assert state["rm"]["RM-02"]["status"] == "PASS"
    assert state["functional_gates"]["F0"] == "IN_PROGRESS"
    assert json.loads(run_dg10_f0.EXPERIMENTS.read_text(encoding="utf-8")) == experiment


def test_record_run_waits_for_openworker_before_closing_f1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_dg10_f0, "CURRENT_STATE", tmp_path / "current-state.json")
    monkeypatch.setattr(run_dg10_f0, "EXPERIMENTS", tmp_path / "experiments.jsonl")
    generic = {
        "run_id": "f1-agent-test0001",
        "status": "PASS",
        "cases": {f"F1-{index:02d}": "PASS" for index in range(1, 6)},
    }
    experiment = {
        "experiment_id": "exp-f1-agent-test0001",
        "rm_id": "RM-07",
        "rm_ids": ["RM-07"],
    }
    run_dg10_f0._record_run(generic, experiment)

    current = json.loads(run_dg10_f0.CURRENT_STATE.read_text(encoding="utf-8"))
    assert current["functional_gates"]["F1"] == "GENERIC_PASS_OPENWORKER_PENDING"
    assert current["primary_milestone"]["status"] == "IN_PROGRESS"

    openworker = {
        "run_id": "f1-openworker-test0001",
        "status": "PASS",
        "cases": {"OPENWORKER-F1": "PASS"},
    }
    openworker_experiment = {
        "experiment_id": "exp-f1-openworker-test0001",
        "rm_id": "RM-13",
        "rm_ids": ["RM-13"],
    }
    run_dg10_f0._record_run(openworker, openworker_experiment)

    current = json.loads(run_dg10_f0.CURRENT_STATE.read_text(encoding="utf-8"))
    assert current["functional_gates"]["F1"] == "PASS"


def test_completed_rm00_is_not_reopened_by_later_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_dg10_f0, "CURRENT_STATE", tmp_path / "current-state.json")
    monkeypatch.setattr(run_dg10_f0, "EXPERIMENTS", tmp_path / "experiments.jsonl")
    run_dg10_f0._record_run(
        {
            "run_id": "rm00-workflow-test0001",
            "status": "PASS",
            "cases": {"RM00-ACTIVE-WORKFLOW": "PASS"},
        },
        {
            "experiment_id": "exp-rm00-workflow-test0001",
            "rm_id": "RM-00",
            "rm_ids": ["RM-00"],
        },
    )
    run_dg10_f0._record_run(
        {
            "run_id": "t2-openworker-test0002",
            "status": "PASS",
            "cases": {"T2-01": "PASS"},
        },
        {
            "experiment_id": "exp-t2-openworker-test0002",
            "rm_id": "RM-06",
            "rm_ids": ["RM-06"],
        },
    )

    current = json.loads(run_dg10_f0.CURRENT_STATE.read_text(encoding="utf-8"))
    assert current["rm"]["RM-00"]["status"] == "PASS"

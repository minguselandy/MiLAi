"""All-attempt accounting must not pool protocols or inflate independent roots."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import summarize_v0218_e0 as module
from run_v0218 import episode_plan


@pytest.fixture
def summary_fixture(tmp_path, monkeypatch):
    base = tmp_path / "20260911"
    audits, ledgers = {}, {}
    for wave in (1, 2, 3, 4):
        probe = wave == 4
        root = base / ("e0-probes-v4-v1" if probe else f"e0-baseline-wave{wave}-v2")
        root.mkdir(parents=True)
        selected = 3 if probe else wave
        roots = [{"root": f"lineage-{selected}-{i}"} for i in (1, 2)]
        variants = ("helpful", "irrelevant", "unresolved") if probe else ("stable", "superseded")
        plan = episode_plan(roots, ("N0", "N1", "N2"), variants)
        rows = [
            {
                **row,
                "business_status": "FAIL" if row["arm"] == "N2" else "PASS",
                "status": "FINISHED",
                "execution_status": "FINISHED",
                "episode_id": row["id"],
                "requests": 1,
                "raw_tokens": 10,
                "seconds": 1.0,
                "business_mutations": 1,
                "exact_redundant_business_writes": 0,
                "source_reads": {"current": 1},
                "cold_old_note": row["arm"] in ("N1", "N2"),
                "both_presented": row["arm"] in ("N1", "N2"),
                "agent_note_writes": int(row["phase"] == "A"),
                "actions": [],
            }
            for row in plan
        ]
        cost = {"requests": len(rows), "raw_tokens": 10 * len(rows), "pending": 0, "violations": 0}
        result = {
            "status": "E0_EXECUTED_REQUIRES_CHAIN_AND_BEHAVIOR_AUDIT",
            "cost": cost,
            "cleanup": {"api_stopped": True, "compose_stop_returncode": 0},
            "rows": rows,
        }
        manifest = {
            "protocol_revision": {"revision": "COMMON_HOST_V4_SETTLED_ENCODING_ERROR_FEEDBACK"},
            "implementation": {"tools/v0218_host.py": "same-host"},
            "stage": "PROBES" if probe else f"WAVE_{wave}",
            "episodes": plan,
        }
        (root / "result.json").write_text(json.dumps(result))
        (root / "manifest.json").write_text(json.dumps(manifest))
        (root / "baseline-audit-v1.json").write_text(json.dumps({"rows": rows}))
        audits[root] = {"rows": rows}
        ledgers[root] = cost.copy()
    historical = [
        tmp_path / "20260910" / name
        for name in ("t3-note-chain-v1", "t3-note-chain-v2", "t3-note-chain-v3", "t4-note-chain-v1")
    ] + [base / f"e0-baseline-wave{wave}-v1" for wave in (1, 2, 3)]
    for root in historical:
        root.mkdir(parents=True)
        cost = {"requests": 1, "raw_tokens": 100, "pending": 0, "violations": 0}
        (root / "result.json").write_text(json.dumps({"cost": cost}))
        ledgers[root] = cost.copy()
    monkeypatch.setattr(module, "audit_baseline", audits.__getitem__)
    monkeypatch.setattr(module, "costs", ledgers.__getitem__)
    return base, tmp_path / "summary.json", ledgers


def test_summary_separates_probes_old_protocols_and_shared_A(summary_fixture):
    base, output, _ = summary_fixture
    result = module.summarize(base, output)
    assert result["standard_root_count"] == 6
    assert result["probe_root_count_not_additional"] == 2
    assert result["standard"]["A_attempts"] == 6
    assert result["standard"]["B_attempts"] == 36
    assert result["probes"]["A_attempts"] == 2
    assert result["probes"]["B_attempts"] == 18
    assert result["standard"]["shared_A_cost_once"]["requests"] == 6
    assert result["all_goal_provider_cost"] == {"requests": 69, "raw_tokens": 1320}
    assert len(result["pairs"]) == 18
    assert result["standard"]["B_by_arm"]["N2"] == {"FAIL": 12}
    assert not result["whole_goal_complete"]
    assert module.summarize(base, output) == result


@pytest.mark.parametrize("fault", ["protocol", "host", "pending", "cleanup", "missing_episode"])
def test_summary_rejects_invalid_comparison(summary_fixture, fault):
    base, output, _ = summary_fixture
    root = base / "e0-baseline-wave2-v2"
    manifest = module.read(root / "manifest.json")
    result = module.read(root / "result.json")
    if fault == "protocol":
        manifest["protocol_revision"]["revision"] = "old"
    elif fault == "host":
        manifest["implementation"]["tools/v0218_host.py"] = "changed"
    elif fault == "pending":
        result["cost"]["pending"] = 1
    elif fault == "cleanup":
        result["cleanup"]["api_stopped"] = False
    else:
        result["rows"].pop()
    (root / "manifest.json").write_text(json.dumps(manifest))
    (root / "result.json").write_text(json.dumps(result))
    with pytest.raises(AssertionError):
        module.summarize(base, output)
    assert not output.exists()


def test_summary_rejects_unreconciled_historical_cost(summary_fixture):
    base, output, ledgers = summary_fixture
    ledgers[base / "e0-baseline-wave1-v1"]["requests"] += 1
    with pytest.raises(AssertionError):
        module.summarize(base, output)
    assert not output.exists()


def test_summary_cannot_overwrite_prior_result(summary_fixture):
    base, output, _ = summary_fixture
    output.write_text('{"whole_goal_complete": true}')
    with pytest.raises(AssertionError):
        module.summarize(base, output)
    assert module.read(output) == {"whole_goal_complete": True}

"""Original Host admission and cost closure use synthetic children, never model calls."""

import sys
from pathlib import Path

import pytest
from test_original_feedback_host import close_fit, study_fixture

import run_bound_original_feedback_host as runner
from milai_lab.harness.artifact_io import read_json, write_json
from prepare_original_feedback_host import bind_study, inspect_bindings


def prepared(tmp_path, mode="completed"):
    study, _, config = study_fixture(tmp_path)
    saved = tmp_path / "saved"
    for i, fit in enumerate(study["fits"]):
        close_fit(study, fit, saved, updates={"answer": 0} if i == 0 else None)
    attention = tmp_path / "attention.py"
    attention.write_text("import runpy,sys\nsys.argv=sys.argv[1:]\n"
                         "runpy.run_path(sys.argv[0],run_name='__main__')\n")
    inference = tmp_path / "inference.py"
    inference.write_text(
        "import json,runpy,sys\nfrom pathlib import Path\n"
        "receipt=Path(sys.argv[1]);sys.argv=sys.argv[2:]\n"
        "try:\n runpy.run_path(sys.argv[0],run_name='__main__')\n"
        "except BaseException:\n receipt.write_text(json.dumps({'status':'FAILED'}));raise\n"
        "else:\n receipt.write_text(json.dumps({'status':'COMPLETED'}))\n"
    )
    entry = Path(study["runtime"]) / "tools/run_host_intent_retrieval.py"
    entry.parent.mkdir(parents=True)
    entry.write_text(
        "import copy,json,sys\nfrom pathlib import Path\n"
        f"mode={mode!r}\n"
        "config= json.loads(Path(sys.argv[1]).read_text());root=Path(sys.argv[3])\n"
        "ledger=Path(config['entrypoints']['functional']['budget_path'])\n"
        "before=json.loads(ledger.read_text());after=copy.deepcopy(before)\n"
        "phase='unexpected_phase' if mode=='accounting' else 'dynamic_memory_laya'\n"
        "after['compute'][phase]={'cpu_seconds':0.00001}\n"
        "after['generation']['unknown_usage']=1\n"
        "root.mkdir(parents=True)\n"
        "(root/'budget-before.json').write_text(json.dumps(before))\n"
        "ledger.write_text(json.dumps(after))\n"
        "(root/'budget-after.json').write_text(json.dumps(after))\n"
        "status={'failed':'FAILED','known_failure':'COMPLETED_WITH_FAILURES'}.get(\n"
        " mode,'COMPLETED')\n"
        "count=1 if mode in ('failed','short') else 16\n"
        "(root/'driver.json').write_text(json.dumps({'status':status,\n"
        " 'completed':[{'position':i} for i in range(count)]}))\n"
        "if mode=='failed':sys.exit(7)\n"
    )
    ledger = Path(config["entrypoints"]["functional"]["budget_path"])
    write_json(ledger, {"limits": {}, "compute": {}, "generation": {"unknown_usage": 0}})
    dispatch = bind_study(
        study, inspect_bindings(study, saved), tmp_path / "bound", python=sys.executable,
        attention_wrapper=str(attention), inference_wrapper=str(inference),
    )
    return tmp_path / "bound/dispatch.json", saved, dispatch, ledger


@pytest.mark.parametrize("mode,expected,code", [
    ("completed", "COMPLETED", 0),
    ("known_failure", "COMPLETED_WITH_NATIVE_FAILURES_RETAINED", 0),
    ("failed", "FAILED_RETAINED", 7),
])
def test_one_actual_synthetic_child_retains_native_failure_and_disjoint_cost(
    tmp_path, monkeypatch, mode, expected, code,
):
    path, saved, dispatch, ledger = prepared(tmp_path, mode)
    monkeypatch.setattr(runner, "active_model_owners", lambda: [])
    before = read_json(ledger)
    receipt = tmp_path / "owner"
    report = runner.run_arm(path, saved, "jev_initialization", receipt)
    assert report["status"] == expected and report["exit_code"] == code
    assert not Path("/proc", str(report["child_pid"])).exists()
    assert report["planned_positions"] == 16 and report["automatic_retry"] is False
    assert report["known_local_CPU_already_recorded"] == {"dynamic_memory_laya": 0.00001}
    assert report["child_cpu_pending"] == report["whole_child_cpu_seconds"] - 0.00001
    assert read_json(receipt / "budget-before.json") == before
    assert read_json(receipt / "budget-after.json") == read_json(ledger)
    assert read_json(ledger)["generation"]["unknown_usage"] == 1
    assert read_json(receipt / "driver.json") == report
    assert sum(Path(a["output"]).exists() for a in dispatch["arms"]) == 1


@pytest.mark.parametrize("mode,error", [("short", "closure"), ("accounting", "CPU ledger")])
def test_incomplete_success_or_unexpected_cost_keeps_failed_receipt(
    tmp_path, monkeypatch, mode, error,
):
    path, saved, _, ledger = prepared(tmp_path, mode)
    monkeypatch.setattr(runner, "active_model_owners", lambda: [])
    receipt = tmp_path / "owner"
    with pytest.raises(ValueError, match=error):
        runner.run_arm(path, saved, "jev_initialization", receipt)
    report = read_json(receipt / "driver.json")
    assert report["status"] == ("ACCOUNTING_FAILED_RETAINED" if mode == "accounting"
                                else "FAILED_RETAINED")
    assert report["whole_child_cpu_seconds"] > 0
    assert read_json(receipt / "budget-after.json") == read_json(ledger)


@pytest.mark.parametrize("mutation", ["pending", "config", "aliases", "forced"])
def test_nine_fit_gate_and_bound_experiment_cannot_drift(tmp_path, mutation):
    _, saved, dispatch, _ = prepared(tmp_path)
    if mutation == "pending":
        (saved / dispatch["study"]["fits"][-1]["run_id"] / "retention.json").unlink()
    elif mutation == "config":
        path = Path(dispatch["arms"][1]["config"])
        config = read_json(path)
        config["entrypoints"]["functional"]["memory_control"]["threads"] = 8
        write_json(path, config)
    elif mutation == "aliases":
        dispatch["arms"][2]["aliases"] = ["unbound checkpoint attribution"]
    else:
        dispatch["arms"][1]["argv"].append("--given-requests")
    with pytest.raises(ValueError):
        runner.validate_original_arm(dispatch, saved, "rules")
    assert all(not Path(a["output"]).exists() for a in dispatch["arms"])


def test_actual_model_admission_rejects_before_any_receipt(tmp_path, monkeypatch):
    path, saved, _, ledger = prepared(tmp_path)
    before = ledger.read_bytes()
    monkeypatch.setattr(runner, "active_model_owners", lambda: [90000001])
    with pytest.raises(ValueError, match="Another actual model"):
        runner.run_arm(path, saved, "rules", tmp_path / "owner")
    assert not (tmp_path / "owner").exists() and ledger.read_bytes() == before


def test_existing_attempt_is_never_reexecuted(tmp_path):
    _, saved, dispatch, _ = prepared(tmp_path)
    Path(dispatch["arms"][1]["output"]).mkdir(parents=True)
    with pytest.raises(ValueError, match="no automatic retry"):
        runner.validate_original_arm(dispatch, saved, "rules")

"""Real tiny subprocesses and a temporary ledger exercise single-request ownership."""

import sys
from pathlib import Path

import pytest

from milai_lab.harness.artifact_io import read_json, write_json
from run_prepared_known_request import prerequisites, run_job


def fixture(tmp_path, monkeypatch, *, exit_code=0, unknown=False, extra_cpu=False):
    monkeypatch.setattr("run_prepared_known_request.active_model_owners", lambda: [])
    ledger = tmp_path / "budget.json"
    measures = {"cpu_seconds": 1, "runs": 1}
    write_json(ledger, {"limits": {}, "compute": {"prior": measures},
                        "generation": {"unknown_usage": 0}, "generation_requests": 0})
    job = "source128/selected-retention-48"
    settled = tmp_path / "settled.json"
    write_json(settled, {"status": "SETTLED_ONCE_WITH_NO_NEURAL_JOB_ACTIVE", "job_id": job,
                        "phase": "prior", "measures": measures})
    driver = tmp_path / "cpu-driver.json"
    write_json(driver, {"status": "COMPLETED", "job_id": job, "pid": 999999990,
                        "child_pid": 999999991})
    verification = tmp_path / "cpu-verification.json"
    write_json(verification, {"status": "SAVED_CPU_SELECTED_RETENTION_JOB_VERIFIED;"
                             "WHOLE_FIT_RETENTION_NOT_INFERRED", "job_id": job})
    retention = tmp_path / "retention.json"
    write_json(retention, {"status": "SAVED_CPU_SELECTION_AND_RETENTION_VERIFIED;"
                          "HOST_EVALUATION_PENDING", "run_id": "source128"})
    preparation = tmp_path / "preparation.json"
    request = {"query": "Cedar code"}
    write_json(preparation, {"conditions": [{"arm": "baseline", "request": request}],
                             "original_ledger": str(ledger)})
    output = tmp_path / "fresh"
    worker = tmp_path / "scripted_worker.py"
    worker.write_text('''import copy,json,sys
from pathlib import Path
ledger,output=map(Path,sys.argv[1:3]);code=int(sys.argv[3]);unknown=sys.argv[4]=='True'
before=json.loads(ledger.read_text());after=copy.deepcopy(before)
after['generation_requests']+=1
after['generation']['unknown_usage']+=int(unknown)
if sys.argv[5]=='True':after['compute']['unexpected']={'cpu_seconds':1}
ledger.write_text(json.dumps(after));output.mkdir()
report={'status':'COMPLETED' if code==0 else 'FAILED_RETAINED',
        'request':{'query':'Cedar code'},'exact_starting_bank_values':True,
        'host_request_generated':False,'budget_before':before,'budget_after':after,
        'call_captures':[],'actual_initial_states':0}
(output/'run.json').write_text(json.dumps(report))
raise SystemExit(code)
''')
    ready = tmp_path / "ready.json"
    write_json(ready, {"status": "KNOWN_SUFFICIENT_FRESH_SINGLE_REQUEST_BOUND_NOT_EXECUTED",
        "preparation": str(preparation), "output": str(output), "cwd": str(tmp_path),
        "environment": {}, "argv": [sys.executable, str(worker), str(ledger), str(output),
                                    str(exit_code), str(unknown), str(extra_cpu)]})
    plan = {"cpu_job_id": job, "cpu_driver": str(driver), "cpu_verification": str(verification),
        "fit_retention": str(retention), "original_ledger": str(ledger),
        "request_readiness": str(ready), "owner": str(tmp_path / "owner")}
    return plan, settled, ledger


def test_live_process_and_unclosed_retention_prevent_any_launch(tmp_path, monkeypatch):
    plan, settled, ledger = fixture(tmp_path, monkeypatch)
    before = read_json(ledger)
    monkeypatch.setattr("run_prepared_known_request.active_model_owners", lambda: [123])
    assert prerequisites(plan, settled)["status"] == "WAITING"
    with pytest.raises(ValueError, match="prerequisites are not closed"):
        run_job(plan, settled)
    monkeypatch.setattr("run_prepared_known_request.active_model_owners", lambda: [])
    Path(plan["fit_retention"]).unlink()
    assert prerequisites(plan, settled)["checks"]["fit_retention"] is False
    with pytest.raises(ValueError, match="prerequisites are not closed"):
        run_job(plan, settled)
    assert not Path(plan["owner"]).exists() and read_json(ledger) == before


@pytest.mark.parametrize("exit_code,unknown", [(0, False), (7, True)])
def test_one_child_preserves_native_failure_usage_and_all_unreached_states(
    tmp_path, monkeypatch, exit_code, unknown,
):
    plan, settled, ledger = fixture(tmp_path, monkeypatch, exit_code=exit_code, unknown=unknown)
    report = run_job(plan, settled)
    assert report["status"] == ("COMPLETED" if exit_code == 0 else "FAILED_RETAINED")
    assert report["exit_code"] == exit_code
    assert report["call_captures"] == [] and report["actual_initial_states"] == 0
    assert report["whole_child_cpu_seconds"] > 0
    assert report["child_cpu_pending"] == report["whole_child_cpu_seconds"]
    assert report["known_local_CPU_already_recorded"] == {}
    assert read_json(ledger)["generation"]["unknown_usage"] == int(unknown)
    with pytest.raises(ValueError, match="already exists"):
        run_job(plan, settled)
    assert read_json(ledger)["generation_requests"] == 1
    assert set(read_json(ledger)["compute"]) == {"prior"}


def test_accounting_failure_retains_actual_whole_child_measurement(tmp_path, monkeypatch):
    plan, settled, _ = fixture(tmp_path, monkeypatch, extra_cpu=True)
    with pytest.raises(ValueError, match="Unexpected CPU ledger delta"):
        run_job(plan, settled)
    report = read_json(Path(plan["owner"]) / "driver.json")
    assert report["status"] == "ACCOUNTING_FAILED_RETAINED"
    assert report["whole_child_cpu_seconds"] > 0 and "child_cpu_pending" not in report
    assert read_json(Path(plan["owner"]) / "budget-after.json")["generation_requests"] == 1

"""Own exactly one reserved64 fixed-model segment and bill its whole CPU after exit."""
import argparse
import fcntl
import json
import os
import resource
import subprocess
import time
from pathlib import Path

from milai_lab.harness.artifact_io import write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from reserved64_protocol_common_v1 import admission, expected_plan, read, verify_code

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("plan",type=Path)
parser.add_argument("--check-only",action="store_true")
args=parser.parse_args()
plan=read(args.plan)
protocol=read(plan["protocol"])
assert plan==expected_plan(protocol,plan)
verify_code(protocol)
ready=admission(protocol,plan)
if args.check_only:
    print(json.dumps({**ready,"new_model_HTTP_calls":0,"ledger_opened_or_written":False,"no_sha_validation":True}),flush=True)
    raise SystemExit(0)
assert ready["ready"],ready
owner_path=Path(plan["owner"])
assert not owner_path.exists() and not Path(plan["output"]).exists()
ledger=Path(protocol["original_ledger"])
with Path(protocol["single_stage_lock"]).open("a+b") as stage_lock:
    fcntl.flock(stage_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    before_ledger=read(ledger)
    assert plan["compute_phase"] not in before_ledger["compute"]
    owner={"status":"STARTING_RESERVED64_NATIVE_MODEL","pid":os.getpid(),"plan":str(args.plan.resolve()),
        "model":plan["model"],"positions":plan["positions"],"client_CPU_recorded":False,
        "automatic_retry":False,"automatic_next_model":False,"HTTP_calls":0,"no_sha_validation":True}
    write_json(owner_path,owner)
    started=time.perf_counter()
    children_before=resource.getrusage(resource.RUSAGE_CHILDREN)
    with Path(plan["log"]).open("x") as log:
        child=subprocess.Popen(plan["argv"],cwd=plan["cwd"],env={**os.environ,**plan["environment"]},
            stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
        owner.update(status="RUNNING",child_pid=child.pid,started_epoch=time.time())
        write_json(owner_path,owner)
        print("RESERVED64_NATIVE_MODEL_STARTED",plan["model"],child.pid,flush=True)
        code=child.wait()
    children_after=resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu=children_after.ru_utime-children_before.ru_utime+children_after.ru_stime-children_before.ru_stime
    wall=time.perf_counter()-started
    driver_path=Path(plan["output"])/"driver.json"
    driver=read(driver_path) if driver_path.exists() else None
    compute_path=Path(plan["output"])/"compute.json"
    native_compute=read(compute_path) if compute_path.exists() else None
    native_counters=native_compute["actual_native_model_counters"] if native_compute is not None else None
    complete=driver is not None and len(driver["cases"])==plan["positions"] and all(
        row["status"] in ("COMPLETED","FAILED_FIRST_FORWARD") for row in driver["cases"])
    owner.update(status="CHILD_EXITED_COST_PENDING",exit_code=code,whole_child_CPU_seconds=cpu,
        wall_seconds=wall,whole_prediction_coverage=complete,native_model_counters=native_counters,
        child_already_charged_native_CPU=False,
        GPU2_job_interval_hours_including_load_IO=wall/3600,
        cost_scope="Whole child including imports, model loading, all first forwards, serialization and failures. No nested model/compute receipt is added again. Parent through billing measured once; launcher/cleanup unknown_not_zero.")
    write_json(owner_path,owner)
    with ledger.with_name("budget.json.http-owner.lock").open("a+b") as lease:
        fcntl.flock(lease,fcntl.LOCK_EX)
        before=read(ledger)
        assert plan["compute_phase"] not in before["compute"]
        assert all(before[k]==before_ledger[k] for k in ("limits","generation","generation_requests","embedding"))
        parent_cpu=time.process_time()
        measures={"cpu_seconds":cpu+parent_cpu,"runs":1,"reserved64_model_segments":1,"cuda_job_wall_seconds":wall}
        if native_counters is not None:measures.update(native_counters)
        RunBudget(RunLimits(**before["limits"]),ledger).record_compute(plan["compute_phase"],measures)
        after=read(ledger)
        assert all(before[k]==after[k] for k in ("limits","generation","generation_requests","embedding"))
        assert all(after["compute"][k]==v for k,v in before["compute"].items())
    owner.update(status="CLOSED_RESERVED64_FIRST_PREDICTIONS_RETAINED" if complete else "FAILED_RETAINED",
        client_CPU_recorded=True,client_compute_phase=plan["compute_phase"],
        parent_CPU_seconds_through_billing=parent_cpu,unmetered_launch_cleanup_CPU="unknown_not_zero")
    write_json(owner_path,owner)
    print("RESERVED64_NATIVE_SEGMENT_EXITED",plan["model"],code,"coverage",complete,"CPU",cpu,flush=True)
raise SystemExit(code)

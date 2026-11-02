"""Serialize one declared fresh request after original CPU closure and settlement."""

from __future__ import annotations

import argparse
import os
import resource
import subprocess
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from run_bound_optimization_host import active_model_owners, local_cpu_accounting


def prerequisites(plan: dict[str, Any], settlement: Path | None) -> dict[str, Any]:
    """Read actual closure records; a live process is never treated as a failed job."""
    active = active_model_owners()
    checks = {}
    for name, expected in (
        ("cpu_driver", "COMPLETED"),
        ("cpu_verification",
         "SAVED_CPU_SELECTED_RETENTION_JOB_VERIFIED;WHOLE_FIT_RETENTION_NOT_INFERRED"),
        ("fit_retention", "SAVED_CPU_SELECTION_AND_RETENTION_VERIFIED;HOST_EVALUATION_PENDING"),
    ):
        path = Path(plan[name])
        value = read_json(path) if path.exists() else None
        checks[name] = value is not None and value["status"] == expected
        if value is not None and checks[name]:
            if name in {"cpu_driver", "cpu_verification"}:
                checks[name] = value["job_id"] == plan["cpu_job_id"]
            else:
                checks[name] = value["run_id"] == plan["cpu_job_id"].split("/")[0]
            if name == "cpu_driver":
                checks[name] = checks[name] and all(
                    not Path("/proc", str(value[k])).exists() for k in ("pid", "child_pid"))
    checks["settlement"] = False
    if settlement is not None and settlement.exists():
        paid = read_json(settlement)
        ledger = read_json(Path(plan["original_ledger"]))
        checks["settlement"] = (
            paid["status"] == "SETTLED_ONCE_WITH_NO_NEURAL_JOB_ACTIVE"
            and paid["job_id"] == plan["cpu_job_id"]
            and ledger["compute"].get(paid["phase"]) == paid["measures"])
    return {"status": "READY" if not active and all(checks.values()) else "WAITING",
            "active_model_pids": active, "checks": checks, "model_calls": 0}


def run_job(plan: dict[str, Any], settlement: Path) -> dict[str, Any]:
    """One subprocess; retain failure and charge only through the native ledger owner."""
    started = time.perf_counter()
    admission = prerequisites(plan, settlement)
    if admission["status"] != "READY":
        raise ValueError(f"Fresh request prerequisites are not closed: {admission}")
    ready = read_json(Path(plan["request_readiness"]))
    preparation = read_json(Path(ready["preparation"]))
    condition, = preparation["conditions"]
    if (ready["status"] != "KNOWN_SUFFICIENT_FRESH_SINGLE_REQUEST_BOUND_NOT_EXECUTED"
            or condition["arm"] != "baseline"
            or preparation["original_ledger"] != plan["original_ledger"]):
        raise ValueError("Coordinator requires the declared single baseline request")
    output = Path(ready["output"])
    if output.exists():
        raise ValueError("The declared fresh output already exists; do not retry")
    owner = Path(plan["owner"])
    owner.mkdir(parents=True, exist_ok=False)
    ledger = Path(plan["original_ledger"])
    before = read_json(ledger)
    write_json(owner / "budget-before.json", before)
    report: dict[str, Any] = {
        "status": "LAUNCHING", "pid": os.getpid(), "request_readiness": plan["request_readiness"],
        "settlement": str(settlement.resolve()), "prerequisites": admission,
        "argv": ready["argv"], "output": str(output), "automatic_retry": False,
        "ledger_recorded": False, "host_request_generated": False,
    }
    write_json(owner / "driver.json", report)
    initial = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        with (owner / "native.log").open("x") as stream:
            child = subprocess.Popen(  # noqa: S603 -- prebound local interpreter and runner
                ready["argv"], cwd=ready["cwd"], env={**os.environ, **ready["environment"]},
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
            report.update(status="RUNNING", child_pid=child.pid, started_epoch=time.time())
            write_json(owner / "driver.json", report)
            print("STARTED_FRESH_REQUEST", os.getpid(), child.pid, flush=True)
            report["exit_code"] = child.wait()
        native = read_json(output / "run.json") if (output / "run.json").exists() else None
        report["native_status"] = native["status"] if native is not None else None
        report["call_captures"] = native["call_captures"] if native is not None else []
        report["actual_initial_states"] = native["actual_initial_states"] if native else None
        if report["exit_code"] == 0:
            if (native is None or native["status"] != "COMPLETED"
                    or not native["exact_starting_bank_values"]
                    or native["request"] != condition["request"]
                    or native["host_request_generated"]
                    or native["budget_before"] != before
                    or native["budget_after"] != read_json(ledger)):
                raise ValueError("Fresh native closure does not match the declared request/budget")
            report["status"] = "COMPLETED"
        else:
            report["status"] = "FAILED_RETAINED"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        final = resource.getrusage(resource.RUSAGE_CHILDREN)
        whole = final.ru_utime + final.ru_stime - initial.ru_utime - initial.ru_stime
        after = read_json(ledger)
        write_json(owner / "budget-after.json", after)
        # Persist measured boundaries even if a ledger reconciliation itself fails.
        report["whole_child_cpu_seconds"] = whole
        report.update(wall_seconds=time.perf_counter() - started,
                      orchestration_cpu_seconds_pending=time.process_time(),
                      coordinator_cpu_scope="Whole dedicated coordinator process through closure; "
                      "production CLI invokes run_job once, including interpreter/import CPU.",
                      scope="One controlled fresh retrieval call, without Host readout. Native "
                      "HTTP/local scorer costs stay in the original ledger; remaining whole-child "
                      "and coordinator CPU await idle settlement. No retry or automatic next job.")
        write_json(owner / "driver.json", report)
        try:
            accounting = local_cpu_accounting(before, after, whole)
        except BaseException as error:
            report.update(status="ACCOUNTING_FAILED_RETAINED",
                          error_type=type(error).__name__, error=str(error))
            write_json(owner / "driver.json", report)
            raise
        report["cpu_accounting_scope"] = accounting.pop("scope")
        report.update(accounting)
        write_json(owner / "driver.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--settlement", type=Path)
    parser.add_argument("--inspect", action="store_true", help="Read gates without launching")
    args = parser.parse_args()
    plan = read_json(args.plan)
    if args.inspect:
        print(prerequisites(plan, args.settlement))
        return
    if args.settlement is None:
        parser.error("Execution requires the actual original CPU settlement record")
    report = run_job(plan, args.settlement)
    print(report["status"], flush=True)
    if report["status"] != "COMPLETED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

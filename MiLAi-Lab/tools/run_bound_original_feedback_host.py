"""Own one original nine-fit Host arm after its actual saved/retention bindings close."""

from __future__ import annotations

import argparse
import os
import resource
import subprocess
import time
from pathlib import Path
from typing import Any, cast

from milai_lab.harness.artifact_io import read_json, write_json
from prepare_original_feedback_host import inspect_bindings
from run_bound_optimization_host import MODEL_ENTRIES, active_model_owners, local_cpu_accounting

MODEL_ENTRIES.add("run_bound_original_feedback_host.py")


def validate_original_arm(
    dispatch: dict[str, Any], saved_root: Path, arm_id: str,
) -> dict[str, Any]:
    study = dispatch["study"]
    if (dispatch["status"] != "ALL_ORIGINAL_SAVED_POLICIES_BOUND_NOT_EXECUTED"
            or dispatch["automatic_retry"]
            or study["schema"] != "original_feedback_autonomous_host_v1"
            or len(study["fits"]) != 9 or study["positions_per_arm"] != 16
            or study["family_units"] != 8):
        raise ValueError("Original Host dispatch requires its complete nine-fit/16-position study")
    verified = inspect_bindings(study, saved_root)
    if verified["status"] != "READY" or verified != dispatch["bindings"]:
        raise ValueError("Actual nine-fit saved/retention bindings changed or remain incomplete")
    # Reconcile the declared aliases and execution denominator, including shared CE points.
    expected: list[dict[str, Any]] = [
        {"id": name, "policy": name, "aliases": []} for name in ("fixed_context", "rules")
    ]
    base = str(Path(study["common_initialization"]).resolve())
    expected.append({"id": "jev_initialization", "policy": "laya",
                     "checkpoint": study["common_initialization"],
                     "aliases": ["original_source256_update262"]})
    by_checkpoint = {base: expected[-1]}
    for fit in verified["fits"]:
        for target, point in fit["deployment_selection"].items():
            checkpoint = str(Path(point["checkpoint"]).resolve())
            if checkpoint not in by_checkpoint:
                descriptor: dict[str, Any] = {
                    "id": f"{fit['run_id']}-{target}-selected-u{point['update']}",
                    "policy": "laya", "checkpoint": checkpoint, "aliases": [],
                }
                expected.append(descriptor)
                by_checkpoint[checkpoint] = descriptor
            by_checkpoint[checkpoint]["aliases"].append({
                "run_id": fit["run_id"], "target": target, "update": point["update"],
                "selection": fit["selection"], "retention": fit["retention"],
            })
    descriptors = [
        {k: a[k] for k in ("id", "policy", "aliases", "checkpoint") if k in a}
        for a in dispatch["arms"]
    ]
    if (descriptors != expected or dispatch["unique_arms"] != len(expected)
            or dispatch["planned_positions"] != 16 * len(expected)):
        raise ValueError("Original selected-checkpoint aliases or task denominator changed")
    arm, = [a for a in dispatch["arms"] if a["id"] == arm_id]
    argv = arm["argv"]
    entry = argv.index(str(Path(study["runtime"]) / "tools/run_host_intent_retrieval.py"))
    if (argv[entry + 1:entry + 4] != [arm["config"], study["histories"], arm["output"]]
            or argv[argv.index("--policies") + 1] != arm["policy"]
            or argv[argv.index("--source-version") + 1] != study["source_version"]
            or argv[argv.index("--interfaces") + 1] != "rich"
            or argv[argv.index("--split") + 1] != "dev"
            or "--continue-host-history" not in argv or "--capture-control-steps" not in argv
            or any(flag in argv for flag in ("--given-requests", "--native-probe"))
            or arm["environment"]["CUDA_VISIBLE_DEVICES"] != ""
            or Path(arm["cwd"]).resolve() != Path(study["runtime"]).resolve()):
        raise ValueError("Original Host command changed its autonomous task or inference protocol")
    host_site = dispatch["host_site_packages"]
    if host_site is not None and (
        argv[-2:] != ["--host-site-packages", host_site]
        or host_site in arm["environment"]["PYTHONPATH"].split(":")
    ):
        raise ValueError("Host dependencies must use the declared appended site directory")
    expected_config = read_json(Path(study["config_template"]))
    settings = expected_config["entrypoints"]["functional"]
    settings["memory_control"]["policy"] = arm["policy"]
    if "checkpoint" in arm:
        settings["memory_control"]["checkpoint"] = arm["checkpoint"]
    settings["config_version"] += "-host-followup-" + arm["id"]
    if (read_json(Path(arm["config"])) != expected_config
            or settings["budget_path"] != dispatch["ledger"]):
        raise ValueError("Bound original Host configuration differs from its declared template")
    if Path(arm["output"]).exists() or Path(arm["output"] + "-inference.json").exists():
        raise ValueError("Existing original Host attempts are retained; no automatic retry")
    return cast(dict[str, Any], arm)


def run_arm(dispatch_path: Path, saved_root: Path, arm_id: str, receipt: Path) -> dict[str, Any]:
    started, cpu_started = time.perf_counter(), time.process_time()
    active = active_model_owners()
    if active:
        raise ValueError(f"Another actual model job is alive: {active}")
    dispatch = read_json(dispatch_path)
    arm = validate_original_arm(dispatch, saved_root, arm_id)
    ledger = Path(dispatch["ledger"])
    before = read_json(ledger)
    receipt.mkdir(parents=True, exist_ok=False)
    write_json(receipt / "budget-before.json", before)
    report: dict[str, Any] = {
        "status": "LAUNCHING", "pid": os.getpid(), "dispatch": str(dispatch_path.resolve()),
        "saved_root": str(saved_root.resolve()), "arm_id": arm_id, "output": arm["output"],
        "source_version": dispatch["study"]["source_version"], "argv": arm["argv"],
        "environment": arm["environment"], "automatic_retry": False,
        "planned_positions": dispatch["study"]["positions_per_arm"], "ledger_recorded": False,
    }
    driver = receipt / "driver.json"
    write_json(driver, report)
    usage0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        with (receipt / "host.log").open("x") as stream:
            child = subprocess.Popen(  # noqa: S603 -- bound original local entry and recipe
                arm["argv"], cwd=arm["cwd"], env={**os.environ, **arm["environment"]},
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
            report.update(status="RUNNING", child_pid=child.pid, started_epoch=time.time())
            write_json(driver, report)
            print("STARTED_ORIGINAL_HOST", arm_id, os.getpid(), child.pid, flush=True)
            code = child.wait()
        report["exit_code"] = code
        native_path = Path(arm["output"]) / "driver.json"
        inference_path = Path(arm["output"] + "-inference.json")
        native = read_json(native_path) if native_path.exists() else None
        inference = read_json(inference_path) if inference_path.exists() else None
        report.update(native_status=native["status"] if native else None,
                      inference_status=inference["status"] if inference else None)
        after = read_json(ledger)
        if code == 0:
            if (native is None or inference is None
                    or native["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}
                    or inference["status"] != "COMPLETED"
                    or len(native["completed"]) != report["planned_positions"]
                    or read_json(Path(arm["output"]) / "budget-before.json") != before
                    or read_json(Path(arm["output"]) / "budget-after.json") != after):
                raise ValueError("Original Host closure or actual ledger boundaries differ")
            report["status"] = ("COMPLETED" if native["status"] == "COMPLETED"
                                else "COMPLETED_WITH_NATIVE_FAILURES_RETAINED")
        else:
            report["status"] = "FAILED_RETAINED"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        after = read_json(ledger)
        write_json(receipt / "budget-after.json", after)
        usage1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        whole = usage1.ru_utime + usage1.ru_stime - usage0.ru_utime - usage0.ru_stime
        report["whole_child_cpu_seconds"] = whole
        try:
            report.update(local_cpu_accounting(before, after, whole))
        except BaseException as error:
            report.update(status="ACCOUNTING_FAILED_RETAINED",
                          accounting_error_type=type(error).__name__, accounting_error=str(error))
            raise
        finally:
            report.update(wall_seconds=time.perf_counter() - started,
                          orchestration_cpu_seconds_pending=time.process_time() - cpu_started,
                          scope="One original arm only. Actual worker owns HTTP/local model "
                                "ledger entries; this coordinator does not settle or start a "
                                "next arm. Nested message/driver/inference CPU is not extra. "
                                "Unmeasured interpreter/import overhead remains unknown. "
                                "Failed/unexecuted positions and actual semantic reviews remain.")
            write_json(driver, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispatch", type=Path)
    parser.add_argument("saved_root", type=Path)
    parser.add_argument("arm_id")
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    report = run_arm(args.dispatch, args.saved_root, args.arm_id, args.receipt)
    print(report["status"], args.arm_id, flush=True)
    raise SystemExit(report["exit_code"])


if __name__ == "__main__":
    main()

"""One complete P3 or conditionally admitted P4 matrix; no retry or next candidate."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from v0220_evidence import LAB, save
from v0220_provider_hardened import ProviderStop
from v0222_presentation_batch import Batch
from v0222_presentation_worker import stop_batch


def run_child(command: list[str], *, timeout: float, on_failure) -> dict:
    started = time.monotonic()
    child = subprocess.Popen(  # noqa: S603 - fixed sealed worker; tests use local Python only
        command, cwd=LAB, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    timed_out = False
    try:
        stdout, stderr = child.communicate(timeout=timeout)
    except BaseException as exc:
        # Lock before cleanup/evidence writes; never leave an owned worker running.
        try:
            on_failure(exc)
        finally:
            child.kill()
            stdout, stderr = child.communicate()
        if not isinstance(exc, subprocess.TimeoutExpired):
            raise
        timed_out = True
    if child.returncode != 0:
        on_failure(ProviderStop("PRESENTATION_WORKER_STOPPED"))
    return {
        "pid": child.pid,
        "parent_pid": os.getpid(),
        "returncode": child.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "seconds": time.monotonic() - started,
        "timed_out": timed_out,
    }


def run(root: Path, binding: str, stage: str) -> dict:
    batch, rows, error = None, [], None
    try:
        batch = Batch(root, binding)
        if stage not in {"P3", "P4"}:
            raise ProviderStop("ONLY_FULL_VALIDATION_OR_CONDITIONAL_EXECUTION")
        batch.launch_once(stage)
        with batch.transaction() as db:
            deadline = float(
                db.execute("SELECT value FROM meta WHERE key=?", (stage + "_deadline",)).fetchone()[
                    0
                ]
            )
        for spec in batch.plan[stage]:
            batch.authorize(stage)
            with batch.transaction() as db:
                batch.check_journal(db)
            remaining = min(300.0, deadline - time.time())
            if remaining <= 0:
                raise ProviderStop("BATCH_PHASE_DEADLINE")
            exit_record = run_child(
                [
                    sys.executable,
                    str(LAB / "tools/v0222_presentation_worker.py"),
                    "--root",
                    str(root),
                    "--binding-sha256",
                    binding,
                    "--episode",
                    spec["id"],
                ],
                timeout=remaining,
                on_failure=lambda exc: stop_batch(root, binding, batch, exc),
            )
            save(root / "exits" / (spec["id"] + ".json"), exit_record)
            if exit_record["returncode"] != 0 or exit_record["timed_out"]:
                raise ProviderStop("PRESENTATION_WORKER_STOPPED")
            result = batch.finish(spec["id"])  # Independent raw/usage/effects audit + freeze.
            if result["pid"] != exit_record["pid"] or result["pid"] == os.getpid():
                raise ProviderStop("ACTUAL_COLD_CHILD_PID_NOT_PROVEN")
            rows.append(result)
        if stage == "P3":
            gate = batch.p3_gate()
            path = root / "P3-gate.json"
            save(path, gate)
            batch.freeze_p3_gate(path)
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        if batch is None or stage not in {"P3", "P4"} or not isinstance(exc, Exception):
            raise
        error = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
    try:
        snapshot = batch.snapshot()
        result = {
            "status": (
                "FULL_FIDELITY_PASS"
                if stage == "P3" and len(rows) == 16 and not snapshot["stop"]
                else "KNOWN_INTENT_PASS"
                if stage == "P4" and len(rows) == 24 and not snapshot["stop"]
                else "FULL_STAGE_NOT_MET"
            ),
            "stage": stage,
            "passed": len(rows),
            "rows": rows,
            "error": error,
            "batch": snapshot,
            "unrun": [s["id"] for s in snapshot["episodes"] if s["status"] == "PENDING"],
            "Memory": "NOT_ADMITTED",
            "Judge": 0,
            "direct_device_calls": 0,
        }
        save(root / (stage + "-result.json"), result)
        return result
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--stage", choices=("P3", "P4"), required=True)
    args = parser.parse_args()
    run(args.root, args.binding_sha256, args.stage)

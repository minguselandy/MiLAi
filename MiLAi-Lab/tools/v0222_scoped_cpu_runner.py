"""Complete CPU replay stages with sequential real, guarded Python workers.

This is not a model-capability gate. Only the fixed local worker bootstrap may
be launched; parent and each child install socket denial before stack imports.
Original phase/chain deadlines, exit-before-finish, P3 gate and stop rules remain.
Use run_v0222_scoped_cpu.py; this module is not a standalone unguarded command.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from run_v0222_presentation import run_child
from v0220_evidence import LAB, save
from v0220_provider_hardened import ProviderStop
from v0222_scoped_cpu_batch import OfflineBatch as Batch
from v0222_scoped_cpu_guard import CPU_MODE, require_cpu_network_guard
from v0222_scoped_cpu_worker import stop_batch


def run(root: Path, binding: str, stage: str) -> dict:
    require_cpu_network_guard()
    batch, rows, error = None, [], None
    try:
        if stage not in {"P3", "P4"}:
            raise ProviderStop("ONLY_FULL_VALIDATION_OR_CONDITIONAL_EXECUTION")
        batch = Batch(root, binding)
        batch.launch_once(stage)
        for spec in batch.plan[stage]:
            # One explicit admission; no historical/global reader patching.
            with batch._operation(stage) as (db, _scope, _state):
                deadline = float(
                    db.execute(
                        "SELECT value FROM meta WHERE key=?", (stage + "_deadline",)
                    ).fetchone()[0]
                )
            remaining = min(300.0, deadline - time.time())
            if remaining <= 0:
                raise ProviderStop("BATCH_PHASE_DEADLINE")
            exit_record = run_child(
                [
                    sys.executable,
                    str(LAB / "tools/run_v0222_scoped_cpu_worker.py"),
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
            audit = batch.finish(spec["id"])
            if audit["pid"] != exit_record["pid"] or audit["pid"] == os.getpid():
                raise ProviderStop("ACTUAL_COLD_CHILD_PID_NOT_PROVEN")
            rows.append(audit)
        if stage == "P3":
            # This API derives, re-audits and freezes in one scoped operation.
            batch.freeze_p3_gate(root / "P3-gate.json")
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        if batch is None or stage not in {"P3", "P4"} or not isinstance(exc, Exception):
            raise
        error = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
    try:
        snapshot = batch.snapshot()
        result = {
            "status": (
                "CPU_REPLAY_P3_PASS"
                if stage == "P3" and len(rows) == 16 and error is None and not snapshot["stop"]
                else "CPU_REPLAY_P4_PASS"
                if stage == "P4" and len(rows) == 24 and error is None and not snapshot["stop"]
                else "CPU_REPLAY_STAGE_NOT_MET"
            ),
            "execution_mode": CPU_MODE,
            "real_http_requests": 0,
            "real_model_requests": 0,
            "mock_cost_is_not_real_cost": True,
            "model_capability_or_live_admission": False,
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


def main():
    require_cpu_network_guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--stage", choices=("P3", "P4"), required=True)
    args = parser.parse_args()
    result = run(args.root, args.binding_sha256, args.stage)
    return 0 if result["status"] in {"CPU_REPLAY_P3_PASS", "CPU_REPLAY_P4_PASS"} else 1

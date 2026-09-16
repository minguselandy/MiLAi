"""One finite 8+conditional8 residual-boundary matrix; no old-batch resumption."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from v0220_evidence import LAB, save
from v0220_provider_hardened import ProviderStop
from v0222_boundary_batch import Batch


def run(root: Path, binding: str) -> dict:
    batch = Batch(root, binding)
    batch.launch_once()
    rows, decision = [], None
    try:
        for spec in batch.plan["episodes"]:
            if len(rows) == 8:
                decision = batch.decision(final=False)
                path = root / "firstpass-decision.json"
                save(path, decision)
                batch.set_decision(path, final=False)
                if not decision["repeat_required"]:
                    break
            started = time.monotonic()
            child = subprocess.run(  # noqa: S603 - one sealed owned cold worker
                [
                    sys.executable,
                    str(LAB / "tools/v0222_boundary_worker.py"),
                    "--root",
                    str(root),
                    "--binding-sha256",
                    binding,
                    "--episode",
                    spec["id"],
                ],
                cwd=LAB,
                capture_output=True,
                text=True,
                timeout=310,
            )
            save(
                root / "exits" / (spec["id"] + ".json"),
                {
                    "returncode": child.returncode,
                    "stdout": child.stdout,
                    "stderr": child.stderr,
                    "seconds": time.monotonic() - started,
                },
            )
            if child.returncode != 0:
                raise ProviderStop("BOUNDARY_WORKER_STOPPED")
            result = batch.finish(spec["id"])
            if result["pid"] == os.getpid():
                raise ProviderStop("COLD_CLIENT_PROCESS_NOT_PROVEN")
            rows.append(result)
            print(
                json.dumps(
                    {
                        "episode": spec["id"],
                        "condition": spec["condition"],
                        "exact": result["exact_fidelity"],
                        "known_raw": batch.snapshot()["cost"]["known_raw_tokens"],
                    }
                ),
                flush=True,
            )
        if len(rows) == 16 and not batch.snapshot()["stop"]:
            decision = batch.decision(final=True)
            path = root / "final-decision.json"
            save(path, decision)
            batch.set_decision(path, final=True)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        batch.stop(reason)
    try:
        snapshot = batch.snapshot()
        result = {
            "status": "BOUNDARY_FATAL_STOP" if snapshot["stop"] else decision["status"],
            "decision": decision,
            "rows": rows,
            "batch": snapshot,
            "unrun": [s["id"] for s in snapshot["episodes"] if s["status"] == "PENDING"],
            "business_dispatches": 0,
            "direct_device_calls": 0,
            "full_fidelity_and_execution": "NOT_ADMITTED_BY_DIAGNOSTIC",
            "Memory": "NOT_ADMITTED",
            "Judge": 0,
        }
        save(root / "result.json", result)
    except Exception as exc:
        batch.stop(type(exc).__name__)
        raise
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    args = parser.parse_args()
    run(args.root, args.binding_sha256)

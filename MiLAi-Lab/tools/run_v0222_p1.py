"""Finite P1 diagnostic matrix; contents observed, fatal failures stop all stages."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from v0220_evidence import LAB, read, save
from v0220_provider_hardened import ProviderStop
from v0222_batch import Batch


def _sequence(batch: Batch) -> dict:
    root, binding = batch.root, batch.binding_sha
    rows, decision = [], None
    for spec in batch.plan["P1"]:
        if len(rows) == 12:
            decision = batch.p1_decision()
            path = root / "P1-firstpass-decision.json"
            save(path, decision)
            batch.set_p1_decision(path)
            if not decision["repeat_required"]:
                break
        try:
            started = time.monotonic()
            child = subprocess.run(  # noqa: S603 - fixed owned cold worker and bound identifiers
                [
                    sys.executable,
                    str(LAB / "tools/v0222_p1_worker.py"),
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
                raise ProviderStop("P1_WORKER_STOPPED")
            path = root / "episodes" / spec["id"] / "observation.json"
            result = read(path)
            if result["pid"] == os.getpid():
                raise ProviderStop("COLD_CLIENT_PROCESS_NOT_PROVEN")
            batch.freeze_artifact(spec["id"] + "_observation", path)
            batch.finish(spec["id"], "OBSERVED")
            rows.append({**spec, **result})
            print(
                json.dumps(
                    {
                        "episode": spec["id"],
                        "fixture": spec["fixture"],
                        "condition": spec["condition"],
                        "exact": result["exact_fidelity"],
                        "known_raw": batch.snapshot()["cost"]["known_raw_tokens"],
                    }
                ),
                flush=True,
            )
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
            batch.stop(reason)
            break
    if len(rows) == 24 and not batch.snapshot()["stop"]:
        decision = batch.p1_decision(final=True)
        path = root / "P1-final-selection.json"
        save(path, decision)
        batch.set_p1_decision(path, final=True)
    snapshot = batch.snapshot()
    result = {
        "status": "P1_FATAL_STOP" if snapshot["stop"] else decision["status"],
        "rows": rows,
        "decision": decision,
        "batch": snapshot,
        "business_dispatches": 0,
        "direct_device_calls": 0,
        "unrun": [r["id"] for r in snapshot["episodes"] if r["status"] == "PENDING"],
    }
    save(root / "P1-result.json", result)
    return result


def run(root: Path, binding: str) -> dict:
    batch = Batch(root, binding)
    batch.launch_once("P1")
    try:
        return _sequence(batch)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        batch.stop(reason)
        snapshot = batch.snapshot()
        result = {
            "status": "P1_COORDINATOR_FATAL_STOP",
            "reason": reason,
            "batch": snapshot,
            "unrun": [r["id"] for r in snapshot["episodes"] if r["status"] == "PENDING"],
        }
        if not (root / "P1-result.json").exists():
            save(root / "P1-result.json", result)
        else:
            save(root / "P1-coordinator-error.json", result)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    args = parser.parse_args()
    run(args.root, args.binding_sha256)

"""One P3 matrix or conditional P4 matrix; first acceptance failure is terminal."""

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
from v0222_batch import Batch
from v0222_full_audit import audit


def run(root: Path, binding: str, stage: str) -> dict:
    if stage not in {"P3", "P4"}:
        raise ValueError("ONLY_FULL_VALIDATION_OR_CONDITIONAL_EXECUTION")
    batch = Batch(root, binding)
    batch.launch_once(stage)
    rows = []
    try:
        for spec in batch.plan[stage]:
            started = time.monotonic()
            child = subprocess.run(  # noqa: S603 - sealed own worker and stage/episode arguments
                [
                    sys.executable,
                    str(LAB / "tools/v0222_full_worker.py"),
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
                raise ProviderStop("FULL_STAGE_WORKER_STOPPED")
            result = audit(batch, spec["id"])
            path = root / "audits" / (spec["id"] + ".json")
            # Freeze all episode receipts/canonical/usage before permitting the next cold process.
            from v0220_evidence import sha

            result["files"] = {
                str(p): sha(p) for p in sorted((root / "episodes" / spec["id"]).rglob("*.json"))
            }
            result["files"][
                str(root / "episodes" / spec["id"] / "provider/provider-ledger-v2.jsonl")
            ] = sha(root / "episodes" / spec["id"] / "provider/provider-ledger-v2.jsonl")
            save(path, result)
            if result["status"] != "PASS" or result["pid"] == os.getpid():
                raise ProviderStop("INDEPENDENT_FULL_INTENT_OR_EFFECT_AUDIT_FAILED")
            batch.freeze_artifact(spec["id"] + "_audit", path, "PASS")
            batch.finish(spec["id"])
            rows.append(result)
            print(
                json.dumps(
                    {
                        "episode": spec["id"],
                        "stage": stage,
                        "status": "PASS",
                        "requests": batch.snapshot()["cost"]["requests"],
                        "known_raw": batch.snapshot()["cost"]["known_raw_tokens"],
                    }
                ),
                flush=True,
            )
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        batch.stop(reason)
    snapshot = batch.snapshot()
    result = {
        "status": "FULL_FIDELITY_PASS"
        if stage == "P3" and len(rows) == 16 and not snapshot["stop"]
        else "KNOWN_INTENT_PASS"
        if stage == "P4" and len(rows) == 24 and not snapshot["stop"]
        else "FULL_STAGE_NOT_MET",
        "stage": stage,
        "passed": len(rows),
        "rows": rows,
        "batch": snapshot,
        "unrun": [
            s["id"]
            for s in snapshot["episodes"]
            if s["stage"] == stage and s["status"] == "PENDING"
        ],
        "Memory": "NOT_ADMITTED",
        "Judge": 0,
        "direct_device_calls": 0,
    }
    save(root / (stage + "-result.json"), result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--stage", choices=("P3", "P4"), required=True)
    args = parser.parse_args()
    run(args.root, args.binding_sha256, args.stage)

"""One bounded W2 / conditional W3 sequence. First failure permanently stops batch."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from v0220_evidence import LAB, read, save
from v0221_http_audit import audit
from v0221_http_batch import Batch


def run(root: Path, binding: str) -> dict:
    batch = Batch(root, binding)
    if read(root / "preflight/result.json")["status"] != "G_PREFLIGHT_PASS":
        raise ValueError("PREFLIGHT_REQUIRED_BEFORE_LIVE_LAUNCH")
    batch.launch_once()
    rows = []
    for spec in [*batch.plan["W2"], *batch.plan["W3"]]:
        if batch.snapshot()["stop"]:
            break
        batch.authorize(spec["stage"])
        started = time.monotonic()
        try:
            child = subprocess.run(  # noqa: S603 - frozen owned worker, one client at a time
                [
                    sys.executable,
                    str(LAB / "tools/v0221_http_worker.py"),
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
            exit_receipt = {
                "returncode": child.returncode,
                "stdout": child.stdout,
                "stderr": child.stderr,
            }
        except subprocess.TimeoutExpired:
            exit_receipt = {"returncode": None, "status": "OWNED_WORKER_TIMEOUT_NO_USAGE_INFERENCE"}
        save(root / "exits" / (spec["id"] + ".json"), exit_receipt)
        if exit_receipt["returncode"] != 0:
            verdict = {"status": "FAIL", "reason": "WORKER_STOPPED"}
        else:
            try:
                verdict = audit(root, spec)
                if verdict["pid"] == os.getpid():
                    raise ValueError("COLD_CLIENT_PROCESS_NOT_PROVEN")
            except Exception as exc:
                verdict = {"status": "FAIL", "reason": "AUDIT_" + type(exc).__name__}
        row = {
            "episode": spec["id"],
            "stage": spec["stage"],
            "root": spec["root"],
            "seconds": time.monotonic() - started,
            **verdict,
        }
        save(root / "audits" / (spec["id"] + ".json"), row)
        rows.append(row)
        if verdict["status"] == "PASS":
            batch.finish(spec["id"])
        else:
            batch.stop(verdict.get("reason", "INTENT_OR_EFFECT_AUDIT_FAILED"))
        snapshot = batch.snapshot()
        print(
            json.dumps(
                {
                    "episode": spec["id"],
                    "stage": spec["stage"],
                    "status": verdict["status"],
                    "requests": snapshot["cost"]["requests"],
                    "known_raw": snapshot["cost"]["known_raw_tokens"],
                }
            ),
            flush=True,
        )
    snapshot = batch.snapshot()
    passed_w2 = sum(r["status"] == "PASS" and r["stage"] == "W2" for r in rows)
    passed_w3 = sum(r["status"] == "PASS" and r["stage"] == "W3" for r in rows)
    result = {
        "status": "LIVE_COMPAT_PASS_KNOWN_INTENT_PASS_MEMORY_NOT_ADMITTED"
        if passed_w2 == 16 and passed_w3 == 24
        else "BOUNDED_LIVE_CHECK_NOT_MET",
        "W2_pass": passed_w2,
        "W3_pass": passed_w3,
        "rows": rows,
        "batch": snapshot,
        "historical_usage": batch.auth["historical"],
        "unrun": [r["id"] for r in snapshot["episodes"] if r["status"] == "PENDING"],
        "direct_device_queries": 0,
        "Judge": 0,
        "Memory": "NOT_ADMITTED",
    }
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    args = parser.parse_args()
    run(args.root, args.binding_sha256)

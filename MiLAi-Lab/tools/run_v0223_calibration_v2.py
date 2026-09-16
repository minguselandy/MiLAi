"""Fixed six-process U/S calibration; no retries, model calls or Gate A verdict."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path


def read_worker_evidence(directory, child, *, mode, contract_sha256):
    """Bind raw result and start header to this actual child before acceptance."""
    start = json.loads((directory / "worker-start.json").read_bytes())
    raw = (directory / "worker-result.json").read_bytes()
    result = json.loads(raw)
    if (
        type(start) is not dict
        or type(result) is not dict
        or start.get("pid") != child["pid"]
        or start.get("mode") != mode
        or start.get("contract_sha256") != contract_sha256
        or type(result.get("observer")) is not dict
        or result["observer"].get("pid") != child["pid"]
    ):
        raise ValueError("MISSING_OR_WRONG_PROCESS_RESULT")
    if result.get("status") == "MEASUREMENT_STOP":
        raise ValueError("WORKER_REPORTED_MEASUREMENT_STOP")
    if result.get("measurement_readiness") == "NOT_READY_FOR_K1":
        raise ValueError("WORKER_NOT_K1_READY")
    return result, hashlib.sha256(raw).hexdigest()


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from run_v0222_presentation import run_child
    from run_v0223_admission_pair_v2 import validate_contract
    from v0220_evidence import LAB, save, sha

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    args = parser.parse_args()
    if sha(args.contract) != args.contract_sha256:
        raise ValueError("K0_CONTRACT_HASH_MISMATCH")
    contract = json.loads(args.contract.read_bytes())
    # The worker performs the same field checks independently in each process.
    validate_contract(contract, "k1-u1", "U")
    for name, digest in contract["files"].items():
        if sha(Path(name)) != digest:
            raise ValueError("K0_EXECUTABLE_OR_INPUT_DRIFT")
    out = args.contract.parent / "calibration"
    out.mkdir(exist_ok=False)
    start = time.monotonic()
    save(out / "start.json", {"unix": time.time(), "contract_sha256": args.contract_sha256})
    rows, failures = [], []
    for position in contract["calibration_order"]:
        instance, mode = position["instance"], position["mode"]
        row = {"instance": instance, "mode": mode}
        rows.append(row)
        try:
            child = run_child(
                [
                    sys.executable,
                    str(LAB / "tools/run_v0223_admission_pair_v2.py"),
                    "--contract",
                    str(args.contract),
                    "--contract-sha256",
                    args.contract_sha256,
                    "--instance",
                    instance,
                    "--mode",
                    mode,
                ],
                timeout=300,
                on_failure=lambda exc: failures.append(type(exc).__name__),
            )
            row["exit"] = child
            save(out / (instance + "-exit.json"), child)
            if child["returncode"] != 0 or child["timed_out"]:
                failures.append("CHILD_NONZERO_OR_TIMEOUT")
                break
            row["result"], row["result_sha256"] = read_worker_evidence(
                args.contract.parent / instance,
                child,
                mode=mode,
                contract_sha256=args.contract_sha256,
            )
        except Exception as exc:
            row["evidence_failure"] = {"type": type(exc).__name__, "reason": str(exc)}
            failures.append(type(exc).__name__)
            break
    ratios = []
    if len(rows) == 6 and not failures:
        for left, right in zip(rows[::2], rows[1::2], strict=True):
            pair = {row["mode"]: row for row in (left, right)}
            ratios.append(pair["S"]["exit"]["seconds"] / pair["U"]["exit"]["seconds"])
    result = {
        "status": "SIX_EXITS_PENDING_INDEPENDENT_COVERAGE_AUDIT"
        if len(ratios) == 3
        else "CALIBRATION_STOP",
        "rows": rows,
        "failures": failures,
        "not_run": contract["calibration_order"][len(rows) :],
        "paired_S_over_U_outer_wall": ratios,
        "median_ratio": statistics.median(ratios) if ratios else None,
        "maximum_process_wall_seconds": max(
            (r["exit"]["seconds"] for r in rows if "exit" in r), default=None
        ),
        "parent_wall_before_final_report_seconds": time.monotonic() - start,
        "http_requests": 0,
        "model_requests": 0,
        "limits": [
            "This terminal preserves exits; matching semantic/coverage audit is still required.",
            "Parent exit/report overhead requires the invoking process record.",
            "No K1 or Gate A PASS is issued by this runner.",
        ],
    }
    save(out / "terminal.json", result)
    return 0 if len(ratios) == 3 else 1


if __name__ == "__main__":
    sys.exit(main())

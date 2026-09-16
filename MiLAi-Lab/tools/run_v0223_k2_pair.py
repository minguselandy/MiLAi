"""Exactly one original and one candidate U prefix, in that order, no retries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def read_worker_evidence(directory, child, position, contract_sha256):
    header = json.loads((directory / "worker-start.json").read_bytes())
    raw = (directory / "worker-result.json").read_bytes()
    result = json.loads(raw)
    if type(header) is not dict or type(result) is not dict:
        raise ValueError("WRONG_OR_FAILED_RAW_CHILD_EVIDENCE")
    if (
        header.get("pid") != child["pid"]
        or result.get("pid") != child["pid"]
        or header.get("contract_sha256") != contract_sha256
        or any(
            value.get("variant") != position["variant"]
            or value.get("instance") != position["instance"]
            or value.get("mode") != "U"
            for value in (header, result)
        )
        or result.get("status") != "PREFIX_REACHED_NOT_REFERENCE_PASS"
    ):
        raise ValueError("WRONG_OR_FAILED_RAW_CHILD_EVIDENCE")
    return result, hashlib.sha256(raw).hexdigest()


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from run_v0222_presentation import run_child
    from run_v0223_k2_prefix import validate_contract
    from v0220_evidence import LAB, save, sha

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    args = parser.parse_args()
    if sha(args.contract) != args.contract_sha256:
        raise ValueError("K2_CONTRACT_HASH_MISMATCH")
    contract = json.loads(args.contract.read_bytes())
    validate_contract(contract, "k2-base")
    for name, digest in contract["files"].items():
        if sha(Path(name)) != digest:
            raise ValueError("K2_EXECUTABLE_OR_INPUT_DRIFT")
    out = args.contract.parent / "pair"
    out.mkdir(exist_ok=False)
    save(
        out / "start.json",
        {"unix": time.time(), "pid": os.getpid(), "contract_sha256": args.contract_sha256},
    )
    start = time.monotonic()
    rows, failures = [], []
    interruption = None
    for position in contract["pair_order"]:
        row = {"instance": position["instance"], "variant": position["variant"]}
        rows.append(row)
        try:
            child = run_child(
                [
                    sys.executable,
                    str(LAB / "tools/run_v0223_k2_prefix.py"),
                    "--contract",
                    str(args.contract),
                    "--contract-sha256",
                    args.contract_sha256,
                    "--instance",
                    position["instance"],
                ],
                timeout=3600,
                on_failure=lambda exc: failures.append(type(exc).__name__),
            )
            row["exit"] = child
            save(out / (position["instance"] + "-exit.json"), child)
            if child["returncode"] != 0 or child["timed_out"] or child["seconds"] > 3600:
                failures.append("CHILD_NONZERO_TIMEOUT_OR_COMPLETE_OUTER_LIMIT")
                break
            directory = args.contract.parent / position["instance"]
            row["result"], row["result_sha256"] = read_worker_evidence(
                directory,
                child,
                position,
                args.contract_sha256,
            )
        except BaseException as exc:
            failures.append(type(exc).__name__)
            row["evidence_failure"] = {"type": type(exc).__name__, "reason": str(exc)}
            if "exit" not in row:
                row["exit_receipt_limit"] = (
                    "Original run_child cleans up a spawned worker on wait exception, "
                    "but does not return its exit receipt on a non-timeout exception. "
                    "No successful exit is inferred."
                )
            if not isinstance(exc, Exception):
                interruption = exc
            break
    complete = len(rows) == 2 and not failures
    save(
        out / "terminal.json",
        {
            "status": "TWO_EXITS_PENDING_INDEPENDENT_EQUIVALENCE_AUDIT"
            if complete
            else "K2_PAIR_STOP",
            "rows": rows,
            "failures": failures,
            "not_run": contract["pair_order"][len(rows) :],
            "candidate_over_original_outer_wall": rows[1]["exit"]["seconds"]
            / rows[0]["exit"]["seconds"]
            if complete
            else None,
            "parent_wall_before_final_report_seconds": time.monotonic() - start,
            "http_requests": 0,
            "model_requests": 0,
            "limits": [
                "No equivalence or Gate A PASS issued by this runner.",
                "Outer invoking-process receipt must include parent report and exit.",
                "communicate has a 3600-second wait ceiling; complete spawn/cleanup "
                "wall must also be <=3600 or this pair stops before the next position.",
            ],
        },
    )
    if interruption is not None:
        raise interruption
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())

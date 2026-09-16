"""First P4 reference prefix through two original runtime guards, CPU only.

This worker does not construct fixtures, alter deadlines, or send HTTP. The
parent must measure spawn through exit: 300 seconds for calibration, 3600 for
the conditional 55-scope prefix. K0 and calibration review remain external. A worker
report is not a terminal process result or a complete reference Session.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

CALIBRATION_ORDER = (
    ("k1-u1", "U"),
    ("k1-s1", "S"),
    ("k1-s2", "S"),
    ("k1-u2", "U"),
    ("k1-u3", "U"),
    ("k1-s3", "S"),
)


def validate_contract(contract, instance, mode, *, prefix55=False):
    """Pure refusal checks; a well-shaped contract is not independent K0 review."""
    if sys.getprofile() is not None or sys.gettrace() is not None:
        raise ValueError("UNPROFILED_UNTRACED_PROCESS_REQUIRED")
    if contract.get("status") != "K0_FROZEN" or any(
        type(contract.get(key)) is not int or contract[key] != 0
        for key in ("http_requests_allowed", "model_requests_allowed")
    ):
        raise ValueError("REVIEWED_CPU_ONLY_K0_REQUIRED")
    order = contract.get("calibration_order")
    if type(order) is not list or any(type(row) is not dict for row in order):
        raise ValueError("FROZEN_SIX_PROCESS_ORDER_REQUIRED")
    if tuple((row.get("instance"), row.get("mode")) for row in order) != CALIBRATION_ORDER:
        raise ValueError("FROZEN_SIX_PROCESS_ORDER_REQUIRED")
    if prefix55:
        prefix = contract.get("prefix55", {})
        if (
            instance != "k1-prefix"
            or mode != "S"
            or prefix.get("instance") != instance
            or prefix.get("mode") != mode
        ):
            raise ValueError("FROZEN_55_SCOPE_S_PREFIX_REQUIRED")
        selected = [prefix]
    else:
        selected = [row for row in order if row["instance"] == instance]
        if len(selected) != 1 or selected[0]["mode"] != mode:
            raise ValueError("FROZEN_U_S_POSITION_REQUIRED")
    if type(contract.get("files")) is not dict or not contract["files"]:
        raise ValueError("FROZEN_EXECUTABLE_AND_INPUT_CLOSURE_REQUIRED")
    return selected[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--mode", choices=("U", "S"), required=True)
    parser.add_argument("--prefix55", action="store_true")
    parser.add_argument("--calibration-review-sha256")
    args = parser.parse_args()
    if sys.getprofile() is not None or sys.gettrace() is not None:
        raise ValueError("UNPROFILED_UNTRACED_PROCESS_REQUIRED")
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    raw = args.contract.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.contract_sha256:
        raise ValueError("K0_CONTRACT_HASH_MISMATCH")
    contract = json.loads(raw)
    position = validate_contract(contract, args.instance, args.mode, prefix55=args.prefix55)
    os.environ["MILA_V0223_INSTANCE"] = args.instance
    from v0220_evidence import save, sha
    from v0222_presentation_lineage_v2 import verify_lineage  # noqa: F401
    from v0223_coarse_observation import CoarseObserver, installed
    from v0223_cpu_batch_v2 import OfflineBatch, selected_root
    from v0223_reference_prefix_v2 import run_reference_prefix

    if args.prefix55:
        review_path = args.contract.parent / "calibration-review.json"
        if not args.calibration_review_sha256 or sha(review_path) != args.calibration_review_sha256:
            raise ValueError("CALIBRATION_REVIEW_HASH_REQUIRED_FOR_PREFIX55")
        review = json.loads(review_path.read_bytes())
        if (
            review.get("status") != "MEASUREMENT_CALIBRATION_PASS"
            or review.get("contract_sha256") != args.contract_sha256
        ):
            raise ValueError("MATCHING_CALIBRATION_PASS_REQUIRED_FOR_PREFIX55")
        if type(review.get("files")) is not dict or not review["files"]:
            raise ValueError("CALIBRATION_EVIDENCE_REQUIRED")
        for name, digest in review["files"].items():
            if sha(Path(name)) != digest:
                raise ValueError("CALIBRATION_EVIDENCE_CHANGED")
    root = selected_root()
    if (
        position["root"] != str(root)
        or sha(root / "execution-binding.json") != position["binding_sha256"]
    ):
        raise ValueError("FROZEN_FIXTURE_BINDING_REQUIRED")
    for name, digest in contract["files"].items():
        if sha(Path(name)) != digest:
            raise ValueError("K0_EXECUTABLE_OR_INPUT_DRIFT")
    out = args.contract.parent / args.instance
    out.mkdir(exist_ok=False)
    save(
        out / "worker-start.json",
        {
            "pid": os.getpid(),
            "unix": time.time(),
            "mode": args.mode,
            "contract_sha256": args.contract_sha256,
        },
    )
    observer = CoarseObserver(args.instance, enabled=args.mode == "S")
    started = time.perf_counter_ns()
    failure = None
    try:
        with installed(observer, batch_class=OfflineBatch), observer.span("execution"):
            prefix = run_reference_prefix(
                lambda: OfflineBatch(root, position["binding_sha256"]),
                out / "reference-prefix",
                full_prefix=args.prefix55,
                observe_internal_timing=args.mode == "S",
            )
        result = {
            "status": prefix["terminal_status"],
            "prefix": prefix,
            "original_reference_deadline_ns": 60_000_000_000,
        }
        if prefix["terminal_status"] != "PREFIX_REACHED_NOT_REFERENCE_PASS":
            failure = RuntimeError(prefix["terminal_status"])
    except BaseException as exc:
        failure = exc
        result = {
            "status": "MEASUREMENT_STOP",
            "exception_type": type(exc).__name__,
            "reason": str(exc),
        }
    result.update(
        observer=observer.report(),
        measurement_readiness="PARENT_CALIBRATION_REVIEW_REQUIRED",
        coverage_equivalence="NOT_ESTABLISHED",
        original_reference_session_executed=(
            result.get("prefix", {}).get("session_result") is not None
        ),
        workload_wall_ns=time.perf_counter_ns() - started,
        http_requests=0,
        model_requests=0,
        limits=[
            "Parent must include import, contract verification, report IO and exit.",
            "Two guards alone do not establish the complete 60-second Session.",
            "The first-generate cutoff is a diagnostic FAIL_CLOSED, not a reference PASS.",
            "COMPLETE_SPANS is observation closure, not validation coverage equivalence.",
            "A parent must compare all six outputs and coverage before the 1.10 overhead gate.",
        ],
    )
    save(out / "worker-result.json", result)
    if failure is not None:
        raise failure
    return 0


if __name__ == "__main__":
    sys.exit(main())

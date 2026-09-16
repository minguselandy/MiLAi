"""One current-candidate five-scope U/S diagnostic, never a K3 success run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

CALIBRATION_ORDER = (
    ("k3-u1", "U"),
    ("k3-s1", "S"),
    ("k3-s2", "S"),
    ("k3-u2", "U"),
    ("k3-u3", "U"),
    ("k3-s3", "S"),
)
CPU_BASE = Path("/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-current-v1")


def _unprofiled():
    if sys.getprofile() is not None or sys.gettrace() is not None:
        raise ValueError("UNPROFILED_UNTRACED_PROCESS_REQUIRED")


def _digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_contract(contract, instance, mode):
    _unprofiled()
    if (
        type(contract) is not dict
        or contract.get("status") != "CURRENT_CANDIDATE_CALIBRATION_FROZEN"
    ):
        raise ValueError("REVIEWED_CURRENT_CANDIDATE_CALIBRATION_REQUIRED")
    if (
        contract.get("execution_revision") != "V0224_GATE_A_EXECUTION_R02"
        or contract.get("baseline_policy") != "TRANSACTION_PRIMARY_FIX_BOTH_MODES"
        or contract.get("candidate_policy") != "TREE_CANDIDATE_BOTH_MODES"
    ):
        raise ValueError("SAME_CURRENT_CANDIDATE_AND_CORRECTED_BASELINE_REQUIRED")
    for key, value in {
        "http_requests_allowed": 0,
        "model_requests_allowed": 0,
        "concurrency": 1,
        "calibration_outer_seconds": 300,
        "session_seconds": 60,
        "expected_scope_count": 5,
    }.items():
        if type(contract.get(key)) is not int or contract[key] != value:
            raise ValueError("EXACT_CPU_ONLY_CALIBRATION_LIMITS_REQUIRED")
    if (
        type(contract.get("overhead_median_limit")) not in (int, float)
        or contract["overhead_median_limit"] != 1.10
    ):
        raise ValueError("UNCHANGED_MEDIAN_OVERHEAD_LIMIT_REQUIRED")
    order = contract.get("calibration_order")
    if (
        type(order) is not list
        or any(type(row) is not dict for row in order)
        or tuple((row.get("instance"), row.get("mode")) for row in order) != CALIBRATION_ORDER
    ):
        raise ValueError("FROZEN_SIX_PROCESS_ORDER_REQUIRED")
    for row in order:
        if (
            row.get("variant") != "candidate"
            or row.get("root") != str(CPU_BASE / ("currentv1-" + row["instance"]))
            or not _digest(row.get("binding_sha256"))
        ):
            raise ValueError("EXACT_CURRENT_CANDIDATE_ROOT_AND_BINDING_REQUIRED")
    files = contract.get("files")
    if (
        type(files) is not dict
        or not files
        or any(
            type(path) is not str or not Path(path).is_absolute() or not _digest(digest)
            for path, digest in files.items()
        )
    ):
        raise ValueError("COMPLETE_EXECUTABLE_AND_INPUT_PINS_REQUIRED")
    selected = [row for row in order if row["instance"] == instance and row["mode"] == mode]
    if len(selected) != 1:
        raise ValueError("FROZEN_U_S_POSITION_REQUIRED")
    return selected[0]


@contextmanager
def installed_current_stack(observer, *, batch_class):
    """Explicit fixed order; private JSON is timed inside tree inventory spans."""
    _unprofiled()
    from v0222_scoped_cpu_guard import require_cpu_network_guard

    require_cpu_network_guard()
    from v0222_presentation_lineage_v2 import verify_lineage  # noqa: F401
    from v0223_coarse_observation import installed
    from v0223_transaction_primary_fix import installed_transaction_fix
    from v0223_tree_readonly_candidate import installed_candidate

    with (
        installed_transaction_fix(),
        installed_candidate(),
        installed(observer, batch_class=batch_class),
    ):
        yield observer


def observation_coverage(prefix, report, mode):
    """Report complete parse events without pretending public-reader timing is total."""
    total = sum(row["stats"]["json_parses"] for row in prefix["coverage"]["scopes"])
    public = (
        sum(row["json_docs"] for row in report["records"] if row["category"] == "json_parse_copy")
        if mode == "S"
        else None
    )
    return {
        "scope_json_parse_events": total,
        "observed_public_read_json_parse_events": public,
        "unclassified_private_parse_events": total - public if public is not None else None,
        "json_parse_copy_meaning": "Public read_json calls only, not all JSON parse/copy work.",
        "private_work": (
            "Private parse/scan/sentinel/fallback copy remains in inventory "
            "exclusive time; no subtraction."
        ),
        "failed_call_counts": "Successful-call counters only; failure counts may be lower bounds.",
    }


def main():
    _unprofiled()
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--mode", choices=("U", "S"), required=True)
    args = parser.parse_args()
    raw = args.contract.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.contract_sha256:
        raise ValueError("CURRENT_CALIBRATION_CONTRACT_HASH_MISMATCH")
    contract = json.loads(raw)
    position = validate_contract(contract, args.instance, args.mode)
    os.environ["MILA_V0223_INSTANCE"] = args.instance
    from v0220_evidence import save, sha
    from v0223_coarse_observation import CoarseObserver
    from v0223_current_cpu_batch import OfflineBatch, selected_root
    from v0223_reference_prefix_v2 import run_reference_prefix

    root = selected_root()
    if (
        position["root"] != str(root)
        or sha(root / "execution-binding.json") != position["binding_sha256"]
    ):
        raise ValueError("EXACT_CURRENT_CALIBRATION_ROOT_REQUIRED")
    for name, digest in contract["files"].items():
        if sha(Path(name)) != digest:
            raise ValueError("CURRENT_CALIBRATION_INPUT_OR_EXECUTABLE_DRIFT")
    out = args.contract.parent / args.instance
    out.mkdir(exist_ok=False)
    save(
        out / "worker-start.json",
        {
            "pid": os.getpid(),
            "unix": time.time(),
            "instance": args.instance,
            "variant": "candidate",
            "mode": args.mode,
            "contract_sha256": args.contract_sha256,
        },
    )
    observer = CoarseObserver(args.instance, enabled=args.mode == "S")
    started, failure = time.perf_counter_ns(), None
    try:
        with (
            installed_current_stack(observer, batch_class=OfflineBatch),
            observer.span("execution"),
        ):
            prefix = run_reference_prefix(
                lambda: OfflineBatch(root, position["binding_sha256"]),
                out / "reference-prefix",
                full_prefix=False,
                observe_internal_timing=args.mode == "S",
            )
        result = {"status": prefix["terminal_status"], "prefix": prefix}
        if prefix["terminal_status"] != "PREFIX_REACHED_NOT_REFERENCE_PASS":
            failure = RuntimeError(prefix["terminal_status"])
    except BaseException as exc:
        failure = exc
        result = {
            "status": "CURRENT_CALIBRATION_STOP",
            "exception_type": type(exc).__name__,
            "reason": str(exc),
        }
    report = observer.report()
    result.update(
        pid=os.getpid(),
        instance=args.instance,
        variant="candidate",
        mode=args.mode,
        observer=report,
        workload_wall_ns=time.perf_counter_ns() - started,
        baseline_policy="TRANSACTION_PRIMARY_FIX_BOTH_MODES",
        http_requests=0,
        model_requests=0,
        limits=[
            "Parent complete spawn/exit bound is300s including imports, pins, report and exit.",
            "Five-scope cutoff is not reference success, calibration or K3 PASS.",
            "Median S/U<=1.10 requires independent all-six coverage/semantic audit.",
        ],
    )
    if "prefix" in result:
        result["observation_coverage"] = observation_coverage(result["prefix"], report, args.mode)
    save(out / "worker-result.json", result)
    if failure is not None:
        raise failure
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""One frozen original/candidate U historical prefix; never a reference PASS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from contextlib import nullcontext
from pathlib import Path

PAIR_ORDER = (("k2-base", "original"), ("k2-edit", "candidate"))


def validate_contract(contract, instance):
    if sys.getprofile() is not None or sys.gettrace() is not None:
        raise ValueError("UNPROFILED_UNTRACED_PROCESS_REQUIRED")
    if contract.get("status") != "K2_PAIR_FROZEN":
        raise ValueError("INDEPENDENTLY_REVIEWED_K2_PAIR_REQUIRED")
    if (
        contract.get("execution_revision") != "V0224_GATE_A_EXECUTION_R02"
        or contract.get("baseline_policy") != "TRANSACTION_PRIMARY_FIX_BOTH_ARMS"
    ):
        raise ValueError("EXPLICIT_SHARED_CORRECTED_BASELINE_REQUIRED")
    if any(
        type(contract.get(k)) is not int or contract[k] != 0
        for k in ("http_requests_allowed", "model_requests_allowed")
    ):
        raise ValueError("ZERO_HTTP_AND_MODEL_REQUIRED")
    positions = contract.get("pair_order")
    if type(positions) is not list or any(type(p) is not dict for p in positions):
        raise ValueError("FIXED_ORIGINAL_CANDIDATE_PAIR_REQUIRED")
    if tuple((p.get("instance"), p.get("variant")) for p in positions) != PAIR_ORDER:
        raise ValueError("FIXED_ORIGINAL_CANDIDATE_PAIR_REQUIRED")
    if any(p.get("mode") != "U" for p in positions):
        raise ValueError("BOTH_FROZEN_POSITIONS_MUST_BE_U")
    if contract.get("prefix_outer_seconds") != 3600 or contract.get("session_seconds") != 60:
        raise ValueError("UNCHANGED_PREFIX_AND_SESSION_LIMITS_REQUIRED")
    if type(contract.get("files")) is not dict or not contract["files"]:
        raise ValueError("COMPLETE_PINNED_INPUTS_REQUIRED")
    selected = [p for p in positions if p["instance"] == instance]
    if len(selected) != 1 or selected[0].get("mode") != "U":
        raise ValueError("ONLY_ONE_FROZEN_U_POSITION_REQUIRED")
    return selected[0]


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    raw = args.contract.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.contract_sha256:
        raise ValueError("K2_CONTRACT_HASH_MISMATCH")
    contract = json.loads(raw)
    position = validate_contract(contract, args.instance)
    os.environ["MILA_V0223_INSTANCE"] = args.instance
    from v0220_evidence import save, sha
    from v0222_presentation_lineage_v2 import verify_lineage  # noqa: F401
    from v0223_k2_cpu_batch import OfflineBatch, selected_root
    from v0223_reference_prefix_v2 import run_reference_prefix
    from v0223_transaction_primary_fix import installed_transaction_fix
    from v0223_tree_readonly_candidate import installed_candidate

    root = selected_root()
    if (
        position["root"] != str(root)
        or sha(root / "execution-binding.json") != position["binding_sha256"]
    ):
        raise ValueError("EXACT_FROZEN_K2_ROOT_REQUIRED")
    for path, digest in contract["files"].items():
        if sha(Path(path)) != digest:
            raise ValueError("K2_INPUT_OR_EXECUTABLE_DRIFT")
    out = args.contract.parent / args.instance
    out.mkdir(exist_ok=False)
    save(
        out / "worker-start.json",
        {
            "pid": os.getpid(),
            "unix": time.time(),
            "instance": args.instance,
            "variant": position["variant"],
            "mode": "U",
            "contract_sha256": args.contract_sha256,
        },
    )
    start = time.perf_counter_ns()
    failure = None
    try:
        context = installed_candidate() if position["variant"] == "candidate" else nullcontext()
        with installed_transaction_fix(), context:
            prefix = run_reference_prefix(
                lambda: OfflineBatch(root, position["binding_sha256"]),
                out / "reference-prefix",
                full_prefix=True,
                observe_internal_timing=False,
            )
        result = {"status": prefix["terminal_status"], "prefix": prefix}
        if prefix["terminal_status"] != "PREFIX_REACHED_NOT_REFERENCE_PASS":
            failure = RuntimeError(prefix["terminal_status"])
    except BaseException as exc:
        failure = exc
        result = {
            "status": "K2_PREFIX_STOP",
            "exception_type": type(exc).__name__,
            "reason": str(exc),
        }
    result.update(
        pid=os.getpid(),
        instance=args.instance,
        variant=position["variant"],
        mode="U",
        workload_wall_ns=time.perf_counter_ns() - start,
        http_requests=0,
        model_requests=0,
        limits=[
            "Outer parent must include imports, integrity checks, reporting and exit.",
            "Strict U has no internal timing; no admission share inferred.",
            "This diagnostic is not full preparation, equivalence or Gate A PASS.",
        ],
    )
    save(out / "worker-result.json", result)
    if failure is not None:
        raise failure
    return 0


if __name__ == "__main__":
    sys.exit(main())

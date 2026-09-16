"""One parent-owned 300s preparation lifecycle, including independent-review wait.

Only the trusted host may send the externally pinned approval on stdin. This
controller never discovers an approval hash, approves evidence, or retries.
External actual parent exit remains necessary; the helper cannot attest its exit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

LIMIT_SECONDS = 300
APPROVAL_BYTES_LIMIT = 65536
FINALIZER_CODE = (
    "import json,sys;from v0222_scoped_cpu_guard import enable_cpu_network_guard;"
    "enable_cpu_network_guard();"
    "from finalize_v0224_bundle_authority import finalize_authority;"
    "print(json.dumps(finalize_authority(**dict(zip("
    "('candidate_path','candidate_sha256','mechanical_path','mechanical_sha256',"
    "'approval_path','approval_sha256'),sys.argv[1:],strict=True)))))"
)


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("COMPLETE_PREPARATION_300_SECONDS_EXHAUSTED")
    return remaining


def _group_gone(pid):
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _cleanup_owned(child):
    notes = []
    gone = False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            gone = True
        except BaseException as exc:
            notes.append(repr(exc))
        try:
            child.wait(timeout=5)
        except BaseException as exc:
            notes.append(repr(exc))
        try:
            gone = _group_gone(child.pid)
        except BaseException as exc:
            gone = None
            notes.append(repr(exc))
        if gone:
            break
    return {
        "returncode": child.returncode,
        "owned_group_gone": gone,
        "cleanup_complete": child.returncode is not None and gone is True,
        "cleanup_notes": notes,
    }


def _run_child(argv, phase, out, deadline, children):
    row = {"phase": phase, "argv": argv, "pid": None, "returncode": None, "cleanup_complete": None}
    children.append(row)
    start = time.monotonic()
    child = None
    primary_error = None
    try:
        _remaining(deadline)
        with (
            (out / (phase + ".stdout")).open("xb") as stdout,
            (out / (phase + ".stderr")).open("xb") as stderr,
        ):
            child = subprocess.Popen(  # noqa: S603 -- fixed executable/code; values are separate argv
                argv,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                cwd=Path(__file__).resolve().parent,
            )
            row["pid"] = child.pid
            with (out / (phase + ".start.json")).open("x") as stream:
                json.dump(row, stream, allow_nan=False)
            child.wait(timeout=_remaining(deadline))
            row["returncode"] = child.returncode
            if not _group_gone(child.pid):
                raise RuntimeError("OWNED_CHILD_LEFT_PROCESS_GROUP")
            row.update(owned_group_gone=True, cleanup_complete=True)
            _remaining(deadline)
            if child.returncode != 0:
                raise RuntimeError("PREPARATION_CHILD_FAILED: " + phase)
    except BaseException as primary:
        primary_error = primary
        row.update(exception_type=type(primary).__name__, reason=str(primary))
        if child is not None and row.get("cleanup_complete") is not True:
            row.update(_cleanup_owned(child))
        raise
    finally:
        row["elapsed_seconds"] = time.monotonic() - start
        try:
            with (out / (phase + ".exit.json")).open("x") as stream:
                json.dump(row, stream, allow_nan=False)
        except BaseException as record_error:
            if primary_error is None:
                raise
            primary_error.add_note("SECONDARY_CHILD_TERMINAL_RECORD: " + repr(record_error))
    return row


def _approval_input(path, deadline, fd):
    buffer = bytearray()
    while True:
        ready, _, _ = select.select([fd], [], [], _remaining(deadline))
        if not ready:
            raise TimeoutError("INDEPENDENT_APPROVAL_WAIT_EXHAUSTED")
        chunk = os.read(fd, min(4096, APPROVAL_BYTES_LIMIT + 1 - len(buffer)))
        if not chunk:
            raise ValueError("TRUSTED_HOST_APPROVAL_INPUT_EOF")
        buffer.extend(chunk)
        if len(buffer) > APPROVAL_BYTES_LIMIT:
            raise ValueError("BOUNDED_APPROVAL_INPUT_REQUIRED")
        if b"\n" in buffer:
            from v0222_scoped_evidence import _strict_json

            value = _strict_json(bytes(buffer).decode("utf-8"))
            if (
                type(value) is not dict
                or set(value) != {"approval_path", "approval_sha256"}
                or value["approval_path"] != str(path)
                or type(value["approval_sha256"]) is not str
                or re.fullmatch("[0-9a-f]{64}", value["approval_sha256"]) is None
            ):
                raise ValueError("EXACT_EXTERNALLY_PINNED_APPROVAL_INPUT_REQUIRED")
            _remaining(deadline)
            return value


def _pinned_json(path, digest):
    from v0222_admission_read_scope import AdmissionReadScope

    with AdmissionReadScope() as scope:
        value = scope.read_json(path, digest)
    return value


def run_preparation(contract_path, contract_sha256, *, approval_fd=0):
    start = time.monotonic()
    deadline = start + LIMIT_SECONDS
    if sys.getprofile() is not None or sys.gettrace() is not None or threading.active_count() != 1:
        raise ValueError("UNPROFILED_UNTRACED_SINGLE_THREAD_PARENT_REQUIRED")
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from prepare_v0224_bundle_authority import _validate_contract
    from v0220_evidence import dependencies
    from v0222_admission_read_scope import AdmissionReadScope
    from v0224_static_bundle import canonical_json

    contract_path = Path(contract_path)
    if (
        not contract_path.is_absolute()
        or contract_path.resolve() != contract_path
        or ".." in contract_path.parts
    ):
        raise ValueError("CANONICAL_FROZEN_PREPARATION_CONTRACT_REQUIRED")
    out = contract_path.parent / "preparation-controller-v1"
    out.mkdir(exist_ok=False)
    children = []
    phase = "verify_frozen_contract"
    record = {
        "status": "PREPARATION_INCOMPLETE",
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "contract_sha256": contract_sha256,
        "children": children,
    }
    try:
        with AdmissionReadScope() as scope:
            contract = scope.read_json(contract_path, contract_sha256)
            _validate_contract(contract, {str(p) for p in dependencies([Path(__file__).resolve()])})
            for name, digest in contract["files"].items():
                scope.read_bytes(Path(name), digest)
        _remaining(deadline)
        tools = Path(__file__).resolve().parent
        phase = "authority_builder"
        authority_child = _run_child(
            [
                sys.executable,
                str(tools / "prepare_v0224_bundle_authority.py"),
                "--contract-path",
                str(contract_path),
                "--contract-sha256",
                contract_sha256,
            ],
            phase,
            out,
            deadline,
            children,
        )
        directory = contract_path.parent / "authority-v1"
        report_path = directory / "authority-prepared.json"
        report = _pinned_json(report_path, hashlib.sha256(report_path.read_bytes()).hexdigest())
        if (
            report["status"] != "READY_FOR_INDEPENDENT_AUTHORITY_REVIEW"
            or report["runtime_authorized"] is not False
            or report["pid"] != authority_child["pid"]
            or report["contract_sha256"] != contract_sha256
        ):
            raise ValueError("ACTUAL_AUTHORITY_CHILD_REPORT_REQUIRED")
        generated = report["generated_files"]
        candidate_path = directory / "sealed/candidate-receipt.json"
        mechanical_path = directory / "revalidated/mechanical-revalidation.json"
        bundle_path = directory / "sealed/static.bundle"
        observation_path = directory / "sealed/seal-observation.json"
        if set(generated) != {
            str(p) for p in (candidate_path, mechanical_path, bundle_path, observation_path)
        }:
            raise ValueError("EXACT_CURRENT_AUTHORITY_OUTPUTS_REQUIRED")
        candidate = _pinned_json(candidate_path, generated[str(candidate_path)])
        if candidate["bundle_sha256"] != generated[str(bundle_path)]:
            raise ValueError("ACTUAL_BUNDLE_OUTPUT_BINDING_REQUIRED")
        phase = "waiting_for_independent_approval"
        wait_start = time.monotonic()
        print("WAITING_FOR_INDEPENDENT_APPROVAL", flush=True)
        approval = _approval_input(
            contract_path.parent / "independent-authority-approval.json", deadline, approval_fd
        )
        record["approval_wait_seconds"] = time.monotonic() - wait_start
        record["approval"] = approval
        phase = "finalizer"
        _run_child(
            [
                sys.executable,
                "-c",
                FINALIZER_CODE,
                str(candidate_path),
                generated[str(candidate_path)],
                str(mechanical_path),
                generated[str(mechanical_path)],
                approval["approval_path"],
                approval["approval_sha256"],
            ],
            phase,
            out,
            deadline,
            children,
        )
        # The finalizer import path is provided by the controller's fixed tools cwd.
        from v0222_scoped_evidence import _strict_json

        finalizer = _strict_json((out / "finalizer.stdout").read_text())
        receipt_path = directory / "approved-receipt.json"
        if finalizer["status"] != "APPROVED_RECEIPT_MATERIALIZED_NOT_GATE_A" or finalizer[
            "path"
        ] != str(receipt_path):
            raise ValueError("ACTUAL_FINALIZER_RESULT_REQUIRED")
        receipt = _pinned_json(receipt_path, finalizer["sha256"])
        if receipt != {**candidate, "status": "INDEPENDENT_STATIC_BUNDLE_APPROVED"}:
            raise ValueError("FINALIZED_RECEIPT_NOT_EXACT_APPROVED_CANDIDATE")
        phase = "fixture_preparer"
        argv = [
            sys.executable,
            str(tools / "prepare_v0224_bundle_fixture_v2.py"),
            "--instance",
            "bundle-v2-slice",
            "--bundle-path",
            str(bundle_path),
            "--bundle-sha256",
            candidate["bundle_sha256"],
            "--receipt-path",
            str(receipt_path),
            "--receipt-sha256",
            finalizer["sha256"],
        ]
        for name, value in contract["limits"].items():
            argv.extend(["--" + name.replace("_", "-"), str(value)])
        _run_child(argv, phase, out, deadline, children)
        phase = "parent_input_recheck"
        with AdmissionReadScope() as scope:
            current_contract = scope.read_json(contract_path, contract_sha256)
            if current_contract != contract:
                raise ValueError("FINAL_PARENT_CONTRACT_DRIFT")
            for name, digest in contract["files"].items():
                scope.read_bytes(Path(name), digest)
        _remaining(deadline)
        record["final_parent_input_scope_stats"] = scope.stats
        phase = "parent_report"
        _remaining(deadline)
        record.update(
            status="PREPARATION_STEPS_COMPLETE_EXTERNAL_EXIT_REQUIRED",
            elapsed_before_report_seconds=time.monotonic() - start,
        )
        with (out / "preparation-result.json").open("xb") as stream:
            stream.write(canonical_json(record))
        _remaining(deadline)
        return record
    except BaseException as primary:
        record.update(
            status="PREPARATION_FAILED_NO_RETRY",
            phase=phase,
            exception_type=type(primary).__name__,
            reason=str(primary),
            elapsed_seconds=time.monotonic() - start,
        )
        try:
            with (out / "preparation-failure.json").open("xb") as stream:
                stream.write(canonical_json(record))
        except BaseException as secondary:
            primary.add_note("SECONDARY_PREPARATION_FAILURE_RECORD: " + repr(secondary))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-path", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    args = parser.parse_args()
    run_preparation(args.contract_path, args.contract_sha256)


if __name__ == "__main__":
    main()

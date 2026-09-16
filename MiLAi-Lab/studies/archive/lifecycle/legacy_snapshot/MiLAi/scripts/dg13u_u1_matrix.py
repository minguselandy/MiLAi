#!/usr/bin/env python3
"""Serial, fail-fast orchestrator for the exact DG-13U U1 case matrix."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg13u_u1_aggregate as aggregate
from scripts import dg13u_u1_openworker as runner

RUNS_ROOT = ROOT / "var/dg13/runs"
MATRIX_TMP_ROOT = ROOT / "var/dg13/matrix-tmp"
MATRIX_LOCK = ROOT / "var/dg13/dg13u-u1-matrix.lock"
RUNNER_SCRIPT = ROOT / "scripts/dg13u_u1_openworker.py"
MATRIX_SCHEMA = "milai.dg13u.u1-matrix-terminal.v1"
_BATCH_ID = re.compile(r"[a-z0-9][a-z0-9-]{7,31}")
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")
_EXPECTED_CASE_COUNT = 37
_CASE_TIMEOUT_SECONDS = 1_800
_MAX_RECEIPT_BYTES = 16 * 1024 * 1024


class MatrixError(RuntimeError):
    """A typed matrix preflight or orchestration boundary failed closed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _absolute(path: str | Path, code: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise MatrixError(code)
    return Path(os.path.normpath(os.fspath(candidate)))


def _reject_symlink_chain(path: Path, code: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(metadata.st_mode):
            raise MatrixError(code)


def _validate_inputs(
    batch_id: str, env_file: str | Path, output: str | Path
) -> tuple[Path, Path]:
    if _BATCH_ID.fullmatch(batch_id) is None:
        raise MatrixError("BATCH_ID_INVALID")
    environment = _absolute(env_file, "ENV_FILE_PATH_INVALID")
    _reject_symlink_chain(environment, "ENV_FILE_SYMLINK_REJECTED")
    if not environment.is_file() or environment.is_symlink():
        raise MatrixError("ENV_FILE_NOT_REGULAR")
    destination = _absolute(output, "OUTPUT_PATH_INVALID")
    _reject_symlink_chain(destination, "OUTPUT_SYMLINK_REJECTED")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    for controlled_root in (RUNS_ROOT, MATRIX_TMP_ROOT):
        if not controlled_root.is_absolute():
            raise MatrixError("CONTROLLED_ROOT_NOT_ABSOLUTE")
        _reject_symlink_chain(controlled_root, "CONTROLLED_ROOT_SYMLINK_REJECTED")
        try:
            controlled_root.relative_to(ROOT)
        except ValueError:
            raise MatrixError("CONTROLLED_ROOT_ESCAPE") from None
        try:
            destination.relative_to(controlled_root)
        except ValueError:
            pass
        else:
            raise MatrixError("OUTPUT_PATH_CONFLICTS_WITH_RUN_ROOT")
    _reject_symlink_chain(RUNNER_SCRIPT, "RUNNER_SCRIPT_SYMLINK_REJECTED")
    if not RUNNER_SCRIPT.is_file() or RUNNER_SCRIPT.is_symlink():
        raise MatrixError("RUNNER_SCRIPT_NOT_REGULAR")
    return environment, destination


@contextmanager
def _global_matrix_lock() -> Any:
    _reject_symlink_chain(MATRIX_LOCK, "MATRIX_LOCK_SYMLINK_REJECTED")
    MATRIX_LOCK.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(
        MATRIX_LOCK,
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MatrixError("MATRIX_ALREADY_RUNNING") from None
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _contract_case_ids() -> tuple[str, ...]:
    runner_cases = tuple(runner.CASES)
    runner_set = set(runner_cases)
    implemented = set(runner._IMPLEMENTED_REAL_CASES)
    aggregate_cases = tuple(aggregate.REQUIRED_CASE_IDS)
    if (
        len(runner_cases) != _EXPECTED_CASE_COUNT
        or len(runner_set) != _EXPECTED_CASE_COUNT
    ):
        raise MatrixError("MATRIX_RUNNER_CASE_COUNT_INVALID")
    if implemented != runner_set:
        raise MatrixError("MATRIX_IMPLEMENTATION_SET_INCOMPLETE")
    if (
        len(aggregate_cases) != _EXPECTED_CASE_COUNT
        or len(set(aggregate_cases)) != _EXPECTED_CASE_COUNT
        or set(aggregate_cases) != runner_set
    ):
        raise MatrixError("MATRIX_AGGREGATE_CASE_SET_MISMATCH")
    return aggregate_cases


def _derive_run_id(batch_id: str, index: int, case_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", case_id.casefold()).strip("-")[:32]
    suffix = hashlib.sha256(f"{batch_id}\0{case_id}".encode()).hexdigest()[:10]
    return f"{batch_id}-{index:02d}-{slug}-{suffix}"


def _failure_report(
    batch_id: str,
    *,
    status: str,
    reason_code: str,
    case_ids: Sequence[str] = (),
    cases: Sequence[Mapping[str, Any]] = (),
    stopped_case_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": MATRIX_SCHEMA,
        "status": status,
        "reason_code": reason_code,
        "batch_id": batch_id,
        "required_cases": _EXPECTED_CASE_COUNT,
        "ordered_case_ids": list(case_ids),
        "attempted_cases": len(cases),
        "completed_pass_cases": sum(row.get("status") == "PASS" for row in cases),
        "stopped_case_id": stopped_case_id,
        "cases": list(cases),
        "execution": {
            "global_serial": True,
            "runner_starts_per_case_maximum": 1,
            "automatic_retries": 0,
            "continue_after_failure": False,
            "vllm_lifecycle": "PRESERVE_EXISTING_ONLY",
        },
    }


def _atomic_create(path: Path, value: Mapping[str, Any]) -> None:
    _reject_symlink_chain(path.parent, "OUTPUT_PARENT_SYMLINK_REJECTED")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode):
        raise MatrixError("OUTPUT_PARENT_INVALID")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            raise FileExistsError(path) from None
        path.chmod(0o600)
        parent_descriptor = os.open(
            path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _plan(batch_id: str, case_ids: Sequence[str]) -> list[tuple[str, str, Path]]:
    rows = [
        (
            case_id,
            _derive_run_id(batch_id, index, case_id),
            MATRIX_TMP_ROOT / _derive_run_id(batch_id, index, case_id),
        )
        for index, case_id in enumerate(case_ids, start=1)
    ]
    run_ids = [run_id for _case_id, run_id, _temporary in rows]
    temporary_paths = [temporary for _case_id, _run_id, temporary in rows]
    if len(run_ids) != len(set(run_ids)):
        raise MatrixError("MATRIX_DERIVED_RUN_ID_DUPLICATE")
    if len(temporary_paths) != len(set(temporary_paths)):
        raise MatrixError("MATRIX_TEMP_PATH_DUPLICATE")
    for run_id, temporary in zip(run_ids, temporary_paths, strict=True):
        if _RUN_ID.fullmatch(run_id) is None:
            raise MatrixError("MATRIX_DERIVED_RUN_ID_INVALID")
        if temporary.parent != MATRIX_TMP_ROOT:
            raise MatrixError("MATRIX_TEMP_PATH_ESCAPE")
        if temporary.exists() or temporary.is_symlink():
            raise MatrixError("MATRIX_TEMP_PATH_EXISTS")
        durable = RUNS_ROOT / run_id
        if durable.parent != RUNS_ROOT:
            raise MatrixError("MATRIX_RUN_PATH_ESCAPE")
        if durable.exists() or durable.is_symlink():
            raise MatrixError("MATRIX_RUN_PATH_EXISTS")
    return rows


def _read_json_receipt(path: Path, missing_code: str) -> tuple[dict[str, Any], str]:
    if not path.is_file() or path.is_symlink():
        raise MatrixError(missing_code)
    metadata = path.stat()
    if metadata.st_size > _MAX_RECEIPT_BYTES:
        raise MatrixError("CASE_RECEIPT_TOO_LARGE")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixError("CASE_RECEIPT_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise MatrixError("CASE_RECEIPT_CONTRACT_INVALID")
    return value, _sha256(raw)


def _validate_case_receipts(run_id: str, case_id: str) -> tuple[Path, dict[str, Any]]:
    run_dir = RUNS_ROOT / run_id
    report_path = run_dir / "report.json"
    cleanup_path = run_dir / "cleanup-receipt.json"
    report, report_sha = _read_json_receipt(report_path, "CASE_REPORT_MISSING")
    if (
        report.get("schema") != aggregate.REPORT_SCHEMA
        or report.get("run_id") != run_id
        or report.get("case_id") != case_id
        or report.get("status") != "PASS"
    ):
        raise MatrixError("CASE_REPORT_NOT_PASS")
    report_cleanup = report.get("cleanup")
    if (
        not isinstance(report_cleanup, Mapping)
        or report_cleanup.get("status") != "PASS"
        or report_cleanup.get("receipt") != "cleanup-receipt.json"
        or report_cleanup.get("existing_vllm_preserved") is not True
    ):
        raise MatrixError("CASE_REPORT_CLEANUP_NOT_PASS")

    cleanup, cleanup_sha = _read_json_receipt(
        cleanup_path, "CASE_CLEANUP_RECEIPT_MISSING"
    )
    if (
        cleanup.get("schema") != "milai.dg13u.u1-cleanup-receipt.v1"
        or cleanup.get("run_id") != run_id
        or cleanup.get("status") != "PASS"
    ):
        raise MatrixError("CASE_CLEANUP_RECEIPT_NOT_PASS")
    if (
        cleanup.get("existing_vllm_preserved") is not True
        or not isinstance(cleanup.get("external_lifecycle_mutations"), int)
        or isinstance(cleanup.get("external_lifecycle_mutations"), bool)
        or cleanup.get("external_lifecycle_mutations") != 0
    ):
        raise MatrixError("CASE_VLLM_PRESERVATION_INVALID")
    items = cleanup.get("items")
    if not isinstance(items, list) or not any(
        isinstance(item, Mapping)
        and item.get("kind") == "external_vllm"
        and item.get("ownership") == "PRESERVED_EXTERNAL"
        and item.get("state") == "preserved_external"
        for item in items
    ):
        raise MatrixError("CASE_VLLM_PRESERVATION_INVALID")
    return report_path, {
        "status": "PASS",
        "report_sha256": report_sha,
        "cleanup_receipt_sha256": cleanup_sha,
        "existing_vllm_preserved": True,
    }


def _remove_case_temp(path: Path) -> None:
    if path.parent != MATRIX_TMP_ROOT:
        raise MatrixError("MATRIX_TEMP_CLEANUP_PATH_ESCAPE")
    if path.is_symlink():
        raise MatrixError("MATRIX_TEMP_CLEANUP_SYMLINK_REJECTED")
    if path.exists():
        shutil.rmtree(path)


def _run_one(
    env_file: Path,
    case_id: str,
    run_id: str,
    temporary: Path,
) -> tuple[subprocess.CompletedProcess[bytes], float]:
    MATRIX_TMP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    MATRIX_TMP_ROOT.chmod(0o700)
    temporary.mkdir(mode=0o700)
    environment = os.environ.copy()
    environment["TMPDIR"] = str(temporary)
    command = [
        sys.executable,
        str(RUNNER_SCRIPT),
        "--case-id",
        case_id,
        "--run-id",
        run_id,
        "--execute-local",
        "--env-file",
        str(env_file),
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            check=False,
            timeout=_CASE_TIMEOUT_SECONDS,
        )
        if (
            not isinstance(completed, subprocess.CompletedProcess)
            or not isinstance(completed.returncode, int)
            or isinstance(completed.returncode, bool)
            or not isinstance(completed.stdout, bytes)
            or not isinstance(completed.stderr, bytes)
        ):
            raise MatrixError("CASE_SUBPROCESS_RESULT_INVALID")
        return completed, round((time.monotonic() - started) * 1_000, 3)
    finally:
        _remove_case_temp(temporary)


def run_matrix(
    batch_id: str,
    env_file: str | Path,
    output: str | Path,
) -> dict[str, Any]:
    environment, destination = _validate_inputs(batch_id, env_file, output)
    try:
        with _global_matrix_lock():
            return _run_matrix_locked(batch_id, environment, destination)
    except MatrixError as exc:
        if exc.code != "MATRIX_ALREADY_RUNNING":
            raise
        terminal = _failure_report(
            batch_id,
            status="BLOCKED",
            reason_code=exc.code,
        )
        _atomic_create(destination, terminal)
        return terminal


def _run_matrix_locked(
    batch_id: str,
    environment: Path,
    destination: Path,
) -> dict[str, Any]:
    try:
        case_ids = _contract_case_ids()
    except MatrixError as exc:
        terminal = _failure_report(
            batch_id,
            status="BLOCKED",
            reason_code=exc.code,
        )
        _atomic_create(destination, terminal)
        return terminal
    try:
        plan = _plan(batch_id, case_ids)
    except MatrixError as exc:
        terminal = _failure_report(
            batch_id,
            status="BLOCKED",
            reason_code=exc.code,
            case_ids=case_ids,
        )
        _atomic_create(destination, terminal)
        return terminal

    case_rows: list[dict[str, Any]] = []
    report_paths: list[Path] = []
    for case_id, run_id, temporary in plan:
        try:
            completed, duration_ms = _run_one(environment, case_id, run_id, temporary)
        except subprocess.TimeoutExpired:
            row = {
                "case_id": case_id,
                "run_id": run_id,
                "status": "FAIL",
                "reason_code": "CASE_SUBPROCESS_TIMEOUT",
            }
            case_rows.append(row)
            terminal = _failure_report(
                batch_id,
                status="FAIL",
                reason_code="CASE_SUBPROCESS_TIMEOUT",
                case_ids=case_ids,
                cases=case_rows,
                stopped_case_id=case_id,
            )
            _atomic_create(destination, terminal)
            return terminal
        except (MatrixError, OSError) as exc:
            reason_code = (
                exc.code
                if isinstance(exc, MatrixError)
                else "CASE_SUBPROCESS_OR_TEMP_IO_FAILED"
            )
            row = {
                "case_id": case_id,
                "run_id": run_id,
                "status": "FAIL",
                "reason_code": reason_code,
            }
            case_rows.append(row)
            terminal = _failure_report(
                batch_id,
                status="FAIL",
                reason_code=reason_code,
                case_ids=case_ids,
                cases=case_rows,
                stopped_case_id=case_id,
            )
            _atomic_create(destination, terminal)
            return terminal
        row: dict[str, Any] = {
            "case_id": case_id,
            "run_id": run_id,
            "exit_code": completed.returncode,
            "duration_ms": duration_ms,
            "stdout_sha256": _sha256(completed.stdout),
            "stderr_sha256": _sha256(completed.stderr),
            "raw_process_output_persisted": False,
            "status": "PASS" if completed.returncode == 0 else "FAIL",
        }
        case_rows.append(row)
        if completed.returncode != 0:
            row["reason_code"] = "CASE_SUBPROCESS_NONZERO"
            terminal = _failure_report(
                batch_id,
                status="FAIL",
                reason_code="CASE_SUBPROCESS_NONZERO",
                case_ids=case_ids,
                cases=case_rows,
                stopped_case_id=case_id,
            )
            _atomic_create(destination, terminal)
            return terminal
        try:
            report_path, receipt = _validate_case_receipts(run_id, case_id)
        except MatrixError as exc:
            row["status"] = "FAIL"
            row["reason_code"] = exc.code
            terminal = _failure_report(
                batch_id,
                status="FAIL",
                reason_code=exc.code,
                case_ids=case_ids,
                cases=case_rows,
                stopped_case_id=case_id,
            )
            _atomic_create(destination, terminal)
            return terminal
        row.update(receipt)
        report_paths.append(report_path)

    try:
        result = aggregate.aggregate_reports(report_paths)
    except aggregate.AggregateError as exc:
        terminal = _failure_report(
            batch_id,
            status="FAIL",
            reason_code="AGGREGATE_INPUT_REJECTED",
            case_ids=case_ids,
            cases=case_rows,
        )
        terminal["aggregate_error_type"] = type(exc).__name__
        _atomic_create(destination, terminal)
        return terminal
    _atomic_create(destination, result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the exact DG-13U U1 matrix once, serially, without retries"
    )
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_matrix(args.batch_id, args.env_file, args.output)
    except (MatrixError, FileExistsError) as exc:
        code = exc.code if isinstance(exc, MatrixError) else "OUTPUT_ALREADY_EXISTS"
        print(json.dumps({"status": "FAIL", "reason_code": code}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

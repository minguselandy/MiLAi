#!/usr/bin/env python3
"""Run the fixed DG-13U U1 owning-test gate and emit a durable receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from scripts import run_dg13u_openworker as product_runner
except ImportError:  # pragma: no cover - direct script execution
    import run_dg13u_openworker as product_runner

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_SCHEMA = "milai.dg13u.u1-test-gate-receipt.v1"
_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_COMMAND_TIMEOUT_SECONDS = 30 * 60
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TEMP_PARENT = Path("/dev/shm/milai")
_SUITE_TEMP_KEYS = {
    "u1-top-level-26-plus-u0-support": "u",
    "python-client": "p",
    "openworker-integration": "o",
}
_PYTEST_OUTCOMES = (
    "passed",
    "failed",
    "errors",
    "skipped",
    "xfailed",
    "xpassed",
    "deselected",
)
_PYTEST_COUNT = re.compile(
    r"(?P<count>[0-9]+) (?P<outcome>passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b"
)

TOP_LEVEL_U1_TESTS = (
    "tests/test_dg13u_u1_aggregate.py",
    "tests/test_dg13u_u1_bundle.py",
    "tests/test_dg13u_u1_cache_governance_scenarios.py",
    "tests/test_dg13u_u1_cleanup.py",
    "tests/test_dg13u_u1_contract_freeze.py",
    "tests/test_dg13u_u1_evidence_artifacts.py",
    "tests/test_dg13u_u1_fault_execution.py",
    "tests/test_dg13u_u1_fault_scenarios.py",
    "tests/test_dg13u_u1_fixture.py",
    "tests/test_dg13u_u1_headers_probe.py",
    "tests/test_dg13u_u1_image_contract.py",
    "tests/test_dg13u_u1_interaction_scenarios.py",
    "tests/test_dg13u_u1_lifecycle_runner.py",
    "tests/test_dg13u_u1_lifecycle_scenarios.py",
    "tests/test_dg13u_u1_matrix.py",
    "tests/test_dg13u_u1_mcp_child_fault.py",
    "tests/test_dg13u_u1_mcp_fault.py",
    "tests/test_dg13u_u1_openworker.py",
    "tests/test_dg13u_u1_operator_runbook.py",
    "tests/test_dg13u_u1_provider_fault.py",
    "tests/test_dg13u_u1_resource_registry.py",
    "tests/test_dg13u_u1_review.py",
    "tests/test_dg13u_u1_runtime_fault.py",
    "tests/test_dg13u_u1_runtime_writer.py",
    "tests/test_dg13u_u1_task_scenarios.py",
    "tests/test_dg13u_u1_test_gate.py",
)

U0_SUPPORT_OWNING_TESTS = ("tests/test_dg13u_openworker_runner.py",)

PYTHON_CLIENT_TESTS = (
    "integrations/python-client/tests/test_agent_loop.py",
    "integrations/python-client/tests/test_async_optimization.py",
    "integrations/python-client/tests/test_client_contract.py",
    "integrations/python-client/tests/test_context_policy.py",
    "integrations/python-client/tests/test_lifecycle.py",
    "integrations/python-client/tests/test_memory_need.py",
    "integrations/python-client/tests/test_optimization.py",
    "integrations/python-client/tests/test_optimized_lifecycle.py",
    "integrations/python-client/tests/test_task_memory.py",
    "integrations/python-client/tests/test_task_state.py",
)

OPENWORKER_INTEGRATION_TESTS = (
    "integrations/openworker-mcp/tests/test_adapter.py",
    "integrations/openworker-mcp/tests/test_controller.py",
    "integrations/openworker-mcp/tests/test_host_adapter.py",
    "integrations/openworker-mcp/tests/test_provider_execution.py",
    "integrations/openworker-mcp/tests/test_relay.py",
    "integrations/openworker-mcp/tests/test_settlement.py",
    "integrations/openworker-mcp/tests/test_task_binding.py",
    "integrations/openworker-mcp/tests/test_transport.py",
)

U1_IMPLEMENTATION_INPUTS = (
    "scripts/dg13u_u1_aggregate.py",
    "scripts/dg13u_u1_bundle.py",
    "scripts/dg13u_u1_cache_governance_scenarios.py",
    "scripts/dg13u_u1_cleanup.py",
    "scripts/dg13u_u1_evidence_artifacts.py",
    "scripts/dg13u_u1_fault_execution.py",
    "scripts/dg13u_u1_fault_scenarios.py",
    "scripts/dg13u_u1_fixture.py",
    "scripts/dg13u_u1_headers_probe.py",
    "scripts/dg13u_u1_interaction_scenarios.py",
    "scripts/dg13u_u1_lifecycle_scenarios.py",
    "scripts/dg13u_u1_matrix.py",
    "scripts/dg13u_u1_mcp_child_fault.py",
    "scripts/dg13u_u1_mcp_fault.py",
    "scripts/dg13u_u1_openworker.py",
    "scripts/dg13u_u1_provider_fault.py",
    "scripts/dg13u_u1_resource_registry.py",
    "scripts/dg13u_u1_review.py",
    "scripts/dg13u_u1_runtime_fault.py",
    "scripts/dg13u_u1_runtime_writer.py",
    "scripts/dg13u_u1_task_scenarios.py",
    "scripts/dg13u_u1_test_gate.py",
    "MiLAi_DG-13U_OpenWorker_MCP可用性开发_GOAL.md",
    "contracts/agent/v1/dg13u-u1-interface-freeze.md",
    "contracts/agent/v1/dg13u-u1-review-prompt.md",
    "contracts/agent/v1/dg13u-u1-review-response.schema.json",
    "docs/contracts/DG13U-U1-user-direct-execution-override-20260825.md",
    "docs/contracts/DG13U-U1-owner-decisions-v1.md",
    "docs/runbooks/dg13u-u1-operator.md",
)


class TestGateError(RuntimeError):
    """The fixed test gate cannot run without weakening its evidence contract."""


@dataclass(frozen=True, slots=True)
class SuiteDefinition:
    name: str
    workdir: Path
    python: Path
    source_paths: tuple[str, ...]
    pytest_paths: tuple[str, ...]


SUITES = (
    SuiteDefinition(
        name="u1-top-level-26-plus-u0-support",
        workdir=ROOT,
        python=ROOT / "runtime/.venv/bin/python",
        source_paths=(*TOP_LEVEL_U1_TESTS, *U0_SUPPORT_OWNING_TESTS),
        pytest_paths=(*TOP_LEVEL_U1_TESTS, *U0_SUPPORT_OWNING_TESTS),
    ),
    SuiteDefinition(
        name="python-client",
        workdir=ROOT / "integrations/python-client",
        python=ROOT / "integrations/python-client/.venv/bin/python",
        source_paths=PYTHON_CLIENT_TESTS,
        pytest_paths=tuple(
            path.removeprefix("integrations/python-client/")
            for path in PYTHON_CLIENT_TESTS
        ),
    ),
    SuiteDefinition(
        name="openworker-integration",
        workdir=ROOT / "integrations/openworker-mcp",
        python=ROOT / "integrations/openworker-mcp/.venv/bin/python",
        source_paths=OPENWORKER_INTEGRATION_TESTS,
        pytest_paths=tuple(
            path.removeprefix("integrations/openworker-mcp/")
            for path in OPENWORKER_INTEGRATION_TESTS
        ),
    ),
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_symlink_chain(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(metadata.st_mode):
            raise TestGateError(f"{label} symlink is forbidden")


def _create_run_root(value: str | Path) -> Path:
    run_root = Path(value)
    if not run_root.is_absolute():
        raise TestGateError("run root must be an explicit absolute path")
    run_root = Path(os.path.normpath(os.fspath(run_root)))
    if not _SAFE_RUN_ID.fullmatch(run_root.name):
        raise TestGateError("run root basename is not a safe run id")
    parent = run_root.parent
    _reject_symlink_chain(parent, "run root parent")
    try:
        parent_metadata = parent.stat()
    except OSError as exc:
        raise TestGateError("run root parent must already exist") from exc
    if not stat.S_ISDIR(parent_metadata.st_mode):
        raise TestGateError("run root parent must be a directory")
    try:
        os.mkdir(run_root, 0o700)
        os.chmod(run_root, 0o700)
    except OSError as exc:
        raise TestGateError("run root must be new and uniquely creatable") from exc
    return run_root


def _create_temporary_root(_run_id: str) -> Path:
    parent = Path(os.path.normpath(os.fspath(_TEMP_PARENT)))
    if not parent.is_absolute():
        raise TestGateError("temporary parent must be an absolute path")
    _reject_symlink_chain(parent, "temporary parent")
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent_metadata = parent.lstat()
    except OSError as exc:
        raise TestGateError("temporary parent is unavailable") from exc
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or stat.S_ISLNK(parent_metadata.st_mode)
        or stat.S_IMODE(parent_metadata.st_mode) & 0o077
    ):
        raise TestGateError("temporary parent is unsafe")
    try:
        temporary_root = Path(tempfile.mkdtemp(prefix="u1tg-", dir=parent))
        os.chmod(temporary_root, 0o700)
    except OSError as exc:
        raise TestGateError(
            "temporary root must be new and uniquely creatable"
        ) from exc
    return temporary_root


def _read_bounded_source_fd(descriptor: int, logical_path: str) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while True:
        block = os.read(descriptor, min(1024 * 1024, _MAX_SOURCE_BYTES + 1 - observed))
        if not block:
            break
        chunks.append(block)
        observed += len(block)
        if observed > _MAX_SOURCE_BYTES:
            raise TestGateError(f"source input exceeds byte bound: {logical_path}")
    return b"".join(chunks)


def _read_source(path: Path, logical_path: str) -> dict[str, object]:
    _reject_symlink_chain(path, logical_path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise TestGateError(f"source input is unreadable: {logical_path}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > _MAX_SOURCE_BYTES:
            raise TestGateError(
                f"source input is not a bounded regular file: {logical_path}"
            )
        raw = _read_bounded_source_fd(descriptor, logical_path)
        os.lseek(descriptor, 0, os.SEEK_SET)
        confirmed_raw = _read_bounded_source_fd(descriptor, logical_path)
        closed_over = os.fstat(descriptor)
        opened_identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_nlink,
            opened.st_uid,
            opened.st_gid,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        closed_identity = (
            closed_over.st_dev,
            closed_over.st_ino,
            closed_over.st_mode,
            closed_over.st_nlink,
            closed_over.st_uid,
            closed_over.st_gid,
            closed_over.st_size,
            closed_over.st_mtime_ns,
            closed_over.st_ctime_ns,
        )
        if (
            opened_identity != closed_identity
            or len(raw) != opened.st_size
            or confirmed_raw != raw
        ):
            raise TestGateError(f"source input changed while read: {logical_path}")
    except OSError as exc:
        raise TestGateError(f"source input is unreadable: {logical_path}") from exc
    finally:
        os.close(descriptor)
    return {"path": logical_path, "bytes": len(raw), "sha256": _sha256(raw)}


def _source_inputs() -> tuple[list[dict[str, object]], str]:
    actual_top_level = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").glob("test_dg13u_u1*.py")
        if path.is_file()
    }
    if actual_top_level != set(TOP_LEVEL_U1_TESTS):
        raise TestGateError("top-level U1 owning-test inventory drift")
    try:
        product_files = product_runner._source_files()
    except product_runner.DG13URunnerError as exc:
        raise TestGateError("product source discovery failed") from exc
    product_paths = [path.relative_to(ROOT).as_posix() for path in product_files]
    logical_paths = [*U1_IMPLEMENTATION_INPUTS, *product_paths]
    for suite in SUITES:
        logical_paths.extend(suite.source_paths)
    if len(logical_paths) != len(set(logical_paths)):
        raise TestGateError("source input list contains duplicates")
    inputs = [_read_source(ROOT / path, path) for path in sorted(logical_paths)]
    return inputs, _sha256(_canonical(inputs))


def _command_argv(suite: SuiteDefinition, temporary_root: Path) -> tuple[str, ...]:
    suite_root = temporary_root / _SUITE_TEMP_KEYS[suite.name]
    return (
        os.fspath(suite.python),
        "-m",
        "pytest",
        "-q",
        "-W",
        "error",
        "-p",
        "no:cacheprovider",
        f"--basetemp={suite_root / 'b'}",
        *suite.pytest_paths,
    )


def _parse_pytest_counts(raw: bytes) -> tuple[dict[str, int], bool]:
    counts = {outcome: 0 for outcome in _PYTEST_OUTCOMES}
    text = raw.decode("utf-8", errors="replace")
    summary_matches: list[re.Match[str]] = []
    for line in reversed(text.splitlines()):
        matches = list(_PYTEST_COUNT.finditer(line))
        if matches and re.search(r"\bin [0-9]+(?:\.[0-9]+)?s\b", line):
            summary_matches = matches
            break
    if not summary_matches:
        return counts, False
    for match in summary_matches:
        outcome = match.group("outcome")
        if outcome in {"error", "errors"}:
            outcome = "errors"
        counts[outcome] += int(match.group("count"))
    return counts, True


def _as_bytes(value: str | bytes | None) -> bytes:
    if value is None:
        return b""
    return value.encode() if isinstance(value, str) else value


def _output_observation(raw: bytes) -> dict[str, object]:
    return {
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "within_bound": len(raw) <= _MAX_OUTPUT_BYTES,
    }


def _run_suite(suite: SuiteDefinition, temporary_root: Path) -> dict[str, Any]:
    suite_root = temporary_root / _SUITE_TEMP_KEYS[suite.name]
    temporary_directory = suite_root / "t"
    argv = _command_argv(suite, temporary_root)
    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["TMPDIR"] = os.fspath(temporary_directory)
    started = time.monotonic()
    reason = "EXITED"
    exit_code: int | None
    try:
        temporary_directory.mkdir(parents=True, mode=0o700)
        os.chmod(temporary_directory, 0o700)
        completed = subprocess.run(
            argv,
            cwd=suite.workdir,
            env=environment,
            capture_output=True,
            check=False,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
        exit_code = completed.returncode
        stdout = _as_bytes(completed.stdout)
        stderr = _as_bytes(completed.stderr)
    except subprocess.TimeoutExpired as exc:
        reason = "TIMEOUT"
        exit_code = None
        stdout = _as_bytes(exc.stdout)
        stderr = _as_bytes(exc.stderr)
    except OSError as exc:
        reason = "SPAWN_ERROR"
        exit_code = None
        stdout = b""
        stderr = f"{type(exc).__name__}:{exc.errno}".encode()
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    stdout_observation = _output_observation(stdout)
    stderr_observation = _output_observation(stderr)
    counts, summary_parsed = _parse_pytest_counts(stdout + b"\n" + stderr)
    tests_observed = sum(
        counts[outcome] for outcome in _PYTEST_OUTCOMES if outcome != "deselected"
    )
    status = (
        "PASS"
        if reason == "EXITED"
        and exit_code == 0
        and summary_parsed
        and tests_observed > 0
        and bool(stdout_observation["within_bound"])
        and bool(stderr_observation["within_bound"])
        else "FAIL"
    )
    return {
        "name": suite.name,
        "status": status,
        "file_count": len(suite.source_paths),
        "attempt": 1,
        "automatic_retries": 0,
        "cwd": suite.workdir.relative_to(ROOT).as_posix() or ".",
        "argv": list(argv),
        "argv_sha256": _sha256(_canonical(list(argv))),
        "timeout_seconds": _COMMAND_TIMEOUT_SECONDS,
        "termination_reason": reason,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "pytest_summary_parsed": summary_parsed,
        "pytest_counts": counts,
        "tests_observed": tests_observed,
        "stdout": stdout_observation,
        "stderr": stderr_observation,
        "raw_output_persisted": False,
    }


def _aggregate_counts(commands: list[dict[str, Any]]) -> dict[str, int]:
    return {
        outcome: sum(command["pytest_counts"][outcome] for command in commands)
        for outcome in _PYTEST_OUTCOMES
    }


def _write_receipt(run_root: Path, receipt: dict[str, object]) -> Path:
    path = run_root / "receipt.json"
    raw = _canonical(receipt)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    directory = os.open(run_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return path


def run_gate(run_root_value: str | Path) -> tuple[Path, dict[str, object]]:
    run_root = _create_run_root(run_root_value)
    commands: list[dict[str, Any]] = []
    source_inputs: list[dict[str, object]] = []
    source_inputs_sha256: str | None = None
    post_source_inputs_sha256: str | None = None
    source_revalidation_status = "NOT_RUN"
    setup_error_sha256: str | None = None
    setup_error_reason: str | None = None
    temporary_root: Path | None = None
    temporary_cleanup_status = "NOT_CREATED"
    try:
        source_inputs, source_inputs_sha256 = _source_inputs()
        temporary_root = _create_temporary_root(run_root.name)
        temporary_cleanup_status = "PENDING"
        for suite in SUITES:
            commands.append(_run_suite(suite, temporary_root))
        try:
            post_source_inputs, post_source_inputs_sha256 = _source_inputs()
        except TestGateError as exc:
            source_revalidation_status = "FAIL"
            setup_error_reason = "SOURCE_INPUT_DRIFT"
            setup_error_sha256 = _sha256(type(exc).__name__.encode())
        else:
            if (
                post_source_inputs != source_inputs
                or post_source_inputs_sha256 != source_inputs_sha256
            ):
                source_revalidation_status = "FAIL"
                setup_error_reason = "SOURCE_INPUT_DRIFT"
                setup_error_sha256 = _sha256(b"SourceInputDrift")
            else:
                source_revalidation_status = "PASS"
    except TestGateError as exc:
        setup_error_reason = "SOURCE_INPUT_VALIDATION_FAILED"
        setup_error_sha256 = _sha256(type(exc).__name__.encode())
    finally:
        if temporary_root is not None:
            try:
                shutil.rmtree(temporary_root)
                temporary_cleanup_status = "PASS"
            except OSError:
                temporary_cleanup_status = "FAIL"
    counts = _aggregate_counts(commands)
    total_tests = sum(
        counts[outcome] for outcome in _PYTEST_OUTCOMES if outcome != "deselected"
    )
    passed_commands = sum(command["status"] == "PASS" for command in commands)
    status = (
        "PASS"
        if setup_error_sha256 is None
        and temporary_cleanup_status == "PASS"
        and len(commands) == len(SUITES)
        and passed_commands == len(SUITES)
        else "FAIL"
    )
    receipt: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "status": status,
        "run_id": run_root.name,
        "execution_scope": "FIXED_UNIT_AND_OWNING_TESTS_ONLY",
        "u1_top_level_file_count": len(TOP_LEVEL_U1_TESTS),
        "source_input_count": len(source_inputs),
        "source_inputs_sha256": source_inputs_sha256,
        "source_inputs": source_inputs,
        "source_revalidation": {
            "status": source_revalidation_status,
            "post_source_inputs_sha256": post_source_inputs_sha256,
        },
        "commands": commands,
        "summary": {
            "commands_planned": len(SUITES),
            "commands_executed": len(commands),
            "commands_passed": passed_commands,
            "commands_failed": len(commands) - passed_commands,
            "commands_not_executed": len(SUITES) - len(commands),
            "attempts_per_command_maximum": 1,
            "automatic_retries": 0,
            "pytest_counts": counts,
            "total_tests": total_tests,
        },
        "setup_error_reason": setup_error_reason,
        "setup_error_type_sha256": setup_error_sha256,
        "raw_stdout_stderr_persisted": False,
        "temporary_storage": {
            "kind": "RUN_OWNED_EPHEMERAL_ROOT",
            "path_sha256": (
                _sha256(os.fspath(temporary_root).encode())
                if temporary_root is not None
                else None
            ),
            "cleanup_status": temporary_cleanup_status,
            "exists_after_cleanup": (
                temporary_root.exists() if temporary_root is not None else False
            ),
        },
    }
    return _write_receipt(run_root, receipt), receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        required=True,
        help="New absolute 0700 directory whose existing parent receives receipt.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        receipt_path, receipt = run_gate(arguments.run_root)
    except TestGateError as exc:
        print(f"test gate refused: {type(exc).__name__}")
        return 2
    print(receipt_path)
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

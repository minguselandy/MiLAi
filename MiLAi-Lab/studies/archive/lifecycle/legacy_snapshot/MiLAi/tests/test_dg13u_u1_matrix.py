from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import dg13u_u1_matrix as matrix


def _configure_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    runs = root / "var/dg13/runs"
    matrix_tmp = root / "var/dg13/matrix-tmp"
    env_file = root / "runtime.env"
    env_file.write_text("SYNTHETIC=1\n")
    runner_script = root / "scripts/runner.py"
    runner_script.parent.mkdir()
    runner_script.write_text("# synthetic runner\n")
    monkeypatch.setattr(matrix, "ROOT", root)
    monkeypatch.setattr(matrix, "RUNS_ROOT", runs)
    monkeypatch.setattr(matrix, "MATRIX_TMP_ROOT", matrix_tmp)
    monkeypatch.setattr(matrix, "RUNNER_SCRIPT", runner_script)
    monkeypatch.setattr(matrix, "MATRIX_LOCK", root / "var/dg13/dg13u-u1-matrix.lock")
    return env_file


def _enable_full_contract(monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    case_ids = tuple(matrix.aggregate.REQUIRED_CASE_IDS)
    monkeypatch.setattr(
        matrix.runner, "CASES", {case_id: object() for case_id in case_ids}
    )
    monkeypatch.setattr(matrix.runner, "_IMPLEMENTED_REAL_CASES", frozenset(case_ids))
    return case_ids


def _write_pass_receipts(run_id: str, case_id: str) -> None:
    run_dir = matrix.RUNS_ROOT / run_id
    run_dir.mkdir(parents=True)
    cleanup = {
        "schema": "milai.dg13u.u1-cleanup-receipt.v1",
        "run_id": run_id,
        "status": "PASS",
        "existing_vllm_preserved": True,
        "external_lifecycle_mutations": 0,
        "items": [
            {
                "kind": "external_vllm",
                "ownership": "PRESERVED_EXTERNAL",
                "state": "preserved_external",
            }
        ],
    }
    (run_dir / "cleanup-receipt.json").write_text(json.dumps(cleanup))
    report = {
        "schema": matrix.aggregate.REPORT_SCHEMA,
        "run_id": run_id,
        "case_id": case_id,
        "status": "PASS",
        "cleanup": {
            "status": "PASS",
            "receipt": "cleanup-receipt.json",
            "existing_vllm_preserved": True,
        },
    }
    (run_dir / "report.json").write_text(json.dumps(report))


def _fake_success(
    calls: list[dict[str, Any]],
) -> Any:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        case_id = command[command.index("--case-id") + 1]
        run_id = command[command.index("--run-id") + 1]
        calls.append({"command": command, **kwargs})
        _write_pass_receipts(run_id, case_id)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    return run


def test_current_implementation_contract_is_exact_and_complete() -> None:
    case_ids = matrix._contract_case_ids()

    assert len(case_ids) == 37
    assert case_ids == tuple(matrix.aggregate.REQUIRED_CASE_IDS)
    assert set(case_ids) == set(matrix.runner.CASES)
    assert set(case_ids) == set(matrix.runner._IMPLEMENTED_REAL_CASES)


def test_full_matrix_is_strictly_serial_and_aggregates_explicit_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _configure_paths(tmp_path, monkeypatch)
    case_ids = _enable_full_contract(monkeypatch)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(matrix.subprocess, "run", _fake_success(calls))
    aggregate_calls: list[list[Path]] = []

    def fake_aggregate(paths: list[Path]) -> dict[str, object]:
        aggregate_calls.append(paths)
        return {
            "schema": matrix.aggregate.AGGREGATE_SCHEMA,
            "status": "PASS",
            "product_usable": True,
            "gates": {name: {"status": "PASS"} for name in matrix.aggregate.GATE_NAMES},
        }

    monkeypatch.setattr(matrix.aggregate, "aggregate_reports", fake_aggregate)
    output = tmp_path / "aggregate.json"

    result = matrix.run_matrix("batch-u1-full", env_file, output)

    assert result["status"] == "PASS"
    assert len(calls) == 37
    observed_cases = [
        call["command"][call["command"].index("--case-id") + 1] for call in calls
    ]
    assert observed_cases == list(case_ids)
    run_ids = [call["command"][call["command"].index("--run-id") + 1] for call in calls]
    assert len(run_ids) == len(set(run_ids)) == 37
    temp_paths = [Path(call["env"]["TMPDIR"]) for call in calls]
    assert len(temp_paths) == len(set(temp_paths)) == 37
    assert all(not path.exists() for path in temp_paths)
    assert all(call["check"] is False for call in calls)
    assert all("--execute-local" in call["command"] for call in calls)
    assert len(aggregate_calls) == 1
    assert aggregate_calls[0] == [
        matrix.RUNS_ROOT / run_id / "report.json" for run_id in run_ids
    ]
    assert json.loads(output.read_text())["status"] == "PASS"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_first_nonzero_case_stops_without_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _configure_paths(tmp_path, monkeypatch)
    case_ids = _enable_full_contract(monkeypatch)
    calls: list[list[str]] = []

    def fail_third(
        command: list[str], **_kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        case_id = command[command.index("--case-id") + 1]
        run_id = command[command.index("--run-id") + 1]
        if len(calls) < 3:
            _write_pass_receipts(run_id, case_id)
            return subprocess.CompletedProcess(command, 0, b"ok", b"")
        return subprocess.CompletedProcess(command, 2, b"", b"private failure")

    monkeypatch.setattr(matrix.subprocess, "run", fail_third)
    monkeypatch.setattr(
        matrix.aggregate,
        "aggregate_reports",
        lambda _paths: pytest.fail("aggregate must not run after case failure"),
    )
    output = tmp_path / "failure.json"

    result = matrix.run_matrix("batch-u1-stop", env_file, output)

    assert len(calls) == 3
    assert result["status"] == "FAIL"
    assert result["reason_code"] == "CASE_SUBPROCESS_NONZERO"
    assert result["stopped_case_id"] == case_ids[2]
    assert result["attempted_cases"] == 3
    assert "private failure" not in output.read_text()


@pytest.mark.parametrize(
    "subprocess_result",
    [
        pytest.param(None, id="none"),
        pytest.param(
            subprocess.CompletedProcess([], 0, "not-bytes", b""),
            id="invalid-shape",
        ),
    ],
)
def test_invalid_subprocess_result_fails_closed_with_typed_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    subprocess_result: object,
) -> None:
    env_file = _configure_paths(tmp_path, monkeypatch)
    case_ids = _enable_full_contract(monkeypatch)
    calls: list[object] = []

    def invalid_result(*_args: object, **_kwargs: object) -> object:
        calls.append(1)
        return subprocess_result

    monkeypatch.setattr(matrix.subprocess, "run", invalid_result)
    monkeypatch.setattr(
        matrix.aggregate,
        "aggregate_reports",
        lambda _paths: pytest.fail("aggregate must not run after typed failure"),
    )
    output = tmp_path / "invalid-subprocess.json"

    result = matrix.run_matrix("batch-u1-invalid", env_file, output)

    assert calls == [1]
    assert result["status"] == "FAIL"
    assert result["reason_code"] == "CASE_SUBPROCESS_RESULT_INVALID"
    assert result["stopped_case_id"] == case_ids[0]
    assert result["attempted_cases"] == 1
    assert result["cases"] == [
        {
            "case_id": case_ids[0],
            "run_id": result["cases"][0]["run_id"],
            "status": "FAIL",
            "reason_code": "CASE_SUBPROCESS_RESULT_INVALID",
        }
    ]
    assert json.loads(output.read_text()) == result
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        ("report_missing", "CASE_REPORT_MISSING"),
        ("report_cleanup_fail", "CASE_REPORT_CLEANUP_NOT_PASS"),
        ("receipt_cleanup_fail", "CASE_CLEANUP_RECEIPT_NOT_PASS"),
        ("vllm_not_preserved", "CASE_VLLM_PRESERVATION_INVALID"),
    ],
)
def test_report_and_cleanup_defects_stop_before_second_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    reason_code: str,
) -> None:
    env_file = _configure_paths(tmp_path, monkeypatch)
    _enable_full_contract(monkeypatch)
    calls: list[list[str]] = []

    def defective(
        command: list[str], **_kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        case_id = command[command.index("--case-id") + 1]
        run_id = command[command.index("--run-id") + 1]
        if mutation != "report_missing":
            _write_pass_receipts(run_id, case_id)
            report_path = matrix.RUNS_ROOT / run_id / "report.json"
            cleanup_path = matrix.RUNS_ROOT / run_id / "cleanup-receipt.json"
            if mutation == "report_cleanup_fail":
                value = json.loads(report_path.read_text())
                value["cleanup"]["status"] = "FAIL"
                report_path.write_text(json.dumps(value))
            elif mutation == "receipt_cleanup_fail":
                value = json.loads(cleanup_path.read_text())
                value["status"] = "FAIL"
                cleanup_path.write_text(json.dumps(value))
            else:
                value = json.loads(cleanup_path.read_text())
                value["existing_vllm_preserved"] = False
                cleanup_path.write_text(json.dumps(value))
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(matrix.subprocess, "run", defective)
    output = tmp_path / f"{mutation}.json"
    result = matrix.run_matrix("batch-u1-defect", env_file, output)

    assert len(calls) == 1
    assert result["reason_code"] == reason_code
    assert result["attempted_cases"] == 1


def test_duplicate_derived_run_ids_fail_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _configure_paths(tmp_path, monkeypatch)
    _enable_full_contract(monkeypatch)
    monkeypatch.setattr(matrix, "_derive_run_id", lambda *_args: "duplicate-run-id")
    calls: list[object] = []
    monkeypatch.setattr(
        matrix.subprocess, "run", lambda *_args, **_kwargs: calls.append(1)
    )

    result = matrix.run_matrix("batch-u1-dupe", env_file, tmp_path / "dupe.json")

    assert result["reason_code"] == "MATRIX_DERIVED_RUN_ID_DUPLICATE"
    assert result["attempted_cases"] == 0
    assert calls == []


def test_derived_run_id_escape_fails_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _configure_paths(tmp_path, monkeypatch)
    _enable_full_contract(monkeypatch)
    monkeypatch.setattr(
        matrix, "_derive_run_id", lambda _batch, index, _case: f"../escape-{index}"
    )
    calls: list[object] = []
    monkeypatch.setattr(
        matrix.subprocess, "run", lambda *_args, **_kwargs: calls.append(1)
    )

    result = matrix.run_matrix("batch-u1-path", env_file, tmp_path / "escape.json")

    assert result["reason_code"] == "MATRIX_DERIVED_RUN_ID_INVALID"
    assert calls == []


def test_relative_output_and_existing_output_fail_without_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _configure_paths(tmp_path, monkeypatch)
    _enable_full_contract(monkeypatch)
    calls: list[object] = []
    monkeypatch.setattr(
        matrix.subprocess, "run", lambda *_args, **_kwargs: calls.append(1)
    )

    with pytest.raises(matrix.MatrixError, match="OUTPUT_PATH_INVALID"):
        matrix.run_matrix("batch-u1-path", env_file, Path("relative.json"))

    existing = tmp_path / "existing.json"
    existing.write_text("preserve")
    with pytest.raises(FileExistsError):
        matrix.run_matrix("batch-u1-path", env_file, existing)
    assert existing.read_text() == "preserve"
    assert calls == []


def test_global_lock_rejects_concurrent_matrix_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _configure_paths(tmp_path, monkeypatch)
    _enable_full_contract(monkeypatch)
    calls: list[object] = []
    monkeypatch.setattr(
        matrix.subprocess, "run", lambda *_args, **_kwargs: calls.append(1)
    )
    matrix.MATRIX_LOCK.parent.mkdir(parents=True)
    descriptor = matrix.os.open(
        matrix.MATRIX_LOCK, matrix.os.O_RDWR | matrix.os.O_CREAT, 0o600
    )
    matrix.fcntl.flock(descriptor, matrix.fcntl.LOCK_EX | matrix.fcntl.LOCK_NB)
    try:
        result = matrix.run_matrix(
            "batch-u1-locked", env_file, tmp_path / "locked.json"
        )
    finally:
        matrix.fcntl.flock(descriptor, matrix.fcntl.LOCK_UN)
        matrix.os.close(descriptor)

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "MATRIX_ALREADY_RUNNING"
    assert result["attempted_cases"] == 0
    assert calls == []


def test_cli_help_requires_batch_env_and_output() -> None:
    script = Path(__file__).parents[1] / "scripts/dg13u_u1_matrix.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "--batch-id" in completed.stdout
    assert "--env-file" in completed.stdout
    assert "--output" in completed.stdout

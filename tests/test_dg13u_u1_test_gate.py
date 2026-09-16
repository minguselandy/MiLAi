from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path

import pytest

from scripts import dg13u_u1_test_gate as gate


@pytest.fixture(autouse=True)
def isolated_temporary_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parent = tmp_path / "volatile"
    monkeypatch.setattr(gate, "_TEMP_PARENT", parent)


def _completed(
    returncode: int, stdout: bytes, stderr: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess((), returncode, stdout, stderr)


@pytest.fixture
def valid_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = [{"path": "synthetic", "bytes": 1, "sha256": "a" * 64}]
    monkeypatch.setattr(gate, "_source_inputs", lambda: (inputs, "b" * 64))


def test_fixed_suite_inventory_and_boundaries() -> None:
    assert len(gate.TOP_LEVEL_U1_TESTS) == 26
    assert gate.U0_SUPPORT_OWNING_TESTS == ("tests/test_dg13u_openworker_runner.py",)
    assert len(gate.PYTHON_CLIENT_TESTS) == 10
    assert len(gate.OPENWORKER_INTEGRATION_TESTS) == 8
    assert len(gate.SUITES) == 3
    assert set(gate._SUITE_TEMP_KEYS) == {suite.name for suite in gate.SUITES}
    assert len(set(gate._SUITE_TEMP_KEYS.values())) == len(gate.SUITES)
    assert len("/dev/shm/milai/u1tg-xxxxxxxx/o/t") < 64
    assert len("--basetemp=/dev/shm/milai/u1tg-xxxxxxxx/o/b") < 80
    assert len({path for suite in gate.SUITES for path in suite.source_paths}) == 45
    assert gate.SUITES[0].source_paths == (
        *gate.TOP_LEVEL_U1_TESTS,
        *gate.U0_SUPPORT_OWNING_TESTS,
    )
    actual = {
        path.relative_to(gate.ROOT).as_posix()
        for path in (gate.ROOT / "tests").glob("test_dg13u_u1*.py")
        if path.is_file()
    }
    assert actual == set(gate.TOP_LEVEL_U1_TESTS)
    source_inputs, source_inputs_sha256 = gate._source_inputs()
    source_paths = {str(row["path"]) for row in source_inputs}
    assert len(source_inputs) > 45
    assert set(gate.U1_IMPLEMENTATION_INPUTS).issubset(source_paths)
    assert {
        "MiLAi_DG-13U_OpenWorker_MCP可用性开发_GOAL.md",
        "contracts/agent/v1/dg13u-u1-interface-freeze.md",
        "docs/contracts/DG13U-U1-owner-decisions-v1.md",
        "runtime/src/milai/api/app.py",
        "integrations/python-client/src/milai_client/client.py",
        "integrations/openworker-mcp/src/milai_openworker_mcp/host_adapter.py",
        "scripts/run_dg13u_openworker.py",
        "tests/test_dg13u_openworker_runner.py",
    }.issubset(source_paths)
    assert (
        source_inputs_sha256
        == hashlib.sha256(gate._canonical(source_inputs)).hexdigest()
    )
    assert all(
        "e2e" not in path.casefold()
        for suite in gate.SUITES
        for path in suite.source_paths
    )
    assert all(
        "vllm" not in path.casefold()
        for suite in gate.SUITES
        for path in suite.source_paths
    )


def test_gate_runs_each_fixed_command_once_and_writes_durable_pass_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_sources: None
) -> None:
    results = iter(
        (
            _completed(0, b"24 passed in 1.00s\n"),
            _completed(0, b"40 passed, 2 skipped in 2.00s\n"),
            _completed(0, b"50 passed, 1 xfailed in 3.00s\n"),
        )
    )
    calls: list[dict[str, object]] = []

    def fake_run(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append({"argv": argv, **kwargs})
        return next(results)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    run_root = tmp_path / "gate-pass-001"
    receipt_path, receipt = gate.run_gate(run_root)

    assert receipt["status"] == "PASS"
    assert receipt["schema"] == gate.RECEIPT_SCHEMA
    assert receipt["setup_error_reason"] is None
    assert receipt["source_input_count"] == 1
    assert receipt["source_inputs_sha256"] == "b" * 64
    assert receipt["source_revalidation"] == {
        "status": "PASS",
        "post_source_inputs_sha256": "b" * 64,
    }
    assert receipt["u1_top_level_file_count"] == 26
    assert receipt["summary"] == {
        "commands_planned": 3,
        "commands_executed": 3,
        "commands_passed": 3,
        "commands_failed": 0,
        "commands_not_executed": 0,
        "attempts_per_command_maximum": 1,
        "automatic_retries": 0,
        "pytest_counts": {
            "passed": 114,
            "failed": 0,
            "errors": 0,
            "skipped": 2,
            "xfailed": 1,
            "xpassed": 0,
            "deselected": 0,
        },
        "total_tests": 117,
    }
    assert len(calls) == 3
    assert [command["file_count"] for command in receipt["commands"]] == [27, 10, 8]
    for call, command in zip(calls, receipt["commands"], strict=True):
        argv = call["argv"]
        assert argv[3:6] == ("-q", "-W", "error")
        assert call["capture_output"] is True
        assert call["check"] is False
        assert call["timeout"] == gate._COMMAND_TIMEOUT_SECONDS
        environment = call["env"]
        assert isinstance(environment, dict)
        volatile_root = Path(environment["TMPDIR"]).parents[1]
        assert volatile_root.is_relative_to(gate._TEMP_PARENT)
        assert volatile_root.name.startswith("u1tg-")
        assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        assert command["attempt"] == 1
        assert command["automatic_retries"] == 0
        assert command["raw_output_persisted"] is False
        assert set(command["stdout"]) == {"bytes", "sha256", "within_bound"}
    assert stat.S_IMODE(run_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert json.loads(receipt_path.read_text()) == receipt
    assert not any(path.name in {"stdout", "stderr"} for path in run_root.rglob("*"))
    assert receipt["temporary_storage"]["cleanup_status"] == "PASS"
    assert receipt["temporary_storage"]["exists_after_cleanup"] is False
    assert not volatile_root.exists()


def test_failure_is_retained_and_does_not_retry_or_skip_later_suites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_sources: None
) -> None:
    outputs = iter(
        (
            _completed(1, b"1 failed, 23 passed in 1.00s\n", b"bounded failure\n"),
            _completed(0, b"10 passed in 1.00s\n"),
            _completed(0, b"8 passed in 1.00s\n"),
        )
    )
    call_count = 0

    def fake_run(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal call_count
        call_count += 1
        return next(outputs)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    receipt_path, receipt = gate.run_gate(tmp_path / "gate-fail-001")

    assert call_count == 3
    assert receipt["status"] == "FAIL"
    assert receipt["setup_error_reason"] is None
    assert receipt["summary"]["commands_failed"] == 1
    assert receipt["summary"]["automatic_retries"] == 0
    failed = receipt["commands"][0]
    assert failed["status"] == "FAIL"
    assert failed["exit_code"] == 1
    assert failed["pytest_counts"]["failed"] == 1
    assert (
        failed["stderr"]["sha256"] == hashlib.sha256(b"bounded failure\n").hexdigest()
    )
    assert "bounded failure" not in receipt_path.read_text()


def test_exit_zero_without_parseable_summary_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_sources: None
) -> None:
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(
            0, b"pytest output without terminal counts\n"
        ),
    )
    _, receipt = gate.run_gate(tmp_path / "gate-unparsed-001")
    assert receipt["status"] == "FAIL"
    assert all(not command["pytest_summary_parsed"] for command in receipt["commands"])


def test_output_over_bound_fails_closed_but_persists_only_complete_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_sources: None
) -> None:
    monkeypatch.setattr(gate, "_MAX_OUTPUT_BYTES", 8)
    raw = b"1 passed in 1.00s\n"
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(0, raw),
    )
    receipt_path, receipt = gate.run_gate(tmp_path / "gate-output-bound-001")
    assert receipt["status"] == "FAIL"
    assert receipt["commands"][0]["stdout"] == {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "within_bound": False,
    }
    assert "1 passed" not in receipt_path.read_text()


def test_timeout_is_one_failed_attempt_and_remaining_commands_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_sources: None
) -> None:
    calls = 0

    def fake_run(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired(
                "pytest", 1, output=b"partial", stderr=b"timeout"
            )
        return _completed(0, b"1 passed in 1.00s\n")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    _, receipt = gate.run_gate(tmp_path / "gate-timeout-001")
    assert calls == 3
    first = receipt["commands"][0]
    assert first["termination_reason"] == "TIMEOUT"
    assert first["exit_code"] is None
    assert first["attempt"] == 1
    assert first["automatic_retries"] == 0
    assert receipt["status"] == "FAIL"


def test_existing_or_relative_run_root_is_rejected_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def fake_run(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal called
        called = True
        return _completed(0, b"1 passed in 1.00s\n")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    existing = tmp_path / "existing-run"
    existing.mkdir()
    with pytest.raises(gate.TestGateError, match="new and uniquely creatable"):
        gate.run_gate(existing)
    with pytest.raises(gate.TestGateError, match="explicit absolute"):
        gate.run_gate(Path("relative-run"))
    assert called is False


def test_top_level_inventory_drift_is_rejected_before_source_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gate,
        "TOP_LEVEL_U1_TESTS",
        (*gate.TOP_LEVEL_U1_TESTS, "tests/test_dg13u_u1_unreviewed.py"),
    )
    with pytest.raises(gate.TestGateError, match="owning-test inventory drift"):
        gate._source_inputs()
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run after drift"),
    )
    receipt_path, receipt = gate.run_gate(tmp_path / "gate-inventory-drift-001")
    assert receipt["status"] == "FAIL"
    assert receipt["setup_error_reason"] == "SOURCE_INPUT_VALIDATION_FAILED"
    assert receipt["summary"]["commands_executed"] == 0
    assert receipt["summary"]["commands_not_executed"] == 3
    assert receipt_path.is_file()


def test_source_drift_after_all_suites_fails_closed_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = [{"path": "source.py", "bytes": 1, "sha256": "a" * 64}]
    after = [{"path": "source.py", "bytes": 1, "sha256": "c" * 64}]
    snapshots = iter(((before, "b" * 64), (after, "d" * 64)))
    monkeypatch.setattr(gate, "_source_inputs", lambda: next(snapshots))
    calls = 0

    def fake_run(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return _completed(0, b"1 passed in 1.00s\n")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    receipt_path, receipt = gate.run_gate(tmp_path / "gate-source-drift-001")

    assert calls == 3
    assert receipt["status"] == "FAIL"
    assert receipt["setup_error_reason"] == "SOURCE_INPUT_DRIFT"
    assert receipt["source_inputs"] == before
    assert receipt["source_inputs_sha256"] == "b" * 64
    assert receipt["source_revalidation"] == {
        "status": "FAIL",
        "post_source_inputs_sha256": "d" * 64,
    }
    assert receipt["summary"]["commands_executed"] == 3
    assert receipt["summary"]["commands_passed"] == 3
    assert receipt["summary"]["automatic_retries"] == 0
    assert json.loads(receipt_path.read_text()) == receipt


def test_source_reread_error_after_all_suites_is_typed_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = [{"path": "source.py", "bytes": 1, "sha256": "a" * 64}]
    captures = 0

    def capture() -> tuple[list[dict[str, object]], str]:
        nonlocal captures
        captures += 1
        if captures == 1:
            return before, "b" * 64
        raise gate.TestGateError("bounded source reread failure")

    monkeypatch.setattr(gate, "_source_inputs", capture)
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(0, b"1 passed in 1.00s\n"),
    )

    receipt_path, receipt = gate.run_gate(tmp_path / "gate-source-reread-001")

    assert captures == 2
    assert receipt["status"] == "FAIL"
    assert receipt["setup_error_reason"] == "SOURCE_INPUT_DRIFT"
    assert receipt["source_revalidation"] == {
        "status": "FAIL",
        "post_source_inputs_sha256": None,
    }
    assert receipt["summary"]["commands_executed"] == 3
    assert "bounded source reread failure" not in receipt_path.read_text()


def test_product_source_discovery_error_writes_durable_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gate.product_runner,
        "_source_files",
        lambda: (_ for _ in ()).throw(
            gate.product_runner.DG13URunnerError("missing product source")
        ),
    )
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "subprocess must not run after product source discovery failure"
        ),
    )

    receipt_path, receipt = gate.run_gate(tmp_path / "gate-product-source-error-001")

    assert receipt["status"] == "FAIL"
    assert receipt["setup_error_reason"] == "SOURCE_INPUT_VALIDATION_FAILED"
    assert receipt["source_revalidation"] == {
        "status": "NOT_RUN",
        "post_source_inputs_sha256": None,
    }
    assert receipt["summary"]["commands_executed"] == 0
    assert receipt_path.is_file()


def test_read_source_rejects_same_size_change_during_fd_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.py"
    source.write_bytes(b"alpha")
    original_read = gate.os.read
    changed = False

    def mutate_after_read(descriptor: int, byte_count: int) -> bytes:
        nonlocal changed
        raw = original_read(descriptor, byte_count)
        if raw and not changed:
            changed = True
            source.write_bytes(b"bravo")
        return raw

    monkeypatch.setattr(gate.os, "read", mutate_after_read)

    with pytest.raises(gate.TestGateError, match="changed while read"):
        gate._read_source(source, "source.py")
    assert changed is True


@pytest.mark.parametrize(
    ("summary", "expected"),
    (
        (
            b"1 error, 2 failed, 3 passed in 1.20s\n",
            {"errors": 1, "failed": 2, "passed": 3},
        ),
        (
            b"4 skipped, 2 xpassed, 1 deselected in 0.10s\n",
            {"skipped": 4, "xpassed": 2, "deselected": 1},
        ),
    ),
)
def test_pytest_count_parser(summary: bytes, expected: dict[str, int]) -> None:
    counts, parsed = gate._parse_pytest_counts(summary)
    assert parsed is True
    assert all(counts[key] == value for key, value in expected.items())

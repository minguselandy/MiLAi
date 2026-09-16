"""Synthetic process ownership, pipe input and fixed-deadline orchestration."""

import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_v0224_bundle_preparation as controller


def test_approval_only_exact_host_line_and_fixed_path(tmp_path):
    path = tmp_path / "independent-authority-approval.json"
    read, write = os.pipe()
    try:
        value = {"approval_path": str(path), "approval_sha256": "a" * 64}
        os.write(write, (json.dumps(value) + "\n").encode())
        assert controller._approval_input(path, controller.time.monotonic() + 2, read) == value
    finally:
        os.close(read)
        os.close(write)


@pytest.mark.parametrize(
    "line",
    [
        b"{}\n",
        b'{"approval_path":"/other","approval_sha256":"bad"}\n',
        b'{"approval_path":"x","approval_path":"y"}\n',
        b"[]\n",
    ],
)
def test_approval_rejects_schema_duplicates_and_untrusted_path(line, tmp_path):
    read, write = os.pipe()
    try:
        os.write(write, line)
        with pytest.raises(ValueError):
            controller._approval_input(
                tmp_path / "independent-authority-approval.json",
                controller.time.monotonic() + 2,
                read,
            )
    finally:
        os.close(read)
        os.close(write)


def test_wait_exhaustion_and_eof_do_not_discover_file(monkeypatch, tmp_path):
    path = tmp_path / "independent-authority-approval.json"
    path.write_text("{}")
    monkeypatch.setattr(controller.select, "select", lambda *args: ([], [], []))
    with pytest.raises(TimeoutError, match="WAIT_EXHAUSTED"):
        controller._approval_input(path, controller.time.monotonic() + 2, 123)
    monkeypatch.setattr(controller.select, "select", lambda *args: ([123], [], []))
    monkeypatch.setattr(controller.os, "read", lambda *args: b"")
    with pytest.raises(ValueError, match="INPUT_EOF"):
        controller._approval_input(path, controller.time.monotonic() + 2, 123)


def test_owned_group_cleanup_kills_descendants_after_leader_exit(monkeypatch):
    signals = []
    probes = iter([False, True])
    child = SimpleNamespace(pid=12345, returncode=0, wait=lambda timeout: 0)
    monkeypatch.setattr(controller.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(controller, "_group_gone", lambda pid: next(probes))
    result = controller._cleanup_owned(child)
    assert signals == [(12345, signal.SIGTERM), (12345, signal.SIGKILL)]
    assert result["cleanup_complete"] is True


def test_unknown_cleanup_never_passes(monkeypatch):
    def denied(*args):
        raise PermissionError("synthetic")

    child = SimpleNamespace(pid=12345, returncode=None, wait=lambda timeout: None)
    monkeypatch.setattr(controller.os, "killpg", denied)
    result = controller._cleanup_owned(child)
    assert result["cleanup_complete"] is False and result["owned_group_gone"] is None


def test_child_actual_pid_group_stdout_and_timeout_preserve_primary(monkeypatch, tmp_path):
    primary = subprocess.TimeoutExpired(["synthetic"], 1)

    def wait(timeout):
        raise primary

    child = SimpleNamespace(pid=12345, returncode=None, wait=wait)
    kwargs_seen = {}

    def popen(argv, **kwargs):
        kwargs_seen.update(kwargs)
        return child

    monkeypatch.setattr(controller.subprocess, "Popen", popen)
    monkeypatch.setattr(
        controller,
        "_cleanup_owned",
        lambda child: {"returncode": -9, "cleanup_complete": True, "owned_group_gone": True},
    )
    rows = []
    with pytest.raises(subprocess.TimeoutExpired) as error:
        controller._run_child(
            ["synthetic"], "builder", tmp_path, controller.time.monotonic() + 2, rows
        )
    assert error.value is primary
    assert kwargs_seen["start_new_session"] is True
    assert kwargs_seen["stdin"] == subprocess.DEVNULL
    assert kwargs_seen["stdout"].name != kwargs_seen["stderr"].name
    assert rows[0]["pid"] == 12345 and rows[0]["returncode"] == -9
    assert json.loads((tmp_path / "builder.start.json").read_text())["pid"] == 12345
    assert json.loads((tmp_path / "builder.exit.json").read_text())["returncode"] == -9


@pytest.fixture
def orchestration(monkeypatch, tmp_path):
    import prepare_v0224_bundle_authority as authority
    import v0220_evidence as evidence
    import v0222_scoped_cpu_guard as guard

    monkeypatch.setattr(guard, "enable_cpu_network_guard", lambda: None)
    monkeypatch.setattr(authority, "_validate_contract", lambda *args: None)
    monkeypatch.setattr(evidence, "dependencies", lambda *args: [])
    limits = {"max_header_bytes": 100, "max_payload_bytes": 200, "max_paths": 3, "max_blobs": 4}
    contract_path = tmp_path / "contract.json"
    source = tmp_path / "synthetic-source.py"
    source.write_text("# pinned synthetic source")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    contract_path.write_text(json.dumps({"files": {str(source): source_sha}, "limits": limits}))
    contract_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    calls = []
    candidate = {"bundle_sha256": "a" * 64, "status": "STATIC_BUNDLE_CANDIDATE_NOT_APPROVED"}

    def put(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def child(argv, phase, out, deadline, rows):
        calls.append((phase, argv, deadline))
        row = {"phase": phase, "pid": len(calls) + 100, "returncode": 0, "cleanup_complete": True}
        rows.append(row)
        directory = tmp_path / "authority-v1"
        if phase == "authority_builder":
            generated = {
                str(directory / "sealed/candidate-receipt.json"): put(
                    directory / "sealed/candidate-receipt.json", candidate
                ),
                str(directory / "sealed/static.bundle"): "a" * 64,
                str(directory / "sealed/seal-observation.json"): "b" * 64,
                str(directory / "revalidated/mechanical-revalidation.json"): "c" * 64,
            }
            put(
                directory / "authority-prepared.json",
                {
                    "status": "READY_FOR_INDEPENDENT_AUTHORITY_REVIEW",
                    "runtime_authorized": False,
                    "pid": row["pid"],
                    "contract_sha256": contract_sha,
                    "generated_files": generated,
                },
            )
        elif phase == "finalizer":
            receipt_path = directory / "approved-receipt.json"
            receipt_sha = put(
                receipt_path, {**candidate, "status": "INDEPENDENT_STATIC_BUNDLE_APPROVED"}
            )
            put(
                out / "finalizer.stdout",
                {
                    "status": "APPROVED_RECEIPT_MATERIALIZED_NOT_GATE_A",
                    "path": str(receipt_path),
                    "sha256": receipt_sha,
                },
            )
        return row

    monkeypatch.setattr(controller, "_run_child", child)
    monkeypatch.setattr(
        controller,
        "_approval_input",
        lambda path, deadline, fd: {"approval_path": str(path), "approval_sha256": "d" * 64},
    )
    return contract_path, contract_sha, calls


def test_one_deadline_covers_all_three_children_and_approval(orchestration):
    path, pin, calls = orchestration
    result = controller.run_preparation(path, pin)
    assert [row[0] for row in calls] == ["authority_builder", "finalizer", "fixture_preparer"]
    assert len({row[2] for row in calls}) == 1
    assert calls[1][1][1:3] == ["-c", controller.FINALIZER_CODE]
    assert calls[2][1][-8:] == [
        "--max-header-bytes",
        "100",
        "--max-payload-bytes",
        "200",
        "--max-paths",
        "3",
        "--max-blobs",
        "4",
    ]
    assert "--instance" in calls[2][1] and "bundle-v1-slice" in calls[2][1]
    assert result["status"] == "PREPARATION_STEPS_COMPLETE_EXTERNAL_EXIT_REQUIRED"
    assert len(result["children"]) == 3


def test_approval_failure_stops_before_finalizer(orchestration, monkeypatch):
    path, pin, calls = orchestration
    primary = KeyboardInterrupt("host-interrupt")

    def refused(*args):
        raise primary

    monkeypatch.setattr(controller, "_approval_input", refused)
    with pytest.raises(KeyboardInterrupt) as raised:
        controller.run_preparation(path, pin)
    assert raised.value is primary
    assert len(calls) == 1
    failure = json.loads(
        (path.parent / "preparation-controller-v1/preparation-failure.json").read_text()
    )
    assert failure["phase"] == "waiting_for_independent_approval"
    assert failure["exception_type"] == "KeyboardInterrupt"


def test_successful_child_exit_after_deadline_is_failure(monkeypatch, tmp_path):
    now = [0.0]

    def wait(timeout):
        now[0] = 301.0
        return 0

    child = SimpleNamespace(pid=12345, returncode=0, wait=wait)
    monkeypatch.setattr(controller.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(controller.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(controller, "_group_gone", lambda pid: True)
    rows = []
    with pytest.raises(TimeoutError, match="300_SECONDS"):
        controller._run_child(["synthetic"], "builder", tmp_path, 300.0, rows)
    assert rows[0]["returncode"] == 0
    assert rows[0]["elapsed_seconds"] == 301.0
    assert rows[0]["exception_type"] == "TimeoutError"


def test_parent_report_write_must_leave_budget(orchestration, monkeypatch):
    path, pin, calls = orchestration
    original_remaining = controller._remaining

    def remaining(deadline):
        if (path.parent / "preparation-controller-v1/preparation-result.json").exists():
            raise TimeoutError("synthetic report exhausted300")
        return original_remaining(deadline)

    monkeypatch.setattr(controller, "_remaining", remaining)
    with pytest.raises(TimeoutError, match="report exhausted300"):
        controller.run_preparation(path, pin)
    assert len(calls) == 3
    failure = json.loads(
        (path.parent / "preparation-controller-v1/preparation-failure.json").read_text()
    )
    assert failure["status"] == "PREPARATION_FAILED_NO_RETRY"
    assert failure["phase"] == "parent_report"


def test_terminal_contract_drift_refuses_parent_completion(orchestration, monkeypatch):
    path, pin, calls = orchestration
    original = controller._run_child

    def drift(argv, phase, out, deadline, rows):
        result = original(argv, phase, out, deadline, rows)
        if phase == "fixture_preparer":
            path.write_text("{}")
        return result

    monkeypatch.setattr(controller, "_run_child", drift)
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        controller.run_preparation(path, pin)
    assert len(calls) == 3
    failure = json.loads(
        (path.parent / "preparation-controller-v1/preparation-failure.json").read_text()
    )
    assert failure["phase"] == "parent_input_recheck"
    assert not (path.parent / "preparation-controller-v1/preparation-result.json").exists()


@pytest.mark.parametrize("changed", ["profile", "trace", "thread"])
def test_parent_rejects_observation_or_extra_thread_before_guard(
    orchestration, monkeypatch, changed
):
    path, pin, calls = orchestration
    if changed == "profile":
        monkeypatch.setattr(controller.sys, "getprofile", lambda: object())
    elif changed == "trace":
        monkeypatch.setattr(controller.sys, "gettrace", lambda: object())
    else:
        monkeypatch.setattr(controller.threading, "active_count", lambda: 2)
    with pytest.raises(ValueError, match="SINGLE_THREAD_PARENT_REQUIRED"):
        controller.run_preparation(path, pin)
    assert calls == []
    assert not (path.parent / "preparation-controller-v1").exists()


def test_terminal_source_drift_refuses_parent_completion(orchestration, monkeypatch):
    path, pin, calls = orchestration
    original = controller._run_child

    def drift(argv, phase, out, deadline, rows):
        result = original(argv, phase, out, deadline, rows)
        if phase == "fixture_preparer":
            (path.parent / "synthetic-source.py").write_text("# changed after child exit")
        return result

    monkeypatch.setattr(controller, "_run_child", drift)
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        controller.run_preparation(path, pin)
    assert len(calls) == 3
    failure = json.loads(
        (path.parent / "preparation-controller-v1/preparation-failure.json").read_text()
    )
    assert failure["phase"] == "parent_input_recheck"

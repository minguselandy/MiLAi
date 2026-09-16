"""CPU runner orchestration/AST checks, not a real cold replay matrix.

Batch, guard admission and child outcomes are explicit synthetic fixtures here.
The only real processes are short-lived guarded help/refusal probes. No real
CPU root, lineage, model, HTTP request or successful business audit is exercised.
"""

import ast
import copy
import inspect
import os
import socket
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0222_presentation_runner_v2 import SyntheticBatch

import run_v0222_presentation as child_owner
import run_v0222_presentation_v2 as live
import run_v0222_scoped_cpu as bootstrap
import v0222_scoped_cpu_runner as runner
from v0220_evidence import read, save
from v0220_provider_hardened import ProviderStop
from v0222_scoped_cpu_batch import OfflineBatch


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CPU_RUNNER_SYNTHETIC_NO_HTTP")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def fixture(tmp_path, monkeypatch, *, fail_at=None, timed_out=False):
    clock, calls, guards = [1000.0], [], []
    batch = SyntheticBatch(tmp_path, clock)
    monkeypatch.setattr(runner, "require_cpu_network_guard", lambda: guards.append("SYNTHETIC"))
    monkeypatch.setattr(runner.time, "time", lambda: clock[0])
    monkeypatch.setattr(runner, "Batch", lambda *_: batch)

    def stop(root, binding, candidate, exc):
        # Explicit simulated stop, not CPU guard or exact-root authorization.
        if candidate is not None:
            try:
                candidate.stop(str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__)
            except BaseException as secondary:
                exc.add_note("SECONDARY_STOP_FAILURE: " + type(secondary).__name__)

    monkeypatch.setattr(runner, "stop_batch", stop)

    def child(command, *, timeout, on_failure):
        assert guards and not batch.active_scope
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            batch.last_db.execute("SELECT 1")
        assert command == [
            sys.executable,
            str(runner.LAB / "tools/run_v0222_scoped_cpu_worker.py"),
            "--root",
            str(tmp_path),
            "--binding-sha256",
            "CPU_TEST_ONLY_BINDING",
            "--episode",
            command[-1],
        ]
        assert 0 < timeout <= 300
        assert len(batch.operations) == len(calls) + 1
        episode = command[-1]
        calls.append((episode, timeout))
        next(row for row in batch.rows if row["id"] == episode)["status"] = "RUNNING"
        batch.current_pid = os.getpid() + 100000 + len(calls)
        failed = len(calls) == fail_at
        if failed:
            on_failure(ProviderStop("SYNTHETIC_FIRST_CHILD_FAILURE"))
        return {
            "pid": batch.current_pid,
            "parent_pid": os.getpid(),
            "returncode": -9 if failed else 0,
            "seconds": 0.01,
            "stdout": "SYNTHETIC_NOT_REAL_WORKER",
            "stderr": "",
            "timed_out": bool(failed and timed_out),
        }

    monkeypatch.setattr(runner, "run_child", child)
    return batch, calls, clock, guards


class NormalizeRunner(ast.NodeTransformer):
    def visit_Constant(self, node):
        mapping = {
            "tools/run_v0222_scoped_cpu_worker.py": "tools/v0222_presentation_worker_v2.py",
            "CPU_REPLAY_P3_PASS": "FULL_FIDELITY_PASS",
            "CPU_REPLAY_P4_PASS": "KNOWN_INTENT_PASS",
            "CPU_REPLAY_STAGE_NOT_MET": "FULL_STAGE_NOT_MET",
        }
        if isinstance(node.value, str):
            node.value = mapping.get(node.value, node.value)
        return node


def test_original_run_ast_retained_except_explicit_cpu_guard_path_and_labels():
    original = ast.parse(textwrap.dedent(inspect.getsource(live.run)))
    current = ast.parse(textwrap.dedent(inspect.getsource(runner.run)))
    body = current.body[0].body
    guard = body.pop(0)
    assert ast.dump(guard) == ast.dump(ast.parse("require_cpu_network_guard()").body[0])
    result_dicts = [
        node
        for node in ast.walk(current)
        if isinstance(node, ast.Dict)
        and any(
            isinstance(key, ast.Constant) and key.value == "execution_mode" for key in node.keys
        )
    ]
    assert len(result_dicts) == 1
    result = result_dicts[0]
    fields = {
        "execution_mode": ast.Name(id="CPU_MODE", ctx=ast.Load()),
        "real_http_requests": ast.Constant(0),
        "real_model_requests": ast.Constant(0),
        "mock_cost_is_not_real_cost": ast.Constant(True),
        "model_capability_or_live_admission": ast.Constant(False),
    }
    retained = []
    for key, value in zip(result.keys, result.values, strict=True):
        if isinstance(key, ast.Constant) and key.value in fields:
            assert ast.dump(value) == ast.dump(fields.pop(key.value))
        else:
            retained.append((key, value))
    assert not fields
    result.keys, result.values = [key for key, _ in retained], [value for _, value in retained]
    normalized = NormalizeRunner().visit(copy.deepcopy(current))
    assert ast.dump(original) == ast.dump(normalized)


def test_fixed_public_entry_and_original_child_manager():
    assert list(inspect.signature(runner.run).parameters) == ["root", "binding", "stage"]
    assert runner.Batch is OfflineBatch
    assert runner.run_child is child_owner.run_child
    body = ast.parse(textwrap.dedent(inspect.getsource(bootstrap.main))).body[0].body
    assert isinstance(body[0], ast.ImportFrom) and body[0].module == "v0222_scoped_cpu_guard"
    assert ast.dump(body[1]) == ast.dump(ast.parse("enable_cpu_network_guard()").body[0])
    assert isinstance(body[2], ast.ImportFrom) and body[2].module == "v0222_scoped_cpu_runner"


@pytest.mark.parametrize("stage,count", [("P3", 16), ("P4", 24)])
def test_synthetic_complete_sequence_is_labeled_only_cpu_replay(
    tmp_path, monkeypatch, stage, count
):
    batch, calls, _, guards = fixture(tmp_path, monkeypatch)
    if stage == "P4":
        batch.gate = True
        for row in batch.rows[:16]:
            row["status"] = "PASS"
    result = runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", stage)
    assert result["status"] == f"CPU_REPLAY_{stage}_PASS" and result["passed"] == count
    assert len(calls) == count and batch.operations == [stage] * count
    assert batch.finished == [spec["id"] for spec in batch.plan[stage]]
    assert batch.gate_calls == (1 if stage == "P3" else 0)
    assert batch.launched == [stage] and guards == ["SYNTHETIC"]
    assert result["execution_mode"] == "CPU_MOCK_ONLY"
    assert result["real_http_requests"] == result["real_model_requests"] == 0
    assert result["mock_cost_is_not_real_cost"] is True
    assert result["model_capability_or_live_admission"] is False
    assert result["Memory"] == "NOT_ADMITTED" and result["Judge"] == 0
    assert read(tmp_path / f"{stage}-result.json") == result
    assert len(result["unrun"]) == (24 if stage == "P3" else 0)


@pytest.mark.parametrize("fail_at,timed_out", [(1, False), (8, False), (9, True), (16, False)])
def test_first_child_failure_preserves_stop_and_unrun_without_retry(
    tmp_path, monkeypatch, fail_at, timed_out
):
    batch, calls, _, _ = fixture(tmp_path, monkeypatch, fail_at=fail_at, timed_out=timed_out)
    result = runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", "P3")
    assert result["status"] == "CPU_REPLAY_STAGE_NOT_MET" and result["passed"] == fail_at - 1
    assert len(calls) == fail_at and len(result["unrun"]) == 40 - fail_at
    assert batch.stopped == "SYNTHETIC_FIRST_CHILD_FAILURE" and not batch.gate_calls
    path = tmp_path / "exits" / (calls[-1][0] + ".json")
    assert read(path)["timed_out"] is timed_out
    before = (tmp_path / "P3-result.json").read_bytes()
    with pytest.raises(FileExistsError):
        runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", "P3")
    assert len(calls) == fail_at and (tmp_path / "P3-result.json").read_bytes() == before


def test_p4_requires_gate_before_any_child(tmp_path, monkeypatch):
    batch, calls, _, _ = fixture(tmp_path, monkeypatch)
    result = runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", "P4")
    assert result["status"] == "CPU_REPLAY_STAGE_NOT_MET" and not calls and batch.stopped


@pytest.mark.parametrize("change", ["expired", "close_expired", "close_stop"])
def test_scope_close_failure_prevents_spawn(tmp_path, monkeypatch, change):
    batch, calls, clock, _ = fixture(tmp_path, monkeypatch)
    if change == "expired":
        batch.deadline = 999
    elif change == "close_expired":
        batch.after_scope = lambda: clock.__setitem__(0, batch.deadline)
    else:
        batch.after_scope = lambda: batch.stop("STOP_DURING_SCOPE_CLOSE")
    result = runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", "P3")
    assert not calls and result["status"] == "CPU_REPLAY_STAGE_NOT_MET" and batch.stopped


def test_remaining_timeout_is_computed_after_scope_close(tmp_path, monkeypatch):
    batch, calls, clock, _ = fixture(tmp_path, monkeypatch, fail_at=1)
    batch.after_scope = lambda: clock.__setitem__(0, batch.deadline - 0.25)
    runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", "P3")
    assert calls == [("p3-01", 0.25)]


@pytest.mark.parametrize("change", ["parent", "different_child"])
def test_wrong_audit_pid_stops_next_child(tmp_path, monkeypatch, change):
    batch, calls, _, _ = fixture(tmp_path, monkeypatch)
    original = batch.finish

    def finish(episode):
        result = original(episode)
        result["pid"] = os.getpid() if change == "parent" else result["pid"] + 1
        return result

    monkeypatch.setattr(batch, "finish", finish)
    result = runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", "P3")
    assert result["status"] == "CPU_REPLAY_STAGE_NOT_MET" and len(calls) == 1
    assert batch.stopped == "ACTUAL_COLD_CHILD_PID_NOT_PROVEN"


@pytest.mark.parametrize("failure", ["exit_save", "finish", "gate", "snapshot", "result_save"])
def test_persistence_or_acceptance_failure_never_fake_pass(tmp_path, monkeypatch, failure):
    batch, calls, _, _ = fixture(tmp_path, monkeypatch)

    def fail(*args):
        raise OSError("CPU_SYNTHETIC_FAILURE")

    if failure in {"finish", "gate", "snapshot"}:
        monkeypatch.setattr(batch, {"gate": "freeze_p3_gate"}.get(failure, failure), fail)
    else:

        def persist(path, value):
            if (failure == "exit_save" and path.parent.name == "exits") or (
                failure == "result_save" and path.name == "P3-result.json"
            ):
                fail()
            save(path, value)

        monkeypatch.setattr(runner, "save", persist)
    if failure in {"snapshot", "result_save"}:
        with pytest.raises(OSError):
            runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", "P3")
    else:
        result = runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", "P3")
        assert result["status"] == "CPU_REPLAY_STAGE_NOT_MET"
    assert batch.stopped == "OSError"
    if failure == "exit_save":
        assert len(calls) == 1 and not batch.finished


def test_all_finished_plus_gate_failure_and_stop_failure_cannot_fake_pass(tmp_path, monkeypatch):
    batch, _, _, _ = fixture(tmp_path, monkeypatch)
    primary = OSError("CPU_SYNTHETIC_GATE_FAILURE")

    def gate(path):
        assert len(batch.finished) == 16
        raise primary

    def stop(reason):
        raise OSError("CPU_SYNTHETIC_STOP_FAILURE")

    monkeypatch.setattr(batch, "freeze_p3_gate", gate)
    monkeypatch.setattr(batch, "stop", stop)
    result = runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", "P3")
    assert result["passed"] == 16 and result["batch"]["stop"] is None
    assert result["status"] == "CPU_REPLAY_STAGE_NOT_MET" and result["error"] == "OSError"
    assert primary.__notes__ == ["SECONDARY_STOP_FAILURE: OSError"]


def test_late_stop_prevents_full_success_label(tmp_path, monkeypatch):
    batch, _, _, _ = fixture(tmp_path, monkeypatch)
    original = batch.freeze_p3_gate

    def gate(path):
        original(path)
        batch.stop("CPU_LATE_STOP")

    monkeypatch.setattr(batch, "freeze_p3_gate", gate)
    result = runner.run(tmp_path, "CPU_TEST_ONLY_BINDING", "P3")
    assert result["passed"] == 16 and result["status"] == "CPU_REPLAY_STAGE_NOT_MET"


@pytest.mark.parametrize("kind", ["constructor", "invalid_stage", "interrupt"])
def test_early_or_base_exception_is_not_converted_to_success(tmp_path, monkeypatch, kind):
    _, calls, _, _ = fixture(tmp_path, monkeypatch)
    primary = KeyboardInterrupt("CPU_SYNTHETIC_INTERRUPT") if kind == "interrupt" else ValueError()

    def fail(*args, **kwargs):
        raise primary

    if kind == "constructor":
        monkeypatch.setattr(runner, "Batch", fail)
    elif kind == "interrupt":
        monkeypatch.setattr(runner, "run_child", fail)
    with pytest.raises(ProviderStop if kind == "invalid_stage" else type(primary)):
        runner.run(
            tmp_path, "CPU_TEST_ONLY_BINDING", "INVALID" if kind == "invalid_stage" else "P3"
        )
    assert not calls and not (tmp_path / "P3-result.json").exists()


@pytest.mark.parametrize("operation", ["unguarded", "help", "invalid_root", "command_override"])
def test_fresh_guard_boundary_or_bootstrap_refusal_is_not_a_cold_matrix(tmp_path, operation):
    lab = Path(__file__).resolve().parents[2]
    root = tmp_path / "not-created"
    if operation == "unguarded":
        code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from v0222_scoped_cpu_runner import run
try:
    run(Path(sys.argv[2]), '0' * 64, 'P3')
except RuntimeError as error:
    assert str(error) == 'FRESH_CPU_PROCESS_NETWORK_GUARD_REQUIRED'
else:
    raise AssertionError('unguarded runner accepted')
"""
        command = [sys.executable, "-c", code, str(lab / "tools"), str(root)]
    else:
        command = [sys.executable, str(lab / "tools/run_v0222_scoped_cpu.py")]
        command += (
            ["--help"]
            if operation == "help"
            else ["--root", str(root), "--binding-sha256", "0" * 64, "--stage", "P3"]
        )
        if operation == "command_override":
            command += ["--command", "must-not-run"]
    result = subprocess.run(  # noqa: S603 -- Fixed guarded help/refusal processes only.
        command, capture_output=True, text=True, timeout=30, cwd=lab
    )
    if operation in {"unguarded", "help"}:
        assert result.returncode == 0, result.stderr
    elif operation == "command_override":
        assert result.returncode == 2 and "unrecognized arguments" in result.stderr
    else:
        assert result.returncode != 0 and "CPU_REPLAY_ROOT_REQUIRED" in result.stderr
    assert not root.exists()

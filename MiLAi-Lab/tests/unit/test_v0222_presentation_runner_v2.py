"""Synthetic runner orchestration, not an actual scoped cold-model matrix.

Batch/admission/child behavior is explicitly simulated. Only the reused child
manager's small local Python success/failure/timeout probes create OS processes;
none imports a model, makes HTTP, or touches a formal evidence root.
"""

import copy
import os
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import run_v0222_presentation as old_runner
import run_v0222_presentation_v2 as runner
from v0220_evidence import read, save
from v0220_provider_hardened import ProviderStop


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("LOCAL_RUNNER_TEST_NO_HTTP")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


class SyntheticBatch:
    def __init__(self, root, clock):
        self.root, self.clock, self.stopped = root, clock, None
        self.plan = {
            stage: [{"id": f"{stage.lower()}-{i:02d}"} for i in range(1, count + 1)]
            for stage, count in (("P3", 16), ("P4", 24))
        }
        self.rows = [
            {"id": spec["id"], "stage": stage, "status": "PENDING"}
            for stage, specs in self.plan.items()
            for spec in specs
        ]
        self.deadline, self.launched, self.gate = 2800.0, [], False
        self.active_scope, self.after_scope, self.last_db = False, None, None
        self.operations, self.finished, self.gate_calls = [], [], 0
        self.current_pid = None

    def stop(self, reason):
        self.stopped = self.stopped or reason
        for row in self.rows:
            if row["status"] == "RUNNING":
                row["status"] = "FAIL"

    def _check(self):
        if self.stopped:
            raise ProviderStop("NO_RESTART_AFTER_STOP")

    def launch_once(self, stage):
        self._check()
        if stage in self.launched or (stage == "P4" and not self.gate):
            raise ProviderStop("STAGE_NOT_ADMITTED_OR_ALREADY_LAUNCHED")
        self.launched.append(stage)

    @contextmanager
    def _operation(self, stage):
        self._check()
        assert not self.active_scope
        self.operations.append(stage)
        try:
            with closing(sqlite3.connect(":memory:")) as db:
                self.last_db, self.active_scope = db, True
                db.execute("CREATE TABLE meta(key TEXT,value REAL)")
                db.execute("INSERT INTO meta VALUES (?,?)", (stage + "_deadline", self.deadline))
                yield db, "SYNTHETIC_SCOPE", "SYNTHETIC_STATE"
        finally:
            self.active_scope = False
        if self.after_scope:
            self.after_scope()
        self._check()
        if self.clock[0] >= self.deadline:
            raise ProviderStop("BATCH_PHASE_DEADLINE")

    def finish(self, episode):
        self._check()
        assert not self.active_scope
        # This verifies runner ordering, not the independent business auditor.
        exit_record = read(self.root / "exits" / (episode + ".json"))
        assert exit_record["pid"] == self.current_pid
        assert exit_record["parent_pid"] == os.getpid()
        assert exit_record["returncode"] == 0 and exit_record["timed_out"] is False
        row = next(row for row in self.rows if row["id"] == episode)
        row["status"] = "PASS"
        self.finished.append(episode)
        return {"id": episode, "status": "PASS", "pid": self.current_pid, "SYNTHETIC": True}

    def p3_gate(self):
        raise AssertionError("DO_NOT_DERIVE_GATE_TWICE")

    def freeze_p3_gate(self, path):
        self._check()
        assert sum(row["stage"] == "P3" and row["status"] == "PASS" for row in self.rows) == 16
        assert not path.exists()
        self.gate_calls += 1
        assert self.gate_calls == 1
        save(path, {"status": "G_P3_PASS", "SYNTHETIC_NOT_ACTUAL_AUDIT": True})
        self.gate = True

    def snapshot(self):
        return {
            "stop": self.stopped,
            "episodes": copy.deepcopy(self.rows),
            "cost": {"SYNTHETIC": True},
        }


def fixture(tmp_path, monkeypatch, *, fail_at=None, timeout=False):
    clock, calls = [1000.0], []
    batch = SyntheticBatch(tmp_path, clock)
    monkeypatch.setattr(runner.time, "time", lambda: clock[0])
    monkeypatch.setattr(runner, "Batch", lambda *_: batch)

    def child(command, *, timeout: float, on_failure):
        assert not batch.active_scope
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            batch.last_db.execute("SELECT 1")
        assert command[:2] == [
            sys.executable,
            str(runner.LAB / "tools/v0222_presentation_worker_v2.py"),
        ]
        assert command[2:6] == ["--root", str(tmp_path), "--binding-sha256", "TEST_ONLY_BINDING"]
        assert command[6] == "--episode" and 0 < timeout <= 300
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
            "stdout": "SYNTHETIC",
            "stderr": "",
            "timed_out": failed and timed_out,
        }

    timed_out = timeout
    monkeypatch.setattr(runner, "run_child", child)
    return batch, calls, clock


def test_synthetic_p3_16_sequential_closed_admissions_one_gate(tmp_path, monkeypatch):
    batch, calls, _ = fixture(tmp_path, monkeypatch)
    result = runner.run(tmp_path, "TEST_ONLY_BINDING", "P3")
    assert result["status"] == "FULL_FIDELITY_PASS" and result["passed"] == 16
    assert batch.launched == ["P3"] and batch.operations == ["P3"] * 16
    assert batch.gate_calls == 1 and len(calls) == 16
    assert len({row["pid"] for row in result["rows"]}) == 16
    assert len(result["unrun"]) == 24 and all(ep.startswith("p4-") for ep in result["unrun"])
    assert (
        result["Memory"] == "NOT_ADMITTED" and result["Judge"] == result["direct_device_calls"] == 0
    )
    assert read(tmp_path / "P3-result.json") == result
    assert len(list((tmp_path / "exits").glob("*.json"))) == 16


def test_synthetic_p4_24_requires_prior_gate_and_has_no_next_stage(tmp_path, monkeypatch):
    batch, calls, _ = fixture(tmp_path, monkeypatch)
    batch.gate = True
    for row in batch.rows[:16]:
        row["status"] = "PASS"
    result = runner.run(tmp_path, "TEST_ONLY_BINDING", "P4")
    assert result["status"] == "KNOWN_INTENT_PASS" and result["passed"] == 24
    assert len(calls) == 24 and batch.operations == ["P4"] * 24
    assert batch.launched == ["P4"] and batch.gate_calls == 0 and result["unrun"] == []


@pytest.mark.parametrize("fail_at,timeout", [(1, False), (8, False), (9, True), (16, False)])
def test_first_failed_child_preserves_stop_exits_and_remaining_positions(
    tmp_path, monkeypatch, fail_at, timeout
):
    batch, calls, _ = fixture(tmp_path, monkeypatch, fail_at=fail_at, timeout=timeout)
    result = runner.run(tmp_path, "TEST_ONLY_BINDING", "P3")
    assert result["status"] == "FULL_STAGE_NOT_MET" and result["passed"] == fail_at - 1
    assert len(calls) == fail_at and not batch.gate and batch.gate_calls == 0
    assert batch.stopped == result["batch"]["stop"] == "SYNTHETIC_FIRST_CHILD_FAILURE"
    assert len(result["unrun"]) == 40 - fail_at
    assert read(tmp_path / "exits" / (calls[-1][0] + ".json"))["timed_out"] is timeout
    before = list(calls)
    original_result = (tmp_path / "P3-result.json").read_bytes()
    # Frozen save is exclusive-create: a forbidden rerun cannot overwrite the
    # existing terminal report even while reporting its refusal.
    with pytest.raises(FileExistsError):
        runner.run(tmp_path, "TEST_ONLY_BINDING", "P3")
    assert (tmp_path / "P3-result.json").read_bytes() == original_result
    assert calls == before and batch.launched == ["P3"]


def test_p4_without_gate_has_no_child(tmp_path, monkeypatch):
    batch, calls, _ = fixture(tmp_path, monkeypatch)
    result = runner.run(tmp_path, "TEST_ONLY_BINDING", "P4")
    assert result["status"] == "FULL_STAGE_NOT_MET" and batch.stopped and not calls
    assert len(result["unrun"]) == 40


@pytest.mark.parametrize("change", ["already_expired", "scope_close_expired", "scope_close_stop"])
def test_scope_close_deadline_or_stop_prevents_spawn(tmp_path, monkeypatch, change):
    batch, calls, clock = fixture(tmp_path, monkeypatch)
    if change == "already_expired":
        batch.deadline = 999
    elif change == "scope_close_stop":
        batch.after_scope = lambda: batch.stop("STOP_DURING_SCOPE_CLOSE")
    else:
        batch.after_scope = lambda: clock.__setitem__(0, batch.deadline)
    result = runner.run(tmp_path, "TEST_ONLY_BINDING", "P3")
    assert not calls and not batch.active_scope
    assert result["status"] == "FULL_STAGE_NOT_MET" and batch.stopped


def test_child_timeout_uses_remaining_after_scope_close(tmp_path, monkeypatch):
    batch, calls, clock = fixture(tmp_path, monkeypatch, fail_at=1)
    batch.after_scope = lambda: clock.__setitem__(0, batch.deadline - 0.25)
    runner.run(tmp_path, "TEST_ONLY_BINDING", "P3")
    assert calls == [("p3-01", 0.25)]


@pytest.mark.parametrize("change", ["parent", "different_child"])
def test_wrong_audited_pid_stops_before_next_child(tmp_path, monkeypatch, change):
    batch, calls, _ = fixture(tmp_path, monkeypatch)
    original = batch.finish

    def finish(ep):
        result = original(ep)
        result["pid"] = os.getpid() if change == "parent" else result["pid"] + 1
        return result

    monkeypatch.setattr(batch, "finish", finish)
    result = runner.run(tmp_path, "TEST_ONLY_BINDING", "P3")
    assert result["status"] == "FULL_STAGE_NOT_MET" and len(calls) == 1
    assert batch.stopped == "ACTUAL_COLD_CHILD_PID_NOT_PROVEN"


@pytest.mark.parametrize("failure", ["exit_save", "finish", "gate", "snapshot", "result_save"])
def test_output_and_audit_failures_stop_before_return_or_escape(tmp_path, monkeypatch, failure):
    batch, calls, _ = fixture(tmp_path, monkeypatch)

    def fail(*args):
        raise OSError("SYNTHETIC_OUTPUT_FAILURE")

    if failure in {"finish", "gate", "snapshot"}:
        monkeypatch.setattr(
            batch,
            {"finish": "finish", "gate": "freeze_p3_gate", "snapshot": "snapshot"}[failure],
            fail,
        )
    else:

        def saver(path, value):
            if (failure == "exit_save" and path.parent.name == "exits") or (
                failure == "result_save" and path.name == "P3-result.json"
            ):
                fail()
            save(path, value)

        monkeypatch.setattr(runner, "save", saver)
    if failure in {"snapshot", "result_save"}:
        with pytest.raises(OSError):
            runner.run(tmp_path, "TEST_ONLY_BINDING", "P3")
    else:
        result = runner.run(tmp_path, "TEST_ONLY_BINDING", "P3")
        assert result["status"] == "FULL_STAGE_NOT_MET"
    assert batch.stopped == "OSError"
    if failure == "exit_save":
        assert not batch.finished and len(calls) == 1


def test_late_stop_never_reports_full_success(tmp_path, monkeypatch):
    batch, _, _ = fixture(tmp_path, monkeypatch)
    original = batch.freeze_p3_gate

    def gate(path):
        original(path)
        batch.stop("LATE_STOP")

    monkeypatch.setattr(batch, "freeze_p3_gate", gate)
    result = runner.run(tmp_path, "TEST_ONLY_BINDING", "P3")
    assert result["passed"] == 16 and result["status"] == "FULL_STAGE_NOT_MET"
    assert result["batch"]["stop"] == "LATE_STOP"


def test_gate_error_with_failed_stop_cannot_pass_even_after_all_16_finishes(tmp_path, monkeypatch):
    batch, calls, _ = fixture(tmp_path, monkeypatch)
    gate_error = OSError("SYNTHETIC_GATE_PERSISTENCE_FAILURE")
    stop_calls = []

    def failed_gate(path):
        assert len(batch.finished) == 16
        assert path == tmp_path / "P3-gate.json" and not path.exists()
        batch.gate_calls += 1
        raise gate_error

    def failed_stop(reason):
        stop_calls.append(reason)
        raise RuntimeError("SYNTHETIC_STOP_PERSISTENCE_FAILURE")

    monkeypatch.setattr(batch, "freeze_p3_gate", failed_gate)
    monkeypatch.setattr(batch, "stop", failed_stop)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--root",
            str(tmp_path),
            "--binding-sha256",
            "TEST_ONLY_BINDING",
            "--stage",
            "P3",
        ],
    )
    # Exercise real CLI -> runner -> synthetic complete stage, not a mocked run result.
    assert runner.main() == 1
    result = read(tmp_path / "P3-result.json")
    assert result["passed"] == len(calls) == len(batch.finished) == 16
    assert result["batch"]["stop"] is None and batch.stopped is None
    assert result["error"] == "OSError" and result["status"] == "FULL_STAGE_NOT_MET"
    assert batch.gate_calls == 1 and not batch.gate and not (tmp_path / "P3-gate.json").exists()
    assert len(result["unrun"]) == 24 and stop_calls == ["OSError"]
    assert any("SECONDARY_STOP_FAILURE: RuntimeError" in note for note in gate_error.__notes__)


@pytest.mark.parametrize(
    "status,code", [("FULL_STAGE_NOT_MET", 1), ("FULL_FIDELITY_PASS", 0), ("KNOWN_INTENT_PASS", 0)]
)
def test_cli_exit_status_without_real_batch(tmp_path, monkeypatch, status, code):
    calls = []

    def run(*args):
        calls.append(args)
        return {"status": status}

    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--root", str(tmp_path), "--binding-sha256", "TEST_ONLY", "--stage", "P3"],
    )
    assert runner.main() == code
    assert calls == [(tmp_path, "TEST_ONLY", "P3")]


@pytest.mark.parametrize("code,expected", [("print('local child')", 0), ("raise SystemExit(7)", 7)])
def test_reused_child_manager_actual_local_python(code, expected):
    assert runner.run_child is old_runner.run_child
    failures = []
    result = runner.run_child([sys.executable, "-c", code], timeout=5, on_failure=failures.append)
    assert result["pid"] != os.getpid() and result["parent_pid"] == os.getpid()
    assert result["returncode"] == expected and result["timed_out"] is False
    assert bool(failures) is (expected != 0)


def test_reused_child_manager_kills_only_owned_timed_out_local_python():
    failures = []
    result = runner.run_child(
        [sys.executable, "-c", "import time; print('owned', flush=True); time.sleep(5)"],
        timeout=0.15,
        on_failure=failures.append,
    )
    assert isinstance(failures[0], subprocess.TimeoutExpired)
    assert result["timed_out"] and result["returncode"] < 0 and "owned" in result["stdout"]
    with pytest.raises(ProcessLookupError):
        os.kill(result["pid"], 0)

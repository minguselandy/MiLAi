"""Finite runner orchestration and real local child cleanup; no model HTTP."""

import contextlib
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import run_v0222_presentation as runner
from v0220_evidence import read, save
from v0220_provider_hardened import ProviderStop


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("NO_NETWORK")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


class FixtureBatch:
    def __init__(self, root):
        self.root, self.stopped, self.gate = root, None, False
        self.plan = {
            stage: [{"id": f"{stage.lower()}-{i:02d}"} for i in range(1, count + 1)]
            for stage, count in (("P3", 16), ("P4", 24))
        }
        self.rows = [
            {"id": spec["id"], "stage": stage, "status": "PENDING"}
            for stage, specs in self.plan.items()
            for spec in specs
        ]
        self.deadline, self.launched, self.current_pid = time.time() + 1000, [], None

    def stop(self, reason):
        self.stopped = self.stopped or reason

    def authorize(self, stage):
        assert stage in self.plan
        if self.stopped:
            raise ProviderStop("PERMANENT_STOP")

    def check_journal(self, _):
        self.authorize("P3")

    @contextlib.contextmanager
    def transaction(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE meta(key TEXT,value REAL)")
            for stage in self.plan:
                db.execute("INSERT INTO meta VALUES (?,?)", (stage + "_deadline", self.deadline))
            yield db

    def launch_once(self, stage):
        self.authorize(stage)
        if stage in self.launched or (stage == "P4" and not self.gate):
            raise ProviderStop("STAGE_NOT_ADMITTED_OR_ALREADY_LAUNCHED")
        self.launched.append(stage)

    def finish(self, episode):
        self.authorize("P3")
        row = next(r for r in self.rows if r["id"] == episode)
        row["status"] = "PASS"
        return {"id": episode, "status": "PASS", "pid": self.current_pid}

    def p3_gate(self):
        assert sum(r["stage"] == "P3" and r["status"] == "PASS" for r in self.rows) == 16
        return {"status": "G_P3_PASS", "TEST_ONLY": True}

    def freeze_p3_gate(self, path):
        assert read(path) == self.p3_gate()
        self.gate = True

    def snapshot(self):
        return {"stop": self.stopped, "episodes": self.rows, "cost": {"TEST_ONLY": True}}


def setup(tmp_path, monkeypatch, *, fail_at=None):
    batch, calls = FixtureBatch(tmp_path), []
    monkeypatch.setattr(runner, "Batch", lambda *_: batch)

    def child(command, *, timeout, on_failure):
        assert 0 < timeout <= 300
        assert Path(command[1]).name == "v0222_presentation_worker.py"
        calls.append(command[-1])
        batch.current_pid = os.getpid() + 10000 + len(calls)
        failed = len(calls) == fail_at
        if failed:
            on_failure(ProviderStop("SYNTHETIC_CHILD_FAILURE"))
        return {
            "pid": batch.current_pid,
            "returncode": 1 if failed else 0,
            "stdout": "",
            "stderr": "",
            "seconds": 0.01,
            "timed_out": False,
        }

    monkeypatch.setattr(runner, "run_child", child)
    return batch, calls


def test_p3_complete16_freezes_gate_but_does_not_launch_p4(tmp_path, monkeypatch):
    batch, calls = setup(tmp_path, monkeypatch)
    result = runner.run(tmp_path, "TEST_ONLY", "P3")
    assert result["status"] == "FULL_FIDELITY_PASS" and result["passed"] == 16
    assert batch.gate and batch.launched == ["P3"] and len(calls) == 16
    assert len(result["unrun"]) == 24 and result["Memory"] == "NOT_ADMITTED"


def test_p4_conditional_24_and_no_downstream_launch(tmp_path, monkeypatch):
    batch, calls = setup(tmp_path, monkeypatch)
    batch.gate = True
    for row in batch.rows[:16]:
        row["status"] = "PASS"
    result = runner.run(tmp_path, "TEST_ONLY", "P4")
    assert result["status"] == "KNOWN_INTENT_PASS" and len(calls) == 24
    assert batch.launched == ["P4"] and result["unrun"] == []


@pytest.mark.parametrize("fail_at", [1, 8, 9])
def test_first_failure_keeps_complete_remaining_matrix_and_stop(tmp_path, monkeypatch, fail_at):
    batch, calls = setup(tmp_path, monkeypatch, fail_at=fail_at)
    result = runner.run(tmp_path, "TEST_ONLY", "P3")
    assert result["status"] == "FULL_STAGE_NOT_MET" and not batch.gate
    assert len(calls) == fail_at and result["passed"] == fail_at - 1
    assert batch.stopped == "SYNTHETIC_CHILD_FAILURE"
    assert all(f"p4-{i:02d}" in result["unrun"] for i in range(1, 25))
    assert read(tmp_path / "exits" / (calls[-1] + ".json"))["returncode"] == 1


def test_p4_without_new_gate_never_starts_child(tmp_path, monkeypatch):
    batch, calls = setup(tmp_path, monkeypatch)
    result = runner.run(tmp_path, "TEST_ONLY", "P4")
    assert result["status"] == "FULL_STAGE_NOT_MET" and batch.stopped and not calls


@pytest.mark.parametrize("failure", ["exit_save", "gate_save", "result_save", "finish", "gate"])
def test_all_result_and_gate_failures_permanently_stop(tmp_path, monkeypatch, failure):
    batch, _ = setup(tmp_path, monkeypatch)

    def failed(*_args):
        raise OSError("SYNTHETIC_FAILURE")

    if failure in {"finish", "gate"}:
        monkeypatch.setattr(batch, "finish" if failure == "finish" else "freeze_p3_gate", failed)
    else:

        def checked_save(path, value):
            if (
                (failure == "exit_save" and path.parent.name == "exits")
                or (failure == "gate_save" and path.name == "P3-gate.json")
                or (failure == "result_save" and path.name == "P3-result.json")
            ):
                raise OSError("SYNTHETIC_FAILURE")
            save(path, value)

        monkeypatch.setattr(runner, "save", checked_save)
    if failure == "result_save":
        with pytest.raises(OSError):
            runner.run(tmp_path, "TEST_ONLY", "P3")
    else:
        assert runner.run(tmp_path, "TEST_ONLY", "P3")["status"] == "FULL_STAGE_NOT_MET"
    assert batch.stopped == "OSError"


def test_phase_deadline_stops_before_first_child(tmp_path, monkeypatch):
    batch, calls = setup(tmp_path, monkeypatch)
    batch.deadline = time.time() - 1
    result = runner.run(tmp_path, "TEST_ONLY", "P3")
    assert result["status"] == "FULL_STAGE_NOT_MET" and not calls
    assert batch.stopped == "BATCH_PHASE_DEADLINE"


def test_final_stop_cannot_be_overwritten_by_complete_matrix(tmp_path, monkeypatch):
    batch, _ = setup(tmp_path, monkeypatch)
    batch.gate = True
    original = batch.finish

    def finish(episode):
        result = original(episode)
        if episode == "p4-24":
            batch.stop("LATE_PERMANENT_STOP")
        return result

    monkeypatch.setattr(batch, "finish", finish)
    result = runner.run(tmp_path, "TEST_ONLY", "P4")
    assert result["passed"] == 24 and result["status"] == "FULL_STAGE_NOT_MET"
    assert result["batch"]["stop"] == "LATE_PERMANENT_STOP"


def test_wrong_child_pid_stops_before_next_position(tmp_path, monkeypatch):
    batch, calls = setup(tmp_path, monkeypatch)
    original = batch.finish

    def finish(episode):
        result = original(episode)
        result["pid"] = os.getpid()
        return result

    monkeypatch.setattr(batch, "finish", finish)
    result = runner.run(tmp_path, "TEST_ONLY", "P3")
    assert result["status"] == "FULL_STAGE_NOT_MET" and len(calls) == 1
    assert batch.stopped == "ACTUAL_COLD_CHILD_PID_NOT_PROVEN"


@pytest.mark.parametrize(
    "code,returncode", [("print('cold child')", 0), ("raise SystemExit(7)", 7)]
)
def test_actual_cold_python_child_exit_is_captured(code, returncode):
    stops = []
    result = runner.run_child([sys.executable, "-c", code], timeout=5, on_failure=stops.append)
    assert result["pid"] != os.getpid() and result["parent_pid"] == os.getpid()
    assert result["returncode"] == returncode and not result["timed_out"]
    assert bool(stops) == (returncode != 0)


def test_actual_timed_out_child_is_killed_and_reaped_after_stop():
    stops = []
    result = runner.run_child(
        [sys.executable, "-c", "import time; print('started',flush=True); time.sleep(5)"],
        timeout=0.1,
        on_failure=stops.append,
    )
    assert isinstance(stops[0], subprocess.TimeoutExpired)
    assert result["timed_out"] and result["returncode"] < 0 and "started" in result["stdout"]
    with pytest.raises(ProcessLookupError):
        os.kill(result["pid"], 0)

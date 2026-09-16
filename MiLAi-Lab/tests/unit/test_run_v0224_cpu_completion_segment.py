"""Synthetic parent lifecycle tests; no replay, model or public HTTP."""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_v0224_cpu_completion_segment as runner
import run_v0224_live_completion as children
from v0220_evidence import read
from v0220_provider_hardened import ProviderStop


class Batch:
    def __init__(self, root):
        self.root = root
        self.auth = {"expires_unix": time.time() + 7200}
        self.plan = {"P3": [], "P4": [{"id": f"position-{i}"} for i in range(9, 25)]}
        self.calls, self.finished, self.stops = [], [], []

    def launch_once(self, stage):
        self.calls.append(("launch", stage))

    def authorize(self, stage):
        self.calls.append(("authorize", stage))

    def finish(self, episode):
        terminal = read(self.root / "exits" / (episode + ".json"))
        assert terminal["returncode"] == 0
        self.finished.append(episode)
        return {"id": episode, "pid": terminal["pid"], "status": "PASS"}

    def snapshot(self):
        return {"episodes": [{"id": i, "status": "PASS"} for i in self.finished], "stop": None}

    def stop(self, code):
        self.stops.append(code)


def test_complete_ordered_sixteen_and_actual_exit_before_finish(tmp_path, monkeypatch):
    batch, attempts = Batch(tmp_path), []

    def run(argv, *, timeout, on_failure):
        assert timeout == 3600
        assert argv[-2] == "--episode"
        attempts.append(argv[-1])
        return {"pid": 100 + len(attempts), "returncode": 0, "timed_out": False}

    monkeypatch.setattr(children, "run_child", run)
    result = runner.run_stage(batch, tmp_path / "contract.json", "a" * 64)
    assert result["status"] == "CPU_COMPLETION_SEGMENT_P4_PASS"
    assert attempts == batch.finished == [s["id"] for s in batch.plan["P4"]]
    assert len(list((tmp_path / "exits").glob("*.json"))) == 16
    assert result["real_http_requests"] == 0 and batch.stops == []


def test_failed_child_is_preserved_and_never_finished_or_retried(tmp_path, monkeypatch):
    batch, attempts = Batch(tmp_path), []

    def run(argv, *, timeout, on_failure):
        attempts.append(argv[-1])
        return {"pid": 101, "returncode": -9, "timed_out": True}

    monkeypatch.setattr(children, "run_child", run)
    with pytest.raises(ProviderStop, match="ACTUAL_CLEAN_COLD_SEGMENT_EXIT_REQUIRED"):
        runner.run_stage(batch, tmp_path / "contract.json", "a" * 64)
    assert attempts == ["position-9"] and batch.finished == []
    assert read(tmp_path / "exits/position-9.json")["returncode"] == -9
    assert read(tmp_path / "stage-failure.json")["completed"] == []


def test_failure_report_cannot_replace_original_parent_error(tmp_path, monkeypatch):
    import v0220_evidence

    batch = Batch(tmp_path)
    primary = RuntimeError("original launch")

    def launch(stage):
        raise primary

    def report(*args):
        raise OSError("secondary report")

    batch.launch_once = launch
    monkeypatch.setattr(v0220_evidence, "save", report)
    with pytest.raises(RuntimeError) as caught:
        runner.run_stage(batch, tmp_path / "contract.json", "a" * 64)
    assert caught.value is primary
    assert any("SECONDARY_STAGE_REPORT_FAILURE" in note for note in primary.__notes__)

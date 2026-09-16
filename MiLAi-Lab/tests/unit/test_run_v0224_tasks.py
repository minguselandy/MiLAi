"""Cold task glue with real local Hosts/World and no HTTP transport."""

import copy
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public
from test_v0220_session import FakeProvider, finish

import run_v0224_tasks as m


@pytest.mark.parametrize("stage", ["D1", "D2"])
def test_real_host_fresh_directory_and_wrong_outcome_retained(tmp_path, monkeypatch, stage):
    source = tmp_path / "public.json"
    m.save(source, public())
    initial = m.World.create(tmp_path / "baseline.sqlite", "owned", public()).snapshot()
    spec = {
        "id": "one",
        "stage": stage,
        "scope": "owned",
        "public_source": {"path": str(source), "sha256": m.sha(source)},
        "initial_state_sha256": m.digest(initial),
        "profile": "RECOVERY_ORACLE" if stage == "D1" else "NATURAL_NO_CARRY",
        "arm": "ORACLE" if stage == "D1" else "N0-exec",
        "intent": {"instruction": "Public task"},
        "event": {"event_id": "event", "current": {"authorized": False}},
    }
    stops, claims = [], []
    batch = SimpleNamespace(
        root=tmp_path,
        claim=claims.append,
        spec=lambda episode: copy.deepcopy(spec),
        admit=lambda episode: None,
        stop=stops.append,
    )
    actions = [finish() if stage == "D1" else {**finish(), "review": ""}]
    provider = FakeProvider(actions)
    provider.provider = SimpleNamespace(deadline=time.monotonic() + 30)
    monkeypatch.setattr(m, "TaskProvider", lambda *args, **kwargs: provider)
    result = m.run_worker(batch, "one")
    assert claims == ["one"] and stops == []
    assert result["execution_status"] == "EXECUTION_COMPLETE"
    assert result["task_correctness"] == "NOT_EVALUATED"
    assert m.read(tmp_path / "episodes/one/initial-world.json") == initial
    if stage == "D1":
        assert result["expected_error_exercised"] is False


def test_stage_persists_real_child_terminal_before_finish(tmp_path, monkeypatch):
    calls = []
    terminal = {
        "pid": 111,
        "parent_pid": 222,
        "returncode": 0,
        "timed_out": False,
        "stdout": "actual stdout",
        "stderr": "",
        "seconds": 1.0,
    }

    def child(argv, **kwargs):
        assert argv[2] == "worker" and argv[-2:] == ["--episode", "one"]
        assert kwargs["timeout"] > 0
        return terminal

    def finish_child(episode, path, sha):
        assert m.read(path) == terminal and m.sha(path) == sha
        calls.append(episode)
        return {"status": "EXECUTION_COMPLETE"}

    batch = SimpleNamespace(
        root=tmp_path,
        stage="D2",
        plan={"D2": [{"id": "one"}]},
        auth={"episode_wall_seconds": 3600, "expires_unix": time.time() + 3600},
        launch_once=lambda stage: None,
        authorize=lambda stage: None,
        finish=finish_child,
        snapshot=lambda: {"episodes": [{"status": "EXECUTION_COMPLETE"}]},
        stop=lambda reason: None,
    )
    monkeypatch.setattr(m, "run_child", child)
    result = m.run_stage(batch, tmp_path / "contract.json", "a" * 64)
    assert calls == ["one"] and result["task_correctness"] == "NOT_EVALUATED"


def test_stage_report_failure_never_overwrites_primary(tmp_path, monkeypatch):
    primary = RuntimeError("child failed")

    def fail(*args):
        raise primary

    def fail_save(*args):
        raise OSError("disk failed")

    batch = SimpleNamespace(root=tmp_path, stage="D2", launch_once=fail, stop=lambda reason: None)
    monkeypatch.setattr(m, "save", fail_save)
    with pytest.raises(RuntimeError) as caught:
        m.run_stage(batch, tmp_path / "contract.json", "a" * 64)
    assert caught.value is primary
    assert primary.__notes__

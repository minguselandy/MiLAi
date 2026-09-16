from __future__ import annotations

from pathlib import Path

import pytest

from milai.operations import LocalRuntimeSupervisor, local_runtime


def test_supervisor_uses_existing_product_start_ready_stop_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        local_runtime,
        "load_runtime_environment",
        lambda *_args: calls.append("environment"),
    )
    monkeypatch.setattr(
        local_runtime,
        "start_local",
        lambda *_args, **_kwargs: calls.append("start") or {"status": "RUNNING"},
    )
    monkeypatch.setattr(
        local_runtime,
        "load_settings",
        lambda: type("Settings", (), {"bind_host": "127.0.0.1", "bind_port": 18080})(),
    )
    monkeypatch.setattr(
        local_runtime,
        "local_profile_running",
        lambda *_args: calls.append("ready") or True,
    )
    monkeypatch.setattr(
        local_runtime,
        "stop_local",
        lambda *_args: calls.append("stop") or {"status": "STOPPED"},
    )
    supervisor = LocalRuntimeSupervisor(tmp_path / ".env")

    assert supervisor.start()["status"] == "RUNNING"
    assert supervisor.ready() is True
    assert supervisor.stop()["status"] == "STOPPED"

    assert supervisor.state == "STOPPED"
    assert calls == ["environment", "start", "environment", "ready", "stop"]

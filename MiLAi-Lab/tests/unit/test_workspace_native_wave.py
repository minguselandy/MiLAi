"""A Harbor failure must stop the wave even when its type is a wrapper."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))


@pytest.mark.parametrize("exception", [
    {"exception_type": "RuntimeError", "exception_message": "Command timed out"},
    {"exception_type": "AgentTimeoutError"},
    None,
])
def test_execution_failure_stops_but_native_zero_continues(tmp_path, monkeypatch, exception):
    class Config(SimpleNamespace):
        def model_dump(self, **kwargs):
            return {}

    config = ModuleType("harbor.models.trial.config")
    for name in ("AgentConfig", "EnvironmentConfig", "TaskConfig", "TrialConfig"):
        setattr(config, name, Config)
    started = []

    class Trial:
        @classmethod
        async def create(cls, value):
            started.append(value)
            return cls()

        async def run(self):
            return SimpleNamespace(model_dump=lambda **kwargs: {
                "exception_info": exception, "verifier_result": {"rewards": {"reward": 0}}})

    trial = ModuleType("harbor.trial.trial")
    trial.Trial = Trial
    monkeypatch.setitem(sys.modules, "harbor.models.trial.config", config)
    monkeypatch.setitem(sys.modules, "harbor.trial.trial", trial)
    spec = importlib.util.spec_from_file_location(
        "native_wave_test", TOOLS / "run_workspace_native.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.importlib.metadata, "version", lambda _: "0.23.0")
    task = tmp_path / "task"
    task.mkdir()
    (task / "task.toml").write_text("[agent]\ntimeout_sec = 900\n[environment]\ngpus = 0\n")
    root = tmp_path / "wave"
    asyncio.run(module.run(SimpleNamespace(
        root=root, task=task, smoke=False, order=["H_ONCE", "REVIEW"],
        hiagent_max_calls=None, max_calls=64, revision_source=[], role="transfer_only",
        artifact=[], force_build=False, compose_override=[])))
    assert len(started) == (1 if exception else 2)
    assert len(json.loads((root / "results.json").read_text())) == len(started)
    assert started[0].agent.kwargs["max_calls"] == 64

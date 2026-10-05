"""The exposed-history CLI keeps evaluator material out of Writer inputs."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from milai_lab.harness.artifact_io import read_json, write_json


def tool():
    path = Path(__file__).resolve().parents[2] / "tools/run_edit_development_history.py"
    spec = importlib.util.spec_from_file_location("edit_development_history", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def declaration(tmp_path: Path) -> tuple[Path, Path]:
    config, inputs = tmp_path / "config.json", tmp_path / "inputs.json"
    write_json(config, {"method_version": "milai_edit_v2", "interface_version": "I2",
                        "config_version": "common-v2", "arms": ["B0", "B1", "B2", "M"]})
    write_json(inputs, {
        "arms": ["B0", "B1", "B2", "M"], "candidate_selected": False,
        "story_clusters": 1, "expected_generation_calls": 8,
        "events": [{"event_id": "observed_only", "date": "2030-03-01",
                    "observed_user_text": "项目P周一巡检。",
                    "reader_question": "READER_ONLY_SECRET",
                    "evaluator_only_requirement": "REVIEW_ONLY_SECRET"}],
    })
    return config, inputs


def test_prepare_has_only_observed_writer_material_and_never_opens_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tool()

    def denied(*args, **kwargs):
        raise AssertionError("Preparation must not construct a model client or budget lease")

    monkeypatch.setattr(module, "BenchmarkRun", denied)
    config, inputs = declaration(tmp_path)
    output = tmp_path / "prepared"
    result = module.run_history(config, inputs, output, "recorded-version", prepare=True)
    assert result["actual_model_calls"] == 0 and result["expected_generation_calls"] == 8
    observations = read_json(output / "writer-observations.json")
    assert set(observations) == {"B0", "B1", "B2", "M"}
    assert "READER_ONLY_SECRET" not in str(observations)
    assert "REVIEW_ONLY_SECRET" not in str(observations)
    assert {tuple(row[0]["turns"][0].values()) for row in observations.values()} == {
        ("user", "项目P周一巡检。", "2030-03-01"),
    }
    assert not (output / "banks").exists()
    with pytest.raises(ValueError, match="Preserve prior attempts"):
        module.run_history(config, inputs, output, "recorded-version", prepare=True)


def test_unknown_maintenance_stops_without_retry_or_other_arm_and_keeps_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tool()
    calls = []

    class UnknownRun:
        def __init__(self, settings, root):
            self.settings = settings
            self.budget = SimpleNamespace(state={
                "generation_requests": 10,
                "generation": {"unknown_usage": 2, "known_tokens": 100},
                "embedding": {"unknown_usage": 0},
            })
            self.closed = False
            root.mkdir()
            calls.append(self)

        def maintain(self, service, observed, key):
            assert service.records() == []
            assert "REVIEW_ONLY_SECRET" not in str(observed.turns)
            calls.append(key)
            self.budget.state["generation_requests"] += 1
            self.budget.state["generation"]["unknown_usage"] += 1
            raise RuntimeError("Unconfirmed test outcome")

        def close(self):
            self.closed = True

    monkeypatch.setattr(module, "BenchmarkRun", UnknownRun)
    config, inputs = declaration(tmp_path)
    output = tmp_path / "attempted"
    with pytest.raises(RuntimeError, match="Unconfirmed test outcome"):
        module.run_history(config, inputs, output, "recorded-version")
    terminal = read_json(output / "terminal.json")
    assert terminal["status"] == "STOPPED_EXPOSED_R3_DEVELOPMENT_FAILURE"
    assert terminal["completed_event_rows"] == 0
    assert terminal["historical_generation_unknown_usage"] == 2
    assert terminal["new_generation_unknown_usage"] == 1
    assert terminal["new_generation_requests"] == 1
    assert len(calls) == 2 and calls[1] == "observed/B0/0" and calls[0].closed
    assert {path.name for path in (output / "banks").iterdir()} == {"B0"}
    assert read_json(output / "failure.json")["message"] == "Unconfirmed test outcome"

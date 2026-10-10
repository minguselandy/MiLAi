"""Single-arm alignment settings reach the existing pure-memory maintenance entry."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from milai_lab.datasets.edit_benchmarks import ObservedSession
from milai_lab.methods.append_memory import AppendMemory
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.methods.milai_memory_only import MiLAiMemoryBackend
from milai_lab.runners import edit_benchmarks
from milai_lab.runners.baseline_alignment import BACKENDS, AlignmentRun, alignment_settings


def configuration() -> dict[str, Any]:
    return {
        "entrypoints": {"benchmark": {
            "arms": ["B2", "M"], "interface_version": "I2",
            "maintenance_recipe": "extract_then_edit", "retrieval_limit": 10,
            "source_tokens": 4096, "source_body_tokens": 8192,
            "edit_features": {
                "matter_organization": True, "semantic_operations": True,
                "bound_references": True, "single_record_changes": True,
                "source_metadata": True, "temporal_scope": True,
            },
            "model": {"max_tokens": 32768, "enable_thinking": True},
            "stage_enable_thinking": {"edit": True},
        }},
        "alignment": {"backends": list(BACKENDS), "delivery": "direct",
                      "qa_top_k": 20, "update_top_k": 10},
    }


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M", "Append-only"])
def test_declared_arm_reaches_existing_method_through_facade(
    arm: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = configuration()
    config["entrypoints"]["benchmark"]["arm"] = arm
    before = copy.deepcopy(config)
    settings = alignment_settings(config, "MiLAi-memory-only")
    assert config == before
    assert settings["arm"] == arm and "arms" not in settings
    for key, value in config["entrypoints"]["benchmark"].items():
        if key != "arms":
            assert settings[key] == value
    assert settings["alignment"] == config["alignment"]

    execution = AlignmentRun.__new__(AlignmentRun)
    execution.settings, execution.root = settings, tmp_path
    execution.backends = {}
    execution.budget = SimpleNamespace(state={})
    execution.tokenizer = None  # An empty synthetic session requires no tokenization.
    service = SimpleNamespace(owner="synthetic-owner")
    methods: list[EditMemory] = []

    def edit_method(*args: Any, **kwargs: Any) -> EditMemory:
        method = EditMemory(*args, **kwargs)
        methods.append(method)
        return method

    def append_method(*args: Any, **kwargs: Any) -> AppendMemory:
        method = AppendMemory(*args, **kwargs)
        methods.append(method)
        return method

    monkeypatch.setattr(edit_benchmarks, "EditMemory", edit_method)
    monkeypatch.setattr(edit_benchmarks, "AppendMemory", append_method)
    observed = ObservedSession("synthetic-session", "Jan 01, 2025, 12:00:00", ())
    assert execution.maintain(service, observed, "synthetic-maintenance") == []
    assert isinstance(execution.backends[service.owner], MiLAiMemoryBackend)
    assert len(methods) == 1
    assert type(methods[0]) is (AppendMemory if arm == "Append-only" else EditMemory)
    assert methods[0].method_name == arm and methods[0].service is service
    assert methods[0].conditioned == (arm in {"B2", "M"})
    assert methods[0].features.settings() == settings["edit_features"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_default_arm_stays_m(backend: str) -> None:
    assert alignment_settings(configuration(), backend)["arm"] == "M"


@pytest.mark.parametrize("backend", BACKENDS[:2])
def test_external_backends_keep_m_placeholder(backend: str) -> None:
    config = configuration()
    config["entrypoints"]["benchmark"]["arm"] = "B2"
    assert alignment_settings(config, backend)["arm"] == "M"


@pytest.mark.parametrize("arm", ["new-method", None, ["B2", "M"]])
def test_milai_rejects_unregistered_or_multiple_arms(arm: Any) -> None:
    config = configuration()
    config["entrypoints"]["benchmark"]["arm"] = arm
    with pytest.raises(ValueError, match="Unknown declared MiLAi maintenance arm"):
        alignment_settings(config, "MiLAi-memory-only")

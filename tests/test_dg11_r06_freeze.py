from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import run_dg11_r06_freeze as freeze


def _evidence() -> tuple[dict[str, object], ...]:
    r04: dict[str, object] = {
        "work_package": "DG11-R04",
        "status": "PASS",
        "gates": {"quality": True, "denominator": True},
        "development_ai_reviews": 0,
    }
    functional: dict[str, object] = {
        "status": "PASS",
        "classification": {"gates": {"functional": True, "safety": True}},
        "provider_requests": 30,
        "development_ai_reviews": 0,
    }
    agentic: dict[str, object] = {
        "status": "PASS",
        "gates": {"tasks": True, "safety": True},
        "provider_requests": 60,
        "development_ai_reviews": 0,
    }
    efficiency: dict[str, object] = {
        "status": "PASS",
        "classification": {
            "DG11-04": {"status": "PASS", "gates": {"tokens": True}},
            "DG11-05": {"status": "PASS", "gates": {"latency": True}},
        },
        "development_ai_reviews": 0,
    }
    return r04, functional, agentic, efficiency


def test_r06_evidence_gate_accepts_complete_pass_matrix() -> None:
    freeze._validate_evidence(*_evidence())


@pytest.mark.parametrize(
    ("evidence_index", "path", "value"),
    (
        (0, ("gates", "quality"), False),
        (0, ("development_ai_reviews",), 1),
        (1, ("provider_requests",), 29),
        (2, ("gates", "safety"), False),
        (3, ("classification", "DG11-05", "status"), "FAILED"),
    ),
)
def test_r06_evidence_gate_fails_closed(
    evidence_index: int,
    path: tuple[str, ...],
    value: object,
) -> None:
    evidence = [deepcopy(item) for item in _evidence()]
    target = evidence[evidence_index]
    for part in path[:-1]:
        target = target[part]  # type: ignore[assignment,index]
    target[path[-1]] = value

    with pytest.raises(freeze.R06FreezeError):
        freeze._validate_evidence(*evidence)


def test_projection_identity_ignores_timing_and_scores_but_binds_models() -> None:
    records = []
    for index in range(100):
        records.append(
            {
                "runtime_trace": {
                    "embedding": {
                        "provider": "onnx_sentence_transformer",
                        "model_id": "embedding-model",
                        "source_dimensions": 384,
                        "projection_dimensions": 128,
                        "warmup_duration_ms": float(index),
                    },
                    "retrieved_items": [
                        {
                            "reranker": {
                                "provider": "onnx_cross_encoder",
                                "model_id": "reranker-model",
                                "model_sha256": "a" * 64,
                                "revision": "revision",
                                "runtime": "CPUExecutionProvider",
                                "max_length": 512,
                                "tokenizer_sha256": "b" * 64,
                                "duration_ms": float(index),
                                "score": -float(index),
                            }
                        }
                    ],
                }
            }
        )

    identity = freeze._projection_identity({"records": records})

    assert identity["embedding"]["projection_dimensions"] == 128
    assert identity["reranker"]["model_sha256"] == "a" * 64
    assert "duration_ms" not in identity["reranker"]


def test_r04_default_points_to_dedicated_r04_result() -> None:
    assert freeze.DEFAULT_R04_RESULT.name == "r04-latest-result.json"


def test_candidate_publication_rolls_back_when_binding_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary_candidate = tmp_path / "temporary-candidate"
    temporary_candidate.mkdir()
    (temporary_candidate / "candidate-manifest.json").write_text(
        "{}\n", encoding="utf-8"
    )
    candidate_root = tmp_path / "freeze" / "candidate"
    candidate_root.parent.mkdir()
    split_binding = tmp_path / "splits" / "candidate-binding.json"
    split_binding.parent.mkdir()
    monkeypatch.setattr(freeze, "CANDIDATE_ROOT", candidate_root)
    monkeypatch.setattr(freeze, "SPLIT_BINDING", split_binding)
    real_replace = os.replace

    def fail_binding_publish(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == split_binding:
            raise OSError("simulated binding publication failure")
        real_replace(source, destination)

    monkeypatch.setattr(freeze.os, "replace", fail_binding_publish)

    with pytest.raises(OSError, match="simulated binding publication failure"):
        freeze._publish_candidate(temporary_candidate, {"candidate_id": "candidate"})

    assert temporary_candidate.is_dir()
    assert not candidate_root.exists()
    assert not split_binding.exists()
    assert not list(split_binding.parent.glob(".*.stage"))


def test_candidate_and_binding_publish_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary_candidate = tmp_path / "temporary-candidate"
    temporary_candidate.mkdir()
    candidate_root = tmp_path / "freeze" / "candidate"
    candidate_root.parent.mkdir()
    split_binding = tmp_path / "splits" / "candidate-binding.json"
    split_binding.parent.mkdir()
    monkeypatch.setattr(freeze, "CANDIDATE_ROOT", candidate_root)
    monkeypatch.setattr(freeze, "SPLIT_BINDING", split_binding)

    freeze._publish_candidate(temporary_candidate, {"candidate_id": "candidate"})

    assert candidate_root.is_dir()
    assert not temporary_candidate.exists()
    assert json.loads(split_binding.read_text(encoding="utf-8")) == {
        "candidate_id": "candidate"
    }

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import ClassVar

import pytest

from evals.benchmark import dg11_holdout_context_worker as context_worker
from evals.benchmark import dg11_v2
from evals.benchmark import lme_product_smoke as benchmark
from scripts import run_dg11_v2 as runner


def test_v2_uses_preregistered_four_arm_names() -> None:
    assert dg11_v2.ARMS == (
        "CTRL_NO_MEMORY",
        "CTRL_CUSTOM_LEXICAL_TOP1",
        "MILAI_DG10_FROZEN",
        "MILAI_DG11_FROZEN",
    )


def test_v2_latin_square_is_balanced_and_frozen() -> None:
    schedules = [dg11_v2.schedule(index) for index in range(100)]

    assert all(set(schedule) == set(dg11_v2.ARMS) for schedule in schedules)
    for position in range(4):
        assert Counter(schedule[position] for schedule in schedules) == {
            arm: 25 for arm in dg11_v2.ARMS
        }
    assert len(dg11_v2.schedule_identity()) == 64


def test_v2_generation_id_rejects_unregistered_arm() -> None:
    with pytest.raises(ValueError, match="unknown generalization-v2 arm"):
        dg11_v2.generation_id(0, "NAIVE_RAG")


def test_v2_dg10_config_derivation_removes_only_frozen_dg11_keys() -> None:
    lines = ["MILAI_DATABASE_URL=postgresql://example"] + [
        f"{key}=frozen-value" for key in sorted(runner.DG10_INCOMPATIBLE_ENV_KEYS)
    ]

    derived, removed = runner._dg10_compatible_env("\n".join(lines) + "\n")

    assert derived == "MILAI_DATABASE_URL=postgresql://example\n"
    assert removed == tuple(sorted(runner.DG10_INCOMPATIBLE_ENV_KEYS))


def test_v2_dg10_config_derivation_fails_closed_on_denominator_drift() -> None:
    incomplete = "\n".join(
        f"{key}=frozen-value"
        for key in sorted(runner.DG10_INCOMPATIBLE_ENV_KEYS)
        if key != "MILAI_RETRIEVAL_RERANKER_PROVIDER"
    )

    with pytest.raises(runner.V2RunError, match="missing the expected"):
        runner._dg10_compatible_env(incomplete)


def test_v2_shared_context_harness_accepts_legacy_runtime_settings() -> None:
    class LegacySettings:
        model_fields: ClassVar[dict[str, object]] = {
            "embedding_provider": object(),
            "embedding_model_path": object(),
            "embedding_model_id": object(),
            "embedding_source_dimensions": object(),
            "embedding_prewarm": object(),
            "embedding_max_concurrency": object(),
        }
        embedding_provider = "onnx_sentence_transformer"
        embedding_model_path = Path("/frozen/model")
        embedding_model_id = "frozen-embedding"
        embedding_source_dimensions = 384
        embedding_prewarm = True
        embedding_max_concurrency = 4

    updates = benchmark._embedding_settings_updates(LegacySettings())

    assert updates["embedding_provider"] == "onnx_sentence_transformer"
    assert "embedding_projection_dimensions" not in updates
    assert "retrieval_reranker_provider" not in updates


def test_v2_shared_context_worker_serializes_legacy_prefetch_context() -> None:
    class LegacyContext:
        rendered = "MEMORY_STATUS=NO_MEMORY"
        status = "NO_MEMORY"
        context_sha256 = "a" * 64

    payload = context_worker._context_payload(LegacyContext())

    assert payload["compiler_version"] == "DG10_LEGACY"
    assert payload["context_sha256"] == "a" * 64

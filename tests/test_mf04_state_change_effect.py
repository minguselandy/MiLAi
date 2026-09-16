from __future__ import annotations

from pathlib import Path

from evals.mf01.labels import build_label_seal
from evals.mf04.state_change_effect import (
    execute_mf04_effect,
    load_state_change_sources,
)

ROOT = Path(__file__).resolve().parents[1]


def test_mf04_exact_direct_obligations_close_without_model_or_commit() -> None:
    result = execute_mf04_effect(ROOT)

    assert result["status"] == "PASS_MF04_STATE_CHANGE_FORMATION"
    assert result["metrics"]["STATE_ASSERTION"] == {
        "covered": 6,
        "denominator": 6,
        "recall": 1.0,
        "accepted": 6,
        "produced": 6,
        "precision": 1.0,
    }
    assert result["metrics"]["STATE_TRANSITION"] == {
        "covered": 3,
        "denominator": 3,
        "recall": 1.0,
        "accepted": 3,
        "produced": 3,
        "precision": 1.0,
    }
    assert result["cost"]["model_calls"] == 0
    assert result["cost"]["canonical_mutations"] == 0


def test_mf04_source_hydration_is_exact_and_label_free() -> None:
    seal = build_label_seal(ROOT)
    sources = load_state_change_sources(ROOT, seal)

    assert len(sources) == 6
    assert len({item["evidence_id"] for item in sources}) == 6
    assert all("expected" not in item and "labels" not in item for item in sources)

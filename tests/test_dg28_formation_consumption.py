from __future__ import annotations

from pathlib import Path

import pytest

from evals.dg28.formation_consumption import (
    execute_formation_consumption_replay,
    score_formation_consumption_replay,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def effect() -> tuple[dict[str, object], dict[str, object]]:
    unscored = execute_formation_consumption_replay(ROOT)
    return unscored, score_formation_consumption_replay(ROOT, unscored)


def test_formation_closes_last_target_without_changing_candidate_pool(
    effect: tuple[dict[str, object], dict[str, object]],
) -> None:
    _unscored, score = effect
    assert score["status"] == "PASS_DG28_FORMATION_CONSUMPTION_CLOSURE"
    assert score["baseline"]["target_binding_groups"] == 6
    assert score["treatment"]["target_binding_groups"] == 7
    assert score["delta"]["candidate_count"] == 0
    assert score["remaining_target_binding_groups"] == []
    assert score["treatment"]["accepted_binding_precision"] == 1.0
    assert score["treatment"]["wrong_complete"] == 0


def test_formation_replay_uses_one_resolved_artifact_and_no_query_model_call(
    effect: tuple[dict[str, object], dict[str, object]],
) -> None:
    unscored, score = effect
    [formed] = unscored["formation_events_consumed"]
    assert formed["case_id"] == "2e6d26dc"
    assert formed["time_basis"] == "INFERRED_EVENT_TIME"
    assert unscored["cost"]["model_calls"] == 0
    assert unscored["cost"]["new_official_acquisition_calls"] == 0
    assert unscored["cost"]["canonical_mutations"] == 0
    assert score["dg29_refinding_entry"] is False

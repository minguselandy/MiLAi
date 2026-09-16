from __future__ import annotations

from pathlib import Path

import pytest

from evals.dg28.acquisition_shadow import build_acquisition_shadow
from evals.dg28.lite_effect import (
    CHANNEL_CAPS,
    execute_lite_effect,
    score_lite_effect,
    select_lite_candidates,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def effect() -> tuple[dict[str, object], dict[str, object]]:
    unscored = execute_lite_effect(ROOT)
    return unscored, score_lite_effect(ROOT, unscored)


def test_lite_union_uses_only_raw_and_enriched_caps() -> None:
    shadow = build_acquisition_shadow(ROOT)
    counts = {
        record["case_id"]: len(select_lite_candidates(record))
        for record in shadow["records"]
    }
    assert counts == {"2e6d26dc": 24, "88432d0a": 10, "a82c026e": 10}
    for record in shadow["records"]:
        for candidate in select_lite_candidates(record):
            assert {
                item["channel"] for item in candidate["selected_channel_lineage"]
            }.issubset(CHANNEL_CAPS)


def test_lite_effect_recovers_targets_without_false_complete(
    effect: tuple[dict[str, object], dict[str, object]],
) -> None:
    _unscored, score = effect
    assert score["status"] == "PASS_DG28_LITE_RETRIEVAL_GAIN"
    assert score["baseline"]["target_candidate_groups"] == 4
    assert score["treatment"]["target_candidate_groups"] == 7
    assert score["baseline"]["target_binding_groups"] == 3
    assert score["treatment"]["target_binding_groups"] == 6
    assert score["treatment"]["accepted_binding_precision"] == 1.0
    assert score["treatment"]["wrong_complete"] == 0
    assert score["baseline_binding_groups_lost"] == []


def test_lite_effect_has_no_external_or_state_mutation_cost(
    effect: tuple[dict[str, object], dict[str, object]],
) -> None:
    unscored, score = effect
    assert unscored["cost"] == {
        "new_official_acquisition_calls": 0,
        "historical_official_outputs_replayed": 6,
        "model_calls": 0,
        "reader_calls": 0,
        "canonical_mutations": 0,
        "automatic_retries": 0,
    }
    assert score["dg29_refinding_entry"] is False
    assert score["remaining_target_binding_groups"] == [
        "2e6d26dc:2e6d26dc-charlotte"
    ]

from __future__ import annotations

from pathlib import Path

import pytest

from evals.dg28.acquisition_shadow import CHANNELS, build_acquisition_shadow

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def shadow() -> dict[str, object]:
    return build_acquisition_shadow(ROOT)


def test_target_and_official_call_denominators_are_frozen(
    shadow: dict[str, object],
) -> None:
    assert shadow["target_group_count"] == 7
    assert shadow["query_requirement_count"] == 3
    assert shadow["channels"] == list(CHANNELS)
    assert shadow["historical_official_calls_replayed"] == 15
    assert shadow["new_official_calls"] == 0


def test_union_is_identity_only_and_preserves_all_channel_lineage(
    shadow: dict[str, object],
) -> None:
    records = shadow["records"]
    assert isinstance(records, list)
    candidates = [
        candidate
        for record in records
        for candidate in record["union_candidates"]
    ]

    assert sum(record["union_candidate_count"] for record in records) == 255
    assert sum(len(candidate["channel_lineage"]) for candidate in candidates) == 272
    assert all(record["identity_dedup_only"] is True for record in records)
    assert all(
        len({candidate["evidence_id"] for candidate in record["union_candidates"]})
        == record["union_candidate_count"]
        for record in records
    )


def test_all_seven_targets_have_candidate_level_shadow_hits_only(
    shadow: dict[str, object],
) -> None:
    records = shadow["records"]
    assert isinstance(records, list)
    hits = [
        hit
        for record in records
        for hit in record["target_group_candidate_hits"]
    ]

    assert len(hits) == 7
    assert all(len(hit["candidate_evidence_ids"]) == 1 for hit in hits)
    assert shadow["decision_chain_entered"] is False
    assert all(record["gate_executed"] is False for record in records)
    assert all(record["binding_executed"] is False for record in records)
    assert all(record["sufficiency_executed"] is False for record in records)
    assert all(record["reader_executed"] is False for record in records)

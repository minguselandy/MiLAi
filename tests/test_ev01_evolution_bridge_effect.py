from __future__ import annotations

from pathlib import Path

from evals.ev01.evolution_bridge_effect import execute_ev01_mapping_effect

ROOT = Path(__file__).resolve().parents[1]


def test_ev01_mapping_closes_all_applicable_direct_dispositions() -> None:
    result = execute_ev01_mapping_effect(ROOT)

    assert result["status"] == "PASS_EV01_TYPED_MAPPING"
    assert result["metrics"] == {
        "governed_artifacts_mapped": 4,
        "query_local_artifacts_filtered": 2,
        "WrongTransitionDisposition": 0,
        "MissingProvenanceClosure": 0,
        "ValidTimeMisassignment": 0,
        "UnsupportedCanonicalPromotion": 0,
    }
    assert all(row["commit_policy_decision"] == "USER_REVIEW" for row in result["rows"])
    assert all(row["canonical_commit_authorized"] is False for row in result["rows"])

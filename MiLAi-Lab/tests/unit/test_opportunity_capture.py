from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_owner_exports import _cache_cases

from milai_lab.analysis.opportunity_capture import OpportunityCapture
from milai_lab.analysis.trace_join import CACHE_SCHEMA_VERSION


def test_actual_capture_point_persists_before_fixture_outcome_and_keeps_cache(
    tmp_path: Path,
) -> None:
    capture = OpportunityCapture(tmp_path, "e" * 64)
    cases = _cache_cases()
    for index, case in enumerate(cases, 1):
        case["error_type"] = None
        capture.begin("synthetic-query")
        capture.before_transport(case["runtime"])
        assert (tmp_path / f"opportunity-{index:02d}.json").is_file()
        assert not (tmp_path / f"fixture-outcome-{index:02d}.json").exists()
        snapshot = json.loads((tmp_path / f"opportunity-{index:02d}.json").read_text())
        assert len(snapshot["available_versions"]) == 1
        capture.end(case)
    ledger = capture.finish(
        cases, run_id="capture-test", product_lock_digest="f" * 64,
        owner_schema=CACHE_SCHEMA_VERSION,
    )
    assert [row["retrieval_calls"] for row in ledger["rows"]] == [1, 0]
    assert [row["retrieved_candidate_count"] for row in ledger["rows"]] == [1, 0]
    assert all(row["task_outcome"] == "UNKNOWN" for row in ledger["rows"])
    assert all(row["observable_use"] == "UNKNOWN" for row in ledger["rows"])
    assert all(row["embedding_calls"] is None for row in ledger["rows"])
    assert all(row["model_generations"] == 0 for row in ledger["rows"])
    assert json.loads((tmp_path / "opportunity-ledger.json").read_text()) == ledger


def test_post_outcome_snapshot_is_not_manufactured(tmp_path: Path) -> None:
    capture = OpportunityCapture(tmp_path, "e" * 64)
    capture.begin("query")
    with pytest.raises(ValueError, match="OPPORTUNITY_SNAPSHOT_MISSING_BEFORE_OUTCOME"):
        capture.end(_cache_cases()[0])
    assert not list(tmp_path.iterdir())


def test_persisted_snapshot_tampering_is_rejected(tmp_path: Path) -> None:
    capture = OpportunityCapture(tmp_path, "e" * 64)
    case = _cache_cases()[0]
    capture.begin("query")
    capture.before_transport(case["runtime"])
    (tmp_path / "opportunity-01.json").write_text("{}")
    with pytest.raises(ValueError, match="OPPORTUNITY_PERSISTED_SNAPSHOT_CHANGED"):
        capture.end(case)


def test_empty_control_is_sealed_before_the_host_call(tmp_path: Path) -> None:
    capture = OpportunityCapture(tmp_path, "e" * 64)
    capture.begin("no memory query", empty_pool_control=True)
    assert json.loads((tmp_path / "opportunity-01.json").read_text())["available_versions"] == []
    capture.before_transport([])
    with pytest.raises(ValueError, match="OPPORTUNITY_PREDECLARED_EMPTY_POOL_CHANGED"):
        capture.before_transport(_cache_cases()[0]["runtime"])


def test_unobserved_cache_origin_cannot_supply_a_pool(tmp_path: Path) -> None:
    capture = OpportunityCapture(tmp_path, "e" * 64)
    capture.begin("query")
    with pytest.raises(ValueError, match="OPPORTUNITY_CACHE_ORIGIN_NOT_CAPTURED"):
        capture.before_transport(_cache_cases()[1]["runtime"])


def test_existing_artifact_is_not_overwritten(tmp_path: Path) -> None:
    (tmp_path / "opportunity-01.json").write_text("retained")
    capture = OpportunityCapture(tmp_path, "e" * 64)
    with pytest.raises(FileExistsError):
        capture.begin("query", empty_pool_control=True)
    assert (tmp_path / "opportunity-01.json").read_text() == "retained"

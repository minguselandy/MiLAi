from __future__ import annotations

import json
from pathlib import Path

from scripts.run_dg13_m0_baseline import build_report


def test_m0_baseline_is_payload_free_and_exposes_first_boundaries() -> None:
    report = build_report()

    assert report["status"] == "BASELINE_REPLAYED"
    assert report["case_count"] == 5
    assert report["query_only_possible_or_required_count"] == 4
    assert report["task_gated_none_count"] == 4
    assert report["intent_route_disagreement_count"] == 3
    assert report["first_blocking_boundaries"] == [
        "HOST_TASK_GATE",
        "HOST_TYPED_NEED_FILTER",
    ]
    serialized = json.dumps(report, ensure_ascii=False)
    assert "current release status" not in serialized
    assert "当前项目" not in serialized


def test_m0_baseline_case_fingerprints_and_shadow_are_complete() -> None:
    report = build_report()
    cases = report["cases"]
    assert isinstance(cases, list)

    for case in cases:
        assert len(case["query_fingerprint"]) == 64
        assert case["shadow_changed_production_result"] is False
        assert case["query_only"]["interpreter_version"] == "query-only-shadow-v1"
        assert case["current_task_gated"]["route"] in {"NONE", "L0", "L1"}


def test_m0_baseline_source_does_not_add_a_second_trace_store() -> None:
    source = Path("scripts/run_dg13_m0_baseline.py").read_text(encoding="utf-8")
    assert "CREATE TABLE" not in source
    assert "access_trace_repository" not in source.lower()
    assert "insert_access_trace" not in source.lower()

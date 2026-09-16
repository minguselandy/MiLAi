from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
observations = importlib.import_module("summarize_v02_import_readiness").observations


def fixture():
    captures = [{"index": 0, "committed_response_s": 11, "save_ms": 1000,
                 "receipt": {"evidence_id": "e", "outbox_id": "o", "request_id": "r"}}]
    physical = [
        {"phase": "round-0", "method": "POST", "path": "/v1/evidence", "status": 201,
         "start_s": 10.1, "end_s": 10.9},
        {"phase": "drain-0", "method": "POST", "path": "/v1/system/projection-readiness",
         "status": 200, "start_s": 12, "end_s": 13},
    ]
    readiness = {"drain-0": {
        "status": "READY", "projection_work_started": False, "target_outbox_ids": ["o"],
        "projections": [{"projection": "evidence", "projection_version": "evidence-search-v1",
                         "ready": True, "version_match": True,
                         "current_watermark": 3, "target_watermark": 3}],
    }}
    return captures, physical, readiness


def test_ack_is_not_commit_and_missing_timing_is_not_zero():
    captures, physical, readiness = fixture()
    row = observations(captures, physical, [], readiness, 50)[0]
    assert row["ack_to_ready_observation_ms"] == 2000
    assert row["commit_to_ready_upper_bound_ms"] == 3000
    assert row["actual_commit_to_ready_ms"] is None and row["runtime_timing"] is None


def test_nested_concurrent_request_keeps_conservative_call_bound_without_false_join():
    captures, physical, readiness = fixture()
    physical.append(dict(physical[0]))
    row = observations(captures, physical, [], readiness, 50)[0]
    assert row["physical_request_association"] == "AMBIGUOUS_OVERLAP"
    assert row["commit_to_ready_upper_bound_ms"] == 3000


@pytest.mark.parametrize("fault", ["wrong_target", "wrong_version", "missing_request", "clock"])
def test_unconfirmed_association_does_not_get_a_latency(fault):
    captures, physical, readiness = fixture()
    if fault == "wrong_target":
        readiness["drain-0"]["target_outbox_ids"] = ["other"]
    elif fault == "wrong_version":
        readiness["drain-0"]["projections"][0]["version_match"] = False
    elif fault == "missing_request":
        physical.pop(0)
    else:
        physical[1]["start_s"] = 9
    with pytest.raises(AssertionError):
        observations(captures, physical, [], readiness, 50)

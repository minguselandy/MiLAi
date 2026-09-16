from __future__ import annotations

from scripts import run_dg10_final_completion_audit as completion


def _verification() -> dict[str, object]:
    return {
        "status": "NO_GO_THREE_FROZEN_WORKER_CLOSURE_TESTS_FAIL",
        "root_pytest_full": {
            "total": 128,
            "passed": 125,
            "failed": 3,
        },
        "root_pytest_unaffected": {
            "total": 125,
            "passed": 125,
            "failed": 0,
        },
        "root_ruff": {"status": "PASS"},
    }


def test_completion_audit_preserves_no_go_and_test_denial() -> None:
    values = {name: completion._load(path) for name, path in completion.INPUTS.items()}
    report = completion.build_audit(values, _verification())
    assert report["status"] == "GOAL_EXECUTION_COMPLETE_NO_GO_RELEASE_STOPPED"
    assert report["decision"]["result"] == "NO_GO"
    assert report["decision"]["aggregate_claim_allowed"] is False
    assert report["quality"]["full_benchmark_test"] == "DENIED_NOT_RUN"
    assert report["quality"]["test_labels_or_outputs_opened"] is False


def test_completion_audit_keeps_open_p1_and_cost_unknowns() -> None:
    values = {name: completion._load(path) for name, path in completion.INPUTS.items()}
    report = completion.build_audit(values, _verification())
    assert report["review"]["open_p0_count"] == 0
    assert report["review"]["open_p1_count"] == 2
    assert report["provider_accounting"]["tier3_known_completed_native_calls"] == 44
    assert report["provider_accounting"]["tier3_early_diagnostic_calls"] == "UNKNOWN"
    assert report["provider_accounting"]["codex_formal_review_cost"] == "UNAVAILABLE"


def test_completion_audit_records_worker_environment_drift() -> None:
    values = {name: completion._load(path) for name, path in completion.INPUTS.items()}
    report = completion.build_audit(values, _verification())
    dependency = report["worker_dependency_closure"]
    assert dependency["tree_matches_historical"] is True
    assert dependency["environment_matches_historical"] is False
    assert dependency["status"].startswith("NO_GO")

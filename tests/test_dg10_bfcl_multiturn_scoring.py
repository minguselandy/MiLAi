from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts import run_dg10_bfcl_multiturn_scoring_worker as worker
from scripts import run_dg10_bfcl_multiturn_scoring_worker_v2 as worker_v2
from scripts import run_dg10_bfcl_multiturn_scoring_worker_v4 as worker_v4


def _generation(
    *, success: bool, decoded: list[list[list[str]]], failure_code: str | None = None
) -> dict[str, Any]:
    return {
        "case_id": "bfcl_v4:multi_turn_base_fixture",
        "source_case_id": "multi_turn_base_fixture",
        "generation_success": success,
        "evidence_complete": True,
        "failure_code": failure_code,
        "decoded_execution_calls_by_turn": decoded,
    }


def _test_entry() -> dict[str, Any]:
    return {
        "id": "multi_turn_base_fixture",
        "initial_config": {},
        "involved_classes": ["MathAPI"],
    }


def test_missing_turns_are_only_appended_and_failure_latch_dominates() -> None:
    calls: list[tuple[str, Any]] = []

    def accuracy(decoded: Any, *_args: Any) -> dict[str, bool]:
        calls.append(("accuracy", decoded))
        return {"valid": True}

    def irrelevance(decoded: Any, *_args: Any) -> dict[str, bool]:
        calls.append(("irrelevance", decoded))
        return {"valid": True}

    result = worker.evaluate_case(
        generation_record=_generation(
            success=False,
            decoded=[[["calculate(value=1)"]]],
            failure_code="STEP_LIMIT_BOUNDARY_FORCE_QUIT",
        ),
        ground_truth=[["calculate(value=1)"], []],
        test_entry=_test_entry(),
        category="multi_turn_base",
        accuracy_checker=accuracy,
        irrelevance_checker=irrelevance,
    )

    assert [name for name, _decoded in calls] == ["accuracy", "irrelevance"]
    assert calls[0][1] == [[["calculate(value=1)"]], []]
    assert result["turn_adapter"]["appended_empty_turn_count"] == 1
    assert result["turn_adapter"]["turns_truncated"] == 0
    assert result["official_checkers"]["multi_turn_checker"]["valid"] is True
    assert result["official_checkers"]["multi_turn_irrelevance_checker"]["valid"] is True
    assert result["generation_failure_latch"] is True
    assert result["final_valid"] is False


def test_checker_exception_is_fail_closed_and_other_checker_still_runs() -> None:
    irrelevance_calls = 0

    def accuracy(*_args: Any) -> dict[str, bool]:
        raise AssertionError("fixture checker failure")

    def irrelevance(*_args: Any) -> dict[str, bool]:
        nonlocal irrelevance_calls
        irrelevance_calls += 1
        return {"valid": True}

    result = worker.evaluate_case(
        generation_record=_generation(success=True, decoded=[[[]]]),
        ground_truth=[[]],
        test_entry=_test_entry(),
        category="multi_turn_base",
        accuracy_checker=accuracy,
        irrelevance_checker=irrelevance,
    )

    assert irrelevance_calls == 1
    assert result["both_official_checkers_invoked"] is True
    assert result["official_checkers"]["multi_turn_checker"]["returned"] is False
    assert result["official_checkers"]["multi_turn_checker"]["error_type"] == (
        "CHECKER_EXCEPTION:AssertionError"
    )
    assert result["final_valid"] is False


def test_exact_success_requires_both_official_checkers() -> None:
    result = worker.evaluate_case(
        generation_record=_generation(
            success=True, decoded=[[["calculate(value=1)"]]]
        ),
        ground_truth=[["calculate(value=1)"]],
        test_entry=_test_entry(),
        category="multi_turn_base",
        accuracy_checker=lambda *_args: {"valid": True},
        irrelevance_checker=lambda *_args: {"valid": True},
    )

    assert result["turn_adapter"]["exact_turn_count_before_adapter"] is True
    assert result["generation_failure_latch"] is False
    assert result["final_valid"] is True


def test_extra_turn_is_retained_and_fails_exact_turn_requirement() -> None:
    observed: list[Any] = []

    def checker(decoded: Any, *_args: Any) -> dict[str, bool]:
        observed.append(decoded)
        return {"valid": True}

    result = worker.evaluate_case(
        generation_record=_generation(
            success=True,
            decoded=[[["calculate(value=1)"]], [[]]],
        ),
        ground_truth=[["calculate(value=1)"]],
        test_entry=_test_entry(),
        category="multi_turn_base",
        accuracy_checker=checker,
        irrelevance_checker=checker,
    )

    assert all(len(value) == 2 for value in observed)
    assert result["turn_adapter"]["extra_observed_turn_count"] == 1
    assert result["turn_adapter"]["turns_truncated"] == 0
    assert result["final_valid"] is False


def test_v2_result_hash_canonicalizes_mixed_mapping_keys() -> None:
    left = {"state": {1: "one", "1": "string-one", 2: {"x", "y"}}}
    right = {"state": {2: {"y", "x"}, "1": "string-one", 1: "one"}}

    assert worker_v2._safe_result_hash(left) == worker_v2._safe_result_hash(right)


def test_v2_hash_fix_does_not_change_evaluation_policy() -> None:
    original_hash = worker._safe_result_hash
    worker._safe_result_hash = worker_v2._safe_result_hash
    try:
        result = worker.evaluate_case(
            generation_record=_generation(success=True, decoded=[[[]]]),
            ground_truth=[[]],
            test_entry=_test_entry(),
            category="multi_turn_base",
            accuracy_checker=lambda *_args: {
                "valid": False,
                "details": {1: "integer", "1": "string"},
            },
            irrelevance_checker=lambda *_args: {"valid": True},
        )
    finally:
        worker._safe_result_hash = original_hash

    assert result["both_official_checkers_invoked"] is True
    assert result["official_checkers"]["multi_turn_checker"]["valid"] is False
    assert result["official_checkers"]["multi_turn_irrelevance_checker"]["valid"] is True
    assert result["final_valid"] is False


def test_v3_worker_is_importable_as_a_real_subprocess() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/run_dg10_bfcl_multiturn_scoring_worker_v3.py"),
            "--help",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Score one sealed BFCL multi-turn development case" in result.stdout


def test_v4_typed_hash_is_stable_distinct_and_fail_closed() -> None:
    left = {1: {"x", 2}, "1": [{3: "three", "3": "string"}]}
    right = {"1": [{"3": "string", 3: "three"}], 1: {2, "x"}}

    assert worker_v4._safe_result_hash(left) == worker_v4._safe_result_hash(right)
    assert worker_v4._safe_result_hash({1: "x"}) != worker_v4._safe_result_hash(
        {"1": "x"}
    )
    try:
        worker_v4._safe_result_hash({object(): "x"})
    except TypeError:
        pass
    else:
        raise AssertionError("unsupported checker-result key must fail closed")


def test_v4_schedule_probe_uses_frozen_v1_membership_boundary(
    tmp_path: Path,
) -> None:
    contract = {
        "scoring_schedule": {"ordered_case_ids": ["bfcl_v4:allowed"]},
        "remediation_schedule": {"ordered_case_ids": ["bfcl_v4:allowed"]},
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    allowed_code, allowed = worker_v4._schedule_probe(
        contract_path, "bfcl_v4:allowed"
    )
    rejected_code, rejected = worker_v4._schedule_probe(
        contract_path, "bfcl_v4:rejected"
    )

    assert allowed_code == 0
    assert allowed["status"] == "WOULD_ENTER_LABEL_BOUNDARY"
    assert allowed["real_label_bytes_opened"] is False
    assert rejected_code == 3
    assert rejected["status"] == "REJECTED_AT_FROZEN_SCHEDULE"
    assert rejected["label_loader_reached"] is False


def test_v4_worker_real_subprocess_canonicalizer_probe() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/run_dg10_bfcl_multiturn_scoring_worker_v4.py"),
            "--canonicalizer-probe",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "PASS"
    assert output["algorithm"] == worker_v4.HASH_ALGORITHM
    assert output["typed_keys_distinct"] is True

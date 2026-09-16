from __future__ import annotations

from pathlib import Path

import pytest

from evals.mvp01.u0_warm_contract import (
    AUTHORIZED_RUN_LOCK,
    REQUEST_COUNT,
    SCOPE_IDENTITY,
    U0WarmContractError,
    assert_mvp01_u0_warm_authorized,
    assert_previous_u0_gate,
    required_authority_delta,
)


def _frontmatter(values: dict[str, str]) -> str:
    return "\n".join(
        ["---", *(f"{key}: {value}" for key, value in values.items()), "---", ""]
    )


def _documents(tmp_path: Path) -> tuple[Path, Path]:
    authority = required_authority_delta()
    master = tmp_path / "master.md"
    goal = tmp_path / "goal.md"
    master.write_text(_frontmatter(authority["master"]), encoding="utf-8")
    goal.write_text(_frontmatter(authority["goal"]), encoding="utf-8")
    return master, goal


def test_exact_warm_authority_has_100_requests_and_zero_benchmark_or_models(
    tmp_path: Path,
) -> None:
    master, goal = _documents(tmp_path)

    receipt = assert_mvp01_u0_warm_authorized(
        master_path=master,
        goal_path=goal,
    )

    assert receipt.scope == SCOPE_IDENTITY
    assert receipt.request_count == REQUEST_COUNT
    assert receipt.benchmark_case_count == 0
    assert receipt.reader_answer_judge_calls == 0
    assert receipt.formal_holdout_consumed is False
    assert required_authority_delta()["master"]["active_run_lock"] == (
        AUTHORIZED_RUN_LOCK
    )


def test_successor_lineage_binds_pass_failed_attempt_and_repair_probe() -> None:
    project_root = Path(__file__).resolve().parents[1]

    lineage = assert_previous_u0_gate(project_root)

    passed = lineage["passed_canary"]
    failed = lineage["immediate_failed_warm"]
    probe = lineage["repair_probe"]
    assert isinstance(passed, dict)
    assert isinstance(failed, dict)
    assert isinstance(probe, dict)
    assert passed["status"] == "PASS_MVP01_U0_24_CONTEXT_ONLY_CANARY"
    assert failed["status"] == (
        "FAIL_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK_REPAIR_REQUIRED"
    )
    assert failed["request_count"] == 100
    assert failed["logical_attempt_count"] == 0
    assert failed["runtime_attempt_count"] == 1
    assert failed["reader_answer_judge_calls"] == 0
    assert failed["formal_holdout_consumed"] is False
    assert probe["status"] == "PASS_MVP01_U0_WARM_REPAIR_PRODUCTION_PATH_PROBE"


@pytest.mark.parametrize(
    ("document", "field", "value"),
    (
        ("master", "authorized_benchmark_case_count", "24"),
        ("goal", "benchmark_case_execution_authorized", "true"),
        ("goal", "reader_answer_judge_calls_authorized", "true"),
        ("master", "active_run_scope", "MVP01_U0_24_CASE_CONTEXT_ONLY_CANARY"),
    ),
)
def test_warm_authority_rejects_near_miss(
    tmp_path: Path,
    document: str,
    field: str,
    value: str,
) -> None:
    authority = required_authority_delta()
    authority[document][field] = value
    master = tmp_path / "master.md"
    goal = tmp_path / "goal.md"
    master.write_text(_frontmatter(authority["master"]), encoding="utf-8")
    goal.write_text(_frontmatter(authority["goal"]), encoding="utf-8")

    with pytest.raises(U0WarmContractError, match=SCOPE_IDENTITY):
        assert_mvp01_u0_warm_authorized(
            master_path=master,
            goal_path=goal,
        )

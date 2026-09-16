from __future__ import annotations

from pathlib import Path

import pytest

from evals.gdpm.b0_canary_contract import B0CanaryContractError
from evals.mvp01.u0_canary_contract import (
    AUTHORIZED_RUN_LOCK,
    SCOPE_IDENTITY,
    assert_mvp01_u0_canary_authorized,
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


def test_exact_mvp_u0_authority_returns_zero_model_call_receipt(
    tmp_path: Path,
) -> None:
    master, goal = _documents(tmp_path)

    receipt = assert_mvp01_u0_canary_authorized(
        master_path=master,
        goal_path=goal,
    )

    assert receipt.scope == SCOPE_IDENTITY
    assert receipt.case_count == 24
    assert receipt.reader_answer_judge_calls == 0
    assert receipt.formal_holdout_consumed is False
    assert required_authority_delta()["master"]["active_run_lock"] == (
        AUTHORIZED_RUN_LOCK
    )


def test_mvp_u0_authority_rejects_near_miss(tmp_path: Path) -> None:
    authority = required_authority_delta()
    authority["goal"]["reader_answer_judge_calls_authorized"] = "true"
    master = tmp_path / "master.md"
    goal = tmp_path / "goal.md"
    master.write_text(_frontmatter(authority["master"]), encoding="utf-8")
    goal.write_text(_frontmatter(authority["goal"]), encoding="utf-8")

    with pytest.raises(B0CanaryContractError, match=SCOPE_IDENTITY):
        assert_mvp01_u0_canary_authorized(
            master_path=master,
            goal_path=goal,
        )

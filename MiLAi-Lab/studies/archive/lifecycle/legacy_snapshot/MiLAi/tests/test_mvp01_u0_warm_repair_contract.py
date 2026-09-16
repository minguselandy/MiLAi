from __future__ import annotations

from pathlib import Path

import pytest

from evals.mvp01.u0_warm_contract import (
    U0WarmContractError,
    assert_mvp01_u0_warm_authorized,
)
from evals.mvp01.u0_warm_repair_contract import (
    AUTHORIZED_RUN_ID,
    AUTHORIZED_RUN_LOCK,
    QUERY_CLASS_COUNT,
    SCOPE_IDENTITY,
    assert_failed_warm_002,
    assert_repair_probe_authorized,
)
from scripts.run_mvp01_u0_warm_repair_probe import (
    GOAL_PATH,
    MASTER_PATH,
    _build_run_lock,
    _probe_schedule,
)

ROOT = Path(__file__).resolve().parents[1]


def test_current_authority_opens_only_the_ten_class_repair_probe() -> None:
    authority = assert_repair_probe_authorized(
        master_path=MASTER_PATH,
        goal_path=GOAL_PATH,
    )

    assert authority.scope == SCOPE_IDENTITY
    assert authority.query_class_count == QUERY_CLASS_COUNT
    assert authority.reader_answer_judge_calls == 0
    assert authority.formal_holdout_consumed is False
    assert authority.formal_warm_successor_authorized is False
    assert AUTHORIZED_RUN_ID == "mvp01-u0-warm-repair-probe-20260901-002"
    assert AUTHORIZED_RUN_LOCK.endswith(f"{AUTHORIZED_RUN_ID}/run-lock.json")
    with pytest.raises(U0WarmContractError):
        assert_mvp01_u0_warm_authorized(
            master_path=MASTER_PATH,
            goal_path=GOAL_PATH,
        )


def test_repair_probe_binds_immutable_002_failure_and_dense_runtime() -> None:
    authority = assert_repair_probe_authorized(
        master_path=MASTER_PATH,
        goal_path=GOAL_PATH,
    )
    predecessor = assert_failed_warm_002(ROOT)
    schedule = _probe_schedule()
    run_lock = _build_run_lock(
        authority=authority,
        predecessor=predecessor,
        schedule=schedule,
    )

    assert predecessor["status"].startswith("FAIL_MVP01_U0_100_REQUEST")
    assert len(schedule) == 10
    assert len({row["query_class"] for row in schedule}) == 10
    scope = run_lock["scope"]
    retrieval = run_lock["retrieval_runtime"]
    assert isinstance(scope, dict)
    assert isinstance(retrieval, dict)
    assert scope["formal_warm_successor_authorized"] is False
    assert scope["formal_holdout_authorized"] is False
    assert retrieval["evidence_dense_enabled"] is True

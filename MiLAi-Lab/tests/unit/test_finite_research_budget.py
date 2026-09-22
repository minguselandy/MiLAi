from pathlib import Path

import pytest

from milai_lab.methods.finite_research_budget import BudgetStop, FiniteResearchBudget

SHA = "a" * 64


def opened(path: Path) -> FiniteResearchBudget:
    return FiniteResearchBudget(path, manifest_sha256=SHA)


def reserve(budget, kind="text", tokens=100):
    return budget.reserve(
        kind,
        upper_tokens=tokens,
        purpose="embedding" if kind == "embedding" else "generation",
        payload_sha256=SHA,
    )


def test_no_clock_before_first_attempt_and_no_reset_on_reopen(tmp_path):
    path = tmp_path / "budget.sqlite"
    budget = opened(path)
    assert budget.status()["started_at_unix"] is None
    key = reserve(budget)
    started = budget.status()["started_at_unix"]
    budget.settle(key, reported_tokens=20, failed=False)
    budget.close()
    budget = opened(path)
    assert budget.status()["started_at_unix"] == started
    assert budget.status()["kinds"]["text"]["charged_tokens"] == 20
    assert budget.status()["total_requests"] == 1
    budget.close()


@pytest.mark.parametrize("settled", [False, True])
def test_unknown_failure_or_interruption_retains_upper_bound(tmp_path, settled):
    budget = opened(tmp_path / "budget.sqlite")
    key = reserve(budget, tokens=2_999_999)
    if settled:
        budget.settle(key, reported_tokens=None, failed=True)
    assert budget.status()["kinds"]["text"]["unknown_token_upper_bound"] == 2_999_999
    with pytest.raises(BudgetStop, match="TOKEN_LIMIT"):
        reserve(budget, tokens=2)
    assert budget.status()["total_requests"] == 1
    budget.close()


@pytest.mark.parametrize("kind,cap", [("text", 400), ("embedding", 128)])
def test_failed_requests_and_retries_count_toward_cap(tmp_path, kind, cap):
    budget = opened(tmp_path / "budget.sqlite")
    for _ in range(cap):
        budget.settle(reserve(budget, kind), reported_tokens=None, failed=True)
    with pytest.raises(BudgetStop, match="REQUEST_LIMIT"):
        reserve(budget, kind)
    assert budget.status()["total_requests"] == cap
    budget.close()


def test_embedding_tokens_have_independent_hard_ceiling(tmp_path):
    budget = opened(tmp_path / "budget.sqlite")
    reserve(budget, "embedding", 50_000)
    with pytest.raises(BudgetStop, match="TOKEN_LIMIT"):
        reserve(budget, "embedding", 1)
    assert budget.status()["kinds"]["text"]["requests"] == 0
    budget.close()


def test_wall_time_stops_all_new_attempts_across_reopen(tmp_path, monkeypatch):
    path = tmp_path / "budget.sqlite"
    budget = opened(path)
    reserve(budget)
    deadline = budget.status()["deadline_unix"]
    budget.close()
    budget = opened(path)
    monkeypatch.setattr(budget, "_now", lambda: deadline)
    with pytest.raises(BudgetStop, match="WALL_TIME"):
        reserve(budget, "embedding")
    budget.close()


def test_wrong_manifest_cannot_reuse_ledger(tmp_path):
    path = tmp_path / "budget.sqlite"
    opened(path).close()
    with pytest.raises(BudgetStop, match="MANIFEST_CHANGED"):
        FiniteResearchBudget(path, manifest_sha256="b" * 64)


def test_duplicate_settlement_and_unknown_zero_are_rejected(tmp_path):
    budget = opened(tmp_path / "budget.sqlite")
    with pytest.raises(ValueError, match="CANNOT_BE_ZERO"):
        reserve(budget, tokens=0)
    key = reserve(budget)
    budget.settle(key, reported_tokens=None, failed=True)
    with pytest.raises(ValueError, match="ALREADY_SETTLED"):
        budget.settle(key, reported_tokens=0, failed=False)
    budget.close()


def test_usage_violation_records_actual_usage_and_permanently_stops(tmp_path):
    path = tmp_path / "budget.sqlite"
    budget = opened(path)
    with pytest.raises(BudgetStop, match="BOUND_VIOLATION"):
        budget.settle(reserve(budget, tokens=100), reported_tokens=101, failed=False)
    assert budget.status()["kinds"]["text"]["charged_tokens"] == 101
    budget.close()
    budget = opened(path)
    with pytest.raises(BudgetStop, match="BOUND_VIOLATION"):
        reserve(budget)
    budget.close()


def test_two_workers_share_the_same_reservations(tmp_path):
    path = tmp_path / "budget.sqlite"
    first, second = opened(path), opened(path)
    reserve(first, tokens=2_999_999)
    reserve(second, tokens=1)
    with pytest.raises(BudgetStop, match="TOKEN_LIMIT"):
        reserve(first, tokens=1)
    assert second.status()["total_requests"] == 2
    first.close()
    second.close()

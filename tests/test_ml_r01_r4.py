from __future__ import annotations

from collections.abc import Callable

import pytest

from evals.dg14.provider import MatchedVllmProvider, full_provider_contract
from evals.ml_repair import run_mlr01_r4
from evals.ml_repair.mlr01_r4_contract import (
    ARMS,
    FULL_CASE_COUNT,
    MEMORY_TOKEN_BUDGET,
    TARGET_COUNTS,
    case_seed,
    source_order_sha256,
    target_case_ids,
    target_cases,
)
from evals.ml_repair.mlr01_r4_providers import _official_prompt_function
from evals.ml_repair.mlr01_r4_score import paired_bootstrap


def test_pilot_is_exact_frozen_order_prefix() -> None:
    assert TARGET_COUNTS == (8, 128, 500)
    assert len(target_cases(FULL_CASE_COUNT)) == FULL_CASE_COUNT
    assert target_case_ids(8) == target_case_ids(FULL_CASE_COUNT)[:8]
    assert source_order_sha256(8) != source_order_sha256(128)


def test_provider_contract_accepts_exact_500_output_ceiling() -> None:
    provider = MatchedVllmProvider(max_output_tokens=500)
    assert provider.max_output_tokens == 500
    assert (
        full_provider_contract(max_output_tokens=500)["generation"]["max_tokens"] == 500
    )


def test_case_seed_is_arm_independent_and_lane_separated() -> None:
    case_id = target_case_ids(8)[0]
    answer_seed = case_seed(case_id, "answer")
    assert answer_seed == case_seed(case_id, "answer")
    assert answer_seed != case_seed(case_id, "judge")
    assert 0 <= answer_seed < 2**63
    assert MEMORY_TOKEN_BUDGET == 1024


def test_paired_bootstrap_uses_question_level_differences() -> None:
    positive = paired_bootstrap([1.0] * 8, samples=200, seed=7)
    tied = paired_bootstrap([0.0] * 8, samples=200, seed=7)
    assert positive["estimate"] == 1.0
    assert positive["ci95"] == [1.0, 1.0]
    assert tied["estimate"] == 0.0
    assert tied["ci95"] == [0.0, 0.0]
    assert positive["unit"] == "question_id"


def test_judge_prompt_comes_from_upstream_function_body() -> None:
    prompt = _official_prompt_function()(
        "single-session-user",
        "Where did I go?",
        "Lisbon",
        "You went to Lisbon.",
        abstention=False,
    )
    assert "Where did I go?" in prompt
    assert "Lisbon" in prompt
    assert "You went to Lisbon." in prompt


def test_pilot_runner_stops_after_eight_by_four(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int | None]] = []

    monkeypatch.setattr(
        run_mlr01_r4,
        "build_capability_seal",
        lambda: calls.append(("seal", None)) or {"seal_digest": "frozen"},
    )

    def stage(name: str) -> Callable[[int], dict[str, object]]:
        def run(target: int) -> dict[str, object]:
            calls.append((name, target))
            return {"stage": name, "target_count": target}

        return run

    monkeypatch.setattr(run_mlr01_r4, "run_contexts", stage("context"))
    monkeypatch.setattr(run_mlr01_r4, "run_answers", stage("answer"))
    monkeypatch.setattr(run_mlr01_r4, "run_judges", stage("judge"))
    monkeypatch.setattr(run_mlr01_r4, "score", stage("score"))
    result = run_mlr01_r4.run_pilot_8()

    assert calls == [
        ("seal", None),
        ("context", 8),
        ("answer", 8),
        ("judge", 8),
        ("score", 8),
    ]
    assert result["stopped_before_128"] is True
    assert result["stopped_before_500"] is True
    assert len(ARMS) == 4

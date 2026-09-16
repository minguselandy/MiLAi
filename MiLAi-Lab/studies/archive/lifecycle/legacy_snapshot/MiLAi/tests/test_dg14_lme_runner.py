from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import pytest

from evals.dg14.benchmark import (
    ARMS,
    BUDGETS,
    OPENED_DEV_CASE_IDS,
    aggregate_metrics,
    build_failure_taxonomy,
    build_schedule,
    evaluate_2048_gate,
)
from evals.dg14.ledger import (
    ZERO_SHA256,
    DG14LedgerError,
    DG14StageEvent,
    HashChainStageLedger,
)
from evals.dg14.provider import (
    DG14ProviderError,
    MatchedVllmProvider,
    ReaderConformanceError,
    matched_seed,
)


class _StageCommon(TypedDict):
    run_id: str
    case_id: str
    method_id: str
    token_budget: int
    retry_count: int


def test_opened_dev_schedule_has_the_complete_five_by_two_by_five_denominator() -> None:
    schedule = build_schedule(OPENED_DEV_CASE_IDS)

    assert len(OPENED_DEV_CASE_IDS) == 5
    assert BUDGETS == (512, 2048)
    assert len(ARMS) == 5
    assert len(schedule) == 5 * 2 * 5 == 50
    assert (
        len({(cell.case_id, cell.token_budget, cell.method_id) for cell in schedule})
        == 50
    )
    assert {cell.case_id for cell in schedule} == set(OPENED_DEV_CASE_IDS)
    assert {cell.token_budget for cell in schedule} == {512, 2048}
    assert {cell.method_id for cell in schedule} == set(ARMS)


def test_matched_provider_seed_is_arm_independent_but_case_and_budget_bound() -> None:
    run_id = "dg14-unit"
    for case_id in OPENED_DEV_CASE_IDS:
        by_budget: dict[int, set[int]] = {}
        for token_budget in BUDGETS:
            for _arm in ARMS:
                by_budget.setdefault(token_budget, set()).add(
                    matched_seed(run_id, case_id, token_budget)
                )
        assert {budget: len(seeds) for budget, seeds in by_budget.items()} == {
            512: 1,
            2048: 1,
        }

    assert matched_seed(run_id, OPENED_DEV_CASE_IDS[0], 512) != matched_seed(
        run_id, OPENED_DEV_CASE_IDS[0], 2048
    )
    assert matched_seed(run_id, OPENED_DEV_CASE_IDS[0], 512) != matched_seed(
        run_id, OPENED_DEV_CASE_IDS[1], 512
    )


def test_matched_provider_sends_equal_generation_settings_and_seed_across_arms() -> (
    None
):
    chat_payloads: list[dict[str, object]] = []

    def post_json(
        _base_url: str,
        path: str,
        payload: dict[str, object],
        *,
        timeout: float,
    ) -> tuple[dict[str, object], dict[str, str]]:
        assert timeout > 0
        if path == "/tokenize":
            return {"count": 10, "tokens": list(range(10))}, {}
        assert path == "/v1/chat/completions"
        chat_payloads.append(payload)
        return (
            {
                "id": f"chatcmpl-dg14-{len(chat_payloads):04d}",
                "choices": [
                    {
                        "message": {"content": '{"answer":"UNKNOWN"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            },
            {},
        )

    provider = MatchedVllmProvider(post_json=post_json)  # type: ignore[arg-type]
    for arm in ARMS:
        result = provider.answer(
            run_id="dg14-unit",
            case_id=OPENED_DEV_CASE_IDS[0],
            method_id=arm,
            question="What was remembered?",
            question_as_of="2026-08-26T00:00:00+00:00",
            memory_context=f"context supplied by {arm}",
            token_budget=2048,
        )
        assert result.provider_calls == 1

    assert len(chat_payloads) == len(ARMS)
    invariant_keys = {
        "model",
        "temperature",
        "top_p",
        "max_tokens",
        "stream",
        "seed",
        "response_format",
        "chat_template_kwargs",
        "include_reasoning",
    }
    frozen = {key: chat_payloads[0][key] for key in invariant_keys}
    assert all(
        {key: payload[key] for key in invariant_keys} == frozen
        for payload in chat_payloads
    )
    assert frozen["seed"] == matched_seed("dg14-unit", OPENED_DEV_CASE_IDS[0], 2048)
    assert len({payload["cache_salt"] for payload in chat_payloads}) == len(ARMS)


def test_invalid_provider_response_is_typed_and_never_falls_through_to_a_second_call() -> (
    None
):
    paths: list[str] = []

    def post_json(
        _base_url: str,
        path: str,
        _payload: dict[str, object],
        *,
        timeout: float,
    ) -> tuple[dict[str, object], dict[str, str]]:
        assert timeout > 0
        paths.append(path)
        if path == "/tokenize":
            return {"count": 10, "tokens": list(range(10))}, {}
        return {
            "id": "chatcmpl-dg14-invalid",
            "choices": [{"message": {"content": "not-json"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }, {}

    provider = MatchedVllmProvider(post_json=post_json)  # type: ignore[arg-type]

    with pytest.raises(DG14ProviderError, match="strict answer content"):
        provider.answer(
            run_id="dg14-unit",
            case_id=OPENED_DEV_CASE_IDS[0],
            method_id="CTRL-NONE",
            question="What was remembered?",
            question_as_of="2026-08-26T00:00:00+00:00",
            memory_context="",
            token_budget=512,
        )
    assert paths.count("/v1/chat/completions") == 1


def test_exact_provider_separates_sealed_context_from_one_template_boundary_token() -> None:
    paths: list[str] = []

    def post_json(
        _base_url: str,
        path: str,
        payload: dict[str, object],
        *,
        timeout: float,
    ) -> tuple[dict[str, object], dict[str, str]]:
        assert timeout > 0
        paths.append(path)
        if path == "/tokenize":
            messages = payload["messages"]
            assert isinstance(messages, list)
            count = 1125 if "sealed memory" in str(messages) else 100
            return {"count": count, "tokens": list(range(count))}, {}
        return (
            {
                "id": "chatcmpl-template-boundary-0001",
                "choices": [
                    {
                        "message": {"content": '{"answer":"UNKNOWN"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1125, "completion_tokens": 3},
            },
            {},
        )

    result = MatchedVllmProvider(post_json=post_json).answer(  # type: ignore[arg-type]
        run_id="dg14-sealed-context",
        case_id=OPENED_DEV_CASE_IDS[0],
        method_id="SEALED",
        question="What was remembered?",
        question_as_of="2026-08-26T00:00:00+00:00",
        memory_context="sealed memory",
        token_budget=1024,
        exact_context=True,
        sealed_context_tokens=1024,
    )

    assert paths.count("/tokenize") == 2
    assert paths.count("/v1/chat/completions") == 1
    assert result.memory_tokens == 1025
    assert result.sealed_context_tokens == 1024
    assert result.template_boundary_tokens == 1
    assert result.context_truncated is False


def test_exact_provider_rejects_more_than_one_template_boundary_token() -> None:
    completion_calls = 0

    def post_json(
        _base_url: str,
        path: str,
        payload: dict[str, object],
        *,
        timeout: float,
    ) -> tuple[dict[str, object], dict[str, str]]:
        nonlocal completion_calls
        assert timeout > 0
        if path == "/tokenize":
            messages = payload["messages"]
            assert isinstance(messages, list)
            count = 1126 if "sealed memory" in str(messages) else 100
            return {"count": count, "tokens": list(range(count))}, {}
        completion_calls += 1
        raise AssertionError("completion must not be called after accounting drift")

    with pytest.raises(ReaderConformanceError) as captured:
        MatchedVllmProvider(post_json=post_json).answer(  # type: ignore[arg-type]
            run_id="dg14-sealed-context",
            case_id=OPENED_DEV_CASE_IDS[0],
            method_id="SEALED",
            question="What was remembered?",
            question_as_of="2026-08-26T00:00:00+00:00",
            memory_context="sealed memory",
            token_budget=1024,
            exact_context=True,
            sealed_context_tokens=1024,
        )

    assert captured.value.metadata["template_boundary_tokens"] == 2
    assert completion_calls == 0


def test_exact_provider_rejects_sealed_context_claim_above_budget_before_tokenize() -> None:
    paths: list[str] = []

    def post_json(
        _base_url: str,
        path: str,
        _payload: dict[str, object],
        *,
        timeout: float,
    ) -> tuple[dict[str, object], dict[str, str]]:
        assert timeout > 0
        paths.append(path)
        raise AssertionError("invalid sealed claim must fail before provider I/O")

    with pytest.raises(ReaderConformanceError):
        MatchedVllmProvider(post_json=post_json).answer(  # type: ignore[arg-type]
            run_id="dg14-sealed-context",
            case_id=OPENED_DEV_CASE_IDS[0],
            method_id="SEALED",
            question="What was remembered?",
            question_as_of="2026-08-26T00:00:00+00:00",
            memory_context="sealed memory",
            token_budget=1024,
            exact_context=True,
            sealed_context_tokens=1025,
        )

    assert paths == []


def test_stage_ledger_is_append_only_hash_chained_and_keeps_stage_timings_separate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stage-ledger.jsonl"
    ledger = HashChainStageLedger(path)
    common: _StageCommon = {
        "run_id": "dg14-unit",
        "case_id": OPENED_DEV_CASE_IDS[0],
        "method_id": "DG14-MILAI-MCP",
        "token_budget": 2048,
        "retry_count": 0,
    }
    events = (
        DG14StageEvent(
            **common,
            stage="ingest",
            status="SUCCEEDED",
            duration_ms=1.25,
            logical_calls=1,
        ),
        DG14StageEvent(
            **common,
            stage="finalize",
            status="SUCCEEDED",
            duration_ms=2.5,
            logical_calls=1,
        ),
        DG14StageEvent(
            **common,
            stage="mcp",
            status="SUCCEEDED",
            duration_ms=3.75,
            logical_calls=1,
            candidate_count=3,
            retrieval_route="canonical_required",
        ),
        DG14StageEvent(
            **common,
            stage="runtime",
            status="SUCCEEDED",
            duration_ms=4.0,
            logical_calls=1,
        ),
        DG14StageEvent(
            **common,
            stage="context",
            status="SUCCEEDED",
            duration_ms=5.0,
            memory_tokens=321,
        ),
        DG14StageEvent(
            **common,
            stage="provider",
            status="SUCCEEDED",
            duration_ms=6.0,
            logical_calls=1,
            prompt_tokens=456,
        ),
        DG14StageEvent(
            **common,
            stage="e2e",
            status="SUCCEEDED",
            duration_ms=22.0,
        ),
    )
    for event in events:
        ledger.append(event)

    verification = ledger.verify()
    assert len(verification.events) == len(events)
    assert verification.root_sha256 != ZERO_SHA256
    assert [row["sequence"] for row in verification.events] == list(
        range(1, len(events) + 1)
    )
    assert verification.events[0]["previous_sha256"] == ZERO_SHA256
    assert all(
        later["previous_sha256"] == earlier["event_sha256"]
        for earlier, later in zip(verification.events, verification.events[1:])
    )
    assert [row["event"]["stage"] for row in verification.events] == [
        event.stage for event in events
    ]
    assert [row["event"]["duration_ms"] for row in verification.events[:-1]] == [
        1.25,
        2.5,
        3.75,
        4.0,
        5.0,
        6.0,
    ]


def test_stage_ledger_rejects_tampering_and_nonzero_automatic_retry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stage-ledger.jsonl"
    ledger = HashChainStageLedger(path)
    ledger.append(
        DG14StageEvent(
            run_id="dg14-unit",
            stage="mcp",
            status="SUCCEEDED",
            duration_ms=1.0,
            logical_calls=1,
        )
    )
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["event"]["logical_calls"] = 99
    path.write_text(json.dumps(envelope) + "\n", encoding="utf-8")

    with pytest.raises(DG14LedgerError, match="digest"):
        ledger.verify()
    with pytest.raises(ValueError, match="retries zero"):
        DG14StageEvent(
            run_id="dg14-unit",
            stage="mcp",
            status="FAILED",
            duration_ms=1.0,
            retry_count=1,
            failure_type="transport",
        )


def test_failure_taxonomy_keeps_the_full_denominator_and_typed_case_failures() -> None:
    records: list[dict[str, object]] = []
    for case_id in OPENED_DEV_CASE_IDS:
        for budget in BUDGETS:
            for method_id in ARMS:
                records.append(
                    {
                        "case_id": case_id,
                        "token_budget": budget,
                        "method_id": method_id,
                        "status": "SUCCEEDED",
                        "failure_type": None,
                        "failure_stage": None,
                    }
                )
    records[-1].update(
        {
            "status": "FAILED",
            "failure_type": "CONTEXT_BUDGET_EXHAUSTED",
            "failure_stage": "context",
        }
    )

    taxonomy = build_failure_taxonomy(records)

    assert taxonomy["denominator"] == 50
    assert taxonomy["completed"] == 49
    assert taxonomy["failed"] == 1
    assert taxonomy["by_stage"] == {"context": 1}
    assert taxonomy["by_type"] == {"CONTEXT_BUDGET_EXHAUSTED": 1}
    assert taxonomy["per_case"][OPENED_DEV_CASE_IDS[-1]]["failed"] == 1


def test_2048_gate_fails_when_dg14_is_inferior_to_bm25_turn() -> None:
    methods = {
        "DG14-MILAI-MCP": {
            "2048": {
                "exact_match": 0.6,
                "normalized_f1": 0.6,
                "evidence_coverage": 0.8,
            }
        },
        "LME-BM25-T": {
            "2048": {
                "exact_match": 0.8,
                "normalized_f1": 0.8,
                "evidence_coverage": 1.0,
            }
        },
    }

    gate = evaluate_2048_gate(methods)

    assert gate["minimum_3_of_5_correct"] is True
    assert gate["minimum_evidence_coverage_0_80"] is True
    assert gate["noninferiority"] == {
        "exact_match": False,
        "normalized_f1": False,
        "evidence_coverage": False,
    }
    assert gate["passed"] is False


def test_metrics_keep_quality_efficiency_and_all_correctness_denominators_separate() -> (
    None
):
    records: list[dict[str, object]] = []
    for index, case_id in enumerate(OPENED_DEV_CASE_IDS):
        exact = int(index < 3)
        records.append(
            {
                "answer": "UNKNOWN" if index == 4 else f"answer-{index}",
                "answer_score": {
                    "exact_match": exact,
                    "normalized_f1": float(exact),
                },
                "case_id": case_id,
                "context_truncated": index == 3,
                "e2e_latency_ms": 100.0 + index,
                "is_multi_session": index < 2,
                "mcp_logical_calls": 2,
                "mcp_query_logical_calls": 1,
                "memory_tokens": 200 + index,
                "prompt_tokens": 400 + index,
                "provider_calls": 1,
                "provider_latency_ms": 50.0 + index,
                "query_latency_ms": float(index + 1),
                "retrieval_route": "hybrid",
                "retrieval_score": {
                    "hit_at_k": int(index < 4),
                    "ndcg_at_k": 1.0 if index < 4 else 0.0,
                    "relevant_coverage_at_k": 1.0 if index < 4 else 0.0,
                },
            }
        )
    correctness = {
        "wrong_scope_acceptance": {"accepted": 0, "denominator": 5},
        "cross_case_contamination": {"accepted": 0, "denominator": 5},
        "label_leakage": {"accepted": 0, "denominator": 123},
        "stale_revoked_evidence_acceptance": {"accepted": 0, "denominator": 5},
        "silent_fallback": {"accepted": 0, "denominator": 5},
    }

    metrics = aggregate_metrics(records, correctness)

    assert set(metrics) == {"quality", "efficiency", "correctness"}
    assert metrics["quality"]["case_count"] == 5
    assert metrics["quality"]["exact_match"] == 0.6
    assert metrics["quality"]["normalized_f1"] == 0.6
    assert metrics["quality"]["evidence_coverage"] == 0.8
    assert metrics["quality"]["unknown_abstention_rate"] == 0.2
    assert metrics["quality"]["multi_session_success"] == {
        "denominator": 2,
        "rate": 1.0,
        "successes": 2,
    }
    assert metrics["efficiency"]["mcp_query_logical_calls"] == 5
    assert metrics["efficiency"]["provider_calls"] == 5
    assert metrics["efficiency"]["query_latency_ms_p50"] == 3.0
    assert metrics["efficiency"]["query_latency_ms_p95"] == 5.0
    assert metrics["correctness"] == correctness

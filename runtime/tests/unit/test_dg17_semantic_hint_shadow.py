from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from milai.adapters.semantic_hint import LoopbackVllmSemanticProvider
from milai.application.query_planner import QueryPlanner
from milai.application.semantic_hint import (
    MAX_HINT_COMPLETION_TOKENS,
    SemanticHintCompletion,
    SemanticHintError,
    SemanticHintShadowService,
)
from milai.domain.retrieval import RetrievalRequest

REFERENCE = datetime(2023, 3, 27, 12, tzinfo=UTC)


class _Provider:
    def __init__(
        self,
        content: dict[str, object],
        *,
        provider_calls: int = 1,
        retries: int = 0,
        finish_reason: str = "stop",
    ) -> None:
        self.content = content
        self.provider_calls = provider_calls
        self.retries = retries
        self.finish_reason = finish_reason
        self.calls = 0
        self.max_tokens: int | None = None
        self.schema: object = None

    def complete_structured(  # type: ignore[no-untyped-def]
        self,
        *,
        messages,
        schema_name,
        schema,
        max_completion_tokens,
        seed,
    ) -> SemanticHintCompletion:
        self.calls += 1
        self.max_tokens = max_completion_tokens
        self.schema = schema
        assert schema_name == "semantic_query_hint_v01"
        assert seed >= 0
        assert len(messages) == 2
        payload = json.loads(messages[1]["content"])
        assert "deterministic_outcome" not in payload
        return SemanticHintCompletion(
            content=json.dumps(self.content),
            provider="fake-vllm",
            model="fake-model",
            prompt_tokens=64,
            completion_tokens=24,
            tokenizer_latency_ms=1.0,
            queue_ms=2.0,
            ttft_ms=3.0,
            decode_ms=4.0,
            total_ms=9.0,
            provider_calls=self.provider_calls,
            automatic_retry_count=self.retries,
            finish_reason=self.finish_reason,
        )


def _valid_hint(query: str) -> dict[str, object]:
    cue = "How many"
    temporal = "past two weeks"
    return {
        "schema_version": "semantic-query-hint-v0.1",
        "route": "COMPOSE",
        "operator_family": "COUNT",
        "cue_spans": [
            {"start": query.index(cue), "end": query.index(cue) + len(cue), "text": cue}
        ],
        "temporal_spans": [
            {
                "start": query.index(temporal),
                "end": query.index(temporal) + len(temporal),
                "text": temporal,
            }
        ],
        "requires_complete_set": True,
        "ambiguities": [],
    }


def test_q3c_shadow_receipts_one_strict_non_executable_hint_call() -> None:
    query = "How many times did I bake in the past two weeks?"
    provider = _Provider(_valid_hint(query))
    receipt = SemanticHintShadowService(provider).generate(
        run_id="shadow-run",
        case_id="count-en",
        query=query,
        reference_time=REFERENCE,
    )

    assert provider.calls == 1
    assert provider.max_tokens == MAX_HINT_COMPLETION_TOKENS
    assert isinstance(provider.schema, dict)
    assert "final_answer" not in json.dumps(provider.schema)
    assert receipt.hint.operator_family == "COUNT"
    assert receipt.auxiliary_model_calls == 1
    assert receipt.automatic_retry_count == 0
    assert receipt.prompt_tokens == 64
    assert receipt.completion_tokens == 24
    assert receipt.timing.total_ms == 9.0


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"final_answer": "four"}, "SEMANTIC_HINT_SCHEMA_INVALID"),
        (
            {"cue_spans": [{"start": 0, "end": 8, "text": "Not real"}]},
            "SEMANTIC_HINT_CUE_SPAN_INVALID",
        ),
    ],
)
def test_q3c_invalid_schema_or_non_exact_cue_is_rejected_without_fallback(
    mutation: dict[str, object], reason: str
) -> None:
    query = "How many times did I bake in the past two weeks?"
    raw = {**_valid_hint(query), **mutation}
    service = SemanticHintShadowService(_Provider(raw))

    with pytest.raises(SemanticHintError, match=reason):
        service.generate(
            run_id="shadow-run",
            case_id="invalid",
            query=query,
            reference_time=REFERENCE,
        )


@pytest.mark.parametrize(("calls", "retries"), [(2, 0), (1, 1)])
def test_q3c_call_ceiling_or_retry_violation_is_typed(
    calls: int, retries: int
) -> None:
    query = "How many times did I bake in the past two weeks?"
    service = SemanticHintShadowService(
        _Provider(_valid_hint(query), provider_calls=calls, retries=retries)
    )

    with pytest.raises(SemanticHintError, match="CALL_CEILING_VIOLATED"):
        service.generate(
            run_id="shadow-run",
            case_id="ceiling",
            query=query,
            reference_time=REFERENCE,
        )


def test_q3c_length_truncation_is_typed_before_schema_validation() -> None:
    query = "How many times did I bake in the past two weeks?"
    service = SemanticHintShadowService(
        _Provider(_valid_hint(query), finish_reason="length")
    )

    with pytest.raises(SemanticHintError, match="OUTPUT_TRUNCATED"):
        service.generate(
            run_id="shadow-run",
            case_id="truncated",
            query=query,
            reference_time=REFERENCE,
        )


def test_q3c_shadow_cannot_change_the_product_plan_or_exceed_preview_budget() -> None:
    query = "How many times did I bake in the past two weeks?"
    request = RetrievalRequest(route="L1", query=query, as_of=REFERENCE)
    planner = QueryPlanner()
    before = planner.plan(request)
    SemanticHintShadowService(_Provider(_valid_hint(query))).generate(
        run_id="shadow-run",
        case_id="isolation",
        query=query,
        reference_time=REFERENCE,
        evidence_previews=["source-exact preview"],
    )
    after = planner.plan(request)

    assert before == after
    with pytest.raises(ValueError, match="preview budget exceeded"):
        SemanticHintShadowService(_Provider(_valid_hint(query))).generate(
            run_id="shadow-run",
            case_id="preview-overflow",
            query=query,
            reference_time=REFERENCE,
            evidence_previews=["x"] * 13,
        )


def test_q3c_actual_adapter_accepts_loopback_only() -> None:
    LoopbackVllmSemanticProvider(model="local-model")
    with pytest.raises(ValueError, match="loopback"):
        LoopbackVllmSemanticProvider(
            base_url="https://api.example.com/v1", model="remote-model"
        )

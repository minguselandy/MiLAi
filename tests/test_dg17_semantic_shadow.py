from __future__ import annotations

import json

from milai.application.semantic_hint import SemanticHintCompletion

from evals.dg17.semantic_shadow import (
    build_shadow_fixtures,
    deterministic_shadow_manifest,
    run_semantic_shadow,
)


class _ShadowProvider:
    def __init__(self) -> None:
        self.calls = 0

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
        assert schema["type"] == "object"
        assert seed >= 0
        if schema_name == "semantic_query_hint_v01":
            payload = json.loads(messages[1]["content"])
            assert "deterministic_outcome" not in payload
            assert payload["missing_requirement_ids"] == []
            assert payload["evidence_span_previews"] == []
            route = "AMBIGUOUS"
            family = "LOOKUP"
            content = json.dumps(
                {
                    "schema_version": "semantic-query-hint-v0.1",
                    "route": route,
                    "operator_family": family,
                    "cue_spans": [],
                    "temporal_spans": [],
                    "requires_complete_set": route == "COMPOSE",
                    "ambiguities": ["unsupported"] if route == "AMBIGUOUS" else [],
                }
            )
            completion_tokens = 20
        else:
            assert schema_name == "semantic_full_plan_negative_control_v01"
            assert max_completion_tokens == 512
            content = json.dumps(
                {
                    "route": "COMPOSE",
                    "operator_family": "MULTI_JOIN",
                    "requirements": ["LEFT", "RIGHT"],
                    "steps": ["RETRIEVE", "BIND", "JOIN", "REDUCE"],
                    "completeness": "ALL_REQUIRED_BINDINGS",
                    "ambiguities": [],
                }
            )
            completion_tokens = 80
        return SemanticHintCompletion(
            content=content,
            provider="fake-vllm",
            model="fake-model",
            prompt_tokens=100,
            completion_tokens=completion_tokens,
            tokenizer_latency_ms=1.0,
            queue_ms=2.0,
            ttft_ms=3.0,
            decode_ms=4.0,
            total_ms=9.0,
        )


def test_q3c_fixture_matrix_has_required_slices_and_safe_deterministic_baseline() -> None:
    fixtures = build_shadow_fixtures()
    manifest = deterministic_shadow_manifest()

    assert len(fixtures) == manifest["case_count"] == 29
    assert manifest["supported_denominator"] == 25
    assert manifest["deterministic_correct"] == 25
    assert manifest["unsafe_generic_lookup_promotions"] == 0
    assert {fixture.slice for fixture in fixtures} >= {
        "CURRENT_10_OPENED_DEV",
        "EN_AUTHORED_DEV",
        "ZH_AUTHORED_DEV",
        "MULTIPLE_NUMBERS",
        "IMPLICIT_TEMPORAL",
        "ORDINARY_LOOKUP",
        "UNSUPPORTED",
        "UNSUPPORTED_LANGUAGE",
    }


def test_q3c_shadow_reports_quality_latency_calls_and_full_plan_ablation() -> None:
    provider = _ShadowProvider()
    report = run_semantic_shadow(run_id="q3c-unit", provider=provider)
    aggregate = report["aggregate"]

    assert provider.calls == 58
    assert report["status"] == "Q3C_SHADOW_CHARACTERIZED"
    assert report["teacher_target_in_prompt"] is False
    assert report["deterministic_requirement_ids_in_prompt"] is False
    assert report["fixture_split"] == "AUTHORED_DEV_NO_HELDOUT_CLAIM"
    assert aggregate["case_count"] == 29
    assert aggregate["supported_denominator"] == 25
    assert aggregate["minimal_hint_correct"] == 0
    assert aggregate["wrong_promoted_hint"] == 0
    assert aggregate["minimal_hint_provider_p95_ms"] == 9.0
    assert aggregate["minimal_completion_tokens_mean"] == 20.0
    assert aggregate["full_plan_completion_tokens_mean"] == 80.0
    assert aggregate["full_to_minimal_completion_token_ratio"] == 4.0
    assert aggregate["minimal_generation_calls"] == 29
    assert aggregate["full_plan_negative_control_calls"] == 29
    assert aggregate["product_semantic_assist_calls"] == 0
    assert aggregate["product_route_changes"] == 0
    assert aggregate["full_plan_product_consumption"] == 0
    assert report["q3d_gate"]["eligible"] is False

"""Q3C deterministic-vs-minimal-hint shadow matrix and negative control."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from milai.application.memory_query import MemoryQueryCompiler
from milai.application.query_ir_compat import infer_operator_family
from milai.application.semantic_hint import (
    SemanticHintError,
    SemanticHintShadowService,
    StructuredSemanticProvider,
)

from evals.dg17.measurement import load_answer_bearing_labels

_LEGACY_TO_FAMILY = {
    "LOOKUP": "LOOKUP",
    "TEMPORAL_FILTER": "TEMPORAL_FILTER",
    "TEMPORAL_ORDER": "TEMPORAL_ORDER",
    "TEMPORAL_DISTANCE": "TEMPORAL_DISTANCE",
    "COUNT_DISTINCT": "COUNT",
    "DIVIDE_VALUES": "DIVIDE",
    "MULTI_EVIDENCE_JOIN": "MULTI_JOIN",
}
_FAMILY_ROUTE = {
    "LOOKUP": "EVIDENCE",
    "TEMPORAL_FILTER": "COMPOSE",
    "TEMPORAL_ORDER": "COMPOSE",
    "TEMPORAL_DISTANCE": "COMPOSE",
    "COUNT": "COMPOSE",
    "DIVIDE": "COMPOSE",
    "MULTI_JOIN": "COMPOSE",
}
_FULL_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "route",
        "operator_family",
        "requirements",
        "steps",
        "completeness",
        "ambiguities",
    ],
    "properties": {
        "route": {"enum": ["STATE", "EVIDENCE", "COMPOSE", "AMBIGUOUS"]},
        "operator_family": {
            "enum": [
                "LOOKUP",
                "TEMPORAL_FILTER",
                "TEMPORAL_ORDER",
                "TEMPORAL_DISTANCE",
                "COUNT",
                "SUM",
                "AVERAGE",
                "DIVIDE",
                "COMPARE",
                "MULTI_JOIN",
                "WHY_CHANGE",
            ]
        },
        "requirements": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 16,
        },
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 32,
        },
        "completeness": {"type": "string"},
        "ambiguities": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 16,
        },
    },
}


@dataclass(frozen=True, slots=True)
class ShadowFixture:
    case_id: str
    query: str
    reference_time: datetime
    slice: str
    expected_route: str | None
    expected_family: str | None
    declared_supported: bool


def build_shadow_fixtures() -> list[ShadowFixture]:
    """Build the frozen current-10 plus unseen multilingual/adversarial matrix."""

    _envelope, cases, labels = load_answer_bearing_labels()
    fixtures: list[ShadowFixture] = []
    for case in cases:
        operator = str(labels[case.case_id]["gold_ir"]["operator"])
        family = _LEGACY_TO_FAMILY.get(operator)
        fixtures.append(
            ShadowFixture(
                case_id=f"current10:{case.case_id}",
                query=case.question,
                reference_time=_reference_time(case.question_at),
                slice="CURRENT_10_OPENED_DEV",
                expected_route=_FAMILY_ROUTE.get(family) if family else None,
                expected_family=family,
                declared_supported=family is not None,
            )
        )
    static = [
        ("en-lookup", "What hotel did I use on my last trip?", "EN_AUTHORED_DEV", "EVIDENCE", "LOOKUP", True),
        ("zh-lookup", "我上次旅行住在什么酒店?", "ZH_AUTHORED_DEV", "EVIDENCE", "LOOKUP", True),
        ("en-filter", "Which activity did I do two weeks ago?", "EN_AUTHORED_DEV", "COMPOSE", "TEMPORAL_FILTER", True),
        ("zh-filter", "两周前我参加了什么活动?", "ZH_AUTHORED_DEV", "COMPOSE", "TEMPORAL_FILTER", True),
        ("en-order", "Which came earlier, planting the elm or repairing the gate?", "IMPLICIT_TEMPORAL", "COMPOSE", "TEMPORAL_ORDER", True),
        ("zh-order", "种树还是修门, 哪个先发生?", "IMPLICIT_TEMPORAL", "COMPOSE", "TEMPORAL_ORDER", True),
        ("en-distance", "How many weeks elapsed from the demo to the concert?", "EN_AUTHORED_DEV", "COMPOSE", "TEMPORAL_DISTANCE", True),
        ("zh-distance", "演示与音乐会之间有多少周?", "ZH_AUTHORED_DEV", "COMPOSE", "TEMPORAL_DISTANCE", True),
        ("en-count", "How many times did I repair a scooter in the past month?", "EN_AUTHORED_DEV", "COMPOSE", "COUNT", True),
        ("zh-count", "最近三个月内我参加音乐会多少次?", "ZH_AUTHORED_DEV", "COMPOSE", "COUNT", True),
        ("en-divide", "How much did I pay per glass vase?", "EN_AUTHORED_DEV", "COMPOSE", "DIVIDE", True),
        ("zh-divide", "陶瓷杯的单价是多少?", "ZH_AUTHORED_DEV", "COMPOSE", "DIVIDE", True),
        ("en-join", "Using both sessions, combine the evidence about my final city choice.", "MULTI_SESSION", "COMPOSE", "MULTI_JOIN", True),
        ("zh-join", "跨会话查找我最终选择城市的证据", "MULTI_SESSION", "COMPOSE", "MULTI_JOIN", True),
        ("multi-number", "I paid $60 for 5 mugs. How much did I pay per mug?", "MULTIPLE_NUMBERS", "COMPOSE", "DIVIDE", True),
        ("ordinary-lookup", "Who did I meet at lunch last Tuesday?", "ORDINARY_LOOKUP", "EVIDENCE", "LOOKUP", True),
        ("unsupported-en", "Enumerate every memory in a complete timeline.", "UNSUPPORTED", "AMBIGUOUS", None, False),
        ("unsupported-zh", "把所有事件按完整时间线排序。", "UNSUPPORTED", "AMBIGUOUS", None, False),
        ("unsupported-language", "Combien de souvenirs sont pertinents?", "UNSUPPORTED_LANGUAGE", "AMBIGUOUS", None, False),
    ]
    for case_id, query, slice_name, route, family, supported in static:
        fixtures.append(
            ShadowFixture(
                case_id=case_id,
                query=query,
                reference_time=datetime(2023, 3, 27, 12, tzinfo=UTC),
                slice=slice_name,
                expected_route=route,
                expected_family=family,
                declared_supported=supported,
            )
        )
    return fixtures


def deterministic_shadow_manifest() -> dict[str, Any]:
    compiler = MemoryQueryCompiler()
    rows = []
    for fixture in build_shadow_fixtures():
        plan = compiler.compile(
            fixture.query, reference_time=fixture.reference_time
        )
        family = infer_operator_family(plan)
        rows.append(
            {
                "case_id": fixture.case_id,
                "slice": fixture.slice,
                "query_sha256": hashlib.sha256(fixture.query.encode()).hexdigest(),
                "expected_route": fixture.expected_route,
                "expected_family": fixture.expected_family,
                "declared_supported": fixture.declared_supported,
                "deterministic_route": plan.mode,
                "deterministic_family": family,
                "deterministic_reason": plan.planner_trace.reason_code,
                "auxiliary_model_calls": plan.planner_trace.auxiliary_model_calls,
            }
        )
    supported = [row for row in rows if row["declared_supported"]]
    correct = sum(
        row["deterministic_route"] == row["expected_route"]
        and row["deterministic_family"] == row["expected_family"]
        for row in supported
    )
    unsafe = [row for row in rows if row["expected_route"] == "AMBIGUOUS"]
    return {
        "schema": "milai.dg17.semantic-shadow-manifest.v0.2",
        "classification": (
            "AUTHORED_OPENED_DEVELOPMENT_DIAGNOSTIC / SHADOW_EVALUATION_PLANE"
        ),
        "fixture_split": "AUTHORED_DEV_NO_HELDOUT_CLAIM",
        "case_count": len(rows),
        "supported_denominator": len(supported),
        "deterministic_correct": correct,
        "unsafe_generic_lookup_promotions": sum(
            row["deterministic_route"] != "AMBIGUOUS" for row in unsafe
        ),
        "product_semantic_assist_calls": 0,
        "rows": rows,
    }


def run_semantic_shadow(
    *,
    run_id: str,
    provider: StructuredSemanticProvider,
) -> dict[str, Any]:
    """Run Q3C shadow calls. This function never passes a hint to QueryPlanner."""

    compiler = MemoryQueryCompiler()
    service = SemanticHintShadowService(provider)
    rows: list[dict[str, Any]] = []
    for fixture in build_shadow_fixtures():
        deterministic = compiler.compile(
            fixture.query, reference_time=fixture.reference_time
        )
        deterministic_family = infer_operator_family(deterministic)
        try:
            receipt = service.generate(
                run_id=run_id,
                case_id=fixture.case_id,
                query=fixture.query,
                reference_time=fixture.reference_time,
            )
            hint = receipt.hint
            minimal_error = None
            minimal_payload = hint.model_dump_json()
            hint_route: str | None = hint.route
            hint_family: str | None = hint.operator_family
            minimal_receipt: dict[str, Any] | None = receipt.model_dump(mode="json")
        except SemanticHintError as exc:
            minimal_error = str(exc)
            minimal_payload = ""
            hint_route = None
            hint_family = None
            minimal_receipt = None
        full = provider.complete_structured(
            messages=_full_plan_messages(fixture.query),
            schema_name="semantic_full_plan_negative_control_v01",
            schema=_FULL_PLAN_SCHEMA,
            max_completion_tokens=512,
            seed=_negative_control_seed(run_id, fixture.case_id),
        )
        if full.provider_calls != 1 or full.automatic_retry_count != 0:
            raise SemanticHintError("FULL_PLAN_NEGATIVE_CONTROL_CALL_CEILING_VIOLATED")
        correct_hint = (
            fixture.declared_supported
            and hint_route == fixture.expected_route
            and hint_family == fixture.expected_family
        )
        wrong_promoted = (
            fixture.declared_supported
            and hint_route not in {None, "AMBIGUOUS"}
            and not correct_hint
        ) or (
            fixture.expected_route == "AMBIGUOUS"
            and hint_route not in {None, "AMBIGUOUS"}
        )
        rows.append(
            {
                "case_id": fixture.case_id,
                "slice": fixture.slice,
                "query_sha256": hashlib.sha256(fixture.query.encode()).hexdigest(),
                "expected": {
                    "route": fixture.expected_route,
                    "family": fixture.expected_family,
                    "declared_supported": fixture.declared_supported,
                },
                "deterministic": {
                    "route": deterministic.mode,
                    "family": deterministic_family,
                    "auxiliary_model_calls": 0,
                },
                "minimal_hint": {
                    "route": hint_route,
                    "family": hint_family,
                    "correct": correct_hint,
                    "wrong_promoted": wrong_promoted,
                    "typed_ambiguity": hint_route == "AMBIGUOUS",
                    "error": minimal_error,
                    "output_bytes": len(minimal_payload.encode()),
                    "receipt": minimal_receipt,
                },
                "full_plan_negative_control": {
                    "output_bytes": len(full.content.encode()),
                    "prompt_tokens": full.prompt_tokens,
                    "completion_tokens": full.completion_tokens,
                    "total_ms": full.total_ms,
                    "provider_calls": full.provider_calls,
                    "automatic_retry_count": full.automatic_retry_count,
                    "product_path_consumed": False,
                },
                "product_route_changed": False,
            }
        )
    return _aggregate(run_id, rows)


def _aggregate(run_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    supported = [row for row in rows if row["expected"]["declared_supported"]]
    minimal_success = [
        row for row in rows if row["minimal_hint"]["receipt"] is not None
    ]
    totals = [
        float(row["minimal_hint"]["receipt"]["timing"]["total_ms"])
        for row in minimal_success
    ]
    minimal_tokens = [
        int(row["minimal_hint"]["receipt"]["completion_tokens"])
        for row in minimal_success
    ]
    full_tokens = [
        int(row["full_plan_negative_control"]["completion_tokens"])
        for row in rows
    ]
    return {
        "schema": "milai.dg17.semantic-hint-shadow-report.v0.2",
        "classification": (
            "OPENED_DEVELOPMENT_MANUAL_PROXY / SHADOW_EVALUATION_PLANE"
        ),
        "fixture_split": "AUTHORED_DEV_NO_HELDOUT_CLAIM",
        "teacher_target_in_prompt": False,
        "deterministic_requirement_ids_in_prompt": False,
        "run_id": run_id,
        "status": "Q3C_SHADOW_CHARACTERIZED",
        "aggregate": {
            "case_count": len(rows),
            "supported_denominator": len(supported),
            "minimal_hint_correct": sum(
                row["minimal_hint"]["correct"] for row in supported
            ),
            "wrong_promoted_hint": sum(
                row["minimal_hint"]["wrong_promoted"] for row in rows
            ),
            "typed_ambiguity": sum(
                row["minimal_hint"]["typed_ambiguity"] for row in rows
            ),
            "schema_or_span_rejections": len(rows) - len(minimal_success),
            "minimal_hint_provider_p95_ms": _percentile(totals, 0.95),
            "minimal_completion_tokens_mean": (
                round(mean(minimal_tokens), 3) if minimal_tokens else None
            ),
            "full_plan_completion_tokens_mean": round(mean(full_tokens), 3),
            "full_to_minimal_completion_token_ratio": (
                round(mean(full_tokens) / mean(minimal_tokens), 3)
                if minimal_tokens and mean(minimal_tokens) > 0
                else None
            ),
            "minimal_generation_calls": len(rows),
            "full_plan_negative_control_calls": len(rows),
            "product_semantic_assist_calls": 0,
            "automatic_retries": 0,
            "product_route_changes": 0,
            "full_plan_product_consumption": 0,
            "model_final_answers_accepted": 0,
            "model_complete_decisions_accepted": 0,
        },
        "q3d_gate": {
            "eligible": False,
            "reason": "REQUIRES_MEASURED_UNSEEN_MEDIATOR_GAIN_AND_ZERO_WRONG_PROMOTIONS",
        },
        "rows": rows,
    }


def _full_plan_messages(query: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Shadow negative control only. Produce the supplied speculative full "
                "plan schema. Do not answer the query. This output is never executed."
            ),
        },
        {"role": "user", "content": query},
    ]


def _negative_control_seed(run_id: str, case_id: str) -> int:
    digest = hashlib.sha256(f"{run_id}\0{case_id}\0full-plan".encode()).hexdigest()
    return int(digest[:16], 16) & ((1 << 63) - 1)


def _reference_time(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("shadow reference time is naive")
        return value
    if not isinstance(value, str):
        raise TypeError("shadow reference time is invalid")
    try:
        return datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)
    except ValueError:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("shadow reference time is naive")
        return parsed


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * quantile + 0.5)))
    return round(ordered[index], 3)


__all__ = [
    "ShadowFixture",
    "build_shadow_fixtures",
    "deterministic_shadow_manifest",
    "run_semantic_shadow",
]

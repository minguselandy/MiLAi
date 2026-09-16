"""DG-17 Q4/Q5 deterministic product-vertical traces over opened development data."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from milai.application.appointment_composition import compose_evidence_range_count
from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.preference_composition import (
    synthesize_preference_evidence_view,
)
from milai.application.quantity_composition import compose_divide_evidence_values
from milai.application.query_ir_compat import infer_operator_family
from milai.application.query_operators import execute_query_operator
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
SPLIT = ROOT / "var/dg14/splits/public-deidentified-dev-v1/source-ids.json"
LABELS = ROOT / "evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json"
EXPECTED_INPUT_SHA256 = "7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412"
EXPECTED_SPLIT_SHA256 = "91f502f79850b3dfb952c7094bc632615f6f69d8e40b8350ef292681b03913d2"
Q4_CASE_IDS = (
    "gpt4_8279ba03",
    "9a707b82",
    "2a1811e2",
    "0bb5a684",
    "4dfccbf7",
    "gpt4_88806d6e",
    "88432d0a",
)
_EXPECTED_DISTANCE = {
    "2a1811e2": 21,
    "0bb5a684": 7,
    "4dfccbf7": 24,
}


class ProductVerticalError(RuntimeError):
    """A frozen opened-development input or Q4/Q5 trace contract drifted."""


def build_product_vertical_reports() -> tuple[dict[str, Any], dict[str, Any]]:
    cases, labels, identities = _load_frozen_inputs()
    planner = QueryPlanner()
    q4_cases = [_trace_q4_case(planner, cases[case_id], labels[case_id]) for case_id in Q4_CASE_IDS]
    q4_latencies = [float(case["latency_ms"]) for case in q4_cases]
    q4 = {
        "schema": "milai.dg17.q4-temporal-product-trace.v0.1",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "status": (
            "Q4_PRODUCT_VERTICAL_COMPLETE"
            if len(q4_cases) == 7
            and all(case["operator_expected"] for case in q4_cases)
            and not any(case["wrong_complete"] for case in q4_cases)
            else "Q4_PRODUCT_VERTICAL_PARTIAL"
        ),
        "input_identities": identities,
        "measurement_source_mode": "ORACLE_REQUIRED_EVIDENCE_FOR_OPERATOR_ISOLATION",
        "product_case_specific_branches": 0,
        "external_model_calls": 0,
        "external_experiments": "PAUSED_NOT_RUN",
        "gate": {
            "required_case_count": 7,
            "observed_case_count": len(q4_cases),
            "operator_expected": sum(bool(case["operator_expected"]) for case in q4_cases),
            "wrong_complete": sum(bool(case["wrong_complete"]) for case in q4_cases),
            "source_event_system_time_separation_traced": all(
                case["source_event_system_time_separation"] for case in q4_cases
            ),
            "bounded_range_contract": "CLOSED_OPEN_WITH_EVENT_INTERVAL_OVERLAP",
            "top_k_used_as_completeness": False,
        },
        "efficiency": _latency_summary(q4_latencies),
        "cases": q4_cases,
    }

    q5_traces = _trace_q5(planner, cases, labels)
    q5_latencies = [float(trace["latency_ms"]) for trace in q5_traces]
    q5 = {
        "schema": "milai.dg17.q5-multisession-product-trace.v0.1",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "status": (
            "Q5_PRODUCT_VERTICAL_COMPLETE"
            if all(trace["safety_expected"] for trace in q5_traces)
            else "Q5_PRODUCT_VERTICAL_PARTIAL"
        ),
        "input_identities": identities,
        "product_case_specific_branches": 0,
        "external_model_calls": 0,
        "external_experiments": "PAUSED_NOT_RUN",
        "gate": {
            "required_slot_across_sessions": True,
            "same_entity_same_purpose_join": True,
            "bounded_count_unknown_time_abstains": True,
            "preference_authority": "EVIDENCE_ONLY",
            "preference_view_class": "DERIVED_VIEW",
            "preference_canonical_promotion": 0,
            "wrong_complete": sum(bool(trace["wrong_complete"]) for trace in q5_traces),
        },
        "efficiency": _latency_summary(q5_latencies),
        "traces": q5_traces,
    }
    return q4, q5


def _trace_q4_case(
    planner: QueryPlanner,
    case: Mapping[str, Any],
    label: Mapping[str, Any],
) -> dict[str, Any]:
    reference = _parsed_dataset_time(str(case["question_date"]))
    request = RetrievalRequest(
        route="L1",
        query=str(case["question"]),
        as_of=reference,
        system_as_of=reference,
    )
    compile_ms, plan = _timed(planner.plan, request)
    evidence = _oracle_evidence(case, label)
    semantic_started = perf_counter()
    spans = project_evidence_spans(evidence)
    interpretations = interpret_evidence_spans(spans)
    assert plan.memory_query_ir is not None
    bindings = bind_requirements(plan.memory_query_ir.requirements, interpretations, spans)
    semantic_ms = (perf_counter() - semantic_started) * 1_000
    execute_started = perf_counter()
    if plan.operator == "TEMPORAL_COUNT_DISTINCT":
        result = compose_evidence_range_count(plan, _complete_scan(evidence))
    else:
        result = execute_query_operator(plan, evidence)
    execute_ms = (perf_counter() - execute_started) * 1_000
    if result is None:
        raise ProductVerticalError(f"Q4 case {case['source_id']} produced no typed result")
    expected = _q4_result_expected(str(case["source_id"]), label, result)
    completion_claimed = result.get("status") in {"OK", "COMPLETE"}
    event_interpretations = [
        interpretation for interpretation in interpretations if interpretation.kind == "EVENT"
    ]
    time_bases = sorted({item.time_basis for item in event_interpretations})
    separated = all(
        span.provenance.get("system_timestamp") is not None and span.source_timestamp is not None
        for span in spans
    ) and all(
        item.time_basis != "SOURCE_OBSERVED_TIME" or item.event_time is None
        for item in event_interpretations
    )
    return {
        "case_id": case["source_id"],
        "category": case["category"],
        "question": case["question"],
        "gold_operator": label["gold_ir"]["operator"],
        "operator_family": infer_operator_family(plan.memory_query_ir),
        "execution_operator": plan.operator,
        "time_axis": (
            plan.memory_query_ir.constraints.normalized_temporal.time_axis
            if plan.memory_query_ir.constraints.normalized_temporal is not None
            else None
        ),
        "required_slots": [
            requirement.slot_id for requirement in plan.memory_query_ir.requirements
        ],
        "source_turn_count": len(evidence),
        "span_count": len(spans),
        "event_interpretation_count": len(event_interpretations),
        "matched_binding_count": sum(binding.status == "MATCH" for binding in bindings),
        "matched_slots": sorted(
            {binding.requirement_id for binding in bindings if binding.status == "MATCH"}
        ),
        "time_bases": time_bases,
        "source_event_system_time_separation": separated,
        "result": _safe_result(result),
        "operator_expected": expected,
        "wrong_complete": completion_claimed and not expected,
        "latency_ms": round(compile_ms + semantic_ms + execute_ms, 6),
        "latency_breakdown_ms": {
            "compile": round(compile_ms, 6),
            "span_interpret_bind": round(semantic_ms, 6),
            "execute": round(execute_ms, 6),
        },
        "hidden_model_calls": 0,
        "canonical_mutation": False,
    }


def _trace_q5(
    planner: QueryPlanner,
    cases: Mapping[str, Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    divide_plan = planner.plan(
        RetrievalRequest(
            route="L1",
            query="How much did I spend on each coffee mug for my coworkers?",
        )
    )
    divided_evidence = [
        _synthetic_evidence("price", "user: I spent $60 on coffee mugs for my coworkers."),
        _synthetic_evidence("count", "user: I bought 5 coffee mugs for my coworkers."),
    ]
    started = perf_counter()
    divided = compose_divide_evidence_values(divide_plan, divided_evidence)
    latency = (perf_counter() - started) * 1_000
    assert divided is not None
    traces.append(
        {
            "trace_id": "cross-session-required-slots",
            "kind": divided["kind"],
            "status": divided["status"],
            "value": divided["value"],
            "required_slots": divided["completeness"]["required_slots"],
            "filled_slots": divided["completeness"]["filled_slots"],
            "source_session_count": 2,
            "join": divided["trace"]["join"],
            "safety_expected": divided["status"] == "COMPLETE" and divided["value"] == 12,
            "wrong_complete": False,
            "latency_ms": round(latency, 6),
            "hidden_model_calls": divided["hidden_model_calls"],
            "canonical_mutation": divided["canonical_mutation"],
        }
    )

    incompatible = [
        divided_evidence[0],
        _synthetic_evidence("wrong-purpose", "user: I bought 5 coffee mugs for my family."),
    ]
    started = perf_counter()
    rejected = compose_divide_evidence_values(divide_plan, incompatible)
    latency = (perf_counter() - started) * 1_000
    assert rejected is not None
    traces.append(
        {
            "trace_id": "same-purpose-join-rejection",
            "kind": rejected["kind"],
            "status": rejected["status"],
            "reason": rejected["reason"],
            "safety_expected": rejected["status"] == "PARTIAL"
            and rejected["reason"] == "JOIN_PURPOSE_INCOMPATIBLE",
            "wrong_complete": rejected["status"] == "COMPLETE",
            "latency_ms": round(latency, 6),
            "hidden_model_calls": rejected["hidden_model_calls"],
            "canonical_mutation": rejected["canonical_mutation"],
        }
    )

    baby_case = cases["2e6d26dc"]
    baby_reference = _parsed_dataset_time(str(baby_case["question_date"]))
    baby_plan = planner.plan(
        RetrievalRequest(
            route="L1",
            query=str(baby_case["question"]),
            as_of=baby_reference,
            system_as_of=baby_reference,
        )
    )
    baby_evidence = _oracle_evidence(baby_case, labels["2e6d26dc"])
    started = perf_counter()
    baby_result = compose_evidence_range_count(baby_plan, _complete_scan(baby_evidence))
    latency = (perf_counter() - started) * 1_000
    assert baby_result is not None
    traces.append(
        {
            "trace_id": "bounded-count-unknown-event-time",
            "case_id": "2e6d26dc",
            "kind": baby_result["kind"],
            "status": baby_result["status"],
            "reason": baby_result.get("reason"),
            "source_session_count": len(baby_evidence),
            "bounded_scan_complete": baby_result["completeness"]["bounded_scan_complete"],
            "safety_expected": baby_result["status"] == "PARTIAL"
            and baby_result.get("reason") == "EVENT_TIME_UNRESOLVED",
            "wrong_complete": baby_result["status"] == "COMPLETE",
            "latency_ms": round(latency, 6),
            "hidden_model_calls": baby_result["hidden_model_calls"],
            "canonical_mutation": baby_result["canonical_mutation"],
        }
    )

    preference_case = cases["a89d7624"]
    preference_reference = _parsed_dataset_time(str(preference_case["question_date"]))
    preference_plan = planner.plan(
        RetrievalRequest(
            route="L1",
            query=str(preference_case["question"]),
            as_of=preference_reference,
            system_as_of=preference_reference,
        )
    )
    preference_evidence = _oracle_evidence(preference_case, labels["a89d7624"])
    started = perf_counter()
    preference = synthesize_preference_evidence_view(preference_plan, preference_evidence)
    latency = (perf_counter() - started) * 1_000
    assert preference is not None
    preference_safe = (
        preference["authority_class"] == "EVIDENCE_ONLY"
        and preference["view_class"] == "DERIVED_VIEW"
        and preference["canonical"] is False
        and preference["canonical_mutation"] is False
        and preference["completeness"]["currentness_proven"] is False
    )
    traces.append(
        {
            "trace_id": "preference-evidence-derived-view",
            "case_id": "a89d7624",
            "kind": preference["kind"],
            "status": preference["status"],
            "reason": preference["reason"],
            "authority_class": preference["authority_class"],
            "view_class": preference["view_class"],
            "canonical": preference["canonical"],
            "currentness_proven": preference["completeness"]["currentness_proven"],
            "signal_count": len(preference["value"]),
            "safety_expected": preference_safe,
            "wrong_complete": preference["status"] == "COMPLETE",
            "latency_ms": round(latency, 6),
            "hidden_model_calls": preference["hidden_model_calls"],
            "canonical_mutation": preference["canonical_mutation"],
        }
    )
    return traces


def _q4_result_expected(
    case_id: str,
    label: Mapping[str, Any],
    result: Mapping[str, Any],
) -> bool:
    if result.get("status") not in {"OK", "COMPLETE"}:
        return False
    if case_id in _EXPECTED_DISTANCE:
        return result.get("value") == _EXPECTED_DISTANCE[case_id]
    if case_id == "gpt4_88806d6e":
        value = result.get("value")
        return isinstance(value, Mapping) and "tom" in str(value.get("selected", "")).casefold()
    if case_id == "88432d0a":
        return result.get("value") == len(label["atoms"])
    value = result.get("value")
    selected = str(value.get("selected", "")) if isinstance(value, Mapping) else ""
    return any(
        str(atom["span"]["text"]).casefold() in selected.casefold() for atom in label["atoms"]
    )


def _safe_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in (
            "status",
            "kind",
            "operator",
            "value",
            "unit",
            "reason",
            "completeness",
            "count_trace",
            "hidden_model_calls",
            "canonical_mutation",
        )
        if key in result
    }


def _complete_scan(evidence: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "status": "COMPLETE",
        "source_partition_closed": True,
        "projection_watermark_covered": True,
        "projection_watermark": len(evidence),
        "target_watermark": len(evidence),
        "source_count": len(evidence),
        "projected_count": len(evidence),
        "unreadable_evidence_count": 0,
        "items": list(evidence),
    }


def _synthetic_evidence(evidence_id: str, content: str) -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/{evidence_id}/turn/0",
        "session_id": evidence_id,
        "observed_at": "2026-08-27T00:00:00+00:00",
        "captured_at": "2026-08-27T00:00:01+00:00",
        "content": content,
    }


def _oracle_evidence(case: Mapping[str, Any], label: Mapping[str, Any]) -> list[dict[str, Any]]:
    sessions = case["sessions"]
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for atom in label["atoms"]:
        session_ordinal = int(atom["session_ordinal"])
        turn_ordinal = int(atom["turn_ordinal"])
        identity = (session_ordinal, turn_ordinal)
        if identity in seen:
            continue
        seen.add(identity)
        session = sessions[session_ordinal]
        turn = session["turns"][turn_ordinal]
        observed_at = _parsed_dataset_time(str(session["observed_at"]))
        source_ref = str(atom["source_turn_ref"])
        evidence.append(
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "opened-dev-" + hashlib.sha256(source_ref.encode()).hexdigest()[:24],
                "source_ref": source_ref,
                "session_id": str(session["session_id"]),
                "observed_at": observed_at.isoformat(),
                "captured_at": (observed_at + timedelta(seconds=1)).isoformat(),
                "content": f"{turn['role']}: {turn['content']}",
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
            }
        )
    return evidence


def _load_frozen_inputs() -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
    dict[str, str],
]:
    identities = {
        "label_free_inputs_sha256": _sha256_file(INPUTS),
        "public_dev_split_sha256": _sha256_file(SPLIT),
        "answer_bearing_labels_sha256": _sha256_file(LABELS),
    }
    if identities["label_free_inputs_sha256"] != EXPECTED_INPUT_SHA256:
        raise ProductVerticalError("frozen LongMemEval input identity drifted")
    if identities["public_dev_split_sha256"] != EXPECTED_SPLIT_SHA256:
        raise ProductVerticalError("frozen public-dev split identity drifted")
    inputs = _object(INPUTS)
    split = _object(SPLIT)
    labels = _object(LABELS)
    source_ids = [str(value) for value in split["source_ids"][:10]]
    cases = {
        str(case["source_id"]): case
        for case in inputs["cases"]
        if str(case["source_id"]) in source_ids
    }
    indexed_labels = {str(label["case_id"]): label for label in labels["cases"]}
    if len(cases) != 10 or tuple(indexed_labels) != tuple(labels["case_ids"]):
        raise ProductVerticalError("opened-development denominator drifted")
    return cases, indexed_labels, identities


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProductVerticalError(f"JSON object required: {path}")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parsed_dataset_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)


def _timed(function: Callable[..., Any], *args: Any) -> tuple[float, Any]:
    started = perf_counter()
    value = function(*args)
    return (perf_counter() - started) * 1_000, value


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _latency_summary(values: Sequence[float]) -> dict[str, Any]:
    return {
        "definition": "in-process deterministic compile + semantic pipeline + operator",
        "sample_count": len(values),
        "mean_ms": round(mean(values), 6),
        "p50_ms": round(_percentile(values, 0.50), 6),
        "p95_ms": round(_percentile(values, 0.95), 6),
        "max_ms": round(max(values), 6),
        "development_gate_ms": 500,
        "development_gate_passed": _percentile(values, 0.95) <= 500,
        "external_model_time_included": False,
    }


__all__ = ["ProductVerticalError", "build_product_vertical_reports"]

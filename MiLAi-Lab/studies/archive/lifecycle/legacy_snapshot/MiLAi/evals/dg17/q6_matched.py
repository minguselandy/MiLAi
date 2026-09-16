"""Pure scoring and release-gate helpers for DG-17 Q6 matched confirmation."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any

from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.domain.retrieval import QueryPlan

from evals.dg15.milai_mcp_adapter import compact_lme_source_ref
from evals.paper.scorers.longmemeval import score_answer

METHOD_ID = "DG17-DETERMINISTIC-ONLY"
BASELINE_CORRECT_2048 = frozenset({"9a707b82", "a82c026e"})
_EXPECTED_DISTANCE = {"2a1811e2": 21, "0bb5a684": 7, "4dfccbf7": 24}


class Q6MatchedError(RuntimeError):
    """A Q6 product record, scoring label, or denominator drifted."""


def score_matched_records(
    records: Sequence[Mapping[str, Any]],
    *,
    cases: Sequence[Any],
    labels: Mapping[str, Mapping[str, Any]],
    scoring_labels: Mapping[str, Mapping[str, Any]],
    plans: Mapping[str, QueryPlan],
) -> list[dict[str, Any]]:
    expected = {(str(case.case_id), budget) for case in cases for budget in (512, 2048)}
    observed = [
        (str(record.get("case_id")), int(record.get("token_budget", -1)))
        for record in records
    ]
    if (
        len(cases) != 10
        or len(labels) != 10
        or len(scoring_labels) != 10
        or len(records) != 20
        or set(observed) != expected
        or len(set(observed)) != len(observed)
    ):
        raise Q6MatchedError("Q6 matched record denominator drifted")

    scored: list[dict[str, Any]] = []
    for record in records:
        case_id = str(record["case_id"])
        scoring = scoring_labels[case_id]
        label = labels[case_id]
        answers = scoring.get("answers")
        answer_sessions = scoring.get("answer_session_ids")
        retrieval_trace = record.get("retrieval_trace")
        if (
            not isinstance(answers, list)
            or not answers
            or not isinstance(answer_sessions, list)
            or not answer_sessions
            or not isinstance(retrieval_trace, list)
        ):
            raise Q6MatchedError("Q6 scoring input is malformed")
        answer_score = score_answer(
            str(record["answer"]), [str(answer) for answer in answers]
        )
        retrieval_score = _score_retrieval_fixed_ideal(
            retrieval_trace, [str(session) for session in answer_sessions]
        )
        semantic = _semantic_measurement(record, label, plans[case_id])
        operator = _operator_measurement(
            case_id,
            label,
            record.get("derived_result"),
            terminal_sufficiency=record.get("sufficiency_decision"),
            requirements_complete=(
                len(semantic["retrieved_atom_ids"])
                == int(semantic["required_atom_count"])
            ),
        )
        query_ms = _number(record, "query_latency_ms")
        provider = record.get("provider")
        if not isinstance(provider, Mapping):
            raise Q6MatchedError("Q6 provider receipt is missing")
        answer_path_ms = (
            query_ms
            + _number(provider, "tokenize_latency_ms")
            + _number(provider, "provider_latency_ms")
        )
        scored.append(
            {
                **dict(record),
                "query_class": label["gold_ir"]["query_class"],
                "gold_operator": label["gold_ir"]["operator"],
                "answer_score": answer_score,
                "retrieval_score": retrieval_score,
                "answer_path_latency_ms": round(answer_path_ms, 6),
                "strict_em_boundary_candidate": (
                    int(answer_score["exact_match"]) == 0
                    and float(answer_score["normalized_f1"]) >= 0.9
                ),
                **semantic,
                **operator,
            }
        )
    return sorted(
        scored,
        key=lambda row: (int(row["token_budget"]), str(row["case_id"])),
    )


def summarize_matched_records(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for budget in (512, 2048):
        cells = [row for row in records if row.get("token_budget") == budget]
        if len(cells) != 10:
            raise Q6MatchedError("Q6 summary denominator drifted")
        summaries[str(budget)] = _summary(cells)
        grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for cell in cells:
            grouped[str(cell["query_class"])].append(cell)
        summaries[str(budget)]["by_query_class"] = {
            name: _summary(values) for name, values in sorted(grouped.items())
        }
    return summaries


def evaluate_development_gate(
    summaries: Mapping[str, Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    main = summaries["2048"]
    constrained = summaries["512"]
    preserved = {
        str(row["case_id"])
        for row in records
        if row.get("token_budget") == 2048
        and int(row["answer_score"]["exact_match"]) == 1
        and row.get("case_id") in BASELINE_CORRECT_2048
    }
    checks = {
        "exact_match_at_least_5_of_10": int(main["exact_match_count"]) >= 5,
        "normalized_f1_at_least_0_50": float(main["normalized_f1"]) >= 0.50,
        "required_evidence_set_coverage_at_least_0_80": (
            float(main["required_evidence_set_coverage"]) >= 0.80
        ),
        "wrong_complete_zero": int(main["wrong_complete_count"]) == 0,
        "current_two_correct_cases_preserved": preserved == BASELINE_CORRECT_2048,
        "constrained_f1_not_below_dg16": (
            float(constrained["normalized_f1"]) >= 0.119417476
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "PARTIAL",
        "checks": checks,
        "baseline_correct_2048": sorted(BASELINE_CORRECT_2048),
        "preserved_baseline_correct_2048": sorted(preserved),
        "thresholds_changed": False,
    }


def _semantic_measurement(
    record: Mapping[str, Any],
    label: Mapping[str, Any],
    plan: QueryPlan,
) -> dict[str, Any]:
    context = record.get("context")
    if not isinstance(context, str):
        raise Q6MatchedError("Q6 record lacks Runtime MemoryContext")
    items = record.get("evidence_items")
    if not isinstance(items, list) or any(
        not isinstance(item, Mapping) for item in items
    ):
        raise Q6MatchedError("Q6 record lacks acquired Evidence items")
    evidence = [dict(item) for item in items]
    spans = project_evidence_spans(evidence)
    interpretations = interpret_evidence_spans(spans)
    if plan.memory_query_ir is None:
        raise Q6MatchedError("Q6 plan lacks MemoryQueryIR")
    bindings = bind_requirements(
        plan.memory_query_ir.requirements, interpretations, spans
    )
    span_by_id = {span.span_id: span for span in spans}
    interpretation_by_id = {
        interpretation.interpretation_id: interpretation
        for interpretation in interpretations
    }

    expected_span_keys = {
        (
            str(atom["source_turn_ref"]),
            _normalized(str(atom["span"]["text"])),
        )
        for atom in label["atoms"]
    }
    expected_atom_keys = {
        str(atom["atom_id"]): (
            str(atom["source_turn_ref"]),
            _normalized(str(atom["span"]["text"])),
        )
        for atom in label["atoms"]
    }
    retrieved_atom_ids = [
        atom_id
        for atom_id, expected in expected_atom_keys.items()
        if any(_span_matches(span, expected) for span in spans)
    ]
    span_hits = {
        expected
        for expected in expected_span_keys
        if any(_span_matches(span, expected) for span in spans)
    }
    expected_source_turns = {source_ref for source_ref, _text in expected_span_keys}
    hit_source_turns = {source_ref for source_ref, _text in span_hits}
    expected_bindings = [
        (
            str(atom["slot"]),
            str(atom["source_turn_ref"]),
            _normalized(str(atom["span"]["text"])),
        )
        for atom in label["atoms"]
    ]
    matched_bindings = [binding for binding in bindings if binding.status == "MATCH"]
    true_bindings = 0
    for binding in matched_bindings:
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        span = (
            span_by_id.get(interpretation.span_id)
            if interpretation is not None
            else None
        )
        if span is not None and any(
            binding.requirement_id == slot and _span_matches(span, (source_ref, text))
            for slot, source_ref, text in expected_bindings
        ):
            true_bindings += 1
    return {
        "retrieved_atom_ids": retrieved_atom_ids,
        "required_atom_count": len(label["atoms"]),
        "answer_bearing_span_hit_count": len(span_hits),
        "answer_bearing_span_count": len(expected_span_keys),
        "answer_bearing_span_recall": round(
            len(span_hits) / len(expected_span_keys), 9
        ),
        "answer_bearing_source_turn_hit_count": len(hit_source_turns),
        "answer_bearing_source_turn_count": len(expected_source_turns),
        "answer_bearing_source_turn_recall": round(
            len(hit_source_turns) / len(expected_source_turns), 9
        ),
        "coverage_identity_policy": "SOURCE_TURN_REF_PLUS_NORMALIZED_SPAN_TEXT",
        "requirement_binding_true_count": true_bindings,
        "requirement_binding_predicted_count": len(matched_bindings),
        "requirement_binding_precision": (
            round(true_bindings / len(matched_bindings), 9)
            if matched_bindings
            else None
        ),
        "predicted_evidence_span_count": len(spans),
        "predicted_interpretation_count": len(interpretations),
        "predicted_match_binding_count": len(matched_bindings),
    }


def _operator_measurement(
    case_id: str,
    label: Mapping[str, Any],
    raw_result: object,
    *,
    terminal_sufficiency: object = None,
    requirements_complete: bool = True,
) -> dict[str, Any]:
    operator = str(label["gold_ir"]["operator"])
    terminal_complete = (
        isinstance(terminal_sufficiency, Mapping)
        and terminal_sufficiency.get("status") == "COMPLETE"
    )
    if operator == "LOOKUP":
        return {
            "operator_applicable": False,
            "operator_execution_correct": None,
            "operator_safety_correct": not (
                terminal_complete and not requirements_complete
            ),
            "terminal_sufficiency_complete": terminal_complete,
            "wrong_complete": terminal_complete and not requirements_complete,
        }
    result = raw_result if isinstance(raw_result, Mapping) else {}
    status = result.get("status")
    value = result.get("value")
    correct = False
    safety = False
    if case_id in _EXPECTED_DISTANCE:
        correct = status in {"OK", "COMPLETE"} and value == _EXPECTED_DISTANCE[case_id]
        safety = correct or status in {"PARTIAL", "ABSTAINED"}
    elif case_id == "gpt4_88806d6e":
        selected = value.get("selected") if isinstance(value, Mapping) else None
        correct = status in {"OK", "COMPLETE"} and "tom" in str(selected).casefold()
        safety = correct or status in {"PARTIAL", "ABSTAINED"}
    elif case_id in {"gpt4_8279ba03", "9a707b82"}:
        selected = value.get("selected") if isinstance(value, Mapping) else None
        correct = status in {"OK", "COMPLETE"} and any(
            _normalized(str(atom["span"]["text"])) in _normalized(str(selected))
            for atom in label["atoms"]
        )
        safety = correct or status in {"PARTIAL", "ABSTAINED"}
    elif case_id == "88432d0a":
        correct = status == "COMPLETE" and value == len(label["atoms"])
        safety = correct or status in {"PARTIAL", "ABSTAINED"}
    elif case_id == "2e6d26dc":
        correct = status == "COMPLETE" and value == 5
        safety = correct or (
            status == "PARTIAL" and result.get("reason") == "EVENT_TIME_UNRESOLVED"
        )
    elif case_id == "a89d7624":
        correct = False
        safety = (
            result.get("kind") == "PREFERENCE_EVIDENCE_VIEW"
            and result.get("authority_class") == "EVIDENCE_ONLY"
            and result.get("view_class") == "DERIVED_VIEW"
            and result.get("canonical") is False
            and result.get("canonical_mutation") is False
        )
    complete = status in {"OK", "COMPLETE"} or terminal_complete
    wrong_complete = complete and (not correct or not requirements_complete)
    return {
        "operator_applicable": True,
        "operator_execution_correct": correct,
        "operator_safety_correct": safety and not wrong_complete,
        "terminal_sufficiency_complete": terminal_complete,
        "wrong_complete": wrong_complete,
    }


def _summary(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not cells:
        raise Q6MatchedError("cannot summarize empty Q6 cells")
    atom_hits = sum(len(cell["retrieved_atom_ids"]) for cell in cells)
    atom_total = sum(int(cell["required_atom_count"]) for cell in cells)
    span_hits = sum(int(cell["answer_bearing_span_hit_count"]) for cell in cells)
    span_total = sum(int(cell["answer_bearing_span_count"]) for cell in cells)
    source_turn_hits = sum(
        int(cell["answer_bearing_source_turn_hit_count"]) for cell in cells
    )
    source_turn_total = sum(
        int(cell["answer_bearing_source_turn_count"]) for cell in cells
    )
    binding_true = sum(int(cell["requirement_binding_true_count"]) for cell in cells)
    binding_predicted = sum(
        int(cell["requirement_binding_predicted_count"]) for cell in cells
    )
    applicable = [cell for cell in cells if cell["operator_applicable"]]
    answer_path = [float(cell["answer_path_latency_ms"]) for cell in cells]
    return {
        "case_count": len(cells),
        "exact_match_count": sum(
            int(cell["answer_score"]["exact_match"]) for cell in cells
        ),
        "normalized_f1": round(
            mean(float(cell["answer_score"]["normalized_f1"]) for cell in cells), 9
        ),
        "answer_session_coverage": round(
            mean(
                float(cell["retrieval_score"]["relevant_coverage_at_k"])
                for cell in cells
            ),
            9,
        ),
        "required_evidence_set_coverage": round(atom_hits / atom_total, 9),
        "required_evidence_atom_denominator": atom_total,
        "answer_bearing_span_recall": round(span_hits / span_total, 9),
        "answer_bearing_unique_span_denominator": span_total,
        "answer_bearing_source_turn_recall": round(
            source_turn_hits / source_turn_total, 9
        ),
        "answer_bearing_source_turn_denominator": source_turn_total,
        "coverage_identity_policy": "SOURCE_TURN_REF_PLUS_NORMALIZED_SPAN_TEXT",
        "requirement_binding_precision": (
            round(binding_true / binding_predicted, 9) if binding_predicted else None
        ),
        "operator_execution_accuracy": (
            round(
                sum(bool(cell["operator_execution_correct"]) for cell in applicable)
                / len(applicable),
                9,
            )
            if applicable
            else None
        ),
        "operator_safety_accuracy": (
            round(
                sum(bool(cell["operator_safety_correct"]) for cell in applicable)
                / len(applicable),
                9,
            )
            if applicable
            else None
        ),
        "operator_denominator": len(applicable),
        "wrong_complete_count": sum(bool(cell["wrong_complete"]) for cell in cells),
        "strict_em_boundary_candidate_count": sum(
            bool(cell["strict_em_boundary_candidate"]) for cell in cells
        ),
        "query_latency_ms_mean": round(
            mean(float(cell["query_latency_ms"]) for cell in cells), 6
        ),
        "query_latency_ms_p95": round(
            _percentile([float(cell["query_latency_ms"]) for cell in cells], 0.95), 6
        ),
        "answer_path_latency_ms_mean": round(mean(answer_path), 6),
        "quality_per_second": round(
            mean(float(cell["answer_score"]["normalized_f1"]) for cell in cells)
            / (mean(answer_path) / 1_000),
            9,
        ),
        "reader_calls": len(cells),
        "semantic_assist_calls": 0,
        "automatic_retries": 0,
    }


def _span_matches(span: Any, expected: tuple[str, str]) -> bool:
    source_ref, text = expected
    return compact_lme_source_ref(
        str(span.source_turn_ref)
    ) == source_ref and text in _normalized(str(span.text))


def _score_retrieval_fixed_ideal(
    trace: Sequence[Mapping[str, Any]], relevant_session_ids: Sequence[str]
) -> dict[str, float | int | str]:
    """Score DG17 retrieval without a prediction-length-dependent ideal DCG."""

    relevant = set(relevant_session_ids)
    ranked = [
        value for item in trace if (value := _trace_session_id(item)) is not None
    ]
    unique_ranked = list(dict.fromkeys(ranked))
    hits = relevant.intersection(unique_ranked)
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, session_id in enumerate(unique_ranked)
        if session_id in relevant
    )
    ideal = sum(
        1.0 / math.log2(index + 2) for index in range(len(relevant))
    )
    return {
        "hit_at_k": int(bool(hits)),
        "ndcg_at_k": round(dcg / ideal, 9) if ideal else 0.0,
        "relevant_coverage_at_k": (
            round(len(hits) / len(relevant), 9) if relevant else 0.0
        ),
        "retrieved_k": len(unique_ranked),
        "ndcg_ideal_relevant_count": len(relevant),
        "ndcg_denominator_policy": "ALL_RELEVANT_SESSIONS_FIXED_FROM_LABELS",
    }


def _trace_session_id(item: Mapping[str, Any]) -> str | None:
    explicit = item.get("session_id")
    if isinstance(explicit, str):
        return explicit
    source = item.get("source_id")
    if not isinstance(source, str):
        return None
    return re.sub(r"(?::\d+|_\d+)$", "", source)


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _number(value: Mapping[str, Any], key: str) -> float:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise Q6MatchedError(f"Q6 numeric field is missing: {key}")
    return float(raw)


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


__all__ = [
    "BASELINE_CORRECT_2048",
    "METHOD_ID",
    "Q6MatchedError",
    "evaluate_development_gate",
    "score_matched_records",
    "summarize_matched_records",
]

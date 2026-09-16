"""Explicit DG-17 transition from MemoryQueryIR v0.1 into executable v0.2."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import JsonValue

from milai.application.lexical_cues import compile_lexical_cue_sets
from milai.domain.memory_query_ir import MemoryQueryIR as MemoryQueryIRV01
from milai.domain.retrieval import QueryOperator
from milai.domain.semantic_query import (
    EvidenceRequirementV02,
    MemoryAnswerShape,
    MemoryPlannerTrace,
    MemoryQueryConstraints,
    MemoryQueryIRV02,
    MemoryQueryStep,
    NormalizedTemporalConstraint,
    QueryCueSpan,
    RequirementCardinalityV02,
    RequirementSemanticRolesV02,
)

_OPERATOR_FAMILY = {
    "LOOKUP": "LOOKUP",
    "STATE_AT_TIME": "LOOKUP",
    "TEMPORAL_FILTER": "TEMPORAL_FILTER",
    "TEMPORAL_ORDER": "TEMPORAL_ORDER",
    "TEMPORAL_DISTANCE": "TEMPORAL_DISTANCE",
    "COUNT_DISTINCT": "COUNT",
    "SUM_VALUES": "SUM",
    "DIVIDE_VALUES": "DIVIDE",
    "COMPARE_VALUES": "COMPARE",
    "MULTI_EVIDENCE_JOIN": "MULTI_JOIN",
    "PREFERENCE_RESOLVE": "PREFERENCE_RESOLVE",
    "VERSION_DIFF": "WHY_CHANGE",
}
_MODE = {
    "STATE": "STATE",
    "EPISODIC": "EVIDENCE",
    "TEMPORAL": "COMPOSE",
    "AGGREGATION": "COMPOSE",
    "PREFERENCE": "COMPOSE",
    "EXPLANATION": "COMPOSE",
}
_COMPLETENESS = {
    "TOP_K_ACCEPTABLE": "TOP_K_ACCEPTABLE",
    "ALL_REQUIRED_SLOTS": "ALL_REQUIRED_BINDINGS",
    "ALL_MATCHES_IN_RANGE": "ALL_MATCHES_IN_RANGE",
    "COMPLETE_VERSION_CHAIN": "COMPLETE_VERSION_CHAIN",
    "SUPPORT_THRESHOLD": "SUPPORT_THRESHOLD",
}


def translate_memory_query_ir_v01(
    legacy: MemoryQueryIRV01,
    *,
    query: str,
    scope: Mapping[str, JsonValue] | None = None,
) -> MemoryQueryIRV02:
    """Translate the precursor once; no product executor consumes v0.1 directly."""

    return synthesize_memory_query_ir_v02(
        legacy,
        query=query,
        scope=scope,
        compiler_version="v01-to-v02-compat-v1",
        reason_prefix="V01_COMPAT",
    )


def synthesize_memory_query_ir_v02(
    semantic_spec: MemoryQueryIRV01,
    *,
    query: str,
    scope: Mapping[str, JsonValue] | None = None,
    compiler_version: str = "deterministic-v02-native-synthesis-v1",
    reason_prefix: str = "NATIVE_V02",
) -> MemoryQueryIRV02:
    """Build executable V02 from the compiler's internal semantic specification.

    The public V01 translator delegates here for artifact compatibility; the
    product compiler calls this native synthesis entry directly.
    """

    legacy = semantic_spec
    if legacy.parser.kind == "AMBIGUOUS":
        return MemoryQueryIRV02(
            mode="AMBIGUOUS",
            answer_shape=_answer_shape(legacy.answer_type),
            constraints=MemoryQueryConstraints(scope=dict(scope) if scope else None),
            requirements=[],
            steps=[],
            completeness="UNSTRUCTURED_EVIDENCE_ALLOWED",
            planner_trace=MemoryPlannerTrace(
                source="AMBIGUOUS",
                compiler_version=compiler_version,
                auxiliary_model_calls=0,
                reason_code=legacy.parser.reason_code,
            ),
        )

    operator_family = _OPERATOR_FAMILY[legacy.operator]
    normalized_temporal = _translate_temporal(legacy, query)
    requirements = [
        EvidenceRequirementV02(
            slot_id=requirement.slot_id,
            interpretation_kind=requirement.atom_type,
            entity_constraints=list(requirement.entity_constraints),
            predicate_constraints=list(requirement.predicate_constraints),
            temporal_constraints=(
                _translate_requirement_temporal(requirement.temporal_constraints, query)
                if requirement.temporal_constraints is not None
                else None
            ),
            semantic_roles=RequirementSemanticRolesV02(
                actor=(
                    "USER"
                    if "user_fact" in requirement.predicate_constraints
                    or (
                        (
                            requirement.atom_type == "EVENT"
                            or requirement.slot_id == "LOOKUP_ANSWER"
                        )
                        and re.search(r"\b(?:i|my|we|our)\b", query, re.IGNORECASE)
                    )
                    else None
                )
            ),
            value_type=requirement.value_type,
            cardinality=RequirementCardinalityV02(
                minimum=requirement.cardinality.minimum,
                maximum=requirement.cardinality.maximum,
                distinct=requirement.cardinality.distinct,
            ),
            join_key=requirement.join_key,
            required=requirement.required,
        )
        for requirement in legacy.requirements
    ]
    steps = _steps(
        operator_family,
        requirements,
        normalized_temporal,
        reference_time=legacy.temporal.reference_time,
        distance_unit=_legacy_distance_unit(legacy),
    )
    temporal_spans = (
        list(normalized_temporal.normalized_from) if normalized_temporal is not None else []
    )
    return MemoryQueryIRV02.model_validate(
        {
            "mode": _MODE[legacy.query_class],
            "answer_shape": _answer_shape(legacy.answer_type),
            "constraints": MemoryQueryConstraints(
                cue_spans=_entity_cue_spans(query, legacy.entities),
                temporal_expressions=temporal_spans,
                normalized_temporal=normalized_temporal,
                scope=dict(scope) if scope else None,
            ),
            "requirements": requirements,
            "lexical_cues": compile_lexical_cue_sets(requirements),
            "steps": steps,
            "completeness": _COMPLETENESS[legacy.completeness],
            "planner_trace": MemoryPlannerTrace(
                source="DETERMINISTIC",
                compiler_version=compiler_version,
                auxiliary_model_calls=0,
                reason_code=f"{reason_prefix}:{legacy.parser.reason_code}",
            ),
        }
    )


def infer_operator_family(query_ir: MemoryQueryIRV02) -> str | None:
    for step in query_ir.steps:
        value = step.constraints.get("operator_family")
        if isinstance(value, str) and value:
            return value
    return None


def v01_translation_digest(legacy: MemoryQueryIRV01, translated: MemoryQueryIRV02) -> str:
    material = json.dumps(
        {
            "source": legacy.model_dump(mode="json"),
            "target": translated.model_dump(mode="json"),
            "translator": "v01-to-v02-compat-v1",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


def execution_operator_from_ir(
    query_ir: MemoryQueryIRV02,
) -> tuple[QueryOperator | None, dict[str, JsonValue]]:
    """Mechanically adapt v0.2 steps to the existing bounded operator executor."""

    if query_ir.mode == "AMBIGUOUS":
        return None, {}
    family = infer_operator_family(query_ir)
    terms = _requirement_terms(query_ir)
    common: dict[str, JsonValue] = {
        "slot_schema_version": "typed-operator-v1",
        "route_reason": f"MEMORY_QUERY_IR_V02_{family or 'UNKNOWN'}",
        "query_terms": list(terms),
    }
    if family == "TEMPORAL_FILTER":
        temporal = query_ir.constraints.normalized_temporal
        if temporal is not None and temporal.start is not None:
            return "TEMPORAL_BEFORE_AFTER", {
                **common,
                "operand_type": "temporal_event",
                "required_operand_count": 1,
                "direction": "before",
                "target_mode": "relative_point",
                "target_time": temporal.start.isoformat(),
                "time_axis": temporal.time_axis,
                "date_boundary": "closed_open",
            }
        relation = next(
            (
                predicate.removeprefix("relation:")
                for requirement in query_ir.requirements
                for predicate in requirement.predicate_constraints
                if predicate.startswith("relation:")
            ),
            None,
        )
        if relation in {"before", "after"}:
            return "TEMPORAL_BEFORE_AFTER", {
                **common,
                "operand_type": "temporal_event",
                "required_operand_count": 2,
                "direction": relation,
                "target_mode": "event_relation",
                "date_boundary": "exclusive",
            }
        return None, {}
    if family == "TEMPORAL_ORDER":
        anchors = _requirement_anchors(query_ir)
        if anchors is None:
            return None, {}
        return "TEMPORAL_BEFORE_AFTER", {
            **common,
            "operand_type": "temporal_event",
            "required_operand_count": 2,
            "direction": "before",
            "target_mode": "binary_ordering",
            "ordering": "earliest",
            "date_boundary": "exclusive",
            "event_anchor_terms": anchors,
        }
    if family == "TEMPORAL_DISTANCE":
        reduction = next(
            (
                step
                for step in query_ir.steps
                if step.kind == "REDUCE" and step.constraints.get("operation") == "distance"
            ),
            None,
        )
        raw_operands = (
            reduction.constraints.get("operator_operands")
            if reduction is not None
            else None
        )
        typed_operands = (
            [item for item in raw_operands if isinstance(item, dict)]
            if isinstance(raw_operands, list)
            else []
        )
        reference_operand = next(
            (
                item
                for item in typed_operands
                if item.get("kind") == "QUERY_REFERENCE_TIME"
            ),
            None,
        )
        binding_operand_count = sum(
            item.get("kind") == "REQUIREMENT_BINDING" for item in typed_operands
        )
        mode = "from_reference" if reference_operand is not None else "between_events"
        anchors = _requirement_anchors(query_ir)
        unit = (
            str(reduction.constraints.get("unit", "day"))
            if reduction is not None
            else "day"
        )
        return "TEMPORAL_DISTANCE", {
            **common,
            "operand_type": "temporal_event",
            "required_operand_count": binding_operand_count,
            "distance_mode": mode,
            "distance_unit": unit,
            "date_boundary": "exclusive",
            **(
                {"query_reference_time": reference_operand["value"]}
                if reference_operand is not None
                else {}
            ),
            **({"event_anchor_terms": anchors} if anchors is not None else {}),
        }
    if family == "COUNT":
        scalar_fact = any(
            "scalar_count_fact" in requirement.predicate_constraints
            for requirement in query_ir.requirements
        )
        if scalar_fact:
            return "COUNT_DISTINCT", {
                **common,
                "route_reason": "EXPLICIT_SCALAR_COUNT_FACT",
                "operand_type": "count_fact",
                "minimum_operand_count": 1,
                "count_mode": "scalar_fact",
                "required_qualifiers": [term for term in terms if term.isdecimal()],
                "date_boundary": "inclusive",
            }
        temporal = query_ir.constraints.normalized_temporal
        if (
            query_ir.completeness == "ALL_MATCHES_IN_RANGE"
            and temporal is not None
            and temporal.start is not None
            and temporal.end is not None
        ):
            doctor_appointment = any(
                "event_type:doctor_appointment" in requirement.predicate_constraints
                for requirement in query_ir.requirements
            )
            return "TEMPORAL_COUNT_DISTINCT", {
                **common,
                "operand_type": "temporal_event_evidence",
                "required_slots": [item.slot_id for item in query_ir.requirements],
                "event_type": ("DOCTOR_APPOINTMENT" if doctor_appointment else "GENERIC_EVENT"),
                "event_terms": list(terms),
                **({"attendance_status": "ATTENDED"} if doctor_appointment else {}),
                "temporal_range": {
                    "start": temporal.start.isoformat(),
                    "end": temporal.end.isoformat(),
                    "boundary": "CLOSED_OPEN",
                },
                "time_axis": (
                    "SOURCE_OBSERVED_TIME"
                    if temporal.time_axis == "SOURCE_OBSERVED_TIME"
                    else "EVENT_OCCURRENCE_TIME"
                ),
                "completeness": "ALL_MATCHES_IN_RANGE",
                "dedup_key_version": (
                    "appointment-event-v1" if doctor_appointment else "generic-event-v0.2-binding"
                ),
                "date_boundary": "closed_open",
            }
        if query_ir.completeness == "ALL_MATCHES_IN_RANGE":
            return None, {}
        return "COUNT_DISTINCT", {
            **common,
            "operand_type": "count_fact",
            "minimum_operand_count": 1,
            "count_mode": "scalar_fact",
            "required_qualifiers": [],
            "date_boundary": "inclusive",
        }
    if family == "DIVIDE":
        if not terms:
            return None, {}
        return "DIVIDE_EVIDENCE_VALUES", {
            **common,
            "operand_type": "quantity_evidence",
            "required_operand_count": 2,
            "required_slots": [item.slot_id for item in query_ir.requirements],
            "entity_terms": list(terms),
            "completeness": "ALL_REQUIRED_SLOTS",
            "date_boundary": "inclusive",
        }
    if family == "SUM":
        return "SUM_VALUES", {
            **common,
            "operand_type": "numeric_value",
            "minimum_operand_count": 2,
            "aggregation": "sum",
            "date_boundary": "inclusive",
        }
    if family == "COMPARE":
        return "COMPARE_EVENTS", {
            **common,
            "operand_type": "numeric_value",
            "required_operand_count": 2,
            "comparison_mode": "difference",
            "date_boundary": "inclusive",
        }
    if family == "EVENT_IDENTITY_COMPARE":
        return "COMPARE_EVENT_IDENTITY", {
            **common,
            "operand_type": "formation_event_identity",
            "required_operand_count": 2,
            "comparison_mode": "identity_equality",
            "required_slots": [item.slot_id for item in query_ir.requirements if item.required],
            "date_boundary": "inclusive",
        }
    if family == "COMPOSE_STATE":
        return "COMPOSE_STATE", {
            **common,
            "operand_type": "formation_state_components",
            "required_operand_count": len(
                [item for item in query_ir.requirements if item.required]
            ),
            "required_slots": [item.slot_id for item in query_ir.requirements if item.required],
            "composition_mode": "preference_plus_short_lived_state",
            "date_boundary": "inclusive",
        }
    if family == "LOOKUP" and query_ir.mode == "STATE":
        return "LATEST_VALID_STATE", {
            **common,
            "operand_type": "versioned_state",
            "required_operand_count": 1,
            "selection_basis": "valid_time_from",
            "date_boundary": "inclusive",
        }
    return None, {}


def _steps(
    operator_family: str,
    requirements: list[EvidenceRequirementV02],
    temporal: NormalizedTemporalConstraint | None,
    *,
    reference_time: datetime | None = None,
    distance_unit: str | None = None,
) -> list[MemoryQueryStep]:
    operator_operands: list[JsonValue] = []
    if operator_family == "TEMPORAL_DISTANCE":
        required_events = [
            item
            for item in requirements
            if item.required and item.interpretation_kind == "EVENT"
        ]
        operator_operands.extend(
            {
                "kind": "REQUIREMENT_BINDING",
                "operand_id": f"operand:{item.slot_id.casefold()}",
                "slot_id": item.slot_id,
            }
            for item in required_events
        )
        if len(required_events) == 1:
            if reference_time is None:
                raise ValueError("event-to-reference distance lacks query reference time")
            operator_operands.append(
                {
                    "kind": "QUERY_REFERENCE_TIME",
                    "operand_id": "operand:query-reference-time",
                    "value": reference_time.isoformat(),
                    "timezone": _reference_timezone(reference_time),
                }
            )
    steps = [
        MemoryQueryStep(
            kind="RETRIEVE",
            outputs=["candidate_spans"],
            constraints={
                "operator_family": operator_family,
                "retrieval_unit": "TURN_OR_SPAN",
            },
            budget={"candidate_cap_required": True},
        )
    ]
    active_input = "candidate_spans"
    if temporal is not None and temporal.boundary != "UNBOUNDED":
        steps.append(
            MemoryQueryStep(
                kind="TEMPORAL_SCAN",
                inputs=[active_input],
                outputs=["temporal_candidates"],
                constraints={"boundary": temporal.boundary},
                budget={"bounded": True},
            )
        )
        active_input = "temporal_candidates"
    if operator_family == "COUNT":
        steps.append(
            MemoryQueryStep(
                kind="FILTER",
                inputs=[active_input],
                outputs=["applicable_events"],
                constraints={
                    "gate": "TYPE_ENTITY_TIME_STATUS",
                    "binding_owner": "DETERMINISTIC_RUNTIME",
                },
            )
        )
        active_input = "applicable_events"
    for requirement in requirements:
        if not requirement.required:
            continue
        steps.append(
            MemoryQueryStep(
                kind="BIND_SLOT",
                inputs=[active_input],
                outputs=[requirement.slot_id],
                constraints={
                    "interpretation_kind": requirement.interpretation_kind,
                    "binding_owner": "DETERMINISTIC_RUNTIME",
                },
            )
        )
    required_slots = [item.slot_id for item in requirements if item.required]
    if operator_family in {
        "DIVIDE",
        "TEMPORAL_ORDER",
        "TEMPORAL_DISTANCE",
        "COMPARE",
        "MULTI_JOIN",
        "WHY_CHANGE",
    }:
        steps.append(
            MemoryQueryStep(
                kind="JOIN",
                inputs=required_slots,
                outputs=["joined_bindings"],
                constraints={
                    "join_validation": "TYPE_ENTITY_UNIT_TIME_EPISODE",
                    **(
                        {"operator_operands": operator_operands}
                        if operator_operands
                        else {}
                    ),
                },
            )
        )
    if operator_family == "COUNT":
        steps.append(
            MemoryQueryStep(
                kind="DEDUPLICATE",
                inputs=required_slots,
                outputs=["distinct_events"],
                constraints={"identity": "QUERY_CONDITIONED_EVENT_IDENTITY"},
            )
        )
    reduction = {
        "COUNT": "count",
        "SUM": "sum",
        "DIVIDE": "divide",
        "TEMPORAL_DISTANCE": "distance",
    }.get(operator_family)
    if reduction is not None:
        steps.append(
            MemoryQueryStep(
                kind="REDUCE",
                inputs=(
                    ["distinct_events"]
                    if operator_family == "COUNT"
                    else ["joined_bindings"]
                    if operator_family in {"DIVIDE", "TEMPORAL_DISTANCE"}
                    else required_slots
                ),
                outputs=["answer"],
                constraints={
                    "operation": reduction,
                    **(
                        {"operator_operands": operator_operands}
                        if operator_operands
                        else {}
                    ),
                    **({"unit": distance_unit} if distance_unit is not None else {}),
                },
            )
        )
    elif operator_family in {"TEMPORAL_ORDER", "COMPARE", "WHY_CHANGE"}:
        steps.append(
            MemoryQueryStep(
                kind="COMPARE",
                inputs=["joined_bindings"],
                outputs=["answer"],
                constraints={"operation": operator_family.casefold()},
            )
        )
    return steps


def _legacy_distance_unit(legacy: MemoryQueryIRV01) -> str | None:
    if legacy.operator != "TEMPORAL_DISTANCE":
        return None
    for requirement in legacy.requirements:
        for predicate in requirement.predicate_constraints:
            if predicate.startswith("distance_unit:"):
                return predicate.partition(":")[2]
    return "day"


def _reference_timezone(value: datetime) -> str:
    key = getattr(value.tzinfo, "key", None)
    return str(key or value.tzname() or value.utcoffset())


def _requirement_terms(query_ir: MemoryQueryIRV02) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            term.casefold()
            for requirement in query_ir.requirements
            for term in requirement.entity_constraints
            if term
        )
    )


def _requirement_anchors(query_ir: MemoryQueryIRV02) -> list[JsonValue] | None:
    anchors = [list(requirement.entity_constraints) for requirement in query_ir.requirements[:2]]
    if len(anchors) != 2 or not all(anchors):
        return None
    return cast(list[JsonValue], anchors)


def _translate_temporal(
    legacy: MemoryQueryIRV01,
    query: str,
) -> NormalizedTemporalConstraint | None:
    temporal = legacy.temporal
    if temporal.boundary is None:
        return None
    if temporal.reference_time is None:
        raise ValueError("v0.1 bounded temporal constraint lacks reference_time")
    cue_spans = _exact_phrase_spans(query, temporal.normalized_from)
    precision, timezone = _point_precision_timezone(
        temporal.boundary,
        temporal.normalized_from,
        temporal.reference_time,
    )
    return NormalizedTemporalConstraint(
        reference_time=temporal.reference_time,
        start=temporal.start,
        end=temporal.end,
        boundary=temporal.boundary,
        time_axis=_temporal_axis(query),
        precision=precision,
        timezone=timezone,
        normalized_from=cue_spans,
    )


def _translate_requirement_temporal(
    temporal: Any,
    query: str,
) -> NormalizedTemporalConstraint | None:
    if temporal.boundary is None:
        return None
    if temporal.reference_time is None:
        raise ValueError("v0.1 requirement temporal constraint lacks reference_time")
    precision, timezone = _point_precision_timezone(
        temporal.boundary,
        temporal.normalized_from,
        temporal.reference_time,
    )
    return NormalizedTemporalConstraint(
        reference_time=temporal.reference_time,
        start=temporal.start,
        end=temporal.end,
        boundary=temporal.boundary,
        time_axis=_temporal_axis(query),
        precision=precision,
        timezone=timezone,
        normalized_from=_exact_phrase_spans(query, temporal.normalized_from),
    )


def _point_precision_timezone(
    boundary: str,
    normalized_from: str | None,
    reference_time: datetime,
) -> tuple[Literal["DAY", "HOUR", "MINUTE"] | None, str | None]:
    if boundary != "POINT" or not normalized_from:
        return None, None
    if re.search(r"\bminutes?\b", normalized_from, re.IGNORECASE):
        precision: Literal["DAY", "HOUR", "MINUTE"] = "MINUTE"
    elif re.search(r"\bhours?\b", normalized_from, re.IGNORECASE):
        precision = "HOUR"
    elif re.search(
        r"\b(?:days?|weeks?|months?|years?|today|yesterday)\b",
        normalized_from,
        re.IGNORECASE,
    ):
        precision = "DAY"
    else:
        return None, None
    zone = reference_time.tzinfo
    if zone is None or reference_time.utcoffset() is None:
        return None, None
    key = getattr(zone, "key", None)
    if isinstance(key, str) and key:
        return precision, key
    offset = reference_time.utcoffset()
    assert offset is not None
    seconds = int(offset.total_seconds())
    if seconds == 0:
        return precision, "UTC"
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    hours, remainder = divmod(seconds, 3_600)
    minutes = remainder // 60
    return precision, f"{sign}{hours:02d}:{minutes:02d}"


def _temporal_axis(query: str) -> Literal["EVENT_TIME", "SOURCE_OBSERVED_TIME"]:
    relative = re.search(
        r"\b(?:a\s+couple\s+of|couple\s+of|a|an|one|two|three|four|five|"
        r"six|seven|eight|nine|ten|\d+)\s+(?:days?|weeks?|months?|years?)\s+ago\b",
        query,
        re.IGNORECASE,
    )
    source_cue = re.search(
        r"\b(?:ask(?:ed)?|discuss(?:ed)?|mention(?:ed)?|record(?:ed)?|said|told)\b",
        query,
        re.IGNORECASE,
    )
    return (
        "SOURCE_OBSERVED_TIME"
        if relative is not None and source_cue is not None and source_cue.start() < relative.start()
        else "EVENT_TIME"
    )


def _exact_phrase_spans(query: str, phrase: str | None) -> list[QueryCueSpan]:
    if not phrase:
        return []
    start = query.casefold().find(phrase.casefold())
    if start < 0:
        return []
    end = start + len(phrase)
    return [QueryCueSpan(start=start, end=end, text=query[start:end])]


def _entity_cue_spans(query: str, entities: list[str]) -> list[QueryCueSpan]:
    spans: list[QueryCueSpan] = []
    occupied: set[tuple[int, int]] = set()
    lowered = query.casefold()
    for entity in entities:
        start = lowered.find(entity.casefold())
        if start < 0:
            continue
        end = start + len(entity)
        if (start, end) not in occupied:
            occupied.add((start, end))
            spans.append(QueryCueSpan(start=start, end=end, text=query[start:end]))
    return spans


def _answer_shape(value: str) -> MemoryAnswerShape:
    mapping: dict[str, MemoryAnswerShape] = {
        "SCALAR": "SCALAR",
        "LIST": "LIST",
        "STATE": "STATE",
        "TIMELINE": "TIMELINE",
        "EXPLANATION": "EXPLANATION",
    }
    return mapping[value]


__all__ = [
    "execution_operator_from_ir",
    "infer_operator_family",
    "translate_memory_query_ir_v01",
    "v01_translation_digest",
]

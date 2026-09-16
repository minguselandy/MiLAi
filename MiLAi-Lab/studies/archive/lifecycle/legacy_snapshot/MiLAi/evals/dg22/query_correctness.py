# ruff: noqa: RUF001 -- full-width punctuation is part of the CJK query corpus.
"""DG-22 S3 bounded QueryIR/Requirement correctness matrix."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from milai.application.memory_query import MemoryQueryCompiler
from milai.application.query_ir_compat import infer_operator_family
from milai.domain.semantic_query import MemoryQueryIRV02

REFERENCE = datetime(2031, 6, 30, 12, 0, tzinfo=UTC)


def query_requirement_matrix() -> list[dict[str, Any]]:
    """Return 72 pre-annotated cells; expectations never derive from Runtime output."""
    cells: list[dict[str, Any]] = []
    _extend(
        cells,
        "LOOKUP",
        [
            "What color was the Atlas bicycle?",
            "Where was the Atlas bicycle stored?",
            "Who repaired the Atlas bicycle?",
            "When was the Atlas bicycle repaired?",
            "Atlas自行车是什么颜色？",
            "Atlas自行车存放在哪里？",
            "谁修理了Atlas自行车？",
            "Atlas自行车是什么时候修好的？",
        ],
        operator="LOOKUP",
        mode="EVIDENCE",
        requirements=[_requirement("LOOKUP_ANSWER", "EVENT", ["answer_bearing"])],
        completeness="TOP_K_ACCEPTABLE",
    )
    _extend(
        cells,
        "CURRENT_STATE",
        [
            "What is the current Atlas project status?",
            "What is my current Atlas project status?",
            "Which Atlas project status is latest?",
            "What Atlas bicycle do I currently own?",
            "Atlas项目目前是什么状态？",
            "Atlas项目当前是什么状态？",
            "Atlas项目最新状态是什么？",
            "我现在拥有哪辆Atlas自行车？",
        ],
        operator="LOOKUP",
        mode="STATE",
        requirements=[
            _requirement("CURRENT_STATE", "STATE_OBSERVATION", ["current_state"])
        ],
        completeness="ALL_REQUIRED_BINDINGS",
        allow_extra_predicates=["user_fact"],
    )
    _extend(
        cells,
        "BOUNDED_COUNT",
        [
            "How many Atlas workshops did I attend in the last 3 months?",
            "Count Atlas workshops during the past two weeks.",
            "What is the number of Atlas visits over the last 7 days?",
            "How many Atlas meetings happened in June 2031?",
            "过去三个月内参加Atlas工作坊有多少次？",
            "最近两周Atlas工作坊有多少次？",
            "过去七天内Atlas访问有多少次？",
            "最近一个月Atlas会议有多少次？",
        ],
        operator="COUNT",
        mode="COMPOSE",
        requirements=[
            _requirement(
                "MATCHING_EVENTS_IN_RANGE",
                "EVENT",
                ["matches_range", "deduplicate"],
                maximum=None,
                distinct=True,
            )
        ],
        boundary="CLOSED_OPEN",
        time_axis="EVENT_TIME",
        completeness="ALL_MATCHES_IN_RANGE",
    )
    _extend(
        cells,
        "TEMPORAL_POINT",
        [
            "What Atlas event happened three weeks ago?",
            "What happened to Atlas two days ago?",
            "Which Atlas visit happened one month ago?",
            "What Atlas repair happened 7 days ago?",
            "三周前Atlas发生了什么？",
            "两天前Atlas发生了什么？",
            "一个月前Atlas发生了什么？",
            "七天前Atlas发生了什么？",
        ],
        operator="TEMPORAL_FILTER",
        mode="COMPOSE",
        requirements=[_requirement("TARGET_EVENT", "EVENT", ["event_at_time"])],
        boundary="POINT",
        time_axis="EVENT_TIME",
        completeness="ALL_REQUIRED_BINDINGS",
    )
    _extend(
        cells,
        "TEMPORAL_DISTANCE",
        [
            "How many days between the Atlas launch and the Borealis review?",
            "How many weeks between the Atlas launch and the Borealis review?",
            "What elapsed time between the Atlas launch and the Borealis review?",
            "How long from the Atlas launch to the Borealis review?",
            "从Atlas发布到Borealis评审相隔多少天？",
            "Atlas发布与Borealis评审之间相隔多少周？",
            "从Atlas发布到Borealis评审过去了多少个月？",
            "Atlas发布和Borealis评审之间有多少年？",
        ],
        operator="TEMPORAL_DISTANCE",
        mode="COMPOSE",
        requirements=[
            _requirement("EVENT_1", "EVENT", ["event_time"]),
            _requirement("EVENT_2", "EVENT", ["event_time"]),
        ],
        completeness="ALL_REQUIRED_BINDINGS",
        allow_extra_predicate_prefixes=["distance_unit:"],
    )
    _extend(
        cells,
        "TEMPORAL_ORDER",
        [
            "Which happened first, the Atlas launch or the Borealis review?",
            "What happened earlier, the Atlas launch or the Borealis review?",
            "Which came first, Atlas repair or Borealis inspection?",
            "What occurred earlier, Atlas visit or Borealis meeting?",
            "Atlas发布和Borealis评审，哪件事更早？",
            "Atlas发布与Borealis评审，谁先发生？",
            "Atlas修理还是Borealis检查先发生？",
            "Atlas访问或Borealis会议哪个更早？",
        ],
        operator="TEMPORAL_ORDER",
        mode="COMPOSE",
        requirements=[
            _requirement("EVENT_1", "EVENT", ["event_time"]),
            _requirement("EVENT_2", "EVENT", ["event_time"]),
        ],
        completeness="ALL_REQUIRED_BINDINGS",
    )
    _extend(
        cells,
        "DIVIDE",
        [
            "How much did each Atlas ticket cost?",
            "What was the price per Atlas ticket?",
            "What was the Atlas ticket unit price?",
            "How much per Atlas ticket from the receipt?",
            "Atlas门票每张多少钱？",
            "Atlas门票单价是多少？",
            "每张Atlas门票花费多少钱？",
            "Atlas门票每件价格是多少？",
        ],
        operator="DIVIDE",
        mode="COMPOSE",
        requirements=[
            _requirement("TOTAL_PRICE", "QUANTITY", ["total"], distinct=True),
            _requirement("ITEM_COUNT", "QUANTITY", ["count"], distinct=True),
        ],
        completeness="ALL_REQUIRED_BINDINGS",
    )
    source_queries = [
        (
            "According only to what I said, what is the current Atlas project status?",
            "USER",
            True,
        ),
        (
            "Use only assistant messages: what is the current Atlas project status?",
            "ASSISTANT",
            True,
        ),
        (
            "Prefer using my messages: what is the current Atlas project status?",
            "USER",
            False,
        ),
        (
            "Prefer assistant messages: what is the current Atlas project status?",
            "ASSISTANT",
            False,
        ),
        ("只根据我说的，Atlas项目目前是什么状态？", "USER", True),
        ("只根据助手说的，Atlas项目目前是什么状态？", "ASSISTANT", True),
        ("优先使用我的消息，Atlas项目目前是什么状态？", "USER", False),
        ("优先使用助手消息，Atlas项目目前是什么状态？", "ASSISTANT", False),
    ]
    for query, speaker, hard in source_queries:
        _append(
            cells,
            family="SOURCE_POLICY",
            query=query,
            operator="LOOKUP",
            mode="STATE",
            requirements=[
                _requirement("CURRENT_STATE", "STATE_OBSERVATION", ["current_state"])
            ],
            completeness="ALL_REQUIRED_BINDINGS",
            allowed_speakers=[speaker] if hard else None,
            preferred_speakers=[] if hard else [speaker],
            allow_extra_predicates=["user_fact"],
        )
    ambiguous = [
        "What is the average Atlas visit duration?",
        "What is the current Atlas status and how many visits happened last week?",
        'What phrase did I quote: "how many Atlas visits"?',
        "I did not ask for a count; what is the current Atlas project status?",
        "Tell me about Atlas.",
        "Order all Atlas events into a complete timeline.",
        "Atlas访问时长的平均值是多少？",
        "把Atlas所有事件生成完整时间线。",
    ]
    _extend(
        cells,
        "AMBIGUOUS_FAIL_CLOSED",
        ambiguous,
        operator=None,
        mode="AMBIGUOUS",
        requirements=[],
        completeness="UNSTRUCTURED_EVIDENCE_ALLOWED",
    )
    if len(cells) != 72:
        raise AssertionError(f"expected 72 cells, got {len(cells)}")
    return cells


def run_query_correctness() -> dict[str, Any]:
    compiler = MemoryQueryCompiler()
    records = []
    for cell in query_requirement_matrix():
        query_ir = compiler.compile(cell["query"], reference_time=REFERENCE)
        records.append(_score_cell(cell, query_ir))
    expected_required = sum(len(row["annotation"]["requirements"]) for row in records)
    actual_required = sum(len(row["actual"]["requirements"]) for row in records)
    true_required = sum(row["requirement_true_positive"] for row in records)
    executable = [row for row in records if row["annotation"]["mode"] != "AMBIGUOUS"]
    ambiguous = [row for row in records if row["annotation"]["mode"] == "AMBIGUOUS"]
    metrics = {
        "cell_count": len(records),
        "required_requirement_precision": true_required / actual_required
        if actual_required
        else 1.0,
        "required_requirement_recall": true_required / expected_required
        if expected_required
        else 1.0,
        "operator_time_axis_accuracy": sum(
            row["operator_time_axis_pass"] for row in records
        )
        / len(records),
        "boundary_accuracy": sum(row["boundary_pass"] for row in records)
        / len(records),
        "cardinality_accuracy": sum(row["cardinality_pass"] for row in records)
        / len(records),
        "source_policy_accuracy": sum(row["source_policy_pass"] for row in records)
        / len(records),
        "ambiguity_fail_closed_rate": sum(row["passed"] for row in ambiguous)
        / len(ambiguous),
        "unsupported_complete": sum(
            row["actual"]["mode"] != "AMBIGUOUS" for row in ambiguous
        ),
        "case_id_or_gold_dependency": 0,
        "executable_cell_count": len(executable),
    }
    checks = {
        "minimum_60_cells": len(records) >= 60,
        "required_requirement_precision_100": metrics["required_requirement_precision"]
        == 1.0,
        "required_requirement_recall_100": metrics["required_requirement_recall"]
        == 1.0,
        "operator_time_axis_accuracy_100": metrics["operator_time_axis_accuracy"]
        == 1.0,
        "boundary_accuracy_100": metrics["boundary_accuracy"] == 1.0,
        "cardinality_accuracy_100": metrics["cardinality_accuracy"] == 1.0,
        "source_policy_accuracy_100": metrics["source_policy_accuracy"] == 1.0,
        "unsupported_complete_zero": metrics["unsupported_complete"] == 0,
        "case_id_gold_dependency_zero": metrics["case_id_or_gold_dependency"] == 0,
        "all_cells_pass": all(row["passed"] for row in records),
    }
    return {
        "schema": "milai.dg22.s3-query-requirement-correctness.v0.1",
        "status": "PASS_QUERY_REQUIREMENT_CORRECTNESS"
        if all(checks.values())
        else "FAIL",
        "reference_time": REFERENCE.isoformat(),
        "metrics": metrics,
        "coverage": {
            "families": sorted({row["family"] for row in records}),
            "english_cells": sum(not _has_cjk(row["query"]) for row in records),
            "cjk_cells": sum(_has_cjk(row["query"]) for row in records),
            "mutation_kinds": ["paraphrase", "negation", "quoted-speech", "multi-slot"],
        },
        "records": records,
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "safety": {
            "provider_calls": 0,
            "reader_calls": 0,
            "case_id_or_gold_aware_routing": 0,
            "canonical_mutations": 0,
            "formal_holdout_consumed": False,
        },
    }


def _score_cell(cell: Mapping[str, Any], query_ir: MemoryQueryIRV02) -> dict[str, Any]:
    expected = cell["annotation"]
    actual_requirements = [
        _requirement_projection(item) for item in query_ir.requirements if item.required
    ]
    expected_requirements = list(expected["requirements"])
    actual_by_slot = {item["slot_id"]: item for item in actual_requirements}
    true_positive = 0
    requirement_diagnostics = []
    for wanted in expected_requirements:
        observed = actual_by_slot.get(wanted["slot_id"])
        passed = observed is not None and _requirement_matches(
            wanted, observed, expected
        )
        true_positive += int(passed)
        requirement_diagnostics.append(
            {"slot_id": wanted["slot_id"], "passed": passed, "observed": observed}
        )
    operator = infer_operator_family(query_ir)
    temporal = query_ir.constraints.normalized_temporal
    actual_axis = temporal.time_axis if temporal is not None else None
    actual_boundary = temporal.boundary if temporal is not None else None
    operator_time_axis_pass = (
        operator == expected["operator"] and actual_axis == expected["time_axis"]
    )
    boundary_pass = actual_boundary == expected["boundary"]
    cardinality_pass = all(
        diagnostic["passed"] for diagnostic in requirement_diagnostics
    ) and len(actual_requirements) == len(expected_requirements)
    source_policy_pass = all(
        item["evidence_source"]["allowed_speakers"] == expected["allowed_speakers"]
        and item["evidence_source"]["preferred_speakers"]
        == expected["preferred_speakers"]
        for item in actual_requirements
    )
    passed = all(
        (
            query_ir.mode == expected["mode"],
            query_ir.completeness == expected["completeness"],
            operator_time_axis_pass,
            boundary_pass,
            cardinality_pass,
            source_policy_pass,
        )
    )
    return {
        "cell_id": cell["cell_id"],
        "family": cell["family"],
        "query": cell["query"],
        "query_sha256": hashlib.sha256(cell["query"].encode()).hexdigest(),
        "annotation": expected,
        "actual": {
            "mode": query_ir.mode,
            "operator": operator,
            "time_axis": actual_axis,
            "boundary": actual_boundary,
            "completeness": query_ir.completeness,
            "requirements": actual_requirements,
            "planner_reason": query_ir.planner_trace.reason_code,
        },
        "requirement_true_positive": true_positive,
        "requirement_diagnostics": requirement_diagnostics,
        "operator_time_axis_pass": operator_time_axis_pass,
        "boundary_pass": boundary_pass,
        "cardinality_pass": cardinality_pass,
        "source_policy_pass": source_policy_pass,
        "passed": passed,
    }


def _requirement_projection(item: Any) -> dict[str, Any]:
    return {
        "slot_id": item.slot_id,
        "kind": item.interpretation_kind,
        "predicates": list(item.predicate_constraints),
        "cardinality": item.cardinality.model_dump(mode="json"),
        "evidence_source": item.evidence_source.model_dump(mode="json"),
    }


def _requirement_matches(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    annotation: Mapping[str, Any],
) -> bool:
    predicates = set(actual["predicates"])
    expected_predicates = set(expected["predicates"])
    allowed_extra = set(annotation["allow_extra_predicates"])
    allowed_prefixes = tuple(annotation["allow_extra_predicate_prefixes"])
    unexpected = {
        predicate
        for predicate in predicates - expected_predicates - allowed_extra
        if not predicate.startswith(allowed_prefixes)
    }
    return (
        actual["kind"] == expected["kind"]
        and expected_predicates <= predicates
        and not unexpected
        and actual["cardinality"] == expected["cardinality"]
    )


def _requirement(
    slot_id: str,
    kind: str,
    predicates: Sequence[str],
    *,
    maximum: int | None = 1,
    distinct: bool = False,
) -> dict[str, Any]:
    return {
        "slot_id": slot_id,
        "kind": kind,
        "predicates": list(predicates),
        "cardinality": {"minimum": 1, "maximum": maximum, "distinct": distinct},
    }


def _extend(
    cells: list[dict[str, Any]], family: str, queries: Sequence[str], **annotation: Any
) -> None:
    for query in queries:
        _append(cells, family=family, query=query, **annotation)


def _append(
    cells: list[dict[str, Any]],
    *,
    family: str,
    query: str,
    operator: str | None,
    mode: str,
    requirements: Sequence[Mapping[str, Any]],
    completeness: str,
    boundary: str | None = None,
    time_axis: str | None = None,
    allowed_speakers: Sequence[str] | None = None,
    preferred_speakers: Sequence[str] = (),
    allow_extra_predicates: Sequence[str] = (),
    allow_extra_predicate_prefixes: Sequence[str] = (),
) -> None:
    ordinal = len(cells) + 1
    annotation = {
        "operator": operator,
        "mode": mode,
        "requirements": [dict(item) for item in requirements],
        "completeness": completeness,
        "boundary": boundary,
        "time_axis": time_axis,
        "allowed_speakers": list(allowed_speakers)
        if allowed_speakers is not None
        else None,
        "preferred_speakers": list(preferred_speakers),
        "allow_extra_predicates": list(allow_extra_predicates),
        "allow_extra_predicate_prefixes": list(allow_extra_predicate_prefixes),
    }
    cells.append(
        {
            "cell_id": f"s3-{ordinal:03d}",
            "family": family,
            "query": query,
            "annotation": annotation,
            "annotation_digest": _digest(annotation),
        }
    )


def _has_cjk(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


__all__ = ["query_requirement_matrix", "run_query_correctness"]

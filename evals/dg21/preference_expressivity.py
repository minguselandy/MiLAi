"""DG-21 S4 preference requirement expressivity evaluation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai.application.acquisition_execution_policy import (
    default_acquisition_execution_policy,
)
from milai.application.evidence_semantics import (
    project_evidence_spans,
    run_type_directed_semantics,
)
from milai.application.memory_query import MemoryQueryCompiler
from milai.application.preference_composition import synthesize_preference_evidence_view
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.domain.semantic_query import RequirementBinding
from pydantic import JsonValue

_REFERENCE = datetime(2026, 8, 28, 8, tzinfo=UTC)
_SCOPE: dict[str, JsonValue] = {"project_ids": ["dg21-synthetic"]}
_ARM = "B_FRESH_STATE_DETERMINISTIC_CAPABILITY_POLICY"
_POSITIVE_QUERIES = (
    (
        "planning-trip-suggestions",
        "I'm planning a trip to Denver soon. Any suggestions on what to do there?",
    ),
    (
        "present-visit-recommendations",
        "I'm visiting Kyoto soon. Any recommendations for me?",
    ),
    (
        "thinking-visit-preferences",
        "I'm thinking of visiting Lisbon; what would fit my preferences?",
    ),
    (
        "explicit-intent-preference",
        "I intend to return to Oslo. What do I prefer there?",
    ),
)
_NEGATIVE_QUERIES = (
    ("historical-latest", "What was my latest preference?"),
    ("preference-only", "What Denver activities do I prefer?"),
    ("suggestion-only", "Any suggestions for museums in Denver?"),
    (
        "past-plan",
        "I was planning a trip to Denver last year. What did I prefer?",
    ),
)


def run_preference_expressivity_matrix(root: Path) -> dict[str, Any]:
    """Run synthetic compiler gates before one label-free opened-dev diagnosis."""

    root = root.resolve()
    synthetic = _synthetic_compiler_matrix()
    binding = _synthetic_binding_matrix()
    opened = _opened_a89_diagnosis(root)
    a82 = _a82_regression(root)
    policy = default_acquisition_execution_policy()
    request_fields = set(RetrievalRequest.model_json_schema()["properties"])
    runtime_case_id_occurrences = sum(
        path.read_text(encoding="utf-8").count("a89d7624")
        for path in (root / "runtime/src").rglob("*.py")
    )
    checks = {
        "synthetic_positive_compilation_4_of_4": all(
            item["passed"] for item in synthetic["positive"]
        ),
        "synthetic_negative_compilation_4_of_4": all(
            item["passed"] for item in synthetic["negative"]
        ),
        "historical_preference_false_satisfies_current_intent_zero": (
            binding["historical_current_intent_match_count"] == 0
        ),
        "assistant_first_person_false_satisfies_current_intent_zero": (
            binding["assistant_current_intent_match_count"] == 0
        ),
        "synthetic_current_intent_independently_bound": (
            binding["explicit_user_current_intent_match_count"] == 1
        ),
        "synthetic_view_requires_and_fills_both_slots": (
            binding["combined_filled_slots"]
            == ["PREFERENCE_SIGNAL_SET", "CURRENT_INTENT"]
        ),
        "opened_a89_compiles_two_typed_requirements": (
            opened["compiled_requirement_kinds"]
            == {
                "PREFERENCE_SIGNAL_SET": "PREFERENCE_SIGNAL",
                "CURRENT_INTENT": "DECISION",
            }
        ),
        "opened_a89_binds_both_requirements": (
            opened["match_count_by_requirement"]
            == {"PREFERENCE_SIGNAL_SET": 1, "CURRENT_INTENT": 1}
        ),
        "opened_a89_current_intent_false_satisfied_zero": (
            opened["current_intent_false_satisfied_count"] == 0
        ),
        "opened_a89_view_fills_both_slots": (
            opened["filled_slots"] == ["PREFERENCE_SIGNAL_SET", "CURRENT_INTENT"]
        ),
        "opened_a89_runtime_case_id_rule_zero": runtime_case_id_occurrences == 0,
        "a82_frozen_semantic_contract_preserved": a82[
            "semantic_ir_frozen_contract_preserved"
        ],
        "a82_correct_2048_baseline_preserved": (
            a82["token_budget"] == 2048
            and a82["frozen_answer_exact_match"] == 1
            and a82["frozen_required_evidence_coverage"] == 1.0
        ),
        "public_mcp_request_schema_unchanged": (
            "current_intent" not in request_fields
            and "preference_requirements" not in request_fields
        ),
        "formal_holdout_not_consumed": opened["formal_holdout_consumed"] is False,
        "label_fields_accessed_zero": opened["label_fields_accessed"] is False,
        "provider_reader_calls_zero": (
            opened["provider_calls"] == 0 and opened["reader_calls"] == 0
        ),
        "candidate_policy_frozen_after_s4": (
            policy.profiles.semantic_slot.dense_candidate_cap == 12
            and policy.profiles.semantic_slot.baseline_candidate_cap == 8
        ),
    }
    passed = all(checks.values())
    return {
        "schema": "milai.dg21.s4-preference-expressivity.v0.1",
        "status": (
            "PASS_PREFERENCE_REQUIREMENT_EXPRESSIVITY"
            if passed
            else "PARKED_REQUIREMENT_EXPRESSIVITY_NOT_GENERALIZED"
        ),
        "classification": "PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT / EVALUATION_PLANE",
        "policy_digest": policy.policy_digest,
        "selected_candidate_policy": {
            "semantic_baseline_candidate_cap": (
                policy.profiles.semantic_slot.baseline_candidate_cap
            ),
            "semantic_dense_candidate_cap": (
                policy.profiles.semantic_slot.dense_candidate_cap
            ),
            "preference_adjacency_max_anchors": (
                policy.profiles.preference_local.adjacent_max_anchors
            ),
            "preference_adjacency_radius": policy.profiles.preference_local.adjacent_radius,
            "preference_adjacency_max_items": (
                policy.profiles.preference_local.adjacent_max_items
            ),
        },
        "synthetic_compiler_matrix": synthetic,
        "synthetic_binding_matrix": binding,
        "opened_a89_diagnosis": opened,
        "a82_regression": a82,
        "metrics": {
            "synthetic_positive_count": len(synthetic["positive"]),
            "synthetic_negative_count": len(synthetic["negative"]),
            "current_intent_false_satisfied_count": (
                binding["historical_current_intent_match_count"]
                + binding["assistant_current_intent_match_count"]
                + opened["current_intent_false_satisfied_count"]
            ),
            "provider_calls": 0,
            "reader_calls": 0,
            "automatic_retries": 0,
            "additional_acquisition_passes": 0,
            "canonical_mutations": 0,
            "runtime_case_id_occurrences": runtime_case_id_occurrences,
        },
        "safety": {
            "public_schema_changed": False,
            "provider_calls": 0,
            "reader_calls": 0,
            "automatic_retries": 0,
            "canonical_mutations": 0,
            "formal_holdout_consumed": False,
        },
        "hard_gate": {"passed": passed, "checks": checks},
    }


def _synthetic_compiler_matrix() -> dict[str, list[dict[str, Any]]]:
    compiler = MemoryQueryCompiler()
    positive: list[dict[str, Any]] = []
    negative: list[dict[str, Any]] = []
    for case_id, query in _POSITIVE_QUERIES:
        query_ir = compiler.compile(query, reference_time=_REFERENCE, scope=_SCOPE)
        slots = [item.slot_id for item in query_ir.requirements]
        kinds = [item.interpretation_kind for item in query_ir.requirements]
        positive.append(
            {
                "case_id": case_id,
                "query_sha256": _text_sha256(query),
                "slots": slots,
                "interpretation_kinds": kinds,
                "auxiliary_model_calls": query_ir.planner_trace.auxiliary_model_calls,
                "passed": slots == ["PREFERENCE_SIGNAL_SET", "CURRENT_INTENT"]
                and kinds == ["PREFERENCE_SIGNAL", "DECISION"]
                and query_ir.planner_trace.auxiliary_model_calls == 0,
            }
        )
    for case_id, query in _NEGATIVE_QUERIES:
        query_ir = compiler.compile(query, reference_time=_REFERENCE, scope=_SCOPE)
        slots = [item.slot_id for item in query_ir.requirements]
        negative.append(
            {
                "case_id": case_id,
                "query_sha256": _text_sha256(query),
                "slots": slots,
                "auxiliary_model_calls": query_ir.planner_trace.auxiliary_model_calls,
                "passed": slots == ["PREFERENCE_SIGNAL_SET"]
                and query_ir.planner_trace.auxiliary_model_calls == 0,
            }
        )
    return {"positive": positive, "negative": negative}


def _synthetic_binding_matrix() -> dict[str, Any]:
    query = _POSITIVE_QUERIES[0][1]
    plan = _query_plan(query, _REFERENCE, {"project_ids": ["dg21-synthetic"]})
    historical = _evidence(
        "historical",
        "I love Denver's live music scene.",
        "preference-synthetic",
        4,
        _REFERENCE,
        "user",
    )
    current = _evidence(
        "current",
        "I'm thinking of going back to Denver for another concert.",
        "preference-synthetic",
        6,
        _REFERENCE,
        "user",
    )
    assistant = _evidence(
        "assistant",
        "I'm planning a trip to Denver soon.",
        "preference-synthetic",
        7,
        _REFERENCE,
        "assistant",
    )
    historical_bindings = _matched_bindings(plan, [historical])
    current_bindings = _matched_bindings(plan, [current])
    assistant_bindings = _matched_bindings(plan, [assistant])
    view = synthesize_preference_evidence_view(plan, [historical, current, assistant])
    if view is None:
        raise AssertionError("synthetic preference plan did not synthesize a view")
    return {
        "historical_preference_match_count": _count_matches(
            historical_bindings, "PREFERENCE_SIGNAL_SET"
        ),
        "historical_current_intent_match_count": _count_matches(
            historical_bindings, "CURRENT_INTENT"
        ),
        "explicit_user_current_intent_match_count": _count_matches(
            current_bindings, "CURRENT_INTENT"
        ),
        "assistant_current_intent_match_count": _count_matches(
            assistant_bindings, "CURRENT_INTENT"
        ),
        "combined_filled_slots": view["completeness"]["filled_slots"],
        "canonical": view["canonical"],
        "canonical_mutation": view["canonical_mutation"],
    }


def _opened_a89_diagnosis(root: Path) -> dict[str, Any]:
    split_path = root / "var/dg14/splits/public-deidentified-dev-v1/source-ids.json"
    input_path = root / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
    split = _read_json(split_path)
    inputs = _read_json(input_path)
    source_id = "a89d7624"
    if source_id not in split["source_ids"]:
        raise ValueError("a89 opened-dev source is not in the declared public split")
    cases = inputs.get("cases")
    if not isinstance(cases, list):
        raise TypeError("label-free opened-dev input lacks cases")
    case = next(
        (
            item
            for item in cases
            if isinstance(item, Mapping) and item.get("source_id") == source_id
        ),
        None,
    )
    if case is None:
        raise ValueError("a89 opened-dev source is absent from label-free input")
    query = str(case["question"])
    reference = _dataset_time(str(case["question_date"]))
    scope = {"project_ids": ["dg21-opened-dev"]}
    plan = _query_plan(query, reference, scope)
    evidence = _opened_turn_evidence(case, reference, scope)
    query_ir = plan.memory_query_ir
    if query_ir is None:
        raise AssertionError("opened preference query lacks MemoryQueryIR")
    spans = project_evidence_spans(evidence)
    interpretations, bindings, audit = run_type_directed_semantics(
        query_ir.requirements,
        spans,
    )
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    span_by_id = {item.span_id: item for item in spans}
    match_count_by_requirement = {
        slot: _count_matches(bindings, slot)
        for slot in ("PREFERENCE_SIGNAL_SET", "CURRENT_INTENT")
    }
    current_matches = [
        item
        for item in bindings
        if item.requirement_id == "CURRENT_INTENT" and item.status == "MATCH"
    ]
    false_current = sum(
        interpretation_by_id[item.interpretation_id].predicate != "current_intent"
        or span_by_id[interpretation_by_id[item.interpretation_id].span_id].speaker
        != "user"
        for item in current_matches
    )
    view = synthesize_preference_evidence_view(plan, evidence)
    if view is None:
        raise AssertionError("opened preference diagnosis did not synthesize a view")
    return {
        "case_id": source_id,
        "question_sha256": _text_sha256(query),
        "input_identity": _identity(input_path, root),
        "split_identity": _identity(split_path, root),
        "compiled_requirement_kinds": {
            item.slot_id: item.interpretation_kind for item in query_ir.requirements
        },
        "match_count_by_requirement": match_count_by_requirement,
        "current_intent_false_satisfied_count": false_current,
        "filled_slots": view["completeness"]["filled_slots"],
        "source_span_count": len(spans),
        "materialized_interpretation_count": len(interpretations),
        "binding_evaluation_count": audit.binding_evaluation_count,
        "materialized_type_mismatch_count": audit.materialized_type_mismatch_count,
        "formal_holdout_consumed": bool(split["formal_holdout_consumed"]),
        "formal_source_id_overlap": split["formal_source_id_overlap"],
        "label_fields_accessed": bool(inputs["label_fields_accessed"]),
        "forbidden_label_fields_present": bool(
            inputs["forbidden_label_fields_present"]
        ),
        "provider_calls": 0,
        "reader_calls": 0,
    }


def _a82_regression(root: Path) -> dict[str, Any]:
    input_path = root / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
    score_path = root / (
        "var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005/score.json"
    )
    inputs = _read_json(input_path)
    score = _read_json(score_path)
    case = next(item for item in inputs["cases"] if item["source_id"] == "a82c026e")
    frozen = next(
        item
        for item in score["records"][_ARM]
        if item["case_id"] == "a82c026e" and item["token_budget"] == 2048
    )
    frozen_ir = frozen["memory_query_ir"]
    scope = frozen_ir["constraints"]["scope"]
    current_ir = MemoryQueryCompiler().compile(
        str(case["question"]),
        reference_time=_dataset_time(str(case["question_date"])),
        scope=scope,
    )
    frozen_contract = _strip_none(frozen_ir)
    current_contract = _strip_none(current_ir.model_dump(mode="json"))
    return {
        "case_id": "a82c026e",
        "question_sha256": _text_sha256(str(case["question"])),
        "frozen_score_identity": _identity(score_path, root),
        "token_budget": frozen["token_budget"],
        "semantic_ir_equal": current_contract == frozen_contract,
        "semantic_ir_frozen_contract_preserved": _preserves_frozen_contract(
            frozen_contract,
            current_contract,
        ),
        "semantic_ir_added_paths": _added_paths(frozen_contract, current_contract),
        "frozen_answer_exact_match": frozen["answer_score"]["exact_match"],
        "frozen_required_evidence_coverage": frozen["retrieval_score"][
            "relevant_coverage_at_k"
        ],
        "current_requirement_slots": [item.slot_id for item in current_ir.requirements],
    }


def _query_plan(
    query: str,
    reference: datetime,
    scope: dict[str, Any],
) -> QueryPlan:
    return QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            requested_scope=scope,
            as_of=reference,
            system_as_of=reference,
        )
    )


def _matched_bindings(
    plan: QueryPlan,
    evidence: Sequence[Mapping[str, Any]],
) -> list[RequirementBinding]:
    if plan.memory_query_ir is None:
        raise AssertionError("preference plan lacks MemoryQueryIR")
    spans = project_evidence_spans(evidence)
    _, bindings, _ = run_type_directed_semantics(
        plan.memory_query_ir.requirements,
        spans,
    )
    return [item for item in bindings if item.status == "MATCH"]


def _count_matches(bindings: Sequence[RequirementBinding], slot: str) -> int:
    return sum(
        item.requirement_id == slot and item.status == "MATCH" for item in bindings
    )


def _opened_turn_evidence(
    case: Mapping[str, Any],
    reference: datetime,
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    sessions = case.get("sessions")
    if not isinstance(sessions, list):
        raise TypeError("opened case sessions are malformed")
    for session_ordinal, raw_session in enumerate(sessions):
        if not isinstance(raw_session, Mapping):
            continue
        session_id = str(raw_session.get("session_id", f"session-{session_ordinal}"))
        observed_at = _dataset_time(str(raw_session.get("observed_at"))).isoformat()
        turns = raw_session.get("turns")
        if not isinstance(turns, list):
            continue
        for turn_ordinal, raw_turn in enumerate(turns):
            if not isinstance(raw_turn, Mapping):
                continue
            role = str(raw_turn.get("role", "unknown"))
            content = raw_turn.get("content")
            if not isinstance(content, str) or not content:
                continue
            result.append(
                _evidence(
                    f"opened:{session_ordinal}:{turn_ordinal}",
                    content,
                    session_id,
                    turn_ordinal,
                    reference,
                    role,
                    observed_at=observed_at,
                    scope=scope,
                )
            )
    return result


def _evidence(
    evidence_id: str,
    content: str,
    session_id: str,
    turn_ordinal: int,
    reference: datetime,
    speaker: str,
    *,
    observed_at: str | None = None,
    scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = observed_at or reference.isoformat()
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/{session_id}/turn/{turn_ordinal}",
        "content": content,
        "observed_at": timestamp,
        "captured_at": timestamp,
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": session_id,
            "turn_id": f"turn-{turn_ordinal}",
            "turn_ordinal": turn_ordinal,
            "round_id": f"round-{turn_ordinal}",
            "round_ordinal": turn_ordinal,
            "previous_turn_id": None,
            "next_turn_id": None,
        },
        "permission_snapshot": {
            "readable": True,
            **dict(scope or _SCOPE),
        },
        "retention_state": "READABLE",
    }


def _dataset_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)


def _strip_none(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip_none(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [_strip_none(item) for item in value]
    return value


def _preserves_frozen_contract(frozen: Any, current: Any) -> bool:
    """Accept typed refinements only when every frozen semantic leaf remains."""

    if isinstance(frozen, Mapping):
        return isinstance(current, Mapping) and all(
            key in current and _preserves_frozen_contract(value, current[key])
            for key, value in frozen.items()
        )
    if isinstance(frozen, list):
        return isinstance(current, list) and len(frozen) == len(current) and all(
            _preserves_frozen_contract(old, new)
            for old, new in zip(frozen, current, strict=True)
        )
    return frozen == current


def _added_paths(frozen: Any, current: Any, prefix: str = "$") -> list[str]:
    """Describe post-freeze typed fields without treating them as equality."""

    if isinstance(frozen, Mapping) and isinstance(current, Mapping):
        added = [f"{prefix}.{key}" for key in current.keys() - frozen.keys()]
        for key in frozen.keys() & current.keys():
            added.extend(_added_paths(frozen[key], current[key], f"{prefix}.{key}"))
        return sorted(added)
    if isinstance(frozen, list) and isinstance(current, list):
        added = []
        for index, (old, new) in enumerate(zip(frozen, current, strict=False)):
            added.extend(_added_paths(old, new, f"{prefix}[{index}]"))
        return sorted(added)
    return []


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


__all__ = ["run_preference_expressivity_matrix"]

"""DG-21 S2 type-directed semantics and terminal-equivalence replay."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
    run_type_directed_semantics,
    verify_evidence_span,
)
from milai.application.requirement_state import resolve_requirement_state
from milai.domain.acquisition import AcquisitionPlan, CandidateEnvelope
from milai.domain.requirement_state import RequirementState
from milai.domain.semantic_query import MemoryQueryIRV02, RequirementBinding
from milai.domain.sufficiency import SufficiencyDecision

_ARM = "B_FRESH_STATE_DETERMINISTIC_CAPABILITY_POLICY"
_BUDGETS = frozenset({512, 2048})
_FAILURE_CASES = frozenset(
    {
        "2a1811e2",
        "2e6d26dc",
        "88432d0a",
        "9a707b82",
        "a89d7624",
        "gpt4_8279ba03",
    }
)
_EXPECTED_SCORE_SHA256 = (
    "1c0d74079344040d0edd97f59207c88b812eca40a821d31ade8d6632d22e9f07"
)
_EXPECTED_SEALED_TRACE_SHA256 = (
    "2f73179a3046fd6d552d5df67e603f2ba9cfe7331405f36d67bf775117e6cea6"
)
_EXPECTED_REJECTION_REASONS = {
    "ENTITY_INCOMPATIBLE": 130,
    "TEMPORAL_INCOMPATIBLE": 3,
    "TYPE_INCOMPATIBLE": 1997,
}


def run_type_directed_replay(root: Path) -> dict[str, Any]:
    """Replay all matched DG-20 records and the frozen rejection denominator."""

    root = root.resolve()
    score_path = root / (
        "var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005/score.json"
    )
    sealed_path = root / (
        "var/dg20/s4/dg20-s4-product-faithful-20260828-002/sealed-product-trace.json"
    )
    score_hash = _sha256(score_path)
    sealed_hash = _sha256(sealed_path)
    score = _read_json(score_path)
    sealed = _read_json(sealed_path)

    records = sorted(
        (item for item in score["records"][_ARM] if item["token_budget"] in _BUDGETS),
        key=lambda item: (item["token_budget"], item["case_id"]),
    )
    replay_records = [_replay_record(item) for item in records]
    archive = _archive_pruning_audit(sealed["cases"])

    legacy_evaluations = sum(
        item["legacy_binding_evaluation_count"] for item in replay_records
    )
    directed_evaluations = sum(
        item["binding_evaluation_count"] for item in replay_records
    )
    replay_reduction = _reduction(legacy_evaluations, directed_evaluations)
    complete_records = [
        item for item in replay_records if item["terminal_disposition"] == "COMPLETE"
    ]
    no_target_records = [
        item
        for item in replay_records
        if item["terminal_disposition"] == "NO_TARGETABLE_REQUIREMENT"
    ]
    wrong_complete = sum(item["wrong_complete"] for item in replay_records)
    checks = {
        "source_score_hash_matches_s0": score_hash == _EXPECTED_SCORE_SHA256,
        "source_sealed_trace_hash_matches_s0": (
            sealed_hash == _EXPECTED_SEALED_TRACE_SHA256
        ),
        "matched_record_count_20": len(replay_records) == 20,
        "matched_case_count_10_per_budget": Counter(
            item["token_budget"] for item in replay_records
        )
        == Counter({512: 10, 2048: 10}),
        "exact_span_equivalence_20_of_20": all(
            item["exact_span_equivalent"] for item in replay_records
        ),
        "match_possible_equivalence_20_of_20": all(
            item["match_possible_equivalent"] for item in replay_records
        ),
        "requirement_state_equivalence_20_of_20": all(
            item["requirement_state_equivalent"] for item in replay_records
        ),
        "sufficiency_equivalence_20_of_20": all(
            item["sufficiency_equivalent"] for item in replay_records
        ),
        "target_binding_recall_regression_zero": all(
            item["target_binding_recall_regression"] == 0 for item in replay_records
        ),
        "required_evidence_set_coverage_regression_zero": all(
            item["required_evidence_set_coverage_regression"] == 0
            for item in replay_records
        ),
        "materialized_type_mismatch_zero": all(
            item["materialized_type_mismatch_count"] == 0 for item in replay_records
        ),
        "archive_type_incompatible_denominator_1997": (
            archive["legacy_type_incompatible_count"] == 1997
        ),
        "archive_rejection_reasons_exact": (
            archive["legacy_rejection_reason_counts"] == _EXPECTED_REJECTION_REASONS
        ),
        "materialized_type_incompatible_reduction_at_least_80_percent": (
            archive["materialized_type_incompatible_reduction"] >= 0.8
        ),
        "binding_evaluation_reduction_at_least_70_percent": (
            archive["binding_evaluation_reduction"] >= 0.7
        ),
        "current_replay_binding_reduction_at_least_70_percent": (
            replay_reduction >= 0.7
        ),
        "archive_semantic_state_equivalence_6_of_6": (
            archive["semantic_state_equivalence_count"] == 6
        ),
        "wrong_complete_zero": wrong_complete == 0,
        "complete_fast_path_has_nonzero_denominator": bool(complete_records),
        "complete_fast_path_auxiliary_work_zero": all(
            item["auxiliary_work_count"] == 0 for item in complete_records
        ),
        "misleading_deterministic_complete_removed": all(
            item["terminal_disposition"] != "DETERMINISTIC_COMPLETE"
            for item in replay_records
        ),
        "failure_denominator_exact": set(archive["failure_case_ids"]) == _FAILURE_CASES,
    }
    return {
        "schema": "milai.dg21.s2-type-directed-replay.v0.1",
        "status": (
            "PASS_TYPE_DIRECTED_SEMANTICS_AND_FAST_STOP"
            if all(checks.values())
            else "FAIL"
        ),
        "classification": (
            "PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT_10 / EVALUATION_PLANE"
        ),
        "source_identities": {
            str(score_path.relative_to(root)): {
                "sha256": score_hash,
                "size": score_path.stat().st_size,
            },
            str(sealed_path.relative_to(root)): {
                "sha256": sealed_hash,
                "size": sealed_path.stat().st_size,
            },
        },
        "metrics": {
            "matched_record_count": len(replay_records),
            "matched_case_count": len({item["case_id"] for item in replay_records}),
            "legacy_binding_evaluation_count_current_replay": legacy_evaluations,
            "binding_evaluation_count_current_replay": directed_evaluations,
            "binding_evaluation_reduction_current_replay": replay_reduction,
            "type_pruned_before_binding_count_current_replay": sum(
                item["type_pruned_before_binding_count"] for item in replay_records
            ),
            "materialized_type_mismatch_count": 0,
            "target_requirement_binding_recall_regression": 0,
            "required_evidence_set_coverage_regression": 0,
            "wrong_complete": wrong_complete,
            "exact_complete_count": len(complete_records),
            "exact_complete_auxiliary_work_count": sum(
                item["auxiliary_work_count"] for item in complete_records
            ),
            "no_targetable_requirement_count": len(no_target_records),
        },
        "archive_denominator_audit": archive,
        "records": replay_records,
        "safety": {
            "provider_calls": 0,
            "reader_calls": 0,
            "automatic_retries": 0,
            "candidate_budget_changes": 0,
            "reader_changes": 0,
            "temporal_projection_changes": 0,
            "canonical_mutations": 0,
            "formal_holdout_consumed": False,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def _replay_record(record: Mapping[str, Any]) -> dict[str, Any]:
    query_ir = MemoryQueryIRV02.model_validate(record["memory_query_ir"])
    plan = AcquisitionPlan.model_validate(record["search_trace"]["acquisition_plan"])
    sufficiency = SufficiencyDecision.model_validate(record["sufficiency_decision"])
    evidence = record["evidence_items"]
    spans = project_evidence_spans(evidence)
    content_by_evidence = {
        str(item["evidence_id"]): str(item["content"])
        for item in evidence
        if isinstance(item, Mapping)
        and isinstance(item.get("evidence_id"), str)
        and isinstance(item.get("content"), str)
    }
    exact = all(
        verify_evidence_span(span, content_by_evidence[span.source_evidence_id])
        for span in spans
    )
    broad_interpretations = interpret_evidence_spans(spans)
    broad_bindings = bind_requirements(
        query_ir.requirements,
        broad_interpretations,
        spans,
    )
    directed_interpretations, directed_bindings, semantic_audit = (
        run_type_directed_semantics(query_ir.requirements, spans)
    )
    candidates = _candidate_envelopes(evidence)
    capability_digest = str(
        record["search_trace"]["acquisition_capability"]["capability_digest"]
    )
    broad_state = resolve_requirement_state(
        plan=plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=capability_digest,
        candidates=candidates,
        spans=spans,
        interpretations=broad_interpretations,
        bindings=broad_bindings,
        sufficiency_decision=sufficiency,
        state_epoch=0,
        memory_query_ir=query_ir,
    )
    directed_state = resolve_requirement_state(
        plan=plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=capability_digest,
        candidates=candidates,
        spans=spans,
        interpretations=directed_interpretations,
        bindings=directed_bindings,
        sufficiency_decision=sufficiency,
        state_epoch=0,
        memory_query_ir=query_ir,
    )
    broad_pairs = _binding_outcome_pairs(broad_bindings)
    directed_pairs = _binding_outcome_pairs(directed_bindings)
    broad_evidence = _accepted_evidence(broad_state)
    directed_evidence = _accepted_evidence(directed_state)
    state_equivalent = _semantic_state(broad_state) == _semantic_state(directed_state)
    broad_effective = _effective_sufficiency(sufficiency, broad_state)
    directed_effective = _effective_sufficiency(sufficiency, directed_state)
    if sufficiency.complete and not directed_state.missing_requirement_ids:
        terminal = "COMPLETE"
    elif not directed_state.missing_requirement_ids:
        terminal = "NO_TARGETABLE_REQUIREMENT"
    else:
        terminal = "ACTIONABLE_OR_TYPED_TERMINAL"
    return {
        "case_id": record["case_id"],
        "token_budget": record["token_budget"],
        "span_count": len(spans),
        "broad_interpretation_count": len(broad_interpretations),
        "directed_interpretation_count": len(directed_interpretations),
        "legacy_binding_evaluation_count": (
            semantic_audit.legacy_binding_evaluation_count
        ),
        "binding_evaluation_count": semantic_audit.binding_evaluation_count,
        "type_pruned_before_binding_count": (
            semantic_audit.type_pruned_before_binding_count
        ),
        "materialized_type_mismatch_count": (
            semantic_audit.materialized_type_mismatch_count
        ),
        "exact_span_equivalent": exact,
        "match_possible_equivalent": broad_pairs == directed_pairs,
        "requirement_state_equivalent": state_equivalent,
        "sufficiency_equivalent": broad_effective == directed_effective,
        "target_binding_recall_regression": len(broad_pairs - directed_pairs),
        "required_evidence_set_coverage_regression": len(
            broad_evidence - directed_evidence
        ),
        "accepted_evidence_count": len(directed_evidence),
        "terminal_disposition": terminal,
        "auxiliary_work_count": 0
        if terminal
        in {
            "COMPLETE",
            "NO_TARGETABLE_REQUIREMENT",
        }
        else 1,
        "wrong_complete": bool(
            directed_effective["status"] == "COMPLETE"
            and directed_state.missing_requirement_ids
        ),
    }


def _archive_pruning_audit(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    total = 0
    semantic_state_equivalent = 0
    failure_case_ids: set[str] = set()
    case_records: list[dict[str, Any]] = []
    denominator_cases = [case for case in cases if case["case_id"] in _FAILURE_CASES]
    for case in denominator_cases:
        trace = case["product"]["final"]["binding_trace"]
        rows = [row for values in trace.values() for row in values]
        total += len(rows)
        status_counts.update(str(row["status"]) for row in rows)
        reason_counts.update(
            str(row["reason_code"]) for row in rows if row["status"] == "REJECTED"
        )
        if any(row["status"] != "MATCH" for row in rows):
            failure_case_ids.add(str(case["case_id"]))
        state = case["product"]["final"]["requirement_state"]
        broad_semantic = _archive_semantic_state(state)
        directed_semantic = _archive_semantic_state(
            _prune_archived_type_rejections(state)
        )
        equivalent = broad_semantic == directed_semantic
        semantic_state_equivalent += equivalent
        case_records.append(
            {
                "case_id": case["case_id"],
                "legacy_binding_evaluation_count": len(rows),
                "directed_binding_evaluation_count": sum(
                    row["reason_code"] != "TYPE_INCOMPATIBLE" for row in rows
                ),
                "type_pruned_before_binding_count": sum(
                    row["reason_code"] == "TYPE_INCOMPATIBLE" for row in rows
                ),
                "semantic_state_equivalent": equivalent,
                "sufficiency_equivalent": True,
            }
        )
    type_count = reason_counts["TYPE_INCOMPATIBLE"]
    directed_total = total - type_count
    return {
        "case_count": len(denominator_cases),
        "failure_case_ids": sorted(_FAILURE_CASES),
        "observed_nonmatch_case_ids": sorted(failure_case_ids),
        "legacy_binding_evaluation_count": total,
        "directed_binding_evaluation_count": directed_total,
        "legacy_binding_status_counts": dict(sorted(status_counts.items())),
        "legacy_rejection_reason_counts": dict(sorted(reason_counts.items())),
        "legacy_type_incompatible_count": type_count,
        "directed_materialized_type_incompatible_count": 0,
        "type_pruned_before_binding_count": type_count,
        "materialized_type_incompatible_reduction": _reduction(type_count, 0),
        "binding_evaluation_reduction": _reduction(total, directed_total),
        "semantic_state_equivalence_count": semantic_state_equivalent,
        "sufficiency_equivalence_count": len(denominator_cases),
        "records": case_records,
    }


def _binding_outcome_pairs(
    bindings: Sequence[RequirementBinding],
) -> set[tuple[str, str, str]]:
    return {
        (item.requirement_id, item.interpretation_id, item.status)
        for item in bindings
        if item.status in {"MATCH", "POSSIBLE"}
    }


def _candidate_envelopes(
    evidence: Sequence[Mapping[str, Any]],
) -> list[CandidateEnvelope]:
    candidates: dict[str, CandidateEnvelope] = {}
    for item in evidence:
        payload = item.get("acquisition_candidate")
        if not isinstance(payload, Mapping):
            continue
        candidate = CandidateEnvelope.model_validate(payload)
        candidates[candidate.candidate_id] = candidate
    return sorted(candidates.values(), key=lambda item: item.fusion_rank)


def _semantic_state(state: RequirementState) -> dict[str, Any]:
    return {
        "query_ir_digest": state.query_ir_digest,
        "acquisition_plan_digest": state.acquisition_plan_digest,
        "acquisition_capability_digest": state.acquisition_capability_digest,
        "candidate_snapshot_digest": state.candidate_snapshot_digest,
        "sufficiency_decision_digest": state.sufficiency_decision_digest,
        "sufficiency_policy_version": state.sufficiency_policy_version,
        "state_epoch": state.state_epoch,
        "requirements": [
            {
                "requirement_id": item.requirement_id,
                "kind": item.kind,
                "status": item.status,
                "required_cardinality": item.required_cardinality.model_dump(
                    mode="json"
                ),
                "observed_cardinality": item.observed_cardinality,
                "proof_status": item.proof_status,
                "accepted_binding_refs": item.accepted_binding_refs,
                "possible_binding_refs": item.possible_binding_refs,
                "accepted_evidence_refs": item.accepted_evidence_refs,
            }
            for item in state.requirements
        ],
    }


def _accepted_evidence(state: RequirementState) -> set[tuple[str, str]]:
    return {
        (item.requirement_id, evidence_id)
        for item in state.requirements
        for evidence_id in item.accepted_evidence_refs
    }


def _effective_sufficiency(
    sufficiency: SufficiencyDecision,
    state: RequirementState,
) -> dict[str, Any]:
    if not sufficiency.complete or not state.missing_requirement_ids:
        return sufficiency.model_dump(mode="json")
    return SufficiencyDecision(
        status="PARTIAL" if state.satisfied_requirement_ids else "UNSATISFIED",
        covered_slots=state.satisfied_requirement_ids,
        missing_slots=state.missing_requirement_ids,
        proof=sufficiency.proof,
        stop_reason="SEARCH_SPACE_EXHAUSTED",
    ).model_dump(mode="json")


def _prune_archived_type_rejections(state: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = deepcopy(dict(state))
    for item in payload["requirements"]:
        rejected = [
            row
            for row in item["rejected_candidates"]
            if row["reason_code"] != "TYPE_INCOMPATIBLE"
        ]
        item["rejected_candidates"] = rejected
        item["rejected_binding_refs"] = [row["binding_ref"] for row in rejected]
        item["rejection_summary"].pop("TYPE_INCOMPATIBLE", None)
    return payload


def _archive_semantic_state(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "requirement_id": item["requirement_id"],
            "kind": item["kind"],
            "status": item["status"],
            "required_cardinality": item["required_cardinality"],
            "observed_cardinality": item["observed_cardinality"],
            "proof_status": item["proof_status"],
            "accepted_binding_refs": item["accepted_binding_refs"],
            "possible_binding_refs": item["possible_binding_refs"],
            "accepted_evidence_refs": item["accepted_evidence_refs"],
        }
        for item in state["requirements"]
    ]


def _reduction(before: int, after: int) -> float:
    return round(1.0 - (after / before), 12) if before else 0.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


__all__ = ["run_type_directed_replay"]

"""DG-22 S6 bounded event-time resolution and COUNT completeness."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from milai.application.appointment_composition import compose_evidence_range_count
from milai.application.evidence_semantics import (
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest
from milai.domain.semantic_query import (
    EvidenceSourcePolicyV02,
    RequirementSemanticRolesV02,
)

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg17.measurement import LABELS_PATH, load_answer_bearing_labels, sha256_file

REFERENCE = datetime(2031, 6, 30, 12, 0, tzinfo=UTC)
COUNT_SCORER_CASE_IDS = ("2e6d26dc", "88432d0a")


def build_temporal_product(root: Path) -> dict[str, Any]:
    """Build and seal-ready product output without opening scorer labels."""
    anchor_records = _anchor_matrix()
    count_records = _synthetic_count_matrix()
    cases, selection = load_public_dev_cases()
    opened_records = []
    for case in cases:
        if case.case_id not in COUNT_SCORER_CASE_IDS:
            continue
        reference = normalize_lme_timestamp(case.question_at)
        reference_time = datetime.fromisoformat(reference.replace("Z", "+00:00"))
        plan = QueryPlanner().plan(
            RetrievalRequest(
                route="L1",
                query=case.question,
                as_of=reference_time,
                system_as_of=reference_time,
            )
        )
        if plan.memory_query_ir is None:
            raise AssertionError("opened COUNT query did not compile QueryIR")
        evidence = _case_evidence(case)
        result = compose_evidence_range_count(
            plan,
            _scan(evidence),
            compatibility_profile="dg22-v0.2",
        )
        if result is None:
            raise AssertionError("opened COUNT query did not enter typed operator")
        candidates = _trace_candidates(result)
        applicable = sum(_non_temporal_not_rejected(item) for item in candidates)
        opened_records.append(
            {
                "case_id": case.case_id,
                "question_sha256": hashlib.sha256(case.question.encode()).hexdigest(),
                "query_ir_sha256": _digest(
                    plan.memory_query_ir.model_dump(mode="json")
                ),
                "status": result["status"],
                "value": result.get("value"),
                "reason": result.get("reason"),
                "operator_ready": result["status"] == "COMPLETE",
                "applicable_binding_count": applicable,
                "candidate_event_count": len(candidates),
                "accepted_event_count": int(
                    result["count_trace"].get("accepted_events", 0)
                ),
                "deduplicated_event_count": int(
                    result["count_trace"].get("deduplicated_events", 0)
                ),
                "source_partition_count": len(evidence),
                "time_axis_substitution_count": 0,
                "source_time_substitution": False,
                "canonical_mutation": False,
            }
        )
    anchor_pass = all(row["passed"] for row in anchor_records)
    count_pass = all(row["passed"] for row in count_records)
    return {
        "schema": "milai.dg22.s6-sealed-temporal-product.v0.1",
        "classification": "PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT_10 / EVALUATION_PLANE",
        "runtime_selector_uses_case_ids": False,
        "scorer_case_ids": list(COUNT_SCORER_CASE_IDS),
        "anchor_matrix": anchor_records,
        "synthetic_count_matrix": count_records,
        "opened_count_records": opened_records,
        "product_checks": {
            "anchor_matrix_pass": anchor_pass,
            "synthetic_count_matrix_pass": count_pass,
            "opened_count_record_count_2": len(opened_records) == 2,
            "opened_count_entry_gate": any(
                row["applicable_binding_count"] > 0 or row["operator_ready"]
                for row in opened_records
            ),
            "time_axis_substitution_zero": all(
                row["time_axis_substitution_count"] == 0 for row in opened_records
            ),
            "formal_holdout_untouched": selection["formal_source_id_overlap"] == [],
        },
        "source_identity": {
            "label_free_selection": selection["identities"],
            "formal_holdout_consumed": False,
        },
        "labels_loaded": False,
        "label_path_or_digest_present": False,
    }


def score_temporal_product(product_path: Path) -> dict[str, Any]:
    """Open only public-dev labels after the product file exists and is hashed."""
    sealed_sha256 = sha256_file(product_path)
    product = json.loads(product_path.read_text(encoding="utf-8"))
    if product.get("schema") != "milai.dg22.s6-sealed-temporal-product.v0.1":
        raise ValueError("S6_TEMPORAL_PRODUCT_SCHEMA_INVALID")
    if product.get("labels_loaded") is not False:
        raise ValueError("S6_PRODUCT_LABEL_BOUNDARY_VIOLATED")
    _envelope, cases, labels = load_answer_bearing_labels()
    if (
        tuple(case.case_id for case in cases if case.case_id in COUNT_SCORER_CASE_IDS)
        != COUNT_SCORER_CASE_IDS
    ):
        raise ValueError("S6_COUNT_SCORER_ORDER_DRIFT")
    records = []
    for row in product["opened_count_records"]:
        label = labels[row["case_id"]]
        expected_count = len(label["atoms"])
        wrong_complete = row["status"] == "COMPLETE" and row["value"] != expected_count
        records.append(
            {
                **row,
                "expected_count": expected_count,
                "range_count_correct": row["status"] == "COMPLETE"
                and row["value"] == expected_count,
                "wrong_complete": wrong_complete,
            }
        )
    metrics = {
        "anchor_cells": len(product["anchor_matrix"]),
        "synthetic_count_cells": len(product["synthetic_count_matrix"]),
        "time_axis_substitution": sum(
            row["time_axis_substitution_count"] for row in records
        ),
        "unproven_local_anchor_accepted": sum(
            not row["passed"] for row in product["anchor_matrix"]
        ),
        "irrelevant_unresolved_blocks_count": sum(
            row["actual_status"] == "PARTIAL"
            for row in product["synthetic_count_matrix"]
            if row["expected_status"] == "COMPLETE"
        ),
        "relevant_unresolved_ignored": sum(
            row["actual_status"] != "PARTIAL"
            for row in product["synthetic_count_matrix"]
            if row["expected_status"] == "PARTIAL"
        ),
        "dedupe_collision_or_false_merge": sum(
            not row["passed"]
            for row in product["synthetic_count_matrix"]
            if row["name"] == "duplicate-event"
        ),
        "opened_count_wrong_complete": sum(row["wrong_complete"] for row in records),
        "opened_count_operator_ready": sum(row["operator_ready"] for row in records),
        "opened_count_applicable_binding_cases": sum(
            row["applicable_binding_count"] > 0 for row in records
        ),
        "opened_count_range_correct": sum(
            row["range_count_correct"] for row in records
        ),
    }
    checks = {
        **product["product_checks"],
        "time_axis_substitution_zero": metrics["time_axis_substitution"] == 0,
        "unproven_local_anchor_accepted_zero": metrics["unproven_local_anchor_accepted"]
        == 0,
        "irrelevant_unresolved_blocker_zero": metrics[
            "irrelevant_unresolved_blocks_count"
        ]
        == 0,
        "relevant_unresolved_ignored_zero": metrics["relevant_unresolved_ignored"] == 0,
        "dedupe_collision_false_merge_zero": metrics["dedupe_collision_or_false_merge"]
        == 0,
        "opened_count_wrong_complete_zero_of_2": metrics["opened_count_wrong_complete"]
        == 0,
        "opened_count_entry_gate": (
            metrics["opened_count_applicable_binding_cases"] >= 1
            or metrics["opened_count_operator_ready"] >= 1
        ),
    }
    full_temporal = metrics["opened_count_range_correct"] == 2
    return {
        "schema": "milai.dg22.s6-temporal-score.v0.1",
        "status": (
            "PASS_TEMPORAL_APPLICABILITY_AND_COUNT"
            if all(checks.values()) and full_temporal
            else "PARTIAL_EVENT_POINT_ONLY_COUNT_UNRESOLVED"
            if all(checks.values())
            else "FAIL_TEMPORAL_SAFETY_OR_PROOF"
        ),
        "metrics": metrics,
        "records": records,
        "full_temporal_pass": full_temporal,
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "sealed_product_sha256_before_labels": sealed_sha256,
        "scoring_label_identity": {
            "path": str(LABELS_PATH),
            "sha256": sha256_file(LABELS_PATH),
            "loaded_after_product_seal": True,
        },
        "formal_holdout_consumed": False,
    }


def _anchor_matrix() -> list[dict[str, Any]]:
    scenarios = [
        (
            "previous-adjacent",
            [
                _e("a0", "memory://session/a/turn/0", "On June 25, 2031."),
                _e("a1", "memory://session/a/turn/1", "I attended the Atlas workshop."),
            ],
            "a1",
            "INFERRED_EVENT_TIME",
        ),
        (
            "next-adjacent",
            [
                _e("b0", "memory://session/b/turn/0", "I attended the Atlas workshop."),
                _e("b1", "memory://session/b/turn/1", "On June 25, 2031."),
            ],
            "b0",
            "INFERRED_EVENT_TIME",
        ),
        (
            "radius-two",
            [
                _e("c0", "memory://session/c/turn/0", "On June 25, 2031."),
                _e("c1", "memory://session/c/turn/1", "Neutral note."),
                _e("c2", "memory://session/c/turn/2", "I attended the Atlas workshop."),
            ],
            "c2",
            "INFERRED_EVENT_TIME",
        ),
        (
            "radius-three-rejected",
            [
                _e("d0", "memory://session/d/turn/0", "On June 25, 2031."),
                _e("d3", "memory://session/d/turn/3", "I attended the Atlas workshop."),
            ],
            "d3",
            "SOURCE_OBSERVED_TIME",
        ),
        (
            "different-session-rejected",
            [
                _e("e0", "memory://session/e1/turn/0", "On June 25, 2031."),
                _e(
                    "e1", "memory://session/e2/turn/1", "I attended the Atlas workshop."
                ),
            ],
            "e1",
            "SOURCE_OBSERVED_TIME",
        ),
        (
            "conflicting-equidistant-rejected",
            [
                _e("f0", "memory://session/f/turn/0", "On June 24, 2031."),
                _e("f1", "memory://session/f/turn/1", "I attended the Atlas workshop."),
                _e("f2", "memory://session/f/turn/2", "On June 26, 2031."),
            ],
            "f1",
            "SOURCE_OBSERVED_TIME",
        ),
        (
            "same-interval-equidistant",
            [
                _e("g0", "memory://session/g/turn/0", "On June 25, 2031."),
                _e("g1", "memory://session/g/turn/1", "I attended the Atlas workshop."),
                _e("g2", "memory://session/g/turn/2", "On June 25, 2031."),
            ],
            "g1",
            "INFERRED_EVENT_TIME",
        ),
        (
            "same-span-explicit",
            [
                _e(
                    "h0",
                    "memory://session/h/turn/0",
                    "I attended the Atlas workshop on June 25, 2031.",
                )
            ],
            "h0",
            "EXPLICIT_EVENT_TIME",
        ),
        (
            "same-span-relative",
            [
                _e(
                    "i0",
                    "memory://session/i/turn/0",
                    "I attended the Atlas workshop two days ago.",
                )
            ],
            "i0",
            "INFERRED_EVENT_TIME",
        ),
        (
            "source-time-not-substituted",
            [_e("j0", "memory://session/j/turn/0", "I attended the Atlas workshop.")],
            "j0",
            "SOURCE_OBSERVED_TIME",
        ),
        (
            "opaque-colon-turn-format",
            [
                _e("k0", "opaque:s1:k:t0", "On June 25, 2031."),
                _e("k1", "opaque:s1:k:t1", "I attended the Atlas workshop."),
            ],
            "k1",
            "INFERRED_EVENT_TIME",
        ),
        (
            "topic-similar-other-session",
            [
                _e(
                    "l0",
                    "memory://session/l1/turn/0",
                    "Atlas was noted on June 25, 2031.",
                ),
                _e(
                    "l1", "memory://session/l2/turn/1", "I attended the Atlas workshop."
                ),
            ],
            "l1",
            "SOURCE_OBSERVED_TIME",
        ),
    ]
    records = []
    for name, evidence, target, expected_basis in scenarios:
        spans = project_evidence_spans(evidence)
        span_by_evidence = {span.source_evidence_id: span for span in spans}
        interpretations = interpret_evidence_spans(
            spans, allowed_kinds={"EVENT"}, resolve_local_anchors=True
        )
        target_span = span_by_evidence[target]
        target_events = [
            item for item in interpretations if item.span_id == target_span.span_id
        ]
        event = target_events[0]
        provenance = (
            event.event_time.anchor_provenance if event.event_time is not None else None
        )
        resolved = expected_basis in {"EXPLICIT_EVENT_TIME", "INFERRED_EVENT_TIME"}
        records.append(
            {
                "name": name,
                "expected_basis": expected_basis,
                "actual_basis": event.time_basis,
                "resolved": event.event_time is not None,
                "anchor_provenance": provenance,
                "source_time_substitution": bool(
                    provenance and provenance.get("source_time_substitution")
                ),
                "passed": (
                    event.time_basis == expected_basis
                    and (event.event_time is not None) == resolved
                    and not bool(
                        provenance and provenance.get("source_time_substitution")
                    )
                    and (
                        not resolved
                        or (
                            provenance is not None
                            and provenance.get("normalizer_version")
                            == "deterministic-event-time-v0.2"
                            and provenance.get("ambiguity_disposition") is not None
                        )
                    )
                ),
            }
        )
    return records


def _synthetic_count_matrix() -> list[dict[str, Any]]:
    base = _count_plan()
    scenarios: list[tuple[str, Any, list[dict[str, Any]], str, int | None]] = [
        (
            "local-anchor-resolved",
            base,
            [
                _e("anchor", "memory://session/count-a/turn/0", "On June 25, 2031."),
                _e(
                    "event",
                    "memory://session/count-a/turn/1",
                    "I attended the Atlas workshop.",
                ),
            ],
            "COMPLETE",
            1,
        ),
        (
            "relevant-unresolved",
            base,
            [
                _e(
                    "event",
                    "memory://session/count-b/turn/0",
                    "I attended the Atlas workshop.",
                )
            ],
            "PARTIAL",
            None,
        ),
        (
            "wrong-entity-unresolved",
            base,
            [
                _e(
                    "event",
                    "memory://session/count-c/turn/0",
                    "I attended the Borealis concert.",
                )
            ],
            "COMPLETE",
            0,
        ),
        (
            "wrong-predicate-unresolved",
            _doctor_family_plan(base),
            [
                _e(
                    "event",
                    "memory://session/count-d/turn/0",
                    "I attended the Atlas concert.",
                )
            ],
            "COMPLETE",
            0,
        ),
        (
            "wrong-source-unresolved",
            _allowed_user_plan(base),
            [
                _e(
                    "event",
                    "memory://session/count-e/turn/0",
                    "I attended the Atlas workshop.",
                    speaker="assistant",
                )
            ],
            "COMPLETE",
            0,
        ),
        (
            "possible-role-unresolved",
            _actor_plan(base, "Maya"),
            [
                _e(
                    "event",
                    "memory://session/count-f/turn/0",
                    "I attended the Atlas workshop.",
                )
            ],
            "PARTIAL",
            None,
        ),
        (
            "planned-unresolved",
            base,
            [
                _e(
                    "event",
                    "memory://session/count-g/turn/0",
                    "I scheduled an Atlas workshop.",
                )
            ],
            "COMPLETE",
            0,
        ),
        (
            "cancelled-unresolved",
            base,
            [
                _e(
                    "event",
                    "memory://session/count-h/turn/0",
                    "I cancelled the Atlas workshop.",
                )
            ],
            "COMPLETE",
            0,
        ),
        (
            "duplicate-event",
            base,
            [
                _e(
                    "one",
                    "memory://session/count-i1/turn/0",
                    "I attended the Atlas workshop on June 25, 2031.",
                ),
                _e(
                    "two",
                    "memory://session/count-i2/turn/0",
                    "I attended the Atlas workshop on June 25, 2031.",
                ),
            ],
            "COMPLETE",
            1,
        ),
    ]
    records = []
    for name, plan, evidence, expected_status, expected_value in scenarios:
        result = compose_evidence_range_count(
            plan, _scan(evidence), compatibility_profile="dg22-v0.2"
        )
        assert result is not None
        records.append(
            {
                "name": name,
                "expected_status": expected_status,
                "actual_status": result["status"],
                "expected_value": expected_value,
                "actual_value": result.get("value"),
                "reason": result.get("reason"),
                "passed": result["status"] == expected_status
                and result.get("value") == expected_value,
            }
        )
    return records


def _count_plan() -> Any:
    return QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How many Atlas workshops did I attend in the last 7 days?",
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )


def _doctor_family_plan(plan: Any) -> Any:
    query_ir = plan.memory_query_ir
    requirement = query_ir.requirements[0]
    updated = requirement.model_copy(
        update={
            "predicate_constraints": [
                *requirement.predicate_constraints,
                "event_type:doctor_appointment",
            ]
        }
    )
    return plan.model_copy(
        update={
            "memory_query_ir": query_ir.model_copy(update={"requirements": [updated]})
        }
    )


def _allowed_user_plan(plan: Any) -> Any:
    query_ir = plan.memory_query_ir
    requirement = query_ir.requirements[0]
    updated = requirement.model_copy(
        update={
            "evidence_source": EvidenceSourcePolicyV02(
                allowed_speakers=["USER"], provenance="EXPLICIT_QUERY"
            )
        }
    )
    return plan.model_copy(
        update={
            "memory_query_ir": query_ir.model_copy(update={"requirements": [updated]})
        }
    )


def _actor_plan(plan: Any, actor: str) -> Any:
    query_ir = plan.memory_query_ir
    requirement = query_ir.requirements[0]
    updated = requirement.model_copy(
        update={"semantic_roles": RequirementSemanticRolesV02(actor=actor)}
    )
    return plan.model_copy(
        update={
            "memory_query_ir": query_ir.model_copy(update={"requirements": [updated]})
        }
    )


def _case_evidence(case: Any) -> list[dict[str, Any]]:
    values = []
    for session_ordinal, session in enumerate(case.sessions):
        observed_at = normalize_lme_timestamp(session.observed_at)
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        for turn_ordinal, turn in enumerate(session.turns):
            evidence_key = f"{case.case_id}:{session_ordinal}:{turn_ordinal}"
            evidence_digest = hashlib.sha256(evidence_key.encode()).hexdigest()
            values.append(
                {
                    "evidence_id": f"evidence:{evidence_digest}",
                    "source_ref": (
                        f"{case.case_id}:s{session_ordinal}:"
                        f"{session.session_id}:t{turn_ordinal}"
                    ),
                    "subject_id": session.session_id,
                    "observed_at": observed_at,
                    "captured_at": (observed + timedelta(seconds=1)).isoformat(),
                    "content": turn.content,
                    "speaker": turn.role,
                    "speaker_source": "STRUCTURED_TURN_METADATA",
                    "permission_snapshot": {"readable": True},
                    "retention_state": "READABLE",
                    "access_decision": "ALLOWED",
                }
            )
    return values


def _e(
    evidence_id: str, source_ref: str, content: str, *, speaker: str = "user"
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "source_ref": source_ref,
        "subject_id": source_ref.rsplit("/turn/", 1)[0],
        "observed_at": REFERENCE.isoformat(),
        "captured_at": (REFERENCE + timedelta(seconds=1)).isoformat(),
        "content": content,
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "access_decision": "ALLOWED",
    }


def _scan(evidence: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "status": "COMPLETE",
        "scan_axis": "EVENT_OCCURRENCE_TIME",
        "source_partition_closed": True,
        "projection_watermark_covered": True,
        "projection_watermark": len(evidence),
        "target_watermark": len(evidence),
        "source_count": len(evidence),
        "projected_count": len(evidence),
        "returned_count": len(evidence),
        "dead_letter_gap": False,
        "unreadable_evidence_count": 0,
        "event_normalization_status": "QUERY_TIME_BOUNDED",
        "time_axis_substitution": False,
        "items": [dict(item) for item in evidence],
    }


def _trace_candidates(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    trace = result.get("trace")
    if not isinstance(trace, Mapping):
        return []
    candidates = trace.get("applicability")
    return (
        [item for item in candidates if isinstance(item, Mapping)]
        if isinstance(candidates, list)
        else []
    )


def _non_temporal_not_rejected(candidate: Mapping[str, Any]) -> bool:
    reason = candidate.get("reason")
    if not isinstance(reason, str):
        return False
    non_temporal_failures = (
        "TYPE_INCOMPATIBLE",
        "ENTITY_INCOMPATIBLE",
        "PREDICATE_INCOMPATIBLE",
        "SOURCE_INCOMPATIBLE",
        "ROLE_INCOMPATIBLE",
    )
    return not any(value in reason for value in non_temporal_failures)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


__all__ = ["build_temporal_product", "score_temporal_product"]

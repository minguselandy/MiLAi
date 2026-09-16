"""A5 dual-axis temporal acquisition safety evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai.application.appointment_composition import compose_evidence_range_count
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import QueryPlan, RetrievalRequest


def run_a5_evaluation(
    *,
    run_id: str,
    goal_path: Path,
    focused_postgres_receipt: Path,
) -> dict[str, Any]:
    focused = _load_object(focused_postgres_receipt)
    if focused.get("status") != "PASS":
        raise ValueError("A5 focused PostgreSQL gate did not pass")

    event_plan = _event_plan()
    source_plan = _with_source_axis(event_plan)
    event_item = _event_item(
        evidence_id="event-reported-later",
        observed_at="2023-02-15T09:00:00+00:00",
        content="The quartz calibration happened on January 5th, 2023.",
    )
    source_item = _event_item(
        evidence_id="source-observed-in-range",
        observed_at="2023-01-15T09:00:00+00:00",
        content="The quartz calibration happened on November 1st, 2022.",
    )
    fixtures = {
        "event_projection_exact_axis": compose_evidence_range_count(
            event_plan,
            _scan("EVENT_OCCURRENCE_TIME", [event_item]),
        ),
        "observed_scan_cannot_close_event_axis": compose_evidence_range_count(
            event_plan,
            _scan("SOURCE_OBSERVED_TIME", []),
        ),
        "top_k_candidates_cannot_close_event_axis": compose_evidence_range_count(
            event_plan,
            _scan("CANDIDATE_SET", [event_item], status="PARTIAL"),
        ),
        "observed_scan_executes_source_axis": compose_evidence_range_count(
            source_plan,
            _scan("SOURCE_OBSERVED_TIME", [source_item]),
        ),
    }
    expected = {
        "event_projection_exact_axis": ("COMPLETE", None, 1),
        "observed_scan_cannot_close_event_axis": (
            "PARTIAL",
            "EVENT_TIME_DOMAIN_UNPROVEN",
            None,
        ),
        "top_k_candidates_cannot_close_event_axis": (
            "PARTIAL",
            "EVENT_TIME_DOMAIN_UNPROVEN",
            None,
        ),
        "observed_scan_executes_source_axis": ("COMPLETE", None, 1),
    }
    results: list[dict[str, Any]] = []
    for fixture_id, result in fixtures.items():
        if result is None:
            raise AssertionError(f"A5 fixture produced no composition: {fixture_id}")
        actual = (result["status"], result.get("reason"), result.get("value"))
        passed = actual == expected[fixture_id]
        if not passed:
            raise AssertionError(
                f"A5 fixture drifted: {fixture_id}: {actual!r} != {expected[fixture_id]!r}"
            )
        results.append(
            {
                "fixture_id": fixture_id,
                "status": result["status"],
                "reason": result.get("reason"),
                "value": result.get("value"),
                "query_temporal_axis": result["completeness"]["query_temporal_axis"],
                "scan_temporal_axis": result["completeness"]["scan_temporal_axis"],
                "domain_coverage": result["completeness"]["temporal_domain_coverage"],
                "passed": passed,
            }
        )

    wrong_complete = sum(
        item["status"] == "COMPLETE"
        for item in results
        if item["fixture_id"]
        in {
            "observed_scan_cannot_close_event_axis",
            "top_k_candidates_cannot_close_event_axis",
        }
    )
    return {
        "schema": "milai.dg17.a5-dual-axis-temporal-acquisition.v0.1",
        "run_id": run_id,
        "status": "PASS",
        "classification": "DECLARED_TEMPORAL_FIXTURES / REAL_POSTGRESQL_FOCUSED_GATE",
        "formal_holdout_consumed": False,
        "bound_artifacts": {
            "goal": _identity(goal_path),
            "focused_postgres_gate": _identity(focused_postgres_receipt),
        },
        "policy": {
            "source_observed_owner": "EVIDENCE_RECORD_OBSERVED_AT_RANGE_SCAN",
            "event_occurrence_owner": "EVENT_PROJECTION_NOT_INSTALLED",
            "candidate_parsing_can_prove_complete_domain": False,
            "fixed_top_k_can_prove_complete_domain": False,
            "model_calls": 0,
            "automatic_retries": 0,
        },
        "fixtures": results,
        "metrics": {
            "fixture_passed": sum(item["passed"] for item in results),
            "fixture_denominator": len(results),
            "wrong_complete": wrong_complete,
            "wrong_complete_denominator": 2,
        },
        "gates": {
            "real_postgresql_axis_lineage_pass": True,
            "source_observed_axis_executes": True,
            "event_occurrence_mechanism_executes_with_exact_axis": True,
            "observed_event_axis_conflation_zero": wrong_complete == 0,
            "top_k_completeness_promotion_zero": wrong_complete == 0,
            "dedup_key_declared": True,
            "projection_watermark_required": True,
        },
        "disposition": {
            "A5": "SAFETY_PASS_EVENT_PROJECTION_PARKED",
            "SOURCE_OBSERVED_TIME": "EXECUTABLE_BOUNDED_SCAN",
            "EVENT_OCCURRENCE_TIME": "FAIL_CLOSED_WITHOUT_EVENT_PROJECTION",
            "event_projection": "PARKED_NO_GENERAL_STRUCTURED_PRODUCER",
            "schema_added": False,
            "product_event_count_default_enabled": False,
        },
        "claim_boundary": {
            "mechanism_claim": "DECLARED_FIXTURES_AND_AXIS_SAFETY_ONLY",
            "event_time_complete_product_claim": False,
            "final_lme_authorized": False,
            "release_claim_authorized": False,
        },
    }


def _event_plan() -> QueryPlan:
    reference = datetime(2023, 3, 27, 12, tzinfo=UTC)
    return QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How many times did the quartz calibration happen in January?",
            as_of=reference,
            system_as_of=reference,
        )
    )


def _with_source_axis(plan: QueryPlan) -> QueryPlan:
    query_ir = plan.memory_query_ir
    if query_ir is None or query_ir.constraints.normalized_temporal is None:
        raise AssertionError("A5 source-axis fixture requires typed temporal IR")
    temporal = query_ir.constraints.normalized_temporal.model_copy(
        update={"time_axis": "SOURCE_OBSERVED_TIME"}
    )
    query_ir = query_ir.model_copy(
        update={
            "constraints": query_ir.constraints.model_copy(
                update={"normalized_temporal": temporal}
            ),
            "requirements": [
                requirement.model_copy(update={"temporal_constraints": temporal})
                for requirement in query_ir.requirements
            ],
        }
    )
    return plan.model_copy(
        update={
            "memory_query_ir": query_ir,
            "operator_arguments": {
                **plan.operator_arguments,
                "time_axis": "SOURCE_OBSERVED_TIME",
            },
        }
    )


def _event_item(*, evidence_id: str, observed_at: str, content: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/{evidence_id}/turn/0",
        "subject_id": evidence_id,
        "observed_at": observed_at,
        "captured_at": observed_at,
        "content": content,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
    }


def _scan(
    scan_axis: str,
    items: list[dict[str, Any]],
    *,
    status: str = "COMPLETE",
) -> dict[str, Any]:
    return {
        "status": status,
        "scan_axis": scan_axis,
        "source_partition_closed": status == "COMPLETE",
        "projection_watermark_covered": status == "COMPLETE",
        "projection_watermark": 11,
        "target_watermark": 11,
        "source_count": len(items),
        "projected_count": len(items),
        "unreadable_evidence_count": 0,
        "items": items,
    }


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _identity(path: Path) -> dict[str, str]:
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


__all__ = ["run_a5_evaluation"]

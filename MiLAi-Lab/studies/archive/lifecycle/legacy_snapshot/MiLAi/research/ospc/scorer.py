from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any

from .models import CompressionResult, Fixture


def _issue_row(fixture: Fixture, result: CompressionResult) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in result.payload.get("open_issues") or []
            if row.get("issue_id") == fixture.issue.issue_id
        ),
        None,
    )


def score_one(fixture: Fixture, result: CompressionResult) -> dict[str, Any]:
    base: dict[str, Any] = {
        "fixture_id": fixture.fixture_id,
        "domain": fixture.domain,
        "method": result.method,
        "feasible": not result.infeasible,
        "failure_code": result.failure_code,
        "budget_tokens": result.budget_tokens,
        "b_min_tokens": result.b_min_tokens,
        "charged_tokens": result.charged_tokens,
        "budget_compliant": result.budget_compliant,
        "selection_steps": result.selection_steps,
        "validator_checks": result.validator_checks,
        "fallback_count": result.fallback_count,
        "recovery_calls": result.recovery_calls,
        "recovered_tokens": result.recovered_tokens,
        "model_calls": result.model_calls,
        "wall_time_ns": result.wall_time_ns,
        "cpu_time_ns": result.cpu_time_ns,
        "gpu_time_ns": result.gpu_time_ns,
    }
    if result.infeasible:
        return base

    row = _issue_row(fixture, result)
    identity_matches = 0
    if row is not None:
        identity_matches = sum(
            (
                row.get("issue_id") == fixture.issue.issue_id,
                row.get("issue_type") == fixture.issue.issue_type,
                row.get("target_claim_id") == fixture.issue.target_claim_id,
            )
        )
    identity_recall = identity_matches / 3
    expected_branches = set(fixture.issue.support_refs) | set(
        fixture.issue.contradict_refs
    )
    observed_branches = set((row or {}).get("support_refs") or []) | set(
        (row or {}).get("contradict_refs") or []
    )
    branch_recall = len(expected_branches & observed_branches) / len(expected_branches)
    observed_pointers = set(result.payload.get("evidence_pointers") or [])
    evidence_pointer_recall = len(expected_branches & observed_pointers) / len(
        expected_branches
    )
    expected_dependencies = set(fixture.issue.dependencies)
    observed_dependencies = set((row or {}).get("dependencies") or [])
    dependency_recall = (
        len(expected_dependencies & observed_dependencies) / len(expected_dependencies)
        if expected_dependencies
        else 1.0
    )
    discharge_preserved = (row or {}).get(
        "discharge_rule"
    ) == fixture.issue.discharge_rule
    authority_value = (row or {}).get("authority")
    authority_escalated = authority_value not in (None, fixture.issue.authority)

    representation_false_closure = row is None or (row or {}).get("status") in {
        "RESOLVED",
        "DISMISSED",
    }
    recognizes_open = identity_recall == 1.0 and (row or {}).get("status") in {
        "OPEN",
        "WAITING_EVIDENCE",
        "WAITING_USER",
    }
    decision_false_closure = not recognizes_open

    can_apply_resolution = (
        recognizes_open
        and discharge_preserved
        and dependency_recall == 1.0
        and branch_recall == 1.0
        and evidence_pointer_recall == 1.0
        and (row or {}).get("authority") == fixture.issue.authority
    )
    predicted_status = (
        "RESOLVED"
        if can_apply_resolution and fixture.resolution.admissible
        else fixture.issue.status
    )
    resolution_correct = predicted_status == fixture.resolution.expected_status
    later_task_success = mean((not decision_false_closure, resolution_correct))
    unsupported_claim = decision_false_closure

    failures: list[str] = []
    if identity_recall < 1.0:
        failures.append("IDENTITY_LOSS")
    if branch_recall < 1.0:
        failures.append("BRANCH_LOSS")
    if not discharge_preserved:
        failures.append("DISCHARGE_LOSS")
    if representation_false_closure:
        failures.append("REPRESENTATION_FALSE_CLOSURE")
    if decision_false_closure:
        failures.append("DECISION_FALSE_CLOSURE")
    if unsupported_claim:
        failures.append("UNSUPPORTED_CLAIM")
    if not resolution_correct:
        failures.append(
            "LEGAL_RESOLUTION_MISS"
            if fixture.resolution.admissible
            else "ILLEGAL_RESOLUTION_ACCEPTED"
        )
    if authority_escalated:
        failures.append("AUTHORITY_ESCALATION")

    base.update(
        {
            "identity_recall": identity_recall,
            "branch_recall": branch_recall,
            "evidence_pointer_recall": evidence_pointer_recall,
            "dependency_recall": dependency_recall,
            "discharge_preservation": float(discharge_preserved),
            "goal_preservation": float(result.payload.get("goal") == fixture.goal),
            "constraint_recall": len(
                set(result.payload.get("constraints") or []) & set(fixture.constraints)
            )
            / len(fixture.constraints),
            "representation_false_closure": representation_false_closure,
            "decision_false_closure": decision_false_closure,
            "false_closure": decision_false_closure,
            "authority_escalation": authority_escalated,
            "unsupported_claim": unsupported_claim,
            "resolution_candidate_admissible": fixture.resolution.admissible,
            "legal_resolution_correct": resolution_correct,
            "later_task_success": later_task_success,
            "failures": failures,
        }
    )
    return base


def _quantile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    feasible = [row for row in rows if row["feasible"]]
    legal = [row for row in feasible if row["resolution_candidate_admissible"]]
    illegal = [row for row in feasible if not row["resolution_candidate_admissible"]]
    failures: Counter[str] = Counter()
    for row in rows:
        if not row["feasible"]:
            failures[row["failure_code"]] += 1
        else:
            failures.update(row["failures"])
    charged = [row["charged_tokens"] for row in rows]

    def avg(field: str, source: list[dict[str, Any]] = feasible) -> float | None:
        return round(mean(row[field] for row in source), 6) if source else None

    return {
        "fixture_count": len(rows),
        "feasible_count": len(feasible),
        "scored_primary_denominator": len(feasible),
        "infeasible_count": len(rows) - len(feasible),
        "infeasible_rate": round((len(rows) - len(feasible)) / len(rows), 6),
        "identity_recall": avg("identity_recall"),
        "branch_recall": avg("branch_recall"),
        "evidence_pointer_recall": avg("evidence_pointer_recall"),
        "dependency_recall": avg("dependency_recall"),
        "discharge_preservation": avg("discharge_preservation"),
        "goal_preservation": avg("goal_preservation"),
        "constraint_recall": avg("constraint_recall"),
        "representation_false_closure_rate": avg("representation_false_closure"),
        "decision_false_closure_rate": avg("decision_false_closure"),
        "false_closure_rate": avg("decision_false_closure"),
        "authority_escalation_rate": avg("authority_escalation"),
        "unsupported_claim_rate": avg("unsupported_claim"),
        "legal_resolution_accuracy": avg("legal_resolution_correct"),
        "legal_resolution_recall": avg("legal_resolution_correct", legal),
        "illegal_resolution_rejection": avg("legal_resolution_correct", illegal),
        "later_task_success": avg("later_task_success"),
        "budget_violation_count": sum(not row["budget_compliant"] for row in rows),
        "charged_tokens_mean": round(mean(charged), 3),
        "charged_tokens_p50": _quantile(charged, 0.50),
        "charged_tokens_p95": _quantile(charged, 0.95),
        "selection_steps_mean": round(mean(row["selection_steps"] for row in rows), 3),
        "validator_checks_total": sum(row["validator_checks"] for row in rows),
        "fallback_count": sum(row["fallback_count"] for row in rows),
        "recovery_calls": sum(row["recovery_calls"] for row in rows),
        "recovered_tokens": sum(row["recovered_tokens"] for row in rows),
        "model_calls": sum(row["model_calls"] for row in rows),
        "wall_time_ns_mean": round(mean(row["wall_time_ns"] for row in rows), 3),
        "wall_time_ns_p50": _quantile([row["wall_time_ns"] for row in rows], 0.50),
        "wall_time_ns_p95": _quantile([row["wall_time_ns"] for row in rows], 0.95),
        "cpu_time_ns_mean": round(mean(row["cpu_time_ns"] for row in rows), 3),
        "cpu_time_ns_p50": _quantile([row["cpu_time_ns"] for row in rows], 0.50),
        "cpu_time_ns_p95": _quantile([row["cpu_time_ns"] for row in rows], 0.95),
        "gpu_time_ns_total": sum(row["gpu_time_ns"] for row in rows),
        "failure_distribution": dict(sorted(failures.items())),
    }

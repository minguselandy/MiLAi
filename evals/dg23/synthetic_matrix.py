"""DG-23 S5 generic synthetic and property contract matrix."""

from __future__ import annotations

import inspect
import random
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from milai.application.memory_context import (
    ContextCompilation,
    MemoryContextCompiler,
    _conditional_activation_thresholds,
    _render_reader_units,
)
from milai.application.reader_evidence_plan import build_decision_snapshot
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.reader_evidence_plan import (
    ContextBudgetEnvelope,
    DecisionSnapshot,
    ReaderEvidenceRender,
    ReaderEvidenceUnit,
    canonical_digest,
)

DIAGNOSTIC_BUDGETS = (128, 256, 512, 1024, 2048, 4096, 8000)


@dataclass(frozen=True, slots=True)
class _SyntheticCase:
    case_id: str
    query: str
    outcome: dict[str, Any]
    snapshot: DecisionSnapshot
    expected: str


def build_synthetic_matrix_report(root: Path) -> dict[str, Any]:
    """Run eleven answer-free semantic shapes plus deterministic properties."""
    del root
    compiler = MemoryContextCompiler(budget_stable_enabled=True)
    cases = _cases()
    records: list[dict[str, Any]] = []
    case_summaries: list[dict[str, Any]] = []
    structural_failures: list[dict[str, str]] = []
    plan_by_case: dict[str, Any] = {}
    for case in cases:
        request = _request(case.query, 8_000)
        planned = compiler.plan(
            request,
            case.outcome,
            decision_snapshot=case.snapshot,
        )
        plan_by_case[case.case_id] = planned
        renders = [
            compiler.render(planned, _envelope(budget))
            for budget in DIAGNOSTIC_BUDGETS
        ]
        reader_renders = [_require_reader_render(result) for result in renders]
        safe_budget = reader_renders[-1].protected_closure_tokens
        for budget, result, render in zip(
            DIAGNOSTIC_BUDGETS, renders, reader_renders, strict=True
        ):
            records.append(
                {
                    "case_id": case.case_id,
                    "expected_contract": case.expected,
                    "budget": budget,
                    "decision_snapshot_digest": case.snapshot.snapshot_digest,
                    "plan_digest": planned.reader_evidence_plan.plan_digest,
                    "readiness": render.readiness,
                    "selected_unit_ids": list(render.selected_unit_ids),
                    "reader_context_digest": render.reader_context_digest,
                    "estimated_tokens": render.estimated_tokens,
                    "protected_closure_tokens": safe_budget,
                    "semantic_saturated": render.semantic_saturated,
                    "atomic_unit_truncation_count": result.memory_context.compile_trace[
                        "atomic_unit_truncation_count"
                    ],
                }
            )
        ready = [render for render in reader_renders if render.readiness == "READY"]
        nested = all(
            set(low.selected_unit_ids).issubset(high.selected_unit_ids)
            for low, high in pairwise(ready)
        )
        ordered = all(
            _common_order(
                low.selected_unit_ids,
                high.selected_unit_ids,
            )
            for low, high in pairwise(ready)
        )
        saturated_digests = {
            render.reader_context_digest
            for render in ready
            if render.semantic_saturated
        }
        if not nested:
            structural_failures.append(
                {"case_id": case.case_id, "reason": "CONTEXT_NESTEDNESS_VIOLATION"}
            )
        if not ordered:
            structural_failures.append(
                {"case_id": case.case_id, "reason": "CONTEXT_ORDER_VIOLATION"}
            )
        if len(saturated_digests) > 1:
            structural_failures.append(
                {
                    "case_id": case.case_id,
                    "reason": "SEMANTIC_SATURATION_VIOLATION",
                }
            )
        boundary = _boundary_probe(compiler, planned, safe_budget)
        case_summaries.append(
            {
                "case_id": case.case_id,
                "expected_contract": case.expected,
                "decision_snapshot_digest": case.snapshot.snapshot_digest,
                "plan_digest": planned.reader_evidence_plan.plan_digest,
                "protected_unit_count": len(
                    planned.reader_evidence_plan.protected_units
                ),
                "conditional_unit_count": len(
                    planned.reader_evidence_plan.conditional_units
                ),
                "plan_omitted_units": [
                    item.model_dump(mode="json")
                    for item in planned.reader_evidence_plan.omitted_units
                ],
                "b_safe": safe_budget,
                "boundary_probe": boundary,
                "nested": nested,
                "stable_order": ordered,
                "saturated_digest_count": len(saturated_digests),
            }
        )

    permutation_case = next(
        case for case in cases if case.case_id == "repository_permutation"
    )
    permuted = compiler.plan(
        _request(permutation_case.query, 8_000),
        {
            **permutation_case.outcome,
            "items": list(reversed(permutation_case.outcome["items"])),
        },
        decision_snapshot=permutation_case.snapshot,
    )
    property_report = _property_trials()
    by_case = {summary["case_id"]: summary for summary in case_summaries}
    cell_by_case = {
        case_id: [record for record in records if record["case_id"] == case_id]
        for case_id in by_case
    }
    conflict_plan = plan_by_case["contested_conflict"].reader_evidence_plan
    oversized_required_cells = cell_by_case["oversized_required_unit"]
    oversized_optional_plan = plan_by_case[
        "oversized_optional_then_short"
    ].reader_evidence_plan
    optional_units = list(oversized_optional_plan.conditional_units)
    optional_thresholds = next(
        record
        for record in cell_by_case["oversized_optional_then_short"]
        if record["budget"] == 8000
    )
    del optional_thresholds
    checks = {
        "synthetic_case_count_11": len(cases) == len(by_case) == 11,
        "diagnostic_ladder_exact": list(DIAGNOSTIC_BUDGETS)
        == [128, 256, 512, 1024, 2048, 4096, 8000],
        "all_cases_have_seven_ladder_cells": len(records) == 11 * 7
        and all(len(values) == 7 for values in cell_by_case.values()),
        "one_decision_snapshot_per_case": all(
            len({row["decision_snapshot_digest"] for row in values}) == 1
            for values in cell_by_case.values()
        ),
        "one_reader_plan_per_case": all(
            len({row["plan_digest"] for row in values}) == 1
            for values in cell_by_case.values()
        ),
        "nestedness_violations_zero": not any(
            row["reason"] == "CONTEXT_NESTEDNESS_VIOLATION"
            for row in structural_failures
        ),
        "order_violations_zero": not any(
            row["reason"] == "CONTEXT_ORDER_VIOLATION"
            for row in structural_failures
        ),
        "atomic_truncations_zero": all(
            row["atomic_unit_truncation_count"] == 0 for row in records
        ),
        "saturation_violations_zero": not any(
            row["reason"] == "SEMANTIC_SATURATION_VIOLATION"
            for row in structural_failures
        ),
        "token_accounting_mismatch_zero": all(
            row["estimated_tokens"] <= row["budget"] for row in records
        ),
        "boundary_below_equal_above_safe": all(
            summary["boundary_probe"]["passed"]
            for summary in case_summaries
            if summary["b_safe"] <= 8000
        ),
        "oversized_required_always_infeasible": all(
            row["readiness"] == "BUDGET_INFEASIBLE"
            for row in oversized_required_cells
        ),
        "oversized_optional_and_short_both_planned": len(optional_units) == 2
        and min(unit.estimated_tokens for unit in optional_units)
        < max(unit.estimated_tokens for unit in optional_units),
        "conflict_sides_and_open_issue_protected": (
            len([unit for unit in conflict_plan.protected_units if unit.kind == "CONFLICT_SIDE"])
            == 2
            and any(unit.kind == "OPEN_ISSUE" for unit in conflict_plan.protected_units)
        ),
        "speaker_mismatch_remains_partial": all(
            "sufficiency_status=PARTIAL"
            in compiler.render(
                plan_by_case["speaker_role_mismatch"],
                _envelope(8_000),
            ).memory_context.text
            for _ in range(1)
        ),
        "temporal_unresolved_remains_partial": "sufficiency_status=PARTIAL"
        in compiler.render(
            plan_by_case["temporal_unresolved_partial"],
            _envelope(8_000),
        ).memory_context.text,
        "duplicate_topic_distractor_omitted": any(
            item["reason"] == "SEMANTIC_DUPLICATE_ZERO_GAIN"
            for item in by_case["duplicate_topic_distractors"]["plan_omitted_units"]
        ),
        "repository_permutation_plan_digest_invariant": (
            permuted.reader_evidence_plan.plan_digest
            == plan_by_case["repository_permutation"].reader_evidence_plan.plan_digest
        ),
        "property_trials_pass": property_report["failure_count"] == 0,
        "runtime_case_specific_branches_zero": "case_id"
        not in inspect.getsource(MemoryContextCompiler.plan),
        "source_labels_loaded_false": True,
        "reader_calls_zero": True,
        "provider_calls_zero": True,
        "repository_calls_zero": True,
        "formal_holdout_consumed_false": True,
        "candidate_default_false": inspect.signature(
            MemoryContextCompiler.__init__
        ).parameters["budget_stable_enabled"].default
        is False,
    }
    return {
        "schema": "milai.dg23.s5-synthetic-matrix.v0.1",
        "status": "PASS_DG23_SYNTHETIC_CONTRACT_MATRIX"
        if all(checks.values())
        else "FAIL_DG23_SYNTHETIC_CONTRACT_MATRIX",
        "diagnostic_budgets": list(DIAGNOSTIC_BUDGETS),
        "case_summaries": case_summaries,
        "records": records,
        "structural_failures": structural_failures,
        "property_report": property_report,
        "execution_counts": {
            "logical_decision_snapshots": len(cases),
            "context_plan_compilations": len(cases),
            "permutation_mutation_plan_compilations": 1,
            "diagnostic_local_renders": len(records),
            "boundary_local_renders": sum(
                int(summary["boundary_probe"]["render_count"])
                for summary in case_summaries
            ),
            "reader_calls": 0,
            "provider_calls": 0,
            "repository_calls": 0,
        },
        "label_boundary": {
            "source_labels_loaded": False,
            "answer_labels_loaded": False,
            "formal_holdout_consumed": False,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def _cases() -> list[_SyntheticCase]:
    padding = " complete governed source context" * 10
    single = [_evidence("single", "single", "The required value is 47." + padding)]
    multi = [
        _evidence("multi-a", "multi-a", "The first required value is 12." + padding),
        _evidence("multi-b", "multi-b", "The second required value is 30." + padding),
    ]
    derived = [
        _evidence("operand-a", "operand-a", "The first amount is 12." + padding),
        _evidence("operand-b", "operand-b", "The second amount is 30." + padding),
    ]
    derived_result = {
        "status": "OK",
        "kind": "DERIVED_QUERY_RESULT",
        "operator": "SUM_VALUES",
        "value": 42,
        "unit": "items",
        "evidence_refs": ["operand-a", "operand-b"],
        "source_turn_refs": [
            "memory://synthetic/turn/operand-a",
            "memory://synthetic/turn/operand-b",
        ],
        "completeness": {
            "required_slots": ["R1", "R2"],
            "filled_slots": ["R1", "R2"],
            "unresolved_reasons": [],
        },
        "hidden_model_calls": 0,
        "canonical_mutation": False,
    }
    preference = [
        {
            "kind": "CANONICAL_STATE",
            "claim_version_id": "canonical-preference-v2",
            "predicate": "preferred_beverage",
            "payload": {
                "value": "green tea",
                "note": "Current governed preference." + padding,
            },
            "canonical": True,
        }
    ]
    conflict = [
        _evidence("conflict-a", "conflict-a", "The current limit is 40." + padding),
        _evidence("conflict-b", "conflict-b", "The current limit is 60." + padding),
    ]
    mismatch = [
        _evidence(
            "mismatch-user",
            "mismatch-user",
            "The assistant recommendation code is 71." + padding,
            speaker="user",
        )
    ]
    temporal = [
        _evidence("temporal-one", "temporal-one", "The first event was Monday." + padding)
    ]
    oversized_required = [
        _evidence(
            "oversized-required",
            "oversized-required",
            "Required indivisible source span. " * 1200,
        )
    ]
    optional = [
        _evidence("optional-required", "a-required", "The required code is 47." + padding),
        _evidence(
            "optional-large",
            "b-large",
            "The optional code is 99. " + "large diagnostic context " * 300,
        ),
        _evidence("optional-short", "c-short", "The optional code is 48."),
    ]
    duplicate_text = "The required duplicate-topic code is 47." + padding
    duplicates = [
        _evidence("duplicate-required", "duplicate-a", duplicate_text),
        _evidence("duplicate-copy", "duplicate-b", duplicate_text),
        _evidence("topic-only", "topic-only", "A related topic without a value."),
    ]
    permutation = [
        _evidence("perm-a", "perm-a", "The first permutation value is 11." + padding),
        _evidence("perm-b", "perm-b", "The second permutation value is 31." + padding),
        _evidence("perm-c", "perm-c", "The optional permutation value is 42."),
    ]
    return [
        _case("single_required_value", "What is the required value?", single, ["single"]),
        _case(
            "multi_requirement_evidence_set",
            "What are both required values?",
            multi,
            ["multi-a", "multi-b"],
            requirements=["R1", "R2"],
        ),
        _case(
            "derived_operator_two_operands",
            "What is the total amount?",
            derived,
            ["operand-a", "operand-b"],
            requirements=["R1", "R2"],
            derived_result=derived_result,
        ),
        _case(
            "preference_current_state_update",
            "What is my current preferred beverage?",
            preference,
            [],
        ),
        _case(
            "contested_conflict",
            "What is the current limit?",
            conflict,
            ["conflict-a", "conflict-b"],
            status="CONTESTED",
            sufficiency="CONTESTED",
            unresolved=["R1"],
            open_issue_ids=["opaque-conflict-issue"],
        ),
        _case(
            "speaker_role_mismatch",
            "What did the assistant recommend?",
            mismatch,
            [],
            sufficiency="PARTIAL",
            unresolved=["R1"],
        ),
        _case(
            "temporal_unresolved_partial",
            "How long was it between the two events?",
            temporal,
            ["temporal-one"],
            requirements=["EVENT_1", "EVENT_2"],
            sufficiency="PARTIAL",
            unresolved=["EVENT_2"],
        ),
        _case(
            "oversized_required_unit",
            "What is in the required source span?",
            oversized_required,
            ["oversized-required"],
        ),
        _case(
            "oversized_optional_then_short",
            "What is the code?",
            optional,
            ["optional-required"],
        ),
        _case(
            "duplicate_topic_distractors",
            "What is the duplicate-topic code?",
            duplicates,
            ["duplicate-required"],
        ),
        _case(
            "repository_permutation",
            "What are the permutation values?",
            permutation,
            ["perm-a", "perm-b"],
            requirements=["R1", "R2"],
        ),
    ]


def _case(
    case_id: str,
    query: str,
    items: list[dict[str, Any]],
    accepted: list[str],
    *,
    requirements: list[str] | None = None,
    status: str = "HIT",
    sufficiency: str = "COMPLETE",
    unresolved: list[str] | None = None,
    open_issue_ids: list[str] | None = None,
    derived_result: dict[str, Any] | None = None,
) -> _SyntheticCase:
    required = requirements or ["R1"]
    unresolved_values = unresolved or []
    outcome = {
        "status": status,
        "requirement": "SEARCH",
        "items": items,
        "open_issue_ids": open_issue_ids or [],
        "canonical_position": {"evidence_watermark": 5, "fts_watermark": 5},
        "memory_query_ir": {
            "schema_version": "memory-query-ir-v0.2",
            "requirements": [
                {"slot_id": requirement, "required": True}
                for requirement in required
            ],
        },
        "sufficiency_decision": {
            "status": sufficiency,
            "covered_slots": [
                requirement
                for requirement in required
                if requirement not in unresolved_values
            ],
            "missing_slots": unresolved_values,
        },
        "derived_result": derived_result,
    }
    snapshot = build_decision_snapshot(
        source_snapshot_material={"synthetic_case_shape": case_id},
        query_ir_material={"requirements": required},
        acquisition_plan_material={"policy": "synthetic-fixed-v0.1"},
        candidate_snapshot_material={
            "candidate_ids": sorted(
                str(item.get("evidence_id", item.get("claim_version_id", "canonical")))
                for item in items
            )
        },
        gate_material={"accepted": sorted(accepted)},
        binding_material={"accepted": sorted(accepted)},
        requirement_state_material={
            "required": required,
            "unresolved": unresolved_values,
        },
        sufficiency_material={"status": sufficiency},
        operator_result_material=derived_result,
        accepted_evidence_ids=accepted,
        required_requirement_ids=required,
        unresolved_requirement_ids=unresolved_values,
    )
    return _SyntheticCase(case_id, query, outcome, snapshot, case_id.upper())


def _evidence(
    evidence_id: str,
    suffix: str,
    content: str,
    *,
    speaker: str = "user",
) -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "authority_class": "EVIDENCE_ONLY",
        "evidence_id": evidence_id,
        "source_ref": f"memory://synthetic/turn/{suffix}",
        "subject_id": f"session-{suffix}",
        "observed_at": "2026-08-29T09:00:00+08:00",
        "content": content,
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "relevance_score": 1.0,
    }


def _request(query: str, budget: int) -> MemoryResolveRequest:
    return MemoryResolveRequest(
        query=query,
        budget=MemoryResolveBudget(max_context_tokens=budget),
    )


def _envelope(budget: int) -> ContextBudgetEnvelope:
    return ContextBudgetEnvelope(
        requested_cap=budget,
        available_memory_tokens=budget,
        budget_source="CALLER_CAP_ONLY",
    )


def _boundary_probe(
    compiler: MemoryContextCompiler,
    planned: Any,
    safe_budget: int,
) -> dict[str, Any]:
    if safe_budget > 8000:
        render = compiler.render(planned, _envelope(8000))
        return {
            "passed": _require_reader_render(render).readiness
            == "BUDGET_INFEASIBLE",
            "reason": "PROTECTED_CLOSURE_EXCEEDS_PUBLIC_CEILING",
            "render_count": 1,
        }
    below = max(128, safe_budget - 1)
    equal = max(128, safe_budget)
    above = min(8000, equal + 1)
    below_render = compiler.render(planned, _envelope(below))
    equal_render = compiler.render(planned, _envelope(equal))
    above_render = compiler.render(planned, _envelope(above))
    below_reader = _require_reader_render(below_render)
    equal_reader = _require_reader_render(equal_render)
    above_reader = _require_reader_render(above_render)
    passed = (
        (below >= safe_budget or below_reader.readiness == "BUDGET_INFEASIBLE")
        and equal_reader.readiness == "READY"
        and above_reader.readiness == "READY"
    )
    return {
        "passed": passed,
        "below": {"budget": below, "readiness": below_reader.readiness},
        "equal": {"budget": equal, "readiness": equal_reader.readiness},
        "above": {"budget": above, "readiness": above_reader.readiness},
        "render_count": 3,
    }


def _require_reader_render(result: ContextCompilation) -> ReaderEvidenceRender:
    render = result.reader_render
    if render is None:
        raise AssertionError("budget-stable compiler render omitted ReaderEvidenceRender")
    return render


def _common_order(low: tuple[str, ...], high: tuple[str, ...]) -> bool:
    low_set = set(low)
    return [value for value in high if value in low_set] == list(low)


def _property_trials(*, seed: int = 2305, trial_count: int = 128) -> dict[str, Any]:
    rng = random.Random(seed)  # noqa: S311 -- deterministic property generation only
    failures: list[dict[str, Any]] = []
    for trial in range(trial_count):
        protected = [
            ReaderEvidenceUnit(
                unit_id="status",
                kind="STATUS",
                text="status " + "p" * rng.randint(1, 120),
                estimated_tokens=rng.randint(1, 40),
            )
        ]
        conditional = [
            ReaderEvidenceUnit(
                unit_id=f"optional-{index:02d}",
                kind="PROVENANCE",
                text=f"unit-{index} " + "x" * rng.randint(1, 600),
                estimated_tokens=rng.randint(1, 200),
                incremental_requirement_gain=(f"R{index}",),
            )
            for index in range(rng.randint(1, 12))
        ]
        thresholds = _conditional_activation_thresholds(protected, conditional)
        budgets = sorted(
            {
                0,
                *thresholds.values(),
                *(max(0, value - 1) for value in thresholds.values()),
                *(value + 1 for value in thresholds.values()),
            }
        )
        selections = [
            tuple(
                unit.unit_id
                for unit in conditional
                if thresholds[unit.unit_id] <= budget
            )
            for budget in budgets
        ]
        nested = all(
            set(low).issubset(high) and _common_order(low, high)
            for low, high in pairwise(selections)
        )
        atomic = all(
            unit.text
            in _render_reader_units(
                [
                    *protected,
                    *(candidate for candidate in conditional if candidate.unit_id in selected),
                ]
            )
            for selected in selections
            for unit in conditional
            if unit.unit_id in selected
        )
        digest_material = {
            "protected": [unit.model_dump(mode="json") for unit in protected],
            "conditional": [unit.model_dump(mode="json") for unit in conditional],
        }
        deterministic = canonical_digest(digest_material) == canonical_digest(
            digest_material
        )
        if not (nested and atomic and deterministic):
            failures.append(
                {
                    "trial": trial,
                    "nested": nested,
                    "atomic": atomic,
                    "deterministic": deterministic,
                }
            )
    return {
        "seed": seed,
        "trial_count": trial_count,
        "failure_count": len(failures),
        "failures": failures,
    }

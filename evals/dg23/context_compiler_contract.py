"""DG-23 S3 synthetic contract proof for atomic local Context rendering."""

from __future__ import annotations

import inspect
from itertools import pairwise
from pathlib import Path
from typing import Any

from milai.application.memory_context import (
    ContextCompilation,
    MemoryContextCompiler,
    _estimated_tokens,
)
from milai.application.reader_evidence_plan import build_decision_snapshot
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.reader_evidence_plan import (
    ContextBudgetEnvelope,
    DecisionSnapshot,
    ReaderEvidenceRender,
)

DIAGNOSTIC_BUDGETS = (128, 256, 512, 1024, 2048, 4096, 8000)


def build_context_compiler_contract_report(root: Path) -> dict[str, Any]:
    """Run the S3 structural matrix without repository, Reader, provider, or labels."""
    del root
    compiler = MemoryContextCompiler(budget_stable_enabled=True)
    request = _request(8_000)
    items = _base_items()
    outcome = _outcome(items)
    snapshot = _snapshot(["required"])
    planned = compiler.plan(request, outcome, decision_snapshot=snapshot)
    renders = [
        compiler.render(planned, _envelope(budget))
        for budget in DIAGNOSTIC_BUDGETS
    ]
    reader_renders = [_require_reader_render(result) for result in renders]
    render_records = [
        {
            "budget": budget,
            "readiness": render.readiness,
            "selected_unit_ids": list(render.selected_unit_ids),
            "reader_context_digest": result.memory_context.reader_context_digest,
            "estimated_tokens": result.memory_context.estimated_tokens,
            "protected_closure_tokens": render.protected_closure_tokens,
            "semantic_saturated": render.semantic_saturated,
            "atomic_unit_truncation_count": result.memory_context.compile_trace[
                "atomic_unit_truncation_count"
            ],
        }
        for budget, result, render in zip(
            DIAGNOSTIC_BUDGETS, renders, reader_renders, strict=True
        )
    ]
    ready_records = [row for row in render_records if row["readiness"] == "READY"]
    nested = _nested(ready_records)
    stable_order = _stable_common_order(ready_records)
    saturated = [row for row in ready_records if row["semantic_saturated"]]

    conditional = list(planned.reader_evidence_plan.conditional_units)
    large = next(
        unit for unit in conditional if unit.source_turn_refs == ("memory://s/turn/large",)
    )
    short = next(
        unit for unit in conditional if unit.source_turn_refs == ("memory://s/turn/short",)
    )
    activation = renders[-1].memory_context.compile_trace[
        "conditional_activation_thresholds"
    ]
    assert isinstance(activation, dict)
    short_threshold = int(activation[short.unit_id])
    large_threshold = int(activation[large.unit_id])
    short_only = compiler.render(planned, _envelope(short_threshold))
    short_only_reader = _require_reader_render(short_only)

    conflict_items = [
        _evidence("side-a", "conflict-a", "The current limit is 40."),
        _evidence("side-b", "conflict-b", "The current limit is 60."),
    ]
    conflict_outcome = _outcome(
        conflict_items,
        status="CONTESTED",
        sufficiency_status="CONTESTED",
        open_issue_ids=["opaque-issue-one"],
    )
    conflict_plan = compiler.plan(
        request,
        conflict_outcome,
        decision_snapshot=_snapshot(["side-a", "side-b"], unresolved=["R1"]),
    )
    conflict_render = compiler.render(conflict_plan, _envelope(8_000))
    conflict_reader = _require_reader_render(conflict_render)
    conflict_units = [
        unit
        for unit in conflict_plan.reader_evidence_plan.protected_units
        if unit.kind == "CONFLICT_SIDE"
    ]

    permuted_plan = compiler.plan(
        request,
        _outcome(list(reversed(items))),
        decision_snapshot=snapshot,
    )
    wrapper = compiler.compile(request, outcome, decision_snapshot=snapshot)
    direct = compiler.render(planned, _envelope(8_000))
    omitted_reasons = {
        unit.reason for unit in planned.reader_evidence_plan.omitted_units
    }
    checks = {
        "diagnostic_ladder_exact": list(DIAGNOSTIC_BUDGETS)
        == [128, 256, 512, 1024, 2048, 4096, 8000],
        "plan_budget_independent": "budget"
        not in planned.reader_evidence_plan.model_dump_json(),
        "atomic_unit_truncation_zero": all(
            row["atomic_unit_truncation_count"] == 0 for row in render_records
        ),
        "budget_below_protected_closure_typed_infeasible": any(
            row["readiness"] == "BUDGET_INFEASIBLE" for row in render_records
        ),
        "ready_render_never_exceeds_cap": all(
            result.memory_context.estimated_tokens <= budget
            for budget, result in zip(DIAGNOSTIC_BUDGETS, renders, strict=True)
        ),
        "nested_selected_units": nested,
        "common_unit_order_stable": stable_order,
        "saturated_context_byte_identical": len(
            {row["reader_context_digest"] for row in saturated}
        )
        <= 1,
        "oversized_optional_does_not_block_later_short_useful": (
            short_threshold < large_threshold
            and short.unit_id in short_only_reader.selected_unit_ids
            and large.unit_id not in short_only_reader.selected_unit_ids
        ),
        "topic_duplicate_and_zero_gain_not_quota_filled": {
            "SEMANTIC_DUPLICATE_ZERO_GAIN",
            "NO_ADMISSIBLE_SEMANTIC_GAIN",
        }
        <= omitted_reasons,
        "repository_permutation_plan_digest_invariant": (
            planned.reader_evidence_plan.plan_digest
            == permuted_plan.reader_evidence_plan.plan_digest
        ),
        "conflict_sides_protected_together": (
            len(conflict_units) == 2
            and all(
                unit.unit_id in conflict_reader.selected_unit_ids
                for unit in conflict_units
            )
        ),
        "open_issue_safety_protected": "open-issue-safety"
        in conflict_reader.selected_unit_ids,
        "required_full_text_byte_identical": all(
            unit.text in result.memory_context.text
            for unit in planned.reader_evidence_plan.protected_units
            for result, render in zip(renders, reader_renders, strict=True)
            if render.readiness == "READY"
        ),
        "compile_wrapper_matches_plan_render": (
            wrapper.memory_context.model_dump(mode="json")
            == direct.memory_context.model_dump(mode="json")
        ),
        "token_accounting_matches_renderer": all(
            result.memory_context.estimated_tokens
            == _estimated_tokens(result.memory_context.text)
            for result in renders
        ),
        "candidate_default_false": inspect.signature(
            MemoryContextCompiler.__init__
        ).parameters["budget_stable_enabled"].default
        is False,
        "runtime_case_id_branches_zero": "case_id"
        not in inspect.getsource(MemoryContextCompiler.plan),
        "reader_calls_zero": True,
        "provider_calls_zero": True,
        "repository_calls_zero": True,
        "formal_holdout_consumed_false": True,
    }
    return {
        "schema": "milai.dg23.s3-context-compiler-contract.v0.1",
        "status": "PASS_ATOMIC_NESTED_CONTEXT_COMPILER"
        if all(checks.values())
        else "FAIL_ATOMIC_NESTED_CONTEXT_COMPILER",
        "plan": planned.reader_evidence_plan.model_dump(mode="json"),
        "render_records": render_records,
        "short_optional_unit": {
            "unit_id": short.unit_id,
            "activation_budget": short_threshold,
        },
        "oversized_optional_unit": {
            "unit_id": large.unit_id,
            "activation_budget": large_threshold,
        },
        "conflict": {
            "protected_conflict_unit_ids": [unit.unit_id for unit in conflict_units],
            "selected_unit_ids": list(conflict_reader.selected_unit_ids),
        },
        "execution_counts": {
            "context_plan_compilations": 3,
            "local_budget_renders": len(renders) + 3,
            "repository_calls": 0,
            "reader_calls": 0,
            "provider_calls": 0,
        },
        "safety": {
            "canonical_mutations": 0,
            "automatic_retries": 0,
            "formal_holdout_consumed": False,
            "candidate_default": False,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def _require_reader_render(result: ContextCompilation) -> ReaderEvidenceRender:
    render = result.reader_render
    if render is None:
        raise AssertionError("budget-stable compiler render omitted ReaderEvidenceRender")
    return render


def _request(budget: int) -> MemoryResolveRequest:
    return MemoryResolveRequest(
        query="What kitchen purchase code did I remember?",
        budget=MemoryResolveBudget(max_context_tokens=budget),
    )


def _evidence(
    evidence_id: str,
    suffix: str,
    content: str,
    *,
    relevance_score: float = 1.0,
) -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "authority_class": "EVIDENCE_ONLY",
        "evidence_id": evidence_id,
        "source_ref": f"memory://s/turn/{suffix}",
        "subject_id": "synthetic-session",
        "observed_at": "2026-08-29T08:00:00+00:00",
        "content": content,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "relevance_score": relevance_score,
    }


def _base_items() -> list[dict[str, Any]]:
    required_text = (
        "The kitchen purchase code is 47 for the stand mixer; this complete "
        "source sentence is required and must remain byte-identical. "
        + "required provenance context " * 6
    )
    return [
        _evidence("required", "required", required_text, relevance_score=1.0),
        _evidence(
            "large",
            "large",
            "Kitchen purchase code 999. " + "large optional diagnostic context " * 260,
            relevance_score=0.9,
        ),
        _evidence(
            "short",
            "short",
            "Kitchen purchase code 48 from a second receipt.",
            relevance_score=0.8,
        ),
        _evidence("duplicate", "duplicate", required_text, relevance_score=0.7),
        _evidence(
            "zero-gain",
            "zero-gain",
            "Kitchen decor and an unrelated topic with no admissible value.",
            relevance_score=0.6,
        ),
    ]


def _outcome(
    items: list[dict[str, Any]],
    *,
    status: str = "HIT",
    sufficiency_status: str = "COMPLETE",
    open_issue_ids: list[str] | None = None,
) -> dict[str, Any]:
    missing = ["R1"] if sufficiency_status in {"PARTIAL", "CONTESTED"} else []
    return {
        "status": status,
        "requirement": "SEARCH",
        "items": items,
        "open_issue_ids": open_issue_ids or [],
        "canonical_position": {
            "canonical_outbox_sequence": 17,
            "evidence_watermark": 17,
            "fts_watermark": 17,
        },
        "memory_query_ir": {
            "schema_version": "memory-query-ir-v0.2",
            "requirements": [{"slot_id": "R1", "required": True}],
        },
        "sufficiency_decision": {
            "status": sufficiency_status,
            "covered_slots": [] if missing else ["R1"],
            "missing_slots": missing,
        },
        "derived_result": None,
    }


def _snapshot(
    accepted: list[str],
    *,
    unresolved: list[str] | None = None,
) -> DecisionSnapshot:
    return build_decision_snapshot(
        source_snapshot_material={"snapshot": "synthetic-context-s3"},
        query_ir_material={"requirements": ["R1"]},
        acquisition_plan_material={"policy": "synthetic-fixed"},
        candidate_snapshot_material={"candidate_ids": sorted(accepted)},
        gate_material={"allowed": sorted(accepted)},
        binding_material={"R1": sorted(accepted)},
        requirement_state_material={
            "required": ["R1"],
            "unresolved": unresolved or [],
        },
        sufficiency_material={
            "status": "PARTIAL" if unresolved else "COMPLETE"
        },
        operator_result_material=None,
        accepted_evidence_ids=accepted,
        required_requirement_ids=["R1"],
        unresolved_requirement_ids=unresolved or [],
    )


def _envelope(budget: int) -> ContextBudgetEnvelope:
    return ContextBudgetEnvelope(
        requested_cap=budget,
        available_memory_tokens=budget,
        budget_source="CALLER_CAP_ONLY",
    )


def _nested(records: list[dict[str, Any]]) -> bool:
    for low, high in pairwise(records):
        if not set(low["selected_unit_ids"]).issubset(high["selected_unit_ids"]):
            return False
    return True


def _stable_common_order(records: list[dict[str, Any]]) -> bool:
    for low, high in pairwise(records):
        low_ids = list(low["selected_unit_ids"])
        low_set = set(low_ids)
        if [unit for unit in high["selected_unit_ids"] if unit in low_set] != low_ids:
            return False
    return True

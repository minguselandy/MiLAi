"""Pure post-hoc scoring for the DG-17 A1 turn-first acquisition lane."""

from __future__ import annotations

import math
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any

from evals.dg15.milai_mcp_adapter import compact_lme_source_ref

CURRENT_Q6_POLICY = "DG17_QUERY_SPECIFIC_STOP"
CURRENT_Q6_CORRECT_CASE_COUNT = 2


class A1AcquisitionError(RuntimeError):
    """An A1 archive, label, or frozen baseline denominator drifted."""


def score_a1_records(
    records: Sequence[Mapping[str, Any]],
    *,
    labels: Mapping[str, Mapping[str, Any]],
    policy: str = CURRENT_Q6_POLICY,
) -> list[dict[str, Any]]:
    expected = {
        (case_id, budget)
        for case_id in labels
        for budget in (512, 2048)
    }
    selected = [record for record in records if record.get("policy") == policy]
    observed = [
        (str(record.get("case_id")), int(record.get("token_budget", -1)))
        for record in selected
    ]
    if (
        len(labels) != 10
        or len(selected) != 20
        or set(observed) != expected
        or len(set(observed)) != len(observed)
    ):
        raise A1AcquisitionError("A1 matched record denominator drifted")
    return sorted(
        (_score_cell(record, labels[str(record["case_id"])]) for record in selected),
        key=lambda row: (int(row["token_budget"]), str(row["case_id"])),
    )


def summarize_a1_records(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for budget in (512, 2048):
        budget_cells = [cell for cell in cells if cell.get("token_budget") == budget]
        if len(budget_cells) != 10:
            raise A1AcquisitionError("A1 summary denominator drifted")
        atom_total = sum(int(cell["required_atom_count"]) for cell in budget_cells)
        turn_total = sum(int(cell["required_source_turn_count"]) for cell in budget_cells)
        atom_hits = sum(int(cell["candidate_atom_hit_count"]) for cell in budget_cells)
        retained_hits = sum(int(cell["retained_atom_hit_count"]) for cell in budget_cells)
        turn_hits = sum(int(cell["candidate_source_turn_hit_count"]) for cell in budget_cells)
        latencies = [float(cell["query_latency_ms"]) for cell in budget_cells]
        summaries[str(budget)] = {
            "case_count": len(budget_cells),
            "required_evidence_atom_hits": atom_hits,
            "required_evidence_atom_denominator": atom_total,
            "required_evidence_set_coverage": round(atom_hits / atom_total, 9),
            "retained_evidence_atom_hits": retained_hits,
            "retained_evidence_atom_coverage": round(retained_hits / atom_total, 9),
            "answer_bearing_source_turn_hits": turn_hits,
            "answer_bearing_source_turn_denominator": turn_total,
            "answer_bearing_source_turn_recall": round(turn_hits / turn_total, 9),
            "operator_ready_case_count": sum(
                bool(cell["operator_ready"]) for cell in budget_cells
            ),
            "operator_ready_case_denominator": len(budget_cells),
            "packing_loss_count": sum(
                int(cell["packing_loss_count"]) for cell in budget_cells
            ),
            "wrong_complete_count": sum(
                bool(cell["wrong_complete"]) for cell in budget_cells
            ),
            "wrong_scope_or_authority_count": sum(
                bool(cell["wrong_scope_or_authority"]) for cell in budget_cells
            ),
            "candidate_noise_count": sum(
                int(cell["candidate_noise_count"]) for cell in budget_cells
            ),
            "candidate_noise_mean": round(
                mean(float(cell["candidate_noise_count"]) for cell in budget_cells),
                6,
            ),
            "selected_source_turn_count_mean": round(
                mean(float(cell["selected_source_turn_count"]) for cell in budget_cells),
                6,
            ),
            "query_latency_ms_mean": round(mean(latencies), 6),
            "query_latency_ms_p95": round(_percentile(latencies, 0.95), 6),
            "context_tokens_mean": round(
                mean(float(cell["context_tokens"]) for cell in budget_cells), 6
            ),
            "context_truncated_count": sum(
                bool(cell["context_truncated"]) for cell in budget_cells
            ),
        }
    return summaries


def q6_baseline(q6_receipt: Mapping[str, Any]) -> dict[str, Any]:
    raw_records = q6_receipt.get("records")
    if not isinstance(raw_records, list):
        raise A1AcquisitionError("Q6 baseline records are missing")
    records = [
        record
        for record in raw_records
        if isinstance(record, Mapping)
        and record.get("policy") == CURRENT_Q6_POLICY
        and record.get("token_budget") == 2048
    ]
    if len(records) != 10:
        raise A1AcquisitionError("Q6 baseline denominator drifted")
    correct = {
        str(record["case_id"])
        for record in records
        if isinstance(record.get("answer_score"), Mapping)
        and record["answer_score"].get("exact_match") == 1
    }
    if len(correct) != CURRENT_Q6_CORRECT_CASE_COUNT:
        raise A1AcquisitionError("Q6 current correct-case denominator drifted")
    ready = {
        str(record["case_id"])
        for record in records
        if len(_string_list(record.get("retrieved_atom_ids")))
        == _positive_int(record.get("required_atom_count"), "required_atom_count")
    }
    return {
        "current_correct_case_ids": sorted(correct),
        "current_correct_case_count": len(correct),
        "operator_ready_case_ids": sorted(ready),
        "operator_ready_case_count": len(ready),
        "wrong_complete_count": sum(bool(record.get("wrong_complete")) for record in records),
    }


def evaluate_a1_gate(
    summaries: Mapping[str, Mapping[str, Any]],
    cells: Sequence[Mapping[str, Any]],
    *,
    baseline: Mapping[str, Any],
    a0_required_evidence_coverage: int,
    automatic_retries: int,
) -> dict[str, Any]:
    main = summaries.get("2048")
    if not isinstance(main, Mapping):
        raise A1AcquisitionError("A1 2048 summary is missing")
    current_correct = set(_string_list(baseline.get("current_correct_case_ids")))
    retained = {
        str(cell["case_id"])
        for cell in cells
        if cell.get("token_budget") == 2048
        and cell.get("operator_ready") is True
        and str(cell.get("case_id")) in current_correct
    }
    baseline_ready = _positive_int(
        baseline.get("operator_ready_case_count"), "operator_ready_case_count"
    )
    checks = {
        "wrong_complete_zero": int(main["wrong_complete_count"]) == 0,
        "wrong_scope_or_authority_zero": int(main["wrong_scope_or_authority_count"]) == 0,
        "current_q6_correct_cases_retained_2_of_2": retained == current_correct,
        "required_evidence_atoms_at_least_9_of_23": (
            int(main["required_evidence_atom_hits"]) >= 9
            and int(main["required_evidence_atom_denominator"]) == 23
        ),
        "answer_bearing_source_turns_at_least_8_of_21": (
            int(main["answer_bearing_source_turn_hits"]) >= 8
            and int(main["answer_bearing_source_turn_denominator"]) == 21
        ),
        "operator_ready_cases_at_least_baseline_plus_2": (
            int(main["operator_ready_case_count"]) >= baseline_ready + 2
        ),
        "packing_loss_zero": int(main["packing_loss_count"]) == 0,
        "automatic_retries_zero": automatic_retries == 0,
        "a0_acquisition_loss_coverage_23_of_23": a0_required_evidence_coverage == 23,
    }
    return {
        "status": "PASS" if all(checks.values()) else "PARTIAL",
        "checks": checks,
        "thresholds_changed": False,
        "baseline_operator_ready_case_count": baseline_ready,
        "required_operator_ready_case_count": baseline_ready + 2,
        "current_q6_correct_case_ids": sorted(current_correct),
        "retained_current_q6_correct_case_ids": sorted(retained),
    }


def evaluate_a1_factor_disposition(gate: Mapping[str, Any]) -> dict[str, Any]:
    checks = gate.get("checks")
    if not isinstance(checks, Mapping):
        raise A1AcquisitionError("A1 cumulative gate checks are missing")
    a1_owned_checks = (
        "wrong_complete_zero",
        "wrong_scope_or_authority_zero",
        "current_q6_correct_cases_retained_2_of_2",
        "required_evidence_atoms_at_least_9_of_23",
        "answer_bearing_source_turns_at_least_8_of_21",
        "operator_ready_cases_at_least_baseline_plus_2",
        "automatic_retries_zero",
        "a0_acquisition_loss_coverage_23_of_23",
    )
    missing = [name for name in (*a1_owned_checks, "packing_loss_zero") if name not in checks]
    if missing:
        raise A1AcquisitionError(f"A1 cumulative gate checks drifted: {missing}")
    owned_results = {name: checks[name] is True for name in a1_owned_checks}
    status = "PASS_TO_A2" if all(owned_results.values()) else "PARTIAL"
    blockers = [name for name, passed in checks.items() if passed is not True]
    return {
        "status": status,
        "owned_checks": owned_results,
        "cumulative_acquisition_gate_status": gate.get("status"),
        "cumulative_gate_blockers": blockers,
        "deferred_owner": {
            "packing_loss_zero": "A7_SLOT_AWARE_EXPANSION_AND_CONTEXT_PACKING"
        },
        "A2_authorized": status == "PASS_TO_A2",
        "A10_authorized": gate.get("status") == "PASS",
    }


def _score_cell(
    record: Mapping[str, Any], label: Mapping[str, Any]
) -> dict[str, Any]:
    case_id = str(record.get("case_id"))
    context = record.get("context")
    mediators = record.get("semantic_mediators")
    if not isinstance(context, str) or not isinstance(mediators, Mapping):
        raise A1AcquisitionError("A1 Context record is malformed")
    selected_raw = mediators.get("selected_source_refs")
    atoms_raw = label.get("atoms")
    if not isinstance(selected_raw, list) or not isinstance(atoms_raw, list):
        raise A1AcquisitionError("A1 selected refs or labels are malformed")
    selected_refs = list(
        dict.fromkeys(compact_lme_source_ref(str(value)) for value in selected_raw)
    )
    selected_set = set(selected_refs)
    derived_result = mediators.get("derived_result")
    operands = (
        derived_result.get("operands", [])
        if isinstance(derived_result, Mapping)
        else []
    )
    if not isinstance(operands, list) or any(
        not isinstance(operand, Mapping) for operand in operands
    ):
        raise A1AcquisitionError("A1 derived-result operands are malformed")
    operator_operand_refs = list(
        dict.fromkeys(
            compact_lme_source_ref(str(operand["source_ref"]))
            for operand in operands
            if operand.get("source_ref") is not None
        )
    )
    acquired_refs = list(dict.fromkeys([*selected_refs, *operator_operand_refs]))
    acquired_set = set(acquired_refs)
    normalized_context = _normalized(context)
    atoms = [atom for atom in atoms_raw if isinstance(atom, Mapping)]
    if len(atoms) != len(atoms_raw) or not atoms:
        raise A1AcquisitionError("A1 atom denominator is malformed")
    candidate_atom_ids = [
        str(atom["atom_id"])
        for atom in atoms
        if str(atom["source_turn_ref"]) in acquired_set
    ]
    retained_atom_ids = [
        str(atom["atom_id"])
        for atom in atoms
        if str(atom["source_turn_ref"]) in acquired_set
        and (
            str(atom["source_turn_ref"]) in selected_set
            or _normalized(str(atom["span"]["text"])) in normalized_context
        )
    ]
    required_turns = {str(atom["source_turn_ref"]) for atom in atoms}
    hit_turns = required_turns.intersection(acquired_set)
    packed_turns = {
        str(atom["source_turn_ref"])
        for atom in atoms
        if str(atom["atom_id"]) in set(retained_atom_ids)
    }
    slot_atoms: defaultdict[str, set[str]] = defaultdict(set)
    for atom in atoms:
        slot_atoms[str(atom["slot"])].add(str(atom["atom_id"]))
    candidate_set = set(candidate_atom_ids)
    retained_set = set(retained_atom_ids)
    candidate_complete_slots = sorted(
        slot for slot, atom_ids in slot_atoms.items() if atom_ids <= candidate_set
    )
    retained_complete_slots = sorted(
        slot for slot, atom_ids in slot_atoms.items() if atom_ids <= retained_set
    )
    sufficiency = mediators.get("sufficiency")
    sufficiency_status = (
        str(sufficiency.get("status")) if isinstance(sufficiency, Mapping) else None
    )
    scope_authority = mediators.get("scope_authority")
    authority_safe = (
        isinstance(scope_authority, Mapping)
        and scope_authority.get("authority_class") == "EVIDENCE_ONLY"
        and scope_authority.get("canonical_mutation") is False
    )
    scope_safe = all(value.startswith(f"{case_id}:s") for value in selected_refs)
    packing_loss = sorted(candidate_set - retained_set)
    return {
        "case_id": case_id,
        "token_budget": int(record["token_budget"]),
        "policy": str(record["policy"]),
        "required_atom_count": len(atoms),
        "candidate_atom_hit_count": len(candidate_atom_ids),
        "candidate_atom_ids": candidate_atom_ids,
        "retained_atom_hit_count": len(retained_atom_ids),
        "retained_atom_ids": retained_atom_ids,
        "required_source_turn_count": len(required_turns),
        "candidate_source_turn_hit_count": len(hit_turns),
        "candidate_source_turn_refs": sorted(hit_turns),
        "packed_source_turn_hit_count": len(packed_turns),
        "candidate_complete_slots": candidate_complete_slots,
        "retained_complete_slots": retained_complete_slots,
        "required_slot_count": len(slot_atoms),
        "operator_ready": len(candidate_set) == len(atoms),
        "packing_loss_count": len(packing_loss),
        "packing_loss_atom_ids": packing_loss,
        "terminal_sufficiency_status": sufficiency_status,
        "wrong_complete": sufficiency_status == "COMPLETE" and len(candidate_set) < len(atoms),
        "wrong_scope_or_authority": not (scope_safe and authority_safe),
        "selected_source_turn_count": len(selected_refs),
        "operator_operand_source_turn_count": len(operator_operand_refs),
        "operator_operand_source_refs": operator_operand_refs,
        "acquired_source_turn_count": len(acquired_refs),
        "acquired_source_refs": acquired_refs,
        "candidate_noise_count": len(acquired_set - required_turns),
        "query_latency_ms": _number(record.get("query_latency_ms"), "query_latency_ms"),
        "context_tokens": _number(record.get("context_tokens"), "context_tokens"),
        "context_truncated": mediators.get("truncation") is True,
    }


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise A1AcquisitionError("expected a string list")
    return list(value)


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise A1AcquisitionError(f"{name} must be a non-negative integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise A1AcquisitionError(f"{name} must be a non-negative number")
    return float(value)


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise A1AcquisitionError("cannot compute a percentile of no values")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * quantile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


__all__ = [
    "CURRENT_Q6_POLICY",
    "A1AcquisitionError",
    "evaluate_a1_factor_disposition",
    "evaluate_a1_gate",
    "q6_baseline",
    "score_a1_records",
    "summarize_a1_records",
]

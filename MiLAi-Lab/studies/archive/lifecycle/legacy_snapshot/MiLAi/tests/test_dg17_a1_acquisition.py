from __future__ import annotations

from evals.dg17.a1_acquisition import (
    evaluate_a1_factor_disposition,
    evaluate_a1_gate,
    q6_baseline,
    score_a1_records,
    summarize_a1_records,
)


def _label(case_id: str, atom_count: int) -> dict[str, object]:
    return {
        "atoms": [
            {
                "atom_id": f"{case_id}-atom-{index}",
                "slot": "LOOKUP_ANSWER",
                "source_turn_ref": f"{case_id}:s0:session-a:t{index}",
                "span": {"text": f"answer {case_id} {index}"},
            }
            for index in range(atom_count)
        ]
    }


def _record(case_id: str, budget: int, atom_count: int) -> dict[str, object]:
    refs = [
        f"longmemeval://case/{case_id}/session/0/session-a/turn/{index}?event_id=x"
        for index in range(atom_count)
    ]
    context = "\n".join(f"answer {case_id} {index}" for index in range(atom_count))
    return {
        "case_id": case_id,
        "token_budget": budget,
        "policy": "DG17_QUERY_SPECIFIC_STOP",
        "context": context,
        "context_tokens": 100,
        "query_latency_ms": 10.0,
        "semantic_mediators": {
            "selected_source_refs": refs,
            "scope_authority": {
                "authority_class": "EVIDENCE_ONLY",
                "canonical_mutation": False,
            },
            "sufficiency": {"status": "COMPLETE"},
            "truncation": False,
        },
    }


def test_a1_scores_exact_source_identity_and_gate_denominators() -> None:
    case_ids = [f"case-{index}" for index in range(10)]
    atom_counts = {case_id: (5 if index == 0 else 2) for index, case_id in enumerate(case_ids)}
    labels = {case_id: _label(case_id, atom_counts[case_id]) for case_id in case_ids}
    records = [
        _record(case_id, budget, atom_counts[case_id])
        for budget in (512, 2048)
        for case_id in case_ids
    ]

    cells = score_a1_records(records, labels=labels)
    summaries = summarize_a1_records(cells)
    baseline = {
        "current_correct_case_ids": ["case-0", "case-1"],
        "operator_ready_case_count": 2,
    }
    gate = evaluate_a1_gate(
        summaries,
        cells,
        baseline=baseline,
        a0_required_evidence_coverage=23,
        automatic_retries=0,
    )

    assert summaries["2048"]["required_evidence_atom_hits"] == 23
    assert summaries["2048"]["answer_bearing_source_turn_hits"] == 23
    assert summaries["2048"]["packing_loss_count"] == 0
    assert gate["checks"]["current_q6_correct_cases_retained_2_of_2"] is True
    assert gate["status"] == "PARTIAL"  # production turn denominator is fixed at 21


def test_q6_baseline_uses_current_exact_matches_and_atom_complete_cases() -> None:
    records = []
    for index in range(10):
        records.append(
            {
                "case_id": f"case-{index}",
                "token_budget": 2048,
                "policy": "DG17_QUERY_SPECIFIC_STOP",
                "answer_score": {"exact_match": int(index < 2)},
                "retrieved_atom_ids": ["atom"] if index < 3 else [],
                "required_atom_count": 1,
                "wrong_complete": False,
            }
        )

    baseline = q6_baseline({"records": records})

    assert baseline["current_correct_case_ids"] == ["case-0", "case-1"]
    assert baseline["operator_ready_case_count"] == 3


def test_a1_gate_passes_only_with_the_frozen_23_atom_21_turn_denominator() -> None:
    main = {
        "wrong_complete_count": 0,
        "wrong_scope_or_authority_count": 0,
        "required_evidence_atom_hits": 9,
        "required_evidence_atom_denominator": 23,
        "answer_bearing_source_turn_hits": 8,
        "answer_bearing_source_turn_denominator": 21,
        "operator_ready_case_count": 4,
        "packing_loss_count": 0,
    }
    cells = [
        {"case_id": case_id, "token_budget": 2048, "operator_ready": True}
        for case_id in ("case-0", "case-1")
    ]

    gate = evaluate_a1_gate(
        {"2048": main},
        cells,
        baseline={
            "current_correct_case_ids": ["case-0", "case-1"],
            "operator_ready_case_count": 2,
        },
        a0_required_evidence_coverage=23,
        automatic_retries=0,
    )

    assert gate["status"] == "PASS"
    assert all(gate["checks"].values())


def test_a1_counts_deterministic_operator_operand_source_and_packing() -> None:
    case_ids = [f"case-{index}" for index in range(10)]
    labels = {case_id: _label(case_id, 1) for case_id in case_ids}
    records = [
        _record(case_id, budget, 1)
        for budget in (512, 2048)
        for case_id in case_ids
    ]
    target = next(
        record
        for record in records
        if record["case_id"] == "case-0" and record["token_budget"] == 2048
    )
    target["semantic_mediators"]["selected_source_refs"] = []  # type: ignore[index]
    target["semantic_mediators"]["derived_result"] = {  # type: ignore[index]
        "operands": [
            {
                "source_ref": (
                    "longmemeval://case/case-0/session/0/session-a/turn/0?event_id=x"
                )
            }
        ]
    }

    cell = next(
        row
        for row in score_a1_records(records, labels=labels)
        if row["case_id"] == "case-0" and row["token_budget"] == 2048
    )

    assert cell["candidate_atom_hit_count"] == 1
    assert cell["retained_atom_hit_count"] == 1
    assert cell["operator_ready"] is True
    assert cell["packing_loss_count"] == 0
    assert cell["wrong_complete"] is False


def test_a1_factor_can_progress_while_a7_owned_packing_gate_remains_open() -> None:
    checks = {
        "wrong_complete_zero": True,
        "wrong_scope_or_authority_zero": True,
        "current_q6_correct_cases_retained_2_of_2": True,
        "required_evidence_atoms_at_least_9_of_23": True,
        "answer_bearing_source_turns_at_least_8_of_21": True,
        "operator_ready_cases_at_least_baseline_plus_2": True,
        "packing_loss_zero": False,
        "automatic_retries_zero": True,
        "a0_acquisition_loss_coverage_23_of_23": True,
    }

    disposition = evaluate_a1_factor_disposition(
        {"status": "PARTIAL", "checks": checks}
    )

    assert disposition["status"] == "PASS_TO_A2"
    assert disposition["A2_authorized"] is True
    assert disposition["A10_authorized"] is False
    assert disposition["cumulative_gate_blockers"] == ["packing_loss_zero"]

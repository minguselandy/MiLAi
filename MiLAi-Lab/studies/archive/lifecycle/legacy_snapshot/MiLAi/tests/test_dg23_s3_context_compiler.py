from __future__ import annotations

from pathlib import Path

from milai.application.memory_context import (
    ContextTokenAccountingError,
    MemoryContextCompiler,
)
from milai.application.reader_evidence_plan import build_decision_snapshot
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.reader_evidence_plan import AcceptedBindingSpan, ContextBudgetEnvelope

from evals.dg23.context_compiler_contract import (
    build_context_compiler_contract_report,
)

ROOT = Path(__file__).resolve().parents[1]


def test_dg23_s3_atomic_nested_and_saturated_contracts_pass() -> None:
    report = build_context_compiler_contract_report(ROOT)

    assert report["status"] == "PASS_ATOMIC_NESTED_CONTEXT_COMPILER"
    assert report["hard_gate"]["passed"]
    checks = report["hard_gate"]["checks"]
    assert checks["atomic_unit_truncation_zero"]
    assert checks["nested_selected_units"]
    assert checks["common_unit_order_stable"]
    assert checks["saturated_context_byte_identical"]


def test_dg23_s3_infeasible_and_oversized_optional_are_typed() -> None:
    report = build_context_compiler_contract_report(ROOT)
    checks = report["hard_gate"]["checks"]

    assert checks["budget_below_protected_closure_typed_infeasible"]
    assert checks["oversized_optional_does_not_block_later_short_useful"]
    assert checks["topic_duplicate_and_zero_gain_not_quota_filled"]


def test_dg23_s3_conflict_permutation_and_wrapper_contracts_pass() -> None:
    report = build_context_compiler_contract_report(ROOT)
    checks = report["hard_gate"]["checks"]

    assert checks["conflict_sides_protected_together"]
    assert checks["open_issue_safety_protected"]
    assert checks["repository_permutation_plan_digest_invariant"]
    assert checks["compile_wrapper_matches_plan_render"]
    assert checks["candidate_default_false"]


def test_dg23_s3_exact_envelope_uses_injected_reader_counter() -> None:
    compiler = MemoryContextCompiler(
        budget_stable_enabled=True,
        exact_token_counter=lambda text: len(text.split()),
        exact_tokenizer_identity="frozen-reader-tokenizer",
    )
    request = MemoryResolveRequest(
        query="What value was remembered?",
        budget=MemoryResolveBudget(max_context_tokens=8000),
    )
    outcome = {
        "status": "HIT",
        "_reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
        "items": [],
        "sufficiency_decision": {"status": "PARTIAL", "missing_slots": ["R1"]},
    }
    snapshot = build_decision_snapshot(
        source_snapshot_material={},
        query_ir_material={},
        acquisition_plan_material={},
        candidate_snapshot_material={},
        gate_material={},
        binding_material={},
        requirement_state_material={},
        sufficiency_material={},
        operator_result_material=None,
        required_requirement_ids=["R1"],
        unresolved_requirement_ids=["R1"],
    )
    planned = compiler.plan(request, outcome, decision_snapshot=snapshot)
    exact = compiler.render(
        planned,
        ContextBudgetEnvelope(
            requested_cap=8000,
            model_context_limit=8000,
            available_memory_tokens=8000,
            reader_tokenizer_identity="frozen-reader-tokenizer",
            budget_source="EXACT_READER_ENVELOPE",
        ),
    )

    assert exact.reader_render is not None
    assert exact.reader_render.exact_tokens == len(exact.memory_context.text.split())
    assert exact.memory_context.compile_trace["token_accounting_method"] == (
        "READER_EXACT_TOKENIZER"
    )
    assert exact.memory_context.compile_trace["whole_unit_admission"] is True
    assert exact.memory_context.compile_trace["long_turn_split_count"] == 0
    assert exact.memory_context.compile_trace["rank_first_prefix_violation_count"] == 0


def test_dg23_s3_compile_uses_bound_exact_reader_authority() -> None:
    compiler = MemoryContextCompiler(
        budget_stable_enabled=True,
        exact_token_counter=lambda text: len(text.split()),
        exact_tokenizer_identity="frozen-reader-tokenizer",
    )
    request = MemoryResolveRequest(
        query="What value was remembered?",
        budget=MemoryResolveBudget(max_context_tokens=8000),
    )
    outcome = {"status": "ABSENT", "items": []}

    compilation = compiler.compile(request, outcome)

    assert compilation.reader_render is not None
    assert compilation.reader_render.envelope.budget_source == "EXACT_READER_ENVELOPE"
    assert (
        compilation.reader_render.envelope.reader_tokenizer_identity
        == "frozen-reader-tokenizer"
    )
    assert compilation.memory_context.compile_trace["token_accounting_method"] == (
        "READER_EXACT_TOKENIZER"
    )


def test_dg23_s3_exact_counter_and_identity_are_atomic_configuration() -> None:
    try:
        MemoryContextCompiler(
            budget_stable_enabled=True,
            exact_token_counter=lambda text: len(text),
        )
    except ValueError as exc:
        assert "configured together" in str(exc)
    else:
        raise AssertionError("unidentified exact token counter must be rejected")


def test_dg23_s3_exact_envelope_identity_mismatch_fails_closed() -> None:
    compiler = MemoryContextCompiler(
        budget_stable_enabled=True,
        exact_token_counter=lambda text: len(text.split()),
        exact_tokenizer_identity="configured-tokenizer",
    )
    request = MemoryResolveRequest(
        query="What value was remembered?",
        budget=MemoryResolveBudget(max_context_tokens=8000),
    )
    planned = compiler.plan(request, {"status": "ABSENT", "items": []})

    try:
        compiler.render(
            planned,
            ContextBudgetEnvelope(
                requested_cap=8000,
                model_context_limit=8000,
                available_memory_tokens=8000,
                reader_tokenizer_identity="different-tokenizer",
                budget_source="EXACT_READER_ENVELOPE",
            ),
        )
    except ContextTokenAccountingError as exc:
        assert exc.reason_code == "TOKENIZER_IDENTITY_MISMATCH"
    else:
        raise AssertionError("mismatched exact tokenizer identity must fail closed")


def test_dg23_s3_exact_envelope_without_counter_fails_closed() -> None:
    compiler = MemoryContextCompiler(budget_stable_enabled=True)
    request = MemoryResolveRequest(
        query="What value was remembered?",
        budget=MemoryResolveBudget(max_context_tokens=8000),
    )
    outcome = {"status": "ABSENT", "items": []}
    planned = compiler.plan(request, outcome)
    envelope = ContextBudgetEnvelope(
        requested_cap=8000,
        model_context_limit=8000,
        available_memory_tokens=8000,
        reader_tokenizer_identity="missing-reader-tokenizer",
        budget_source="EXACT_READER_ENVELOPE",
    )

    try:
        compiler.render(planned, envelope)
    except ContextTokenAccountingError as exc:
        assert exc.reason_code == "TOKENIZER_UNAVAILABLE"
    else:
        raise AssertionError("exact envelope must fail closed without a tokenizer")


def test_dg23_s3_only_binding_backed_evidence_is_protected() -> None:
    compiler = MemoryContextCompiler(budget_stable_enabled=True)
    request = MemoryResolveRequest(
        query="What value was remembered?",
        budget=MemoryResolveBudget(max_context_tokens=8000),
    )
    bound_text = "I remembered the governed answer."
    outcome = {
        "status": "HIT",
        "items": [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "bound",
                "source_ref": "memory://session/turn/1",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "content": bound_text,
                "observed_at": "2026-08-28T08:00:00+00:00",
            },
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "accepted-but-unbound",
                "source_ref": "memory://session/turn/2",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "content": "An unrelated accepted candidate with no Binding.",
                "observed_at": "2026-08-28T08:01:00+00:00",
            },
        ],
    }
    span = AcceptedBindingSpan(
        requirement_ids=("R1",),
        evidence_id="bound",
        source_turn_ref="memory://session/turn/1",
        session_id="session",
        speaker="user",
        start=0,
        end=len(bound_text),
        text=bound_text,
        observed_at="2026-08-28T08:00:00+00:00",
    )
    snapshot = build_decision_snapshot(
        source_snapshot_material={},
        query_ir_material={},
        acquisition_plan_material={},
        candidate_snapshot_material={},
        gate_material={},
        binding_material={},
        requirement_state_material={},
        sufficiency_material={},
        operator_result_material=None,
        accepted_evidence_ids=("accepted-but-unbound", "bound"),
        accepted_binding_spans=(span,),
        required_requirement_ids=("R1",),
    )

    planned = compiler.plan(request, outcome, decision_snapshot=snapshot)
    protected_evidence_ids = {
        evidence_id
        for unit in planned.reader_evidence_plan.protected_units
        for evidence_id in unit.evidence_ids
    }

    assert planned.required_evidence_ids == ("bound",)
    assert "bound" in protected_evidence_ids
    assert "accepted-but-unbound" not in protected_evidence_ids

    rendered = compiler.compile(request, outcome, decision_snapshot=snapshot)
    receipt = rendered.evidence_receipt
    assert receipt is not None
    assert rendered.memory_context.available_windows == 1
    assert rendered.memory_context.selected_windows == 1
    assert len(rendered.memory_context.windows) == 1
    assert "[E1 ACCEPTED BINDING SPAN" in rendered.memory_context.text
    assert "[B1 " not in rendered.memory_context.text
    window_mappings = [
        mapping for mapping in receipt.receipt_mapping if mapping.alias.startswith("E")
    ]
    assert [mapping.alias for mapping in window_mappings] == [
        f"E{ordinal}" for ordinal in range(1, len(window_mappings) + 1)
    ]
    assert [
        (mapping.evidence_ids, mapping.source_turn_refs) for mapping in window_mappings
    ] == [
        (window.evidence_ids, window.source_turn_refs)
        for window in rendered.memory_context.windows
    ]
    assert all(
        f"[{mapping.alias} " in rendered.memory_context.text
        for mapping in window_mappings
    )
    mapped_ids = [
        evidence_id
        for mapping in receipt.receipt_mapping
        for evidence_id in mapping.evidence_ids
    ]
    assert mapped_ids == rendered.memory_context.selected_evidence_ids
    assert len(mapped_ids) == len(set(mapped_ids))


def test_dg23_s3_multiple_bindings_share_one_contiguous_e_alias_namespace() -> None:
    compiler = MemoryContextCompiler(budget_stable_enabled=True)
    request = MemoryResolveRequest(
        query="Compare the first and second governed values",
        budget=MemoryResolveBudget(max_context_tokens=8000),
    )
    items = [
        {
            "kind": "EVIDENCE_OBSERVATION",
            "evidence_id": f"bound-{ordinal}",
            "source_ref": f"memory://session/turn/{ordinal}",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
            "content": f"The governed value {ordinal} is retained.",
            "observed_at": f"2026-08-28T08:0{ordinal}:00+00:00",
        }
        for ordinal in (1, 2)
    ]
    spans = tuple(
        AcceptedBindingSpan(
            requirement_ids=(f"R{ordinal}",),
            evidence_id=f"bound-{ordinal}",
            source_turn_ref=f"memory://session/turn/{ordinal}",
            session_id="session",
            speaker="user",
            start=0,
            end=len(f"The governed value {ordinal} is retained."),
            text=f"The governed value {ordinal} is retained.",
            observed_at=f"2026-08-28T08:0{ordinal}:00+00:00",
        )
        for ordinal in (1, 2)
    )
    outcome = {
        "status": "HIT",
        "_reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
        "items": items,
    }
    snapshot = build_decision_snapshot(
        source_snapshot_material={},
        query_ir_material={},
        acquisition_plan_material={},
        candidate_snapshot_material={},
        gate_material={},
        binding_material={},
        requirement_state_material={},
        sufficiency_material={},
        operator_result_material=None,
        accepted_evidence_ids=("bound-1", "bound-2"),
        accepted_binding_spans=spans,
        required_requirement_ids=("R1", "R2"),
    )

    rendered = compiler.compile(request, outcome, decision_snapshot=snapshot)
    receipt = rendered.evidence_receipt
    assert receipt is not None
    aliases = [
        mapping.alias
        for mapping in receipt.receipt_mapping
        if mapping.alias.startswith("E")
    ]
    assert aliases == [f"E{ordinal}" for ordinal in range(1, len(aliases) + 1)]
    assert "[E1 ACCEPTED BINDING SPAN" in rendered.memory_context.text
    assert "[E2 ACCEPTED BINDING SPAN" in rendered.memory_context.text
    assert "[B1 " not in rendered.memory_context.text


def test_dg23_s3_open_issue_header_and_receipt_use_exact_i1_alias() -> None:
    compiler = MemoryContextCompiler(budget_stable_enabled=True)
    request = MemoryResolveRequest(
        query="Which governed value is safe?",
        budget=MemoryResolveBudget(max_context_tokens=8000),
    )
    outcome = {
        "status": "CONTESTED",
        "items": [],
        "open_issue_ids": ["issue-alpha", "issue-beta"],
        "sufficiency_decision": {
            "status": "CONTESTED",
            "missing_slots": ["R1"],
        },
    }

    rendered = compiler.compile(request, outcome)
    receipt = rendered.evidence_receipt
    assert receipt is not None
    assert "[I1 OPEN ISSUE / SAFETY]" in rendered.memory_context.text
    issue_mapping = next(
        mapping for mapping in receipt.receipt_mapping if mapping.alias == "I1"
    )
    assert [value.issue_id for value in issue_mapping.issue_revisions] == [
        "issue-alpha",
        "issue-beta",
    ]


def test_dg23_s3_receipt_mapping_follows_e1_i1_e2_render_order() -> None:
    compiler = MemoryContextCompiler(budget_stable_enabled=True)
    request = MemoryResolveRequest(
        query="Which governed launch value is safe?",
        budget=MemoryResolveBudget(max_context_tokens=8000),
    )
    bound_text = "The governed launch value is blue."
    optional_text = "A launch value safety note says to verify blue."
    outcome = {
        "status": "CONTESTED",
        "_reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
        "items": [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "optional",
                "source_ref": "memory://session/turn/2",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "content": optional_text,
                "observed_at": "2026-08-28T08:01:00+00:00",
            },
        ],
        "open_issue_ids": ["issue-alpha"],
        "sufficiency_decision": {
            "status": "CONTESTED",
            "missing_slots": ["R2"],
        },
    }
    span = AcceptedBindingSpan(
        requirement_ids=("R1",),
        evidence_id="bound",
        source_turn_ref="memory://session/turn/1",
        session_id="session",
        speaker="user",
        start=0,
        end=len(bound_text),
        text=bound_text,
        observed_at="2026-08-28T08:00:00+00:00",
    )
    snapshot = build_decision_snapshot(
        source_snapshot_material={},
        query_ir_material={},
        acquisition_plan_material={},
        candidate_snapshot_material={},
        gate_material={},
        binding_material={},
        requirement_state_material={},
        sufficiency_material={},
        operator_result_material=None,
        accepted_evidence_ids=("bound",),
        accepted_binding_spans=(span,),
        required_requirement_ids=("R1", "R2"),
        unresolved_requirement_ids=("R2",),
    )

    rendered = compiler.compile(request, outcome, decision_snapshot=snapshot)
    receipt = rendered.evidence_receipt
    assert receipt is not None
    assert [mapping.alias for mapping in receipt.receipt_mapping] == [
        "E1",
        "I1",
        "E2",
    ]
    assert (
        rendered.memory_context.text.index("[E1 ")
        < rendered.memory_context.text.index("[I1 ")
        < rendered.memory_context.text.index("[E2 ")
    )


def test_dg23_s3_empty_operator_support_does_not_promote_proof_candidates() -> None:
    compiler = MemoryContextCompiler(budget_stable_enabled=True)
    request = MemoryResolveRequest(
        query="How many governed events occurred?",
        budget=MemoryResolveBudget(max_context_tokens=8000),
    )
    outcome = {
        "status": "HIT",
        "items": [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "proof-candidate",
                "source_ref": "memory://session/turn/1",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "content": "A classified event whose occurrence time is unresolved.",
                "observed_at": "2026-08-28T08:00:00+00:00",
            }
        ],
        "derived_result": {
            "status": "PARTIAL",
            "operator": "COUNT",
            "value": None,
            "reason": "EVENT_TIME_UNRESOLVED",
            "operands": [],
            "evidence_refs": [],
            "source_turn_refs": [],
            "canonical_mutation": False,
            "completeness": {
                "bounded_scan_complete": False,
                "unresolved_reasons": ["EVENT_TIME_UNRESOLVED"],
            },
        },
        "sufficiency_decision": {"status": "PARTIAL", "missing_slots": ["R1"]},
    }
    snapshot = build_decision_snapshot(
        source_snapshot_material={},
        query_ir_material={},
        acquisition_plan_material={},
        candidate_snapshot_material={"candidate_ids": ["proof-candidate"]},
        gate_material={},
        binding_material={},
        requirement_state_material={},
        sufficiency_material={},
        operator_result_material=outcome["derived_result"],
        accepted_evidence_ids=("proof-candidate",),
        accepted_binding_spans=(),
        required_requirement_ids=("R1",),
        unresolved_requirement_ids=("R1",),
    )

    planned = compiler.plan(request, outcome, decision_snapshot=snapshot)

    assert planned.required_evidence_ids == ()
    assert planned.required_source_refs == ()
    assert all(
        "proof-candidate" not in unit.evidence_ids
        for unit in planned.reader_evidence_plan.protected_units
    )
    candidate_is_optional = any(
        "proof-candidate" in unit.evidence_ids
        for unit in planned.reader_evidence_plan.conditional_units
    )
    candidate_is_omitted = any(
        unit.reason == "NO_ADMISSIBLE_SEMANTIC_GAIN"
        for unit in planned.reader_evidence_plan.omitted_units
    )
    assert candidate_is_optional or candidate_is_omitted


def test_dg23_s3_reader_derived_projection_omits_recoverable_proof_bulk() -> None:
    compiler = MemoryContextCompiler(budget_stable_enabled=True)
    request = MemoryResolveRequest(
        query="How many governed events occurred?",
        budget=MemoryResolveBudget(max_context_tokens=8000),
    )
    outcome = {
        "status": "PARTIAL",
        "items": [],
        "derived_result": {
            "status": "PARTIAL",
            "kind": "EVIDENCE_COMPOSITION_RESULT",
            "operator": "TEMPORAL_COUNT_DISTINCT",
            "value": None,
            "reason": "EVENT_TIME_UNRESOLVED",
            "canonical_mutation": False,
            "completeness": {
                "required_slots": ["MATCHING_EVENTS_IN_RANGE"],
                "filled_slots": [],
                "unresolved_reasons": ["EVENT_TIME_UNRESOLVED"],
                "bounded_scan_complete": False,
                "deduplication_proven": False,
                "projection_position": 2468,
                "target_position": 2468,
                "projection_watermark_covered": True,
            },
        },
        "sufficiency_decision": {
            "status": "PARTIAL",
            "missing_slots": ["MATCHING_EVENTS_IN_RANGE"],
        },
    }

    planned = compiler.plan(request, outcome)
    derived = next(
        unit
        for unit in planned.reader_evidence_plan.protected_units
        if unit.unit_id == "derived-result"
    )

    assert "EVENT_TIME_UNRESOLVED" in derived.text
    assert '"bounded_scan_complete": false' in derived.text
    assert '"deduplication_proven": false' in derived.text
    assert "projection_position" not in derived.text
    assert "target_position" not in derived.text

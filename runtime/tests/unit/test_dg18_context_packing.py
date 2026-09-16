from __future__ import annotations

from typing import Any

from milai.application.memory_context import MemoryContextCompiler
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest


def _request(*, budget: int = 512) -> MemoryResolveRequest:
    return MemoryResolveRequest(
        query="How many days passed between the ukulele lessons and the guitar service?",
        budget=MemoryResolveBudget(max_context_tokens=budget),
    )


def _evidence(
    evidence_id: str,
    source_ref: str,
    session_id: str,
    content: str,
    *,
    matched_slots: list[str] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "evidence_id": evidence_id,
        "source_ref": source_ref,
        "subject_id": session_id,
        "observed_at": "2026-08-27T00:00:00+00:00",
        "content": content,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "relevance_score": 1.0,
    }
    if matched_slots is not None:
        item["acquisition_candidate"] = {"matched_slots": matched_slots}
    return item


def _outcome(items: list[dict[str, Any]], derived_result: object) -> dict[str, Any]:
    return {
        "status": "HIT",
        "requirement": "SEARCH",
        "items": items,
        "open_issue_ids": [],
        "canonical_position": {"evidence_watermark": 11},
        "sufficiency_decision": {
            "status": "COMPLETE",
            "covered_slots": ["EVENT_1", "EVENT_2"],
            "missing_slots": [],
        },
        "derived_result": derived_result,
    }


def _temporal_result(operands: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "OK",
        "kind": "DERIVED_QUERY_RESULT",
        "operator": "TEMPORAL_DISTANCE",
        "value": 24,
        "unit": "days",
        "operands": operands,
        "completeness": {
            "required_slots": ["EVENT_1", "EVENT_2"],
            "filled_slots": ["EVENT_1", "EVENT_2"],
            "unresolved_reasons": [],
        },
        "hidden_model_calls": 0,
        "canonical_mutation": False,
    }


def test_r1a_reserves_all_validated_derived_operand_sources_before_distractors() -> None:
    lessons_ref = "memory://session/lessons/turn/4"
    service_ref = "memory://session/service/turn/8"
    repeated_noise = " unrelated itinerary detail" * 40
    result = MemoryContextCompiler().compile(
        _request(),
        _outcome(
            [
                _evidence(
                    "noise-one",
                    "memory://session/noise/turn/0",
                    "noise",
                    "The trip lasted 24 days." + repeated_noise,
                    matched_slots=["EVENT_1", "EVENT_2"],
                ),
                _evidence(
                    "lessons",
                    lessons_ref,
                    "lessons",
                    "I started ukulele lessons with Rachel today." + repeated_noise,
                ),
                _evidence(
                    "service",
                    service_ref,
                    "service",
                    "I took the guitar to a technician for service today." + repeated_noise,
                ),
            ],
            _temporal_result(
                [
                    {
                        "authority_class": "EVIDENCE_ONLY",
                        "evidence_ids": ["lessons"],
                        "source_ref": lessons_ref,
                        "source_span": "I started ukulele lessons with Rachel today.",
                    },
                    {
                        "authority_class": "EVIDENCE_ONLY",
                        "evidence_ids": ["service"],
                        "source_ref": service_ref,
                        "source_span": "I took the guitar to a technician for service today.",
                    },
                ]
            ),
        ),
    )

    context = result.memory_context
    assert {"lessons", "service"} <= set(context.selected_evidence_ids)
    assert {lessons_ref, service_ref} <= set(context.selected_source_turn_refs)
    assert context.compile_trace["required_windows_selected"] == 2
    assert context.compile_trace["required_evidence_packing_loss_count"] == 0
    assert context.compile_trace["required_source_turn_packing_loss_count"] == 0
    assert all(window.requirement_priority for window in context.windows[:2])


def test_r1a_receipt_only_claims_required_sources_actually_selected() -> None:
    present_ref = "memory://session/present/turn/4"
    missing_ref = "memory://session/missing/turn/8"
    result = MemoryContextCompiler().compile(
        _request(),
        _outcome(
            [
                _evidence(
                    "present",
                    present_ref,
                    "present",
                    "I started ukulele lessons today.",
                )
            ],
            _temporal_result(
                [
                    {
                        "authority_class": "EVIDENCE_ONLY",
                        "evidence_ids": ["present"],
                        "source_ref": present_ref,
                    },
                    {
                        "authority_class": "EVIDENCE_ONLY",
                        "evidence_ids": ["missing"],
                        "source_ref": missing_ref,
                    },
                ]
            ),
        ),
    )

    context = result.memory_context
    receipt = result.evidence_receipt
    assert receipt is not None
    assert context.selected_evidence_ids == ["present"]
    assert context.selected_source_turn_refs == [present_ref]
    assert receipt.source_evidence_ids == ["present"]
    derived_mapping = next(mapping for mapping in receipt.receipt_mapping if mapping.alias == "D1")
    assert derived_mapping.evidence_ids == ["present"]
    assert derived_mapping.source_turn_refs == [present_ref]
    assert context.compile_trace["required_evidence_packing_loss_count"] == 1
    assert context.compile_trace["required_source_turn_packing_loss_count"] == 1


def test_r1a_recovers_exact_derived_operand_span_omitted_from_result_items() -> None:
    lessons_ref = "memory://session/lessons/turn/4"
    service_ref = "memory://session/service/turn/8"
    result = MemoryContextCompiler().compile(
        _request(budget=512),
        _outcome(
            [
                _evidence(
                    "lessons",
                    lessons_ref,
                    "lessons",
                    "I started ukulele lessons with Rachel today.",
                ),
                _evidence(
                    "noise",
                    "memory://session/noise/turn/0",
                    "noise",
                    "An unrelated long response." * 200,
                ),
            ],
            _temporal_result(
                [
                    {
                        "authority_class": "EVIDENCE_ONLY",
                        "evidence_ids": ["lessons"],
                        "source_ref": lessons_ref,
                        "source_span": "I started ukulele lessons with Rachel today.",
                        "source_timestamp": "2026-08-01T00:00:00+00:00",
                    },
                    {
                        "authority_class": "EVIDENCE_ONLY",
                        "evidence_ids": ["service"],
                        "source_ref": service_ref,
                        "source_span": "I took the guitar to a technician for service today.",
                        "source_timestamp": "2026-08-25T00:00:00+00:00",
                    },
                ]
            ),
        ),
    )

    context = result.memory_context
    assert {"lessons", "service"} <= set(context.selected_evidence_ids)
    assert {lessons_ref, service_ref} <= set(context.selected_source_turn_refs)
    assert "I took the guitar to a technician for service today." in context.text
    assert context.compile_trace["derived_operand_source_recoveries"] == 1
    assert context.compile_trace["required_evidence_packing_loss_count"] == 0
    assert context.compile_trace["required_source_turn_packing_loss_count"] == 0


def test_r1a_matched_slots_are_not_treated_as_validated_requirement_coverage() -> None:
    result = MemoryContextCompiler().compile(
        _request(),
        _outcome(
            [
                _evidence(
                    "probe-hit-only",
                    "memory://session/probe/turn/0",
                    "probe",
                    "The trip lasted 24 days.",
                    matched_slots=["EVENT_1", "EVENT_2"],
                )
            ],
            None,
        ),
    )

    context = result.memory_context
    assert context.windows[0].requirement_priority is False
    assert context.compile_trace["requirement_evidence_count"] == 0
    assert context.compile_trace["required_evidence_selected_count"] == 0

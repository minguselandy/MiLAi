from __future__ import annotations

from milai.application.memory_context import MemoryContextCompiler
from milai.application.preference_composition import (
    synthesize_preference_evidence_view,
)
from milai.application.query_ir_compat import infer_operator_family
from milai.application.query_planner import QueryPlanner
from milai.domain.memory_resolve import MemoryResolveRequest
from milai.domain.retrieval import RetrievalRequest


def _plan():  # type: ignore[no-untyped-def]
    return QueryPlanner().plan(RetrievalRequest(route="L1", query="What is my Denver preference?"))


def _evidence(
    evidence_id: str,
    content: str,
    observed_at: str,
    *,
    speaker: str = "user",
) -> dict[str, object]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/{evidence_id}/turn/0",
        "subject_id": evidence_id,
        "observed_at": observed_at,
        "content": content,
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "canonical": False,
    }


def test_q5_preference_synthesis_is_noncanonical_and_order_stable() -> None:
    plan = _plan()
    evidence = [
        _evidence(
            "music",
            "I love Denver's live music scene.",
            "2023-05-01T12:00:00+00:00",
        ),
        _evidence(
            "food",
            "I enjoyed the Denver barbecue restaurants.",
            "2023-05-02T12:00:00+00:00",
        ),
    ]

    forward = synthesize_preference_evidence_view(plan, evidence)
    reverse = synthesize_preference_evidence_view(plan, list(reversed(evidence)))

    assert plan.operator is None
    assert plan.memory_query_ir is not None
    assert infer_operator_family(plan.memory_query_ir) == "PREFERENCE_RESOLVE"
    assert forward == reverse
    assert forward is not None
    assert forward["status"] == "PARTIAL"
    assert forward["kind"] == "PREFERENCE_EVIDENCE_VIEW"
    assert forward["view_class"] == "DERIVED_VIEW"
    assert forward["authority_class"] == "EVIDENCE_ONLY"
    assert forward["canonical"] is False
    assert forward["canonical_mutation"] is False
    assert forward["persisted"] is False
    assert forward["completeness"]["support_threshold_met"] is True
    assert forward["completeness"]["currentness_proven"] is False
    assert forward["completeness"]["unresolved_reasons"] == ["CANONICAL_CURRENTNESS_UNPROVEN"]
    assert forward["evidence_refs"] == ["music", "food"]
    assert all(signal["requirement_binding"]["status"] == "MATCH" for signal in forward["value"])


def test_q5_preference_conflict_or_missing_signal_never_becomes_current_state() -> None:
    plan = _plan()
    contested = synthesize_preference_evidence_view(
        plan,
        [
            _evidence(
                "positive",
                "I love Denver's music scene.",
                "2023-05-01T12:00:00+00:00",
            ),
            _evidence(
                "negative",
                "I dislike Denver's music scene.",
                "2023-05-02T12:00:00+00:00",
            ),
        ],
    )
    absent = synthesize_preference_evidence_view(
        plan,
        [
            _evidence(
                "assistant",
                "You may explore Denver's music scene.",
                "2023-05-02T12:00:00+00:00",
                speaker="assistant",
            )
        ],
    )

    assert contested is not None and contested["status"] == "CONTESTED"
    assert contested["reason"] == "PREFERENCE_EVIDENCE_CONFLICT"
    assert contested["canonical"] is False
    assert absent is not None and absent["status"] == "ABSENT"
    assert absent["value"] == []
    assert absent["completeness"]["filled_slots"] == []


def test_q5_evidence_source_speaker_is_not_the_preference_experiencer() -> None:
    result = synthesize_preference_evidence_view(
        _plan(),
        [
            _evidence(
                "assistant-report",
                "You told me that you love Denver's live music scene.",
                "2023-05-02T12:00:00+00:00",
                speaker="assistant",
            )
        ],
    )

    assert result is not None and result["status"] == "PARTIAL"
    assert result["value"][0]["span"]["speaker"] == "assistant"
    assert (
        result["value"][0]["span"]["provenance"]["speaker_source"]
        == "STRUCTURED_TURN_METADATA"
    )


def test_q5_context_labels_preference_view_as_evidence_only_derived_view() -> None:
    evidence_id = "e8e10d61-7c34-4a0e-a38c-1ca9eedf24e5"
    evidence = [
        _evidence(
            evidence_id,
            "I love Denver's live music scene.",
            "2023-05-01T12:00:00+00:00",
        )
    ]
    derived = synthesize_preference_evidence_view(_plan(), evidence)
    assert derived is not None
    signal = derived["value"][0]
    opaque_values = {
        signal["evidence_id"],
        signal["source_turn_ref"],
        signal["span"]["span_id"],
        signal["interpretation"]["interpretation_id"],
    }
    result = MemoryContextCompiler().compile(
        MemoryResolveRequest(query="What is my Denver preference?"),
        {
            "items": evidence,
            "derived_result": derived,
            "sufficiency_decision": {
                "status": "PARTIAL",
                "missing_slots": ["CURRENT_CANONICAL_PREFERENCE"],
            },
        },
    )

    assert "PREFERENCE_EVIDENCE_VIEW" in result.memory_context.text
    assert '"authority_class": "EVIDENCE_ONLY"' in result.memory_context.text
    assert '"view_class": "DERIVED_VIEW"' in result.memory_context.text
    assert '"canonical": false' in result.memory_context.text
    assert '"stance": "POSITIVE"' in result.memory_context.text
    assert '"interpretation"' not in result.memory_context.text
    assert '"requirement_binding"' not in result.memory_context.text
    assert '"span"' not in result.memory_context.text
    assert not any(value in result.memory_context.text for value in opaque_values)
    assert '"requirement_id"' not in result.memory_context.text
    assert '"interpretation_id"' not in result.memory_context.text
    assert '"span_id"' not in result.memory_context.text
    assert result.memory_context.authority_class == "EVIDENCE_ONLY"

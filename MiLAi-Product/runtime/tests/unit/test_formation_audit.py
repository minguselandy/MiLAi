from __future__ import annotations

from copy import deepcopy

from milai.domain.requirement_state import canonical_sha256
from milai.observability.formation_audit import (
    STAGES,
    FormationAuditInput,
    PassiveFormationAuditObserver,
    observe_passthrough,
)


def _availability() -> dict[str, str]:
    return {
        stage: (
            "NOT_IMPLEMENTED"
            if stage.startswith(("F10", "F20", "F30", "F40", "F50"))
            else "IMPLEMENTED"
        )
        for stage in STAGES
    }


def _input(kind: str, disposition: str = "GOVERNED_REVIEW_REQUIRED") -> FormationAuditInput:
    return FormationAuditInput(
        case_id="case-1",
        evidence_id="evidence-1",
        source_ref="memory://case-1/turn-1",
        obligation_id=f"obligation:{kind}",
        obligation_kind=kind,
        span_start=0,
        span_end=4,
        span_text="text",
        expected="expected",
        expected_canonical_disposition=disposition,
    )


def test_observer_localizes_missing_mention_without_authority() -> None:
    trace = PassiveFormationAuditObserver(_availability()).observe(
        _input("EVENT_MENTION")
    )

    assert trace.last_surviving_stage == "F00_RAW_EVIDENCE_CAPTURED"
    assert trace.first_loss_stage == "F20_MENTION_FORMED"
    assert trace.reason_code == "EVENT_MENTION_MISSED"
    assert trace.source_lineage_ok is True
    assert trace.audit_authority is False
    assert trace.canonical_mutation is False
    assert trace.provider_calls == 0
    assert [item.outcome for item in trace.stage_availability].count("FIRST_LOSS") == 1


def test_query_only_disposition_is_authorized_terminal_survival() -> None:
    trace = PassiveFormationAuditObserver(_availability()).observe(
        _input("CANONICAL_DISPOSITION", "NOT_APPLICABLE_QUERY_EVIDENCE_ONLY")
    )

    assert trace.first_loss_stage is None
    assert trace.reason_code == "TERMINAL_SURVIVAL"
    outcomes = {item.stage: item.outcome for item in trace.stage_availability}
    assert outcomes["F60_PROPOSAL_EMITTED"] == "AUTHORIZED_REJECTION"
    assert outcomes["F70_CANONICAL_DISPOSITION"] == "AUTHORIZED_REJECTION"


def test_projection_survives_through_raw_read_path() -> None:
    trace = PassiveFormationAuditObserver(_availability()).observe(
        _input("RETRIEVAL_PROJECTION")
    )

    assert trace.first_loss_stage is None
    assert trace.last_surviving_stage == "F80_RETRIEVAL_PROJECTION_BUILT"
    assert trace.reason_code == "TERMINAL_SURVIVAL"


def test_passthrough_preserves_exact_product_value_and_digest() -> None:
    value = {
        "evidence": {"id": "evidence-1", "content": "text"},
        "proposal": None,
        "canonical_state": [],
        "projection": ["evidence-1"],
        "query_output": {"status": "UNSATISFIED"},
    }
    before = deepcopy(value)
    before_digest = canonical_sha256(value)

    observed, _trace = observe_passthrough(
        value,
        observer=PassiveFormationAuditObserver(_availability()),
        audit_input=_input("EVENT_MENTION"),
    )

    assert observed is value
    assert value == before
    assert canonical_sha256(observed) == before_digest

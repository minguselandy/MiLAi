from __future__ import annotations

from datetime import UTC, datetime

from milai.application.evidence_atoms import (
    atom_source_span_valid,
    evidence_requirement_queries,
    project_evidence_atoms,
)
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest

REFERENCE = datetime(2023, 3, 27, 23, 35, tzinfo=UTC)


def _plan(query: str):  # type: ignore[no-untyped-def]
    return QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )


def test_q3a_legacy_atom_is_only_a_source_exact_interpretation_alias() -> None:
    content = "I attended the robotics demo on March 3rd."
    atoms = project_evidence_atoms(
        _plan(
            "What is the elapsed time in days from the robotics demo "
            "to the choir concert?"
        ),
        [
            {
                "evidence_id": "event-1",
                "source_ref": "memory://session/s1/turn/0",
                "subject_id": "s1",
                "observed_at": "2023-03-04T08:00:00+00:00",
                "captured_at": "2023-03-04T08:00:01+00:00",
                "content": content,
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
            }
        ],
    )

    event = next(atom for atom in atoms if atom.atom_type == "EVENT")
    assert atom_source_span_valid(event, content)
    assert event.text_span.text == "I attended the robotics demo on March 3rd."
    assert event.event_time.start == datetime(2023, 3, 3, tzinfo=UTC)
    assert event.source_timestamp == datetime(2023, 3, 4, 8, tzinfo=UTC)
    assert event.provenance["system_timestamp"] == "2023-03-04T08:00:01+00:00"
    assert event.provenance["time_basis"] == "EXPLICIT_EVENT_TIME"
    assert event.provenance["compatibility_alias"] is True
    assert event.provenance["requirement_binding_embedded"] is False
    assert "requirement_slot_id" not in event.provenance
    assert event.canonical is False
    assert event.authority_class == "EVIDENCE_ONLY"
    assert event.canonical_mutation is False


def test_q3a_body_prefix_never_becomes_evidence_source_lineage() -> None:
    content = "assistant: I attended the robotics demo on March 3rd."
    atoms = project_evidence_atoms(
        _plan("When was the robotics demo?"),
        [
            {
                "evidence_id": "prefix-only",
                "source_ref": "memory://session/s1/turn/0",
                "subject_id": "s1",
                "observed_at": "2023-03-04T08:00:00+00:00",
                "content": content,
            }
        ],
    )

    event = next(atom for atom in atoms if atom.atom_type == "EVENT")
    assert event.speaker == "unknown"
    assert event.provenance["speaker_source"] == "UNKNOWN"
    assert event.text_span.text == content
    assert atom_source_span_valid(event, content)


def test_q3a_legacy_alias_obeys_governed_source_eligibility() -> None:
    base = {
        "evidence_id": "blocked",
        "source_ref": "memory://session/s1/turn/0",
        "subject_id": "s1",
        "observed_at": REFERENCE.isoformat(),
        "content": "user: I baked bread yesterday.",
    }
    blocked = [
        {**base, "revoked_at": REFERENCE.isoformat()},
        {**base, "permission_snapshot": {"readable": False}},
        {**base, "retention_state": "EXPIRED"},
        {**base, "access_decision": "DENIED"},
    ]

    for item in blocked:
        assert project_evidence_atoms(
            _plan("How many times did I bake in the past two weeks?"),
            [item],
        ) == []


def test_q3a_legacy_quantity_alias_never_claims_a_requirement_slot() -> None:
    atoms = project_evidence_atoms(
        _plan("How much did I spend on each coffee mug for my coworkers?"),
        [
            {
                "evidence_id": "purchase",
                "source_ref": "memory://session/s1/turn/0",
                "subject_id": "s1",
                "observed_at": REFERENCE.isoformat(),
                "content": "user: I spent $60 on 5 coffee mugs for coworkers.",
            }
        ],
    )

    quantities = [atom for atom in atoms if atom.atom_type == "QUANTITY"]
    assert {(atom.value, atom.unit) for atom in quantities} == {
        (60, "USD"),
        (5, "COUNT"),
    }
    assert all("requirement_slot_id" not in atom.provenance for atom in quantities)
    assert all(atom.canonical_mutation is False for atom in quantities)


def test_q3a_requirement_queries_are_slot_specific_and_label_free() -> None:
    plan = _plan("How much did I spend on each ceramic planter?")
    queries = evidence_requirement_queries(plan)

    assert len(queries) == 2
    assert queries == ("ceramic planter", "ceramic planter")
    assert all("spent" not in query and "purchased" not in query for query in queries)
    assert all("case_id" not in query and "gold" not in query for query in queries)

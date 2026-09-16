from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from evals.dg22.acquisition_correctness import run_acquisition_correctness
from milai.application.accuracy_acquisition import (
    compile_requirement_complete_bundle,
    execute_requirement_complete_bundle,
)
from milai.application.memory_query import MemoryQueryCompiler


def test_s5_requirement_complete_acquisition_hard_gates() -> None:
    result = run_acquisition_correctness()

    assert result["status"] == "PASS_REQUIREMENT_COMPLETE_ACQUISITION_FUSION"
    assert result["hard_gate"]["passed"]
    assert result["metrics"]["target_requirement_count"] == 2
    assert result["metrics"]["global_probe_count"] == 0
    assert result["metrics"]["repeated_accepted_region"] == 0


def test_s5_development_ceiling_matrix_runs_once_per_config() -> None:
    matrix = run_acquisition_correctness()["development_ceiling_matrix"]

    assert [item["development_input_ceiling"] for item in matrix] == [8, 12, 16]
    assert all(
        item["functional_runs"] == item["repository_calls"] == 1 for item in matrix
    )


def test_exhaustive_fusion_keeps_primary_events_and_drops_repeats_and_indexes() -> None:
    reference = datetime(2031, 6, 30, 12, 0, tzinfo=UTC)
    query = MemoryQueryCompiler().compile(
        "How many babies were born to friends and family members?",
        reference_time=reference,
    )
    requirement_ids = [item.slot_id for item in query.requirements if item.required]
    bundle = compile_requirement_complete_bundle(
        query,
        requirement_ids,
        channel="FTS_ENRICHED",
        requirement_state_digest="1" * 64,
        acquisition_capability_digest="2" * 64,
    )
    rows = [
        _event(
            "primary-noah",
            "My cousin Lena had a baby boy named Noah in March.",
            reference - timedelta(days=3),
        ),
        _event(
            "repeat-noah",
            "My cousin Lena had a baby boy named Noah in March.",
            reference - timedelta(days=2),
        ),
        _event(
            "calendar-index",
            "And let me not forget my aunt's twins, Ava and Lily, who were born in April.",
            reference - timedelta(days=1),
        ),
        _event(
            "primary-mia",
            "Our friends welcomed a baby girl named Mia in April.",
            reference,
        ),
    ]

    execution = execute_requirement_complete_bundle(
        query,
        bundle,
        rows,
        current_requirement_state_digest="1" * 64,
        current_acquisition_capability_digest="2" * 64,
    )

    assert {item["evidence_id"] for item in execution["selected_evidence"]} == {
        "primary-noah",
        "primary-mia",
    }


def _event(evidence_id: str, content: str, observed_at: datetime) -> dict[str, object]:
    source_ref = f"memory://synthetic/events/turn/{evidence_id}"
    return {
        "evidence_id": evidence_id,
        "source_ref": source_ref,
        "subject_id": "synthetic-events",
        "observed_at": observed_at.isoformat(),
        "captured_at": (observed_at + timedelta(seconds=1)).isoformat(),
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "access_decision": "ALLOWED",
    }

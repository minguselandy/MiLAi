from __future__ import annotations

from typing import Any

import pytest

from milai_openworker_mcp import MemoryWriteHandoff, MemoryWriteIntent


class _Submitter:
    def __init__(self) -> None:
        self.evidence_calls: list[dict[str, Any]] = []
        self.proposal_calls: list[dict[str, Any]] = []

    def capture_evidence(self, payload):  # type: ignore[no-untyped-def]
        self.evidence_calls.append(dict(payload))
        return {"evidence_id": "evidence-1", "canonical_changed": False}

    def create_proposal(self, payload):  # type: ignore[no-untyped-def]
        self.proposal_calls.append(dict(payload))
        return {
            "proposal_id": "proposal-1",
            "confirmation_summary": {"canonical_changed": False},
        }


def _intent() -> MemoryWriteIntent:
    return MemoryWriteIntent(
        intent_id="task-observation-1",
        task_epoch="task-1",
        source_type="RUNTIME_OBSERVATION",
        source_ref="openworker://task-1/tool-3",
        subject_id="synthetic-project",
        observed_at="2026-08-23T12:00:00+08:00",
        content="runtime is 3.11; token=super-secret-value-123456",
        permission_snapshot={"readable": True, "project_ids": ["milai"]},
        proposal={
            "operation": "CREATE",
            "requested_authority": "INFORMATIONAL",
            "scope_predicate": {"project_ids": ["milai"]},
            "model_id": "host-deterministic",
            "template_version": "memory-write-intent-v1",
            "input_snapshot_hash": "0" * 64,
            "proposed_patch": {
                "subject_id": "synthetic-project",
                "predicate": "runtime.version",
                "claim_type": "FACT",
                "payload": {"python": "3.11"},
                "authority": "INFORMATIONAL",
                "confidence": 1.0,
            },
        },
    )


def test_explicit_handoff_redacts_deduplicates_and_only_submits_evidence_proposal() -> None:
    lane = _Submitter()
    handoff = MemoryWriteHandoff(lane)
    first = handoff.handoff(_intent(), confirmation="HANDOFF")
    second = handoff.handoff(_intent(), confirmation="HANDOFF")

    assert first.canonical_changed is False
    assert first.review_required is True
    assert first.redacted is True
    assert first.deduplicated is False
    assert second.deduplicated is True
    assert len(lane.evidence_calls) == len(lane.proposal_calls) == 1
    assert "super-secret" not in lane.evidence_calls[0]["content"]
    assert lane.evidence_calls[0]["confirmation"] == "CAPTURE"
    assert lane.proposal_calls[0]["confirmation"] == "SUBMIT"
    assert lane.proposal_calls[0]["proposal"]["supporting_evidence_refs"] == ["evidence-1"]


def test_handoff_requires_submitter_profile_and_explicit_confirmation() -> None:
    lane = _Submitter()
    with pytest.raises(PermissionError, match="submitter lane"):
        MemoryWriteHandoff(lane, profile_id="reader-lite")
    handoff = MemoryWriteHandoff(lane)
    with pytest.raises(PermissionError, match="HANDOFF"):
        handoff.handoff(_intent(), confirmation="NO")  # type: ignore[arg-type]
    assert lane.evidence_calls == []

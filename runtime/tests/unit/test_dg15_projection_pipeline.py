from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from milai.application.projection_readiness import ProjectionReadinessService
from milai.application.retrieval import _apply_context_budget
from milai.domain.projection_readiness import ProjectionReadinessRequest
from milai.domain.projection_routing import PROJECTION_VERSIONS, route_projection_event
from milai.persistence import SessionContext
from milai.persistence.projection_repository import ProjectionName, ProjectionRepository

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OUTBOX_ID = UUID("22222222-2222-4222-8222-222222222222")


def test_routing_table_explicitly_acks_inapplicable_combinations() -> None:
    evidence = route_projection_event("evidence", "EVIDENCE_INGESTED", {})
    assert evidence.action == "APPLY"
    assert evidence.projection_version == "evidence-search-v1"

    for lane in cast(tuple[ProjectionName, ...], ("fts", "vector", "purge")):
        skipped = route_projection_event(lane, "EVIDENCE_INGESTED", {})
        assert skipped.action == "ACK_NOT_APPLICABLE"
        assert skipped.reason == "EVENT_FAMILY_NOT_APPLICABLE"

    claim_payload = {"claim_version_id": "33333333-3333-4333-8333-333333333333"}
    assert route_projection_event("fts", "CLAIM_VERSION_COMMITTED", claim_payload).action == (
        "APPLY"
    )
    assert route_projection_event("vector", "CLAIM_VERSION_COMMITTED", {}).action == (
        "ACK_NOT_APPLICABLE"
    )

    for lane in cast(tuple[ProjectionName, ...], ("evidence", "fts", "vector", "purge")):
        purged = route_projection_event(lane, "PURGE_EVIDENCE_DERIVATIVES", {})
        assert purged.action == "APPLY"
        assert purged.projection_version == PROJECTION_VERSIONS[lane]


class _ReadinessRepository:
    def __init__(self, snapshots: list[dict[str, Any]]) -> None:
        self.snapshots = snapshots
        self.calls = 0

    def readiness_status(
        self,
        _context: SessionContext,
        _target_outbox_ids: tuple[UUID, ...],
        _required_projections: tuple[ProjectionName, ...],
        _expected_versions: dict[ProjectionName, str],
    ) -> dict[str, Any]:
        snapshot = dict(self.snapshots[min(self.calls, len(self.snapshots) - 1)])
        self.calls += 1
        return snapshot


def _request(timeout_ms: int = 15_000) -> ProjectionReadinessRequest:
    return ProjectionReadinessRequest(
        target_outbox_id=OUTBOX_ID,
        required_projections=["evidence"],
        expected_versions={"evidence": "evidence-search-v1"},
        timeout_ms=timeout_ms,
        poll_interval_ms=10,
    )


def test_barrier_waits_for_ready_without_starting_projection_work() -> None:
    repository = _ReadinessRepository(
        [
            {"status": "WAITING", "target_watermark": 12},
            {"status": "READY", "target_watermark": 12},
        ]
    )
    service = ProjectionReadinessService(cast(ProjectionRepository, repository))

    result, status_code = service.wait(
        SessionContext(TENANT_ID, ACTOR_ID), _request()
    )

    assert status_code == 200
    assert result["status"] == "READY"
    assert result["poll_count"] == 2
    assert result["projection_work_started"] is False


def test_barrier_timeout_is_typed_and_contains_last_snapshot() -> None:
    repository = _ReadinessRepository(
        [
            {
                "status": "WAITING",
                "target_watermark": 12,
                "earliest_dead_letter_gap": None,
                "projections": [
                    {
                        "projection": "evidence",
                        "current_watermark": 11,
                        "target_watermark": 12,
                    }
                ],
            }
        ]
    )
    service = ProjectionReadinessService(cast(ProjectionRepository, repository))

    result, status_code = service.wait(
        SessionContext(TENANT_ID, ACTOR_ID), _request(timeout_ms=0)
    )

    assert status_code == 408
    assert result["status"] == "PROJECTION_READINESS_TIMEOUT"
    assert result["projections"][0]["current_watermark"] == 11
    assert result["projection_work_started"] is False


def test_barrier_dead_letter_and_version_mismatch_are_terminal() -> None:
    for terminal in ("DEAD_LETTER_GAP", "VERSION_MISMATCH"):
        repository = _ReadinessRepository(
            [{"status": terminal, "earliest_dead_letter_gap": 9}]
        )
        service = ProjectionReadinessService(cast(ProjectionRepository, repository))

        result, status_code = service.wait(
            SessionContext(TENANT_ID, ACTOR_ID), _request()
        )

        assert status_code == 409
        assert result["status"] == terminal
        assert repository.calls == 1


def test_evidence_context_budget_counts_rendered_candidate_not_gate_metadata() -> None:
    evidence = {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": str(OUTBOX_ID),
        "source_ref": "lme://case/session-2/turn-7",
        "subject_id": "dg15-subject",
        "observed_at": "2026-08-15T10:00:00+08:00",
        "content": "Previously the user recorded the unique value cobalt.",
        "authority": "EVIDENCE_ONLY",
        "permission_snapshot": {
            "readable": True,
            "project_ids": ["milai"],
            "large_internal_gate_metadata": "x" * 1_000,
        },
        "retention_state": "READABLE",
        "projection_version": "evidence-search-v1",
    }
    accepted = [{"evidence_id": str(OUTBOX_ID), "accepted": True}]
    progressive: dict[str, Any] = {"context_budget_truncated": False}
    degraded: set[str] = set()

    bounded = _apply_context_budget(
        (accepted, [], [evidence], []), 512, progressive, degraded
    )

    assert bounded[2] == [evidence]
    assert progressive["context_budget_truncated"] is False
    assert progressive["context_token_upper_bound"] <= 512
    assert degraded == set()

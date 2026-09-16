from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

ProjectionLane = Literal["evidence", "fts", "vector", "purge"]
ProjectionAction = Literal["APPLY", "ACK_NOT_APPLICABLE"]

ROUTING_VERSION = "dg15-routing-v1"
PROJECTION_VERSIONS: Mapping[ProjectionLane, str] = {
    "evidence": "evidence-search-v1",
    "fts": "canonical-fts-v1",
    "vector": "canonical-vector-v1",
    "purge": "purge-v1",
}

_CLAIM_VERSION_EVENTS = frozenset(
    {
        "CLAIM_VERSION_COMMITTED",
        # A governed SUPERSEDE may atomically change an OpenIssue while also
        # carrying the new immutable ClaimVersion in the same outbox payload.
        "OPEN_ISSUE_CHANGED",
    }
)
_PURGE_EVENT = "PURGE_EVIDENCE_DERIVATIVES"


@dataclass(frozen=True, slots=True)
class ProjectionRoute:
    lane: ProjectionLane
    action: ProjectionAction
    routing_version: str
    projection_version: str
    reason: str


def route_projection_event(
    lane: ProjectionLane,
    event_type: str,
    payload: Mapping[str, object],
) -> ProjectionRoute:
    """Return the frozen DG-15 applicability decision for one ordered delivery."""

    applicable = False
    reason = "EVENT_FAMILY_NOT_APPLICABLE"
    if lane == "evidence":
        applicable = event_type in {"EVIDENCE_INGESTED", _PURGE_EVENT}
        reason = "EVIDENCE_LIFECYCLE_EVENT" if applicable else reason
    elif lane in {"fts", "vector"}:
        applicable = event_type == _PURGE_EVENT or (
            event_type in _CLAIM_VERSION_EVENTS
            and isinstance(payload.get("claim_version_id"), str)
            and bool(payload.get("claim_version_id"))
        )
        reason = "CANONICAL_SEARCH_EVENT" if applicable else reason
    elif lane == "purge":
        applicable = event_type == _PURGE_EVENT
        reason = "PURGE_EVENT" if applicable else reason

    return ProjectionRoute(
        lane=lane,
        action="APPLY" if applicable else "ACK_NOT_APPLICABLE",
        routing_version=ROUTING_VERSION,
        projection_version=PROJECTION_VERSIONS[lane],
        reason=reason,
    )

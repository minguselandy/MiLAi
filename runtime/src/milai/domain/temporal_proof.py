"""DG-25 interval-valued event identity and bounded proof contracts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.requirement_state import canonical_sha256

EventTimePrecisionV02 = Literal[
    "INSTANT",
    "DAY",
    "WEEKEND",
    "WEEK",
    "MONTH",
    "RELATIVE_RANGE",
]
EventTimeBasisV02 = Literal[
    "EXPLICIT_CALENDAR",
    "SOURCE_RELATIVE",
    "UNIQUE_ANCHOR_RELATIVE",
    "SOURCE_OBSERVED_PROXY",
]
RangeMembershipV01 = Literal[
    "IN_RANGE",
    "OUT_OF_RANGE",
    "AMBIGUOUS_RANGE_MEMBERSHIP",
    "EVENT_TIME_UNRESOLVED",
]


class EventTimeIntervalV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["event-time-interval-v0.2"] = "event-time-interval-v0.2"
    interval_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    interval_start: datetime
    interval_end_exclusive: datetime
    timezone: str = Field(min_length=1, max_length=128)
    precision: EventTimePrecisionV02
    basis: EventTimeBasisV02
    anchor_evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    grounded_span_ids: list[str] = Field(default_factory=list, max_length=32)
    ambiguity_reasons: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        for value in (self.interval_start, self.interval_end_exclusive):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("event-time bounds require timezone offsets")
        if self.interval_start >= self.interval_end_exclusive:
            raise ValueError("event-time interval requires start < end")
        for values in (
            self.anchor_evidence_ids,
            self.grounded_span_ids,
            self.ambiguity_reasons,
        ):
            if values != sorted(set(values)):
                raise ValueError("event-time references and reasons must be sorted and unique")
        if self.basis == "UNIQUE_ANCHOR_RELATIVE":
            if len(self.anchor_evidence_ids) != 1 or not self.grounded_span_ids:
                raise ValueError("unique-anchor time requires one anchor and grounded relation")
        elif self.anchor_evidence_ids:
            raise ValueError("only unique-anchor time may carry anchor Evidence")
        if self.basis == "SOURCE_OBSERVED_PROXY" and not self.ambiguity_reasons:
            raise ValueError("source-observed proxy must retain its ambiguity")
        material = self.model_dump(mode="json", exclude={"interval_digest"})
        if self.interval_digest != canonical_sha256(material):
            raise ValueError("event-time interval digest mismatch")
        return self


def build_event_time_interval_v02(
    *,
    interval_start: datetime,
    interval_end_exclusive: datetime,
    timezone: str,
    precision: EventTimePrecisionV02,
    basis: EventTimeBasisV02,
    anchor_evidence_ids: Sequence[str] = (),
    grounded_span_ids: Sequence[str] = (),
    ambiguity_reasons: Sequence[str] = (),
) -> EventTimeIntervalV02:
    provisional = EventTimeIntervalV02.model_construct(
        interval_digest="0" * 64,
        interval_start=interval_start,
        interval_end_exclusive=interval_end_exclusive,
        timezone=timezone,
        precision=precision,
        basis=basis,
        anchor_evidence_ids=sorted(set(anchor_evidence_ids)),
        grounded_span_ids=sorted(set(grounded_span_ids)),
        ambiguity_reasons=sorted(set(ambiguity_reasons)),
    )
    material = provisional.model_dump(mode="json", exclude={"interval_digest"})
    return EventTimeIntervalV02(interval_digest=canonical_sha256(material), **material)


def classify_range_membership(
    event: EventTimeIntervalV02 | None,
    query: EventTimeIntervalV02,
) -> RangeMembershipV01:
    if event is None or event.ambiguity_reasons:
        return "EVENT_TIME_UNRESOLVED"
    if (
        event.interval_start >= query.interval_start
        and event.interval_end_exclusive <= query.interval_end_exclusive
    ):
        return "IN_RANGE"
    if (
        event.interval_end_exclusive <= query.interval_start
        or event.interval_start >= query.interval_end_exclusive
    ):
        return "OUT_OF_RANGE"
    return "AMBIGUOUS_RANGE_MEMBERSHIP"


class EventIdentityV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["event-identity-v0.1"] = "event-identity-v0.1"
    event_identity_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_type: str = Field(min_length=1, max_length=160)
    actor_identity: str = Field(min_length=1, max_length=256)
    object_or_participant_identity: str = Field(min_length=1, max_length=256)
    occurrence_interval_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence_ids: list[str] = Field(min_length=1, max_length=64)
    identity_policy_version: str = Field(min_length=1, max_length=160)
    disposition: Literal["DISTINCT", "DUPLICATE_OF", "UNRESOLVED"]
    unresolved_reasons: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.source_evidence_ids != sorted(set(self.source_evidence_ids)):
            raise ValueError("event source Evidence references must be sorted and unique")
        if self.unresolved_reasons != sorted(set(self.unresolved_reasons)):
            raise ValueError("event identity reasons must be sorted and unique")
        if (self.disposition == "UNRESOLVED") != bool(self.unresolved_reasons):
            raise ValueError("unresolved event identity must retain a reason")
        material = _event_core_material(
            event_type=self.event_type,
            actor_identity=self.actor_identity,
            object_or_participant_identity=self.object_or_participant_identity,
            occurrence_interval_digest=self.occurrence_interval_digest,
            identity_policy_version=self.identity_policy_version,
        )
        if self.event_identity_digest != canonical_sha256(material):
            raise ValueError("event identity digest mismatch")
        return self


def build_event_identity_v01(
    *,
    event_type: str,
    actor_identity: str,
    object_or_participant_identity: str,
    occurrence_interval_digest: str,
    source_evidence_ids: Sequence[str],
    identity_policy_version: str,
    disposition: Literal["DISTINCT", "DUPLICATE_OF", "UNRESOLVED"] = "DISTINCT",
    unresolved_reasons: Sequence[str] = (),
) -> EventIdentityV01:
    material = _event_core_material(
        event_type=event_type,
        actor_identity=actor_identity,
        object_or_participant_identity=object_or_participant_identity,
        occurrence_interval_digest=occurrence_interval_digest,
        identity_policy_version=identity_policy_version,
    )
    return EventIdentityV01(
        event_identity_digest=canonical_sha256(material),
        event_type=event_type,
        actor_identity=actor_identity,
        object_or_participant_identity=object_or_participant_identity,
        occurrence_interval_digest=occurrence_interval_digest,
        source_evidence_ids=sorted(set(source_evidence_ids)),
        identity_policy_version=identity_policy_version,
        disposition=disposition,
        unresolved_reasons=sorted(set(unresolved_reasons)),
    )


class EventDeduplicationV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["event-deduplication-v0.1"] = "event-deduplication-v0.1"
    dedup_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_identity_policy_version: str = Field(min_length=1, max_length=160)
    distinct_event_identity_digests: list[str]
    duplicate_groups: dict[str, list[str]]
    unresolved_event_identity_digests: list[str]
    dedup_complete: bool

    @model_validator(mode="after")
    def validate_dedup(self) -> Self:
        if self.distinct_event_identity_digests != sorted(
            set(self.distinct_event_identity_digests)
        ):
            raise ValueError("distinct event identities must be sorted and unique")
        if self.unresolved_event_identity_digests != sorted(
            set(self.unresolved_event_identity_digests)
        ):
            raise ValueError("unresolved event identities must be sorted and unique")
        if self.dedup_complete == bool(self.unresolved_event_identity_digests):
            raise ValueError("dedup completeness disagrees with unresolved identities")
        for digest, evidence_ids in self.duplicate_groups.items():
            if digest not in self.distinct_event_identity_digests:
                raise ValueError("duplicate group must resolve to a distinct event identity")
            if evidence_ids != sorted(set(evidence_ids)) or len(evidence_ids) < 2:
                raise ValueError("duplicate group requires at least two unique Evidence refs")
        material = self.model_dump(mode="json", exclude={"dedup_digest"})
        if self.dedup_digest != canonical_sha256(material):
            raise ValueError("event deduplication digest mismatch")
        return self


def deduplicate_event_identities(
    events: Sequence[EventIdentityV01],
) -> EventDeduplicationV01:
    policy_versions = {item.identity_policy_version for item in events}
    if len(policy_versions) != 1:
        raise ValueError("event deduplication requires one policy version")
    grouped: dict[str, set[str]] = defaultdict(set)
    unresolved: set[str] = set()
    for event in events:
        if event.disposition == "UNRESOLVED":
            unresolved.add(event.event_identity_digest)
            continue
        grouped[event.event_identity_digest].update(event.source_evidence_ids)
    distinct = sorted(grouped)
    duplicate_groups = {
        digest: sorted(evidence_ids)
        for digest, evidence_ids in sorted(grouped.items())
        if len(evidence_ids) > 1
    }
    policy_version = policy_versions.pop()
    unresolved_digests = sorted(unresolved)
    dedup_complete = not unresolved
    material = {
        "schema_version": "event-deduplication-v0.1",
        "event_identity_policy_version": policy_version,
        "distinct_event_identity_digests": distinct,
        "duplicate_groups": duplicate_groups,
        "unresolved_event_identity_digests": unresolved_digests,
        "dedup_complete": dedup_complete,
    }
    return EventDeduplicationV01(
        schema_version="event-deduplication-v0.1",
        dedup_digest=canonical_sha256(material),
        event_identity_policy_version=policy_version,
        distinct_event_identity_digests=distinct,
        duplicate_groups=duplicate_groups,
        unresolved_event_identity_digests=unresolved_digests,
        dedup_complete=dedup_complete,
    )


class BoundedRangeQueryClosureV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_ir_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_time_interval: EventTimeIntervalV02
    timezone: str = Field(min_length=1, max_length=128)
    boundary_convention: Literal["CLOSED_OPEN"] = "CLOSED_OPEN"


class BoundedRangeSnapshotClosureV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_snapshot_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_partition_snapshot_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    access_snapshot_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    revocation_snapshot_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_stable: bool


class BoundedRangeScanClosureV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scan_axis: Literal["EVENT_OCCURRENCE_TIME"] = "EVENT_OCCURRENCE_TIME"
    source_partition_closed: bool
    range_scan_complete: bool
    max_items: int = Field(ge=1, le=2_000)
    max_items_hit: bool
    unreadable_source_count: int = Field(ge=0)


class BoundedRangeProjectionClosureV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    projection_version: str = Field(min_length=1, max_length=160)
    temporal_normalizer_version: str = Field(min_length=1, max_length=160)
    target_watermark: int = Field(ge=0)
    projection_watermark: int = Field(ge=0)
    projection_watermark_covered: bool
    dead_letter_gap: bool
    unprojected_source_count: int = Field(ge=0)
    raw_fallback_closed: bool

    @model_validator(mode="after")
    def validate_watermark(self) -> Self:
        observed = self.projection_watermark >= self.target_watermark
        if self.projection_watermark_covered != observed:
            raise ValueError("projection watermark coverage does not match positions")
        return self


class BoundedRangeEventSetClosureV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_event_count: int = Field(ge=0)
    in_range_event_count: int = Field(ge=0)
    out_of_range_event_count: int = Field(ge=0)
    ambiguous_time_count: int = Field(ge=0)
    unresolved_event_count: int = Field(ge=0)
    event_identity_policy_version: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        classified = (
            self.in_range_event_count
            + self.out_of_range_event_count
            + self.ambiguous_time_count
            + self.unresolved_event_count
        )
        if self.candidate_event_count != classified:
            raise ValueError("event-set counts do not partition candidates")
        return self


class BoundedRangeDedupClosureV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dedup_policy_version: str = Field(min_length=1, max_length=160)
    duplicate_group_count: int = Field(ge=0)
    unresolved_duplicate_group_count: int = Field(ge=0)
    distinct_event_count: int = Field(ge=0)
    dedup_complete: bool


class BoundedRangeAccessClosureV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    unreadable_evidence_count: int = Field(ge=0)
    access_snapshot_valid: bool


class BoundedRangeScanProofV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["bounded-range-scan-proof-v0.2"] = "bounded-range-scan-proof-v0.2"
    proof_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    query_closure: BoundedRangeQueryClosureV02
    snapshot_closure: BoundedRangeSnapshotClosureV02
    scan_closure: BoundedRangeScanClosureV02
    projection_closure: BoundedRangeProjectionClosureV02
    event_set_closure: BoundedRangeEventSetClosureV02
    dedup_closure: BoundedRangeDedupClosureV02
    access_closure: BoundedRangeAccessClosureV02

    @property
    def closure_complete(self) -> bool:
        return _proof_closure_complete(self)

    @model_validator(mode="after")
    def validate_proof(self) -> Self:
        complete = _proof_closure_complete(self)
        if (self.status == "COMPLETE") != complete:
            raise ValueError("bounded range proof status disagrees with closure facts")
        if self.status == "UNAVAILABLE" and (
            self.snapshot_closure.snapshot_stable and self.scan_closure.source_partition_closed
        ):
            raise ValueError("available bounded scan cannot be labeled UNAVAILABLE")
        if self.dedup_closure.distinct_event_count > self.event_set_closure.in_range_event_count:
            raise ValueError("distinct in-range event count exceeds the in-range set")
        material = self.model_dump(mode="json", exclude={"proof_digest"})
        if self.proof_digest != canonical_sha256(material):
            raise ValueError("bounded range proof digest mismatch")
        return self


def build_bounded_range_scan_proof_v02(
    *,
    query_closure: BoundedRangeQueryClosureV02,
    snapshot_closure: BoundedRangeSnapshotClosureV02,
    scan_closure: BoundedRangeScanClosureV02,
    projection_closure: BoundedRangeProjectionClosureV02,
    event_set_closure: BoundedRangeEventSetClosureV02,
    dedup_closure: BoundedRangeDedupClosureV02,
    access_closure: BoundedRangeAccessClosureV02,
) -> BoundedRangeScanProofV02:
    provisional = BoundedRangeScanProofV02.model_construct(
        proof_digest="0" * 64,
        status="PARTIAL",
        query_closure=query_closure,
        snapshot_closure=snapshot_closure,
        scan_closure=scan_closure,
        projection_closure=projection_closure,
        event_set_closure=event_set_closure,
        dedup_closure=dedup_closure,
        access_closure=access_closure,
    )
    status: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    if _proof_closure_complete(provisional):
        status = "COMPLETE"
    elif not snapshot_closure.snapshot_stable or not scan_closure.source_partition_closed:
        status = "UNAVAILABLE"
    else:
        status = "PARTIAL"
    material = {
        "schema_version": "bounded-range-scan-proof-v0.2",
        "status": status,
        "query_closure": query_closure.model_dump(mode="json"),
        "snapshot_closure": snapshot_closure.model_dump(mode="json"),
        "scan_closure": scan_closure.model_dump(mode="json"),
        "projection_closure": projection_closure.model_dump(mode="json"),
        "event_set_closure": event_set_closure.model_dump(mode="json"),
        "dedup_closure": dedup_closure.model_dump(mode="json"),
        "access_closure": access_closure.model_dump(mode="json"),
    }
    return BoundedRangeScanProofV02(
        schema_version="bounded-range-scan-proof-v0.2",
        proof_digest=canonical_sha256(material),
        status=status,
        query_closure=query_closure,
        snapshot_closure=snapshot_closure,
        scan_closure=scan_closure,
        projection_closure=projection_closure,
        event_set_closure=event_set_closure,
        dedup_closure=dedup_closure,
        access_closure=access_closure,
    )


class LegacyBoundedRangeScanProofV01(BaseModel):
    """Read-only adapter for historic v0.1 artifacts; no v0.1 writer is added."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    scan_axis: Literal["SOURCE_OBSERVED_TIME", "EVENT_OCCURRENCE_TIME"]
    source_partition_closed: bool
    projection_watermark_covered: bool
    projection_watermark: int | None = Field(default=None, ge=0)
    target_watermark: int | None = Field(default=None, ge=0)
    source_count: int | None = Field(default=None, ge=0)
    projected_count: int | None = Field(default=None, ge=0)
    returned_count: int = Field(ge=0)
    max_items: int | None = Field(default=None, ge=1)
    dead_letter_gap: bool
    unreadable_evidence_count: int = Field(ge=0)


def read_legacy_bounded_range_scan_proof_v01(
    payload: Mapping[str, Any],
) -> LegacyBoundedRangeScanProofV01:
    return LegacyBoundedRangeScanProofV01.model_validate(dict(payload))


def _proof_closure_complete(proof: BoundedRangeScanProofV02) -> bool:
    query = proof.query_closure
    snapshot = proof.snapshot_closure
    scan = proof.scan_closure
    projection = proof.projection_closure
    event_set = proof.event_set_closure
    dedup = proof.dedup_closure
    access = proof.access_closure
    return (
        query.event_time_interval.basis != "SOURCE_OBSERVED_PROXY"
        and not query.event_time_interval.ambiguity_reasons
        and snapshot.snapshot_stable
        and scan.source_partition_closed
        and scan.range_scan_complete
        and not scan.max_items_hit
        and scan.unreadable_source_count == 0
        and not projection.dead_letter_gap
        and projection.projection_watermark_covered
        and (projection.unprojected_source_count == 0 or projection.raw_fallback_closed)
        and event_set.ambiguous_time_count == 0
        and event_set.unresolved_event_count == 0
        and dedup.unresolved_duplicate_group_count == 0
        and dedup.dedup_complete
        and access.unreadable_evidence_count == 0
        and access.access_snapshot_valid
    )


def _event_core_material(
    *,
    event_type: str,
    actor_identity: str,
    object_or_participant_identity: str,
    occurrence_interval_digest: str,
    identity_policy_version: str,
) -> dict[str, str]:
    return {
        "schema_version": "event-identity-core-v0.1",
        "event_type": event_type,
        "actor_identity": actor_identity,
        "object_or_participant_identity": object_or_participant_identity,
        "occurrence_interval_digest": occurrence_interval_digest,
        "identity_policy_version": identity_policy_version,
    }


__all__ = [
    "BoundedRangeAccessClosureV02",
    "BoundedRangeDedupClosureV02",
    "BoundedRangeEventSetClosureV02",
    "BoundedRangeProjectionClosureV02",
    "BoundedRangeQueryClosureV02",
    "BoundedRangeScanClosureV02",
    "BoundedRangeScanProofV02",
    "BoundedRangeSnapshotClosureV02",
    "EventDeduplicationV01",
    "EventIdentityV01",
    "EventTimeBasisV02",
    "EventTimeIntervalV02",
    "EventTimePrecisionV02",
    "LegacyBoundedRangeScanProofV01",
    "RangeMembershipV01",
    "build_bounded_range_scan_proof_v02",
    "build_event_identity_v01",
    "build_event_time_interval_v02",
    "classify_range_membership",
    "deduplicate_event_identities",
    "read_legacy_bounded_range_scan_proof_v01",
]

"""Precision-preserving SOURCE_OBSERVED_TIME point compilation."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.acquisition_execution_policy import SourceTimePointProfile
from milai.domain.semantic_query import NormalizedTemporalConstraint

_OFFSET = re.compile(r"^(?P<sign>[+-])(?P<hour>\d{2}):(?P<minute>\d{2})$")


class SourceTimePointCompilation(BaseModel):
    """Auditable result; UNPROVEN never carries executable bounds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["source-time-point-compilation-v0.1"] = (
        "source-time-point-compilation-v0.1"
    )
    status: Literal["COMPILED", "UNPROVEN"]
    reason_code: str = Field(min_length=1, max_length=160)
    original_axis: Literal["SOURCE_OBSERVED_TIME", "EVENT_TIME"]
    original_boundary: Literal["CLOSED_OPEN", "CLOSED_CLOSED", "POINT", "UNBOUNDED"]
    precision: Literal["DAY", "HOUR", "MINUTE"] | None = None
    timezone: str | None = None
    original_point: datetime | None = None
    range_start: datetime | None = None
    range_end: datetime | None = None
    compiled_boundary: Literal["CLOSED_OPEN"] | None = None
    time_axis_substitution: Literal[False] = False
    semantic_widening: Literal[False] = False

    @model_validator(mode="after")
    def validate_compilation(self) -> Self:
        values = (self.original_point, self.range_start, self.range_end)
        for value in values:
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("source-time compilation requires aware timestamps")
        if self.status == "COMPILED":
            if (
                self.original_boundary != "POINT"
                or self.precision is None
                or self.timezone is None
                or any(value is None for value in values)
                or self.compiled_boundary != "CLOSED_OPEN"
            ):
                raise ValueError("compiled temporal point is missing exact typed bounds")
            assert self.original_point is not None
            assert self.range_start is not None
            assert self.range_end is not None
            if not self.range_start <= self.original_point < self.range_end:
                raise ValueError("compiled bucket does not contain the original point")
        elif any(value is not None for value in values[1:]) or self.compiled_boundary is not None:
            raise ValueError("unproven source point cannot carry executable bounds")
        return self

    def executable_range(self) -> dict[str, object] | None:
        if self.status != "COMPILED":
            return None
        assert self.original_point is not None
        assert self.range_start is not None
        assert self.range_end is not None
        assert self.precision is not None
        assert self.timezone is not None
        return {
            "reference_time": self.original_point.isoformat(),
            "start": self.range_start.isoformat(),
            "end": self.range_end.isoformat(),
            "boundary": "CLOSED_OPEN",
            "time_axis": self.original_axis,
            "precision": self.precision,
            "timezone": self.timezone,
            "compiled_from_boundary": "POINT",
            "compiler_identity": (
                "source-time-point-bucket-v0.1"
                if self.original_axis == "SOURCE_OBSERVED_TIME"
                else "event-time-point-bucket-v0.1"
            ),
            "time_axis_substitution": False,
            "semantic_widening": False,
        }


def compile_source_time_point_bucket(
    temporal: NormalizedTemporalConstraint,
    profile: SourceTimePointProfile,
) -> SourceTimePointCompilation:
    """Compile a declared local precision into the exact UTC closed-open bucket."""

    return _compile_temporal_point_bucket(
        temporal,
        profile,
        expected_axis="SOURCE_OBSERVED_TIME",
        reason_prefix="SOURCE",
    )


def compile_event_time_point_bucket(
    temporal: NormalizedTemporalConstraint,
    profile: SourceTimePointProfile,
) -> SourceTimePointCompilation:
    """Compile an EVENT_TIME point without substituting its temporal axis."""

    return _compile_temporal_point_bucket(
        temporal,
        profile,
        expected_axis="EVENT_TIME",
        reason_prefix="EVENT",
    )


def _compile_temporal_point_bucket(
    temporal: NormalizedTemporalConstraint,
    profile: SourceTimePointProfile,
    *,
    expected_axis: Literal["SOURCE_OBSERVED_TIME", "EVENT_TIME"],
    reason_prefix: Literal["SOURCE", "EVENT"],
) -> SourceTimePointCompilation:

    base = {
        "original_axis": temporal.time_axis,
        "original_boundary": temporal.boundary,
        "precision": temporal.precision,
        "timezone": temporal.timezone,
        "original_point": temporal.start if temporal.boundary == "POINT" else None,
    }
    if temporal.time_axis != expected_axis:
        return SourceTimePointCompilation.model_validate(
            {
                "status": "UNPROVEN",
                "reason_code": (
                    "TIME_AXIS_NOT_SOURCE_OBSERVED"
                    if expected_axis == "SOURCE_OBSERVED_TIME"
                    else "TIME_AXIS_NOT_EVENT"
                ),
                **base,
            }
        )
    if temporal.boundary != "POINT" or temporal.start is None:
        return SourceTimePointCompilation.model_validate(
            {
                "status": "UNPROVEN",
                "reason_code": f"{reason_prefix}_POINT_REQUIRED",
                **base,
            }
        )
    if temporal.precision not in set(profile.supported_precisions):
        return SourceTimePointCompilation.model_validate(
            {
                "status": "UNPROVEN",
                "reason_code": (f"{reason_prefix}_POINT_PRECISION_UNSUPPORTED_OR_MISSING"),
                **base,
            }
        )
    if temporal.timezone is None:
        return SourceTimePointCompilation.model_validate(
            {
                "status": "UNPROVEN",
                "reason_code": f"{reason_prefix}_POINT_TIMEZONE_MISSING",
                **base,
            }
        )
    zone = _timezone(temporal.timezone)
    if zone is None:
        return SourceTimePointCompilation.model_validate(
            {
                "status": "UNPROVEN",
                "reason_code": f"{reason_prefix}_POINT_TIMEZONE_INVALID",
                **base,
            }
        )
    local_point = temporal.start.astimezone(zone)
    local_start = _floor(local_point, temporal.precision)
    local_end = _next(local_start, temporal.precision)
    range_start = local_start.astimezone(UTC)
    range_end = local_end.astimezone(UTC)
    if range_start >= range_end:
        return SourceTimePointCompilation.model_validate(
            {
                "status": "UNPROVEN",
                "reason_code": f"{reason_prefix}_POINT_BUCKET_NON_MONOTONIC",
                **base,
            }
        )
    if not _round_trip_exact(local_start, range_start, zone) or not _round_trip_exact(
        local_end, range_end, zone
    ):
        return SourceTimePointCompilation.model_validate(
            {
                "status": "UNPROVEN",
                "reason_code": f"{reason_prefix}_POINT_DST_ROUNDTRIP_UNPROVEN",
                **base,
            }
        )
    return SourceTimePointCompilation.model_validate(
        {
            "status": "COMPILED",
            "reason_code": "PRECISION_PRESERVING_CLOSED_OPEN_BUCKET",
            "range_start": range_start,
            "range_end": range_end,
            "compiled_boundary": "CLOSED_OPEN",
            **base,
        }
    )


def _timezone(value: str) -> tzinfo | None:
    if value in {"UTC", "Etc/UTC", "Z", "+00:00", "-00:00"}:
        return UTC
    matched = _OFFSET.fullmatch(value)
    if matched is not None:
        hour = int(matched.group("hour"))
        minute = int(matched.group("minute"))
        if hour > 23 or minute > 59:
            return None
        offset = timedelta(hours=hour, minutes=minute)
        if matched.group("sign") == "-":
            offset = -offset
        return timezone(offset)
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return None


def _floor(
    value: datetime,
    precision: Literal["DAY", "HOUR", "MINUTE"],
) -> datetime:
    if precision == "DAY":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    if precision == "HOUR":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(second=0, microsecond=0)


def _next(
    value: datetime,
    precision: Literal["DAY", "HOUR", "MINUTE"],
) -> datetime:
    if precision == "DAY":
        return value + timedelta(days=1)
    if precision == "HOUR":
        return value + timedelta(hours=1)
    return value + timedelta(minutes=1)


def _round_trip_exact(local: datetime, utc_value: datetime, zone: tzinfo) -> bool:
    returned = utc_value.astimezone(zone)
    return returned.replace(tzinfo=None) == local.replace(tzinfo=None)


__all__ = [
    "SourceTimePointCompilation",
    "compile_event_time_point_bucket",
    "compile_source_time_point_bucket",
]

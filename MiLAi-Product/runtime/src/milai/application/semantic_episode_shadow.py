"""Default-off observation-only Semantic Episode hook for MD-02."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from milai.domain.memory_formation import MemoryFormationBundleV01
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_episode_shadow import (
    SemanticEpisodeShadowObservationV01,
    ShadowDisposition,
    ShadowFreshnessStatus,
)


class SemanticEpisodeShadowHook:
    """Validate and observe one prebuilt bundle without changing baseline behavior."""

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled

    def observe(
        self,
        *,
        request_identity: str,
        baseline_behavior: Mapping[str, Any],
        current_sources: Sequence[Mapping[str, Any]],
        official_anchor_evidence_ids: Sequence[str],
        bundle: MemoryFormationBundleV01 | None,
        formation_failed: bool = False,
    ) -> SemanticEpisodeShadowObservationV01 | None:
        if not self.enabled:
            return None
        sources = [dict(item) for item in current_sources]
        if not sources:
            raise ValueError("SHADOW_CURRENT_SOURCE_SNAPSHOT_EMPTY")
        baseline_digest = canonical_sha256(dict(baseline_behavior))
        snapshot_digest, watermark, source_ids = _snapshot_identity(sources)
        anchor_ids = list(dict.fromkeys(str(value) for value in official_anchor_evidence_ids))
        anchor_digest = canonical_sha256(anchor_ids)
        if formation_failed or bundle is None:
            return _observation(
                request_identity=request_identity,
                baseline_digest=baseline_digest,
                snapshot_digest=snapshot_digest,
                watermark=watermark,
                anchor_digest=anchor_digest,
                bundle=None,
                context_ids=[],
                freshness="INELIGIBLE",
                disposition="RAW_FALLBACK",
                rejection_reason="FORMATION_BUILD_UNAVAILABLE",
                raw_fallback=True,
            )
        ineligible = _ineligible_reason(sources)
        if ineligible is not None:
            return _observation(
                request_identity=request_identity,
                baseline_digest=baseline_digest,
                snapshot_digest=snapshot_digest,
                watermark=watermark,
                anchor_digest=anchor_digest,
                bundle=bundle,
                context_ids=[],
                freshness="INELIGIBLE",
                disposition="PERMISSION_REJECTED",
                rejection_reason=ineligible,
                raw_fallback=True,
            )
        if (
            source_ids != bundle.source_evidence_ids
            or snapshot_digest != bundle.source_snapshot_digest
            or watermark != bundle.source_watermark
        ):
            return _observation(
                request_identity=request_identity,
                baseline_digest=baseline_digest,
                snapshot_digest=snapshot_digest,
                watermark=watermark,
                anchor_digest=anchor_digest,
                bundle=bundle,
                context_ids=[],
                freshness="STALE",
                disposition="STALE_REJECTED",
                rejection_reason="SOURCE_SNAPSHOT_OR_WATERMARK_DRIFT",
                raw_fallback=True,
            )
        context_ids = _map_anchors_to_episode_units(bundle, anchor_ids)
        return _observation(
            request_identity=request_identity,
            baseline_digest=baseline_digest,
            snapshot_digest=snapshot_digest,
            watermark=watermark,
            anchor_digest=anchor_digest,
            bundle=bundle,
            context_ids=context_ids,
            freshness="CURRENT",
            disposition="OBSERVED",
            rejection_reason=None,
            raw_fallback=False,
        )


def _map_anchors_to_episode_units(
    bundle: MemoryFormationBundleV01,
    anchor_ids: Sequence[str],
) -> list[str]:
    episode_by_source = {
        span.evidence_id: episode
        for episode in bundle.episode_candidates
        for span in episode.source_spans
    }
    output: list[str] = []
    seen_episodes: set[str] = set()
    for anchor_id in anchor_ids:
        episode = episode_by_source.get(anchor_id)
        if episode is None or episode.episode_digest in seen_episodes:
            continue
        seen_episodes.add(episode.episode_digest)
        output.extend(span.evidence_id for span in episode.source_spans)
    return list(dict.fromkeys(output))


def _snapshot_identity(
    sources: Sequence[Mapping[str, Any]],
) -> tuple[str, datetime, list[str]]:
    rows: list[dict[str, Any]] = []
    source_ids: list[str] = []
    timestamps: list[datetime] = []
    for source in sources:
        evidence_id = str(source["evidence_id"])
        observed = _timestamp(source.get("observed_at"))
        rows.append(
            {
                "evidence_id": evidence_id,
                "source_ref": str(source["source_ref"]),
                "session_id": str(source["session_id"]),
                "speaker": str(source["speaker"]).casefold(),
                "observed_at": observed.isoformat(),
                "content_digest": canonical_sha256(str(source["content"])),
            }
        )
        source_ids.append(evidence_id)
        timestamps.append(observed)
    return canonical_sha256(rows), max(timestamps), source_ids


def _ineligible_reason(sources: Sequence[Mapping[str, Any]]) -> str | None:
    for source in sources:
        if source.get("revoked_at") not in {None, ""}:
            return "SOURCE_REVOKED"
        if source.get("retention_state") != "READABLE":
            return "SOURCE_RETENTION_UNREADABLE"
        permission = source.get("permission_snapshot")
        if not isinstance(permission, Mapping) or permission.get("readable") is not True:
            return "SOURCE_PERMISSION_REMOVED"
    return None


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("SHADOW_SOURCE_TIME_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("SHADOW_SOURCE_TIME_MUST_BE_TIMEZONE_AWARE")
    return parsed


def _observation(
    *,
    request_identity: str,
    baseline_digest: str,
    snapshot_digest: str,
    watermark: datetime,
    anchor_digest: str,
    bundle: MemoryFormationBundleV01 | None,
    context_ids: list[str],
    freshness: ShadowFreshnessStatus,
    disposition: ShadowDisposition,
    rejection_reason: str | None,
    raw_fallback: bool,
) -> SemanticEpisodeShadowObservationV01:
    provisional = SemanticEpisodeShadowObservationV01.model_construct(
        observation_digest="0" * 64,
        request_identity=request_identity,
        baseline_behavior_digest=baseline_digest,
        source_snapshot_digest=snapshot_digest,
        source_watermark=watermark,
        bundle_digest=bundle.bundle_digest if bundle is not None else None,
        episode_digests=(
            [item.episode_digest for item in bundle.episode_candidates]
            if bundle is not None
            else []
        ),
        raw_anchor_digest=anchor_digest,
        shadow_context_evidence_ids=context_ids,
        freshness_status=freshness,
        disposition=disposition,
        rejection_reason=rejection_reason,
        raw_fallback_used=raw_fallback,
    )
    material = provisional.model_dump(mode="json", exclude={"observation_digest"})
    return SemanticEpisodeShadowObservationV01(
        observation_digest=canonical_sha256(material),
        **material,
    )


__all__ = ["SemanticEpisodeShadowHook"]

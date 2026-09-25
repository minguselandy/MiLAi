"""The finite contextual-memory comparison profiles and safe history sharing."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ContextualProfile:
    history_mode: Literal["none", "raw", "ingested"] = "ingested"
    write_profile: Literal["ordinary", "support"] = "ordinary"
    material_mode: Literal["plain", "linked"] = "plain"
    delivery_mode: Literal["full", "delta"] = "full"
    maintenance_mode: Literal["eager", "pending"] = "eager"
    old_source_bytes: int = 0
    ingestion_mode: Literal["ordinary", "support", "events"] = "ordinary"
    state_policy: Literal["off", "optional", "forced_legacy"] = "off"

    @property
    def contextual(self) -> bool:
        return self.state_policy != "off"

    @property
    def history_write_identity(self) -> tuple[str, str, int, str]:
        return (
            self.write_profile,
            self.maintenance_mode,
            self.old_source_bytes,
            self.ingestion_mode,
        )


PROFILES: dict[str, ContextualProfile] = {
    "query_only": ContextualProfile(history_mode="none"),
    "raw": ContextualProfile(history_mode="raw"),
    "ordinary": ContextualProfile(),
    "state": ContextualProfile(state_policy="forced_legacy"),
    "state_optional": ContextualProfile(state_policy="optional"),
    "support": ContextualProfile(write_profile="support", ingestion_mode="support"),
    "events": ContextualProfile(write_profile="support", ingestion_mode="events"),
    "ordinary_linked": ContextualProfile(material_mode="linked"),
    "support_linked": ContextualProfile(
        write_profile="support", material_mode="linked", ingestion_mode="support"
    ),
    "support_delta": ContextualProfile(
        write_profile="support", delivery_mode="delta", ingestion_mode="support"
    ),
    "support_pending": ContextualProfile(
        write_profile="support", maintenance_mode="pending", ingestion_mode="support"
    ),
    "support_raw_evidence": ContextualProfile(
        write_profile="support", old_source_bytes=4096, ingestion_mode="support"
    ),
}


def resolve_profile(name: str) -> ContextualProfile:
    try:
        return PROFILES[name]
    except KeyError as error:
        raise ValueError(f"Unknown method profile: {name}") from error


def validate_history_owners(
    arms: Collection[str],
    assigned_profiles: Mapping[str, str],
    history_owner: Mapping[str, str],
) -> dict[str, str]:
    """Require a direct, same-write owner; reading and delivery may differ."""
    present = set(arms)
    if present != set(assigned_profiles):
        raise ValueError("Each active arm requires exactly one method profile")
    profiles = {arm: resolve_profile(name) for arm, name in assigned_profiles.items()}
    owners = dict(history_owner)
    for subsidiary, owner in owners.items():
        if subsidiary not in present or owner not in present:
            raise ValueError("History owner and subsidiary must both be active arms")
        if subsidiary == owner or owner in owners:
            raise ValueError("History ownership must be direct and acyclic")
        left, right = profiles[subsidiary], profiles[owner]
        if left.history_mode != "ingested" or right.history_mode != "ingested":
            raise ValueError("Only ingested profiles can share a history build")
        if left.history_write_identity != right.history_write_identity:
            raise ValueError("History owner must use the same write and maintenance protocol")
    return owners

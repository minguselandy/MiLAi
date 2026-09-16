from __future__ import annotations

PREFETCH_V1 = "prefetch/v1"
GROUPED_COMPACT_V3 = "grouped-compact/v3"
TURN_WINDOW_V1 = "turn-window/v1"

LEGACY_REPRESENTATION_IDENTITIES = {
    "DG10_PREFETCH_V1": PREFETCH_V1,
    "DG11_GROUPED_COMPACT_V3": GROUPED_COMPACT_V3,
    "DG11_TURN_WINDOW_V1": TURN_WINDOW_V1,
    "dg11-grouped-compact-v1": GROUPED_COMPACT_V3,
}


def semantic_representation_identity(value: str) -> str:
    """Read a frozen legacy alias and return the identity used by new writes."""
    return LEGACY_REPRESENTATION_IDENTITIES.get(value, value)

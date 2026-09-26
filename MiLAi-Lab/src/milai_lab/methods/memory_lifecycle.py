"""Fixed, independent prospective-retention cue for the Formation arm."""

from __future__ import annotations

import hashlib

FORMATION_PROTOCOL_ID = "prospective_retention_cue_v1"
FORMATION_CUE = (
    "Before finishing a turn, consider what would be lost if this observation were "
    "unavailable in a later related session: commitments, constraints, unfinished "
    "obligations, or reusable results. Use the memory tools to retain or update "
    "information worth carrying forward. Keep task-local calculations and one-time "
    "response instructions out of durable memory unless the user establishes a future use."
)
FORMATION_CUE_SHA256 = hashlib.sha256(FORMATION_CUE.encode("utf-8")).hexdigest()

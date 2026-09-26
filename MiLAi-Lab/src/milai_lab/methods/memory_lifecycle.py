"""Fixed, independent prospective-retention cue for the Formation arm."""

from __future__ import annotations

import hashlib

FORMATION_PROTOCOL_ID = "prospective_retention_duty_v2"
FORMATION_CUE = (
    "When the user establishes a future use for a commitment, constraint, unfinished "
    "obligation, or reusable result, call manage_memory before the final reply to save "
    "or update the smallest accurate, scoped durable note, including relevant identifiers "
    "from completed tool results. Do not substitute an oral acknowledgement for the memory "
    "operation. If no future use is established, do not write memory."
)
FORMATION_CUE_SHA256 = hashlib.sha256(FORMATION_CUE.encode("utf-8")).hexdigest()

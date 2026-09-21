"""Pure shared primitives for memory-context compilation."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, cast

from milai.domain.memory_context import ContextAuthorityClass, ContextSufficiencyStatus


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _estimated_tokens(value: str) -> int:
    return math.ceil(len(value.encode("utf-8")) / 3)


def _authority_class(*, has_evidence: bool, has_canonical: bool) -> ContextAuthorityClass:
    if has_evidence and has_canonical:
        return "MIXED"
    if has_evidence:
        return "EVIDENCE_ONLY"
    return "CANONICAL_STATE"


def _positions(raw: object) -> tuple[int | None, dict[str, int]]:
    if not isinstance(raw, dict):
        return None, {}
    canonical = raw.get("canonical_outbox_sequence")
    canonical_position = (
        int(canonical)
        if isinstance(canonical, int) and not isinstance(canonical, bool) and canonical >= 0
        else None
    )
    watermarks = {
        str(key): int(value)
        for key, value in raw.items()
        if key.endswith("_watermark")
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    }
    return canonical_position, watermarks


def _sufficiency_status(
    decision: dict[str, Any], outcome: dict[str, Any]
) -> ContextSufficiencyStatus:
    raw = decision.get("status")
    if raw in {"COMPLETE", "PARTIAL", "UNSATISFIED", "CONTESTED", "UNBOUNDED"}:
        return cast(ContextSufficiencyStatus, raw)
    if outcome.get("status") == "CONTESTED":
        return "CONTESTED"
    return "PARTIAL" if outcome.get("items") else "UNSATISFIED"


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


"""Deterministic cyclic Latin-square schedule."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence


def counterbalanced_order(
    methods: Sequence[str],
    *,
    case_ordinal: int,
    namespace: str = "milai-dg11-paper-v1",
) -> tuple[str, ...]:
    if not methods or len(set(methods)) != len(methods):
        raise ValueError("methods must be non-empty and unique")
    if case_ordinal < 0 or not namespace:
        raise ValueError("case ordinal and namespace are invalid")
    canonical = tuple(methods)
    base_offset = int(hashlib.sha256(namespace.encode()).hexdigest()[:16], 16)
    offset = (base_offset + case_ordinal) % len(canonical)
    return canonical[offset:] + canonical[:offset]

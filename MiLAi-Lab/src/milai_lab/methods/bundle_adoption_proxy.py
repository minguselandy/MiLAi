"""Frozen exact-bundle adoption propensity, not use or causal task benefit."""

from __future__ import annotations

import hashlib
import json
from typing import Any

VERSION = "bundle-adoption-proxy-v1"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def select_bundles(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Candidates are frozen in BGE source-record order, full bundle before subsets.

    Only the first two source records compete. Unknown propensity is UNKNOWN,
    not zero or an invented reward. Evidence-free STATIC or ties stay STATIC.
    Partial selection is positive evidence for that exact subset only; it never
    assigns per-item credit or rejects the original full bundle.
    """
    sources: list[str] = []
    shortlist = []
    for item in candidates:
        if item["source_task"] not in sources:
            sources.append(item["source_task"])
        if sources.index(item["source_task"]) < 2:
            shortlist.append(item)
    if not shortlist:
        return {"STATIC": None, "UTILITY": None, "proxy_distinguishable": False}
    static = shortlist[0]

    def score(item: dict[str, Any]) -> float | None:
        accepted, rejected = item["accepted"], item["rejected"]
        return accepted / (accepted + rejected) if accepted + rejected else None

    known = [item for item in shortlist if score(item) is not None]
    static_score = score(static)
    utility = static
    if static_score is not None and known:
        best = max(known, key=lambda item: float(score(item)))  # type: ignore[arg-type]
        if float(score(best)) > static_score:  # type: ignore[arg-type]
            utility = best
    return {
        "STATIC": static["bundle_id"],
        "UTILITY": utility["bundle_id"],
        "proxy_distinguishable": len({score(item) for item in known}) >= 2,
    }

"""A finite next-evidence decision shared by training exports and real selection.

The selector sees the bounded candidate texts; the Reader receives only opened
items. Controller processing of those texts is real work, not free retrieval.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

STOP_SUFFICIENT = "stop_sufficient"
STOP_EXHAUSTED = "stop_exhausted"


def decision_payload(
    question: str,
    evidence: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project only visible fields; offline labels/IDs never enter model input."""
    def visible(item: dict[str, Any]) -> dict[str, Any]:
        return {key: item[key] for key in ("id", "title", "text")}

    criteria = {f"open_{item['id']}": f"Read candidate {item['id']} next."
                for item in candidates}
    criteria.update({
        STOP_SUFFICIENT: "The already read evidence is sufficient to answer.",
        STOP_EXHAUSTED: "Evidence is insufficient and this pool offers no useful supplement.",
    })
    return {
        "state": {"question": question, "read_evidence": [visible(x) for x in evidence],
                  "candidates": [visible(x) for x in candidates]},
        "questions": {"next": {
            "type": "choice",
            "instructions": (
                "Choose the next evidence needed for this question, or stop. A candidate can "
                "supply a missing premise even if it cannot answer alone. Sufficiency refers "
                "only to already read evidence. Pool exhaustion does not establish that the "
                "answer is false or absent outside this pool."
            ),
            "criteria": criteria,
        }},
    }


def select_bounded(
    question: str,
    candidates: list[dict[str, Any]],
    decide: Callable[[dict[str, Any]], str],
    *,
    max_candidates: int = 8,
    max_reads: int = 4,
) -> dict[str, Any]:
    """At most max_reads decisions, without subset enumeration or retries."""
    remaining = list(candidates[:max_candidates])
    evidence: list[dict[str, Any]] = []
    actions = []
    reason = "read_budget"
    for _ in range(max_reads):
        if not remaining:
            reason = "pool_consumed"  # Consumed is not a semantic sufficiency verdict.
            break
        payload = decision_payload(question, evidence, remaining)
        action = decide(payload)
        if action not in payload["questions"]["next"]["criteria"]:
            raise ValueError(f"Decision is outside the offered actions: {action}")
        actions.append(action)
        if action in (STOP_SUFFICIENT, STOP_EXHAUSTED):
            reason = action
            break
        chosen = next(item for item in remaining if action == f"open_{item['id']}")
        evidence.append(chosen)
        remaining.remove(chosen)
    return {"selected_ids": [item["id"] for item in evidence], "stop_reason": reason,
            "actions": actions, "decision_calls": len(actions),
            "candidate_count": min(len(candidates), max_candidates)}

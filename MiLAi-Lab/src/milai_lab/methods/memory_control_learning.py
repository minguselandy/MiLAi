"""Offline operation examples and metrics; task success requires actual rollouts."""
from __future__ import annotations

import copy
from collections import Counter, defaultdict
from typing import Any

from milai_lab.methods.laya_memory_policy import operation_payload
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState


def decision_example(
    event: dict[str, Any], metadata: dict[str, Any], *, projection: str = "full",
) -> dict[str, Any]:
    """Export the same model input, initially masked until a source-grounded review."""
    state = MemoryControlState(**event["before"])
    actions = [MemoryAction(**a) for a in event["actions"]]
    return {**operation_payload(state, actions, projection), "gold": {},
            "metadata": {**metadata, "action_kinds": {a.id: a.kind for a in actions},
                         "action_parameters": {a.id: copy.deepcopy(a.parameters) for a in actions},
                         "label_status": "unreviewed_masked"}}


def reviewed_prefix_preferences(
    actions: list[dict[str, Any]], *, proofs: list[set[str]], covered: set[str],
    read_sources: dict[str, set[str]], refresh_sources: dict[str, set[str]],
    opened_views: list[bool | None],
) -> tuple[list[str], str, list[str]]:
    """Offline next-step preferences; unreviewed opened views do not become false labels."""
    if len(actions) == 1:
        return [], "forced_single_action_masked", []
    raw_ready = any(proof <= covered for proof in proofs)
    if raw_ready or any(ready is True for ready in opened_views):
        return ([a["id"] for a in actions if a["kind"] == "HANDOFF"],
                "ready_handoff_preference", ["adequate_originals" if raw_ready
                                             else "reviewed_task_adequate_view"])
    if None in opened_views:
        return [], "unreviewed_opened_view_masked", []
    selected, basis = [], []
    for action in actions:
        key, kind = action["id"], action["kind"]
        if kind == "SEARCH":
            selected.append(key)
            basis.append("source_pool_acquisition")
        elif kind == "USE_VIEW":
            selected.append(key)
            basis.append("inspect_existing_interpretation_without_assuming_adequacy")
        elif kind == "REFRESH_VIEW" and any(
            proof <= refresh_sources.get(key, set()) for proof in proofs
        ):
            selected.append(key)
            basis.append("adequate_source_scope;executor_quality_separate")
        elif kind == "READ" and any(
            read_sources.get(key, set()) & (proof - covered) for proof in proofs
        ):
            selected.append(key)
            basis.append("adds_missing_reviewed_original")
    return (selected, "acquire_evidence_preference" if selected
            else "ambiguous_no_proven_progress_masked", sorted(set(basis)))


def score_operation_predictions(
    rows: list[dict[str, Any]], predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    strata: dict[str, Counter[str]] = defaultdict(Counter)
    chosen: dict[str, Counter[str]] = defaultdict(Counter)
    families: dict[str, list[int]] = defaultdict(list)
    for row, prediction in zip(rows, predictions, strict=True):
        target = row.get("gold", {}).get("next", {}).get("probabilities", {})
        if not target:
            counts["masked"] += 1
            continue
        choice = prediction["choice"]
        accepted = int(target.get(choice, 0) > 0)
        kind = row["metadata"]["action_kinds"][choice]
        counts.update(labelled=1, accepted=accepted)
        strata[row["metadata"]["label_status"]].update(labelled=1, accepted=accepted)
        chosen[kind].update(selected=1, accepted=accepted)
        families[row["metadata"]["family"]].append(accepted)
        if kind == "HANDOFF" and not accepted:
            counts["handoff_outside_reviewed_preference"] += 1
    return {"counts": dict(counts), "strata": dict(strata), "selected_operations": dict(chosen),
            "families": len(families), "family_macro_acceptance": (
                sum(sum(v) / len(v) for v in families.values()) / len(families)
                if families else None),
            "scope": "Reviewed operation preferences; not exhaustive action legality, "
                     "Reader task/state success or cost benefit"}

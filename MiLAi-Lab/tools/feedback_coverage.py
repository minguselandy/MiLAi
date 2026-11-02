"""Matched initial-repeat versus actual initial/post data from the same reviewed source pool."""
from __future__ import annotations

import copy
from collections import Counter, defaultdict
from typing import Any

from quality_feedback import QualityMode, quality_counts, targets, validate_quality_pool


def compile_coverage_controls(
    rows: list[dict[str, Any]], *, target: str = "answer", mode: QualityMode = "quality-direction",
) -> dict[str, Any]:
    """Retain source identities; post slots become literal initial repeats in the control."""
    if any(row["metadata"]["split"] != "train" for row in rows):
        raise ValueError("Coverage control inputs must contain only declared training rows")
    validate_quality_pool(rows)
    feedback = [(i, row) for i, row in enumerate(rows) if "feedback" in row]
    replay = [(i, row) for i, row in enumerate(rows) if "feedback" not in row]
    if len({r["metadata"]["event_id"] for _, r in feedback}) != len(feedback):
        raise ValueError("The original feedback pool must contain distinct actual states")
    families = list(dict.fromkeys(r["metadata"]["family"] for _, r in feedback))
    collectors = list(dict.fromkeys(r["metadata"]["collection_policy"] for _, r in feedback))
    slots: dict[tuple[str, str], dict[str, tuple[int, dict[str, Any]]]] = defaultdict(dict)
    known: dict[tuple[str, str], bool] = defaultdict(bool)
    for index, row in feedback:
        meta = row["metadata"]
        stage = "initial" if meta["control_step"] == 0 else "post"
        key = meta["family"], meta["collection_policy"]
        if stage in slots[key]:
            raise ValueError("Freeze one actual initial/post state per family/collector first")
        slots[key][stage] = (index, row)
        known[meta["family"], stage] |= bool(targets(row["feedback"]["comparisons"], target, mode))
    eligible, excluded = [], []
    for family in families:
        complete = all(set(slots[family, collector]) == {"initial", "post"}
                       for collector in collectors)
        both_known = all(known[family, stage] for stage in ("initial", "post"))
        if complete and both_known:
            eligible.append(family)
        else:
            excluded.append({"family": family, "all_collector_stage_slots_present": complete,
                             "has_known_target_initial": known[family, "initial"],
                             "has_known_target_post": known[family, "post"]})
    if not eligible:
        raise ValueError("No source families satisfy the declared matched coverage criterion")
    kept = [(i, row) for i, row in feedback if row["metadata"]["family"] in eligible]
    if len(replay) < len(kept) or any(not row["gold"] for _, row in replay):
        raise ValueError("The source pool does not supply the declared labelled replay prefix")
    replay = replay[:len(kept)]
    initial_post, initial_only, mapping = [], [], []
    for position, (source_index, row) in enumerate(kept):
        meta = row["metadata"]
        initial_index, initial = slots[meta["family"], meta["collection_policy"]]["initial"]
        initial_post.append(copy.deepcopy(row))
        initial_only.append(copy.deepcopy(initial))
        mapping.append({"position": position, "component": "feedback",
            "family": meta["family"], "collector": meta["collection_policy"],
            "original_slot_stage": "initial" if meta["control_step"] == 0 else "post",
            "initial_post_source_index": source_index, "initial_only_source_index": initial_index,
            "initial_post_event_id": meta["event_id"],
            "initial_only_event_id": initial["metadata"]["event_id"],
            "same_training_event": meta.get("training_event", meta["row"])
                == initial["metadata"].get("training_event", initial["metadata"]["row"])})
    for index, row in replay:
        position = len(initial_post)
        initial_post.append(copy.deepcopy(row))
        initial_only.append(copy.deepcopy(row))
        mapping.append({"position": position, "component": "replay",
            "initial_post_source_index": index, "initial_only_source_index": index,
            "initial_post_event_id": row["metadata"]["event_id"],
            "initial_only_event_id": row["metadata"]["event_id"]})
    arms = {"initial_only": initial_only, "initial_post": initial_post}
    counts = {}
    for name, arm in arms.items():
        actual = [r for r in arm if "feedback" in r]
        counts[name] = {"rows": len(arm), "feedback_rows": len(actual), "replay_rows": len(replay),
            "unique_feedback_states": len({r["metadata"]["event_id"] for r in actual}),
            "unique_feedback_state_ids": len({r["metadata"]["state_id"] for r in actual}),
            "unique_feedback_training_events": len({r["metadata"].get("training_event",
                r["metadata"]["row"]) for r in actual}),
            "actual_stage_counts": dict(Counter("initial" if r["metadata"]["control_step"] == 0
                                                  else "post" for r in actual)),
            "target_coverage": quality_counts(arm, target, mode)}
    return {"arms": arms, "mapping": mapping, "eligible_families": eligible,
        "excluded_families": excluded, "collectors": collectors, "target": target, "mode": mode,
        "counts": counts,
        "scope": "Actual control_step0 versus post-operation states, not cold/known-empty versus "
                 "warm episodes. Every row is a literal original or an identified initial repeat. "
                 "No post labels, material, known evidence or stage identity transfer to initials. "
                 "Post request/known context may differ; this is experience coverage, not a "
                 "phase-tag-only intervention."}

"""Attach explicit source-reviewed preferences to unchanged observed decisions."""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from milai_lab.memory.functional_state import body_text, canonical
from milai_lab.memory.reader_projection import merge_source_ranges
from milai_lab.methods.intent_retrieval import retrieval_packet


def original_binding_material(
    binding: dict[str, Any], sources: dict[str, dict[str, Any]], *, expand: bool = False,
) -> dict[str, Any]:
    """Project issued original ranges from immutable captured bodies for offline costing."""
    ranges = merge_source_ranges(binding[
        "context_source_ranges" if expand else "source_ranges"])
    turns = []
    for span in ranges:
        source = sources[span["source_ref"]]
        turns.append({"source_ref": span["source_ref"], "source_revision": span["source_revision"],
            "role": source["role"], "origin": source["origin"],
            "content": body_text(source)[span["start"]:span["end"]],
            "range": [span["start"], span["end"]],
            "occurred_at": source.get("occurred_at"), "observed_at": source["observed_at"],
            **({"source_total_codepoints": len(body_text(source))}
               if binding.get("source_observation_read") else {}),
            **({"calendar_context": source["calendar_context"]}
               if "calendar_context" in source else {})})
    return {"kind": "original_source", "source_ranges": ranges,
            **({"source_observation_read": True} if binding.get("source_observation_read") else {}),
            "visibility": "visible", "body_delivered": True,
            "text": json.dumps(turns, ensure_ascii=False)}


def complete_originals(
    bindings: list[dict[str, Any]], sources: dict[str, dict[str, Any]],
) -> set[str]:
    """Conservative whole-turn witnesses; excerpts never count as the whole report."""
    spans = merge_source_ranges([span for item in bindings
        if item["kind"] == "original_source" and item.get("body_delivered") is not False
        for span in item.get("source_ranges", [])])
    return {span["source_ref"] for span in spans if span["start"] == 0
            and span["source_revision"] == sources[span["source_ref"]].get("source_revision", 1)
            and span["end"] == len(body_text(sources[span["source_ref"]]))}


def original_witness_preferences(
    row: dict[str, Any], *, proofs: list[set[str]], sources: dict[str, dict[str, Any]],
    return_key: str, token_count: Callable[[str], int],
    observed_search: tuple[str, list[dict[str, Any]]] | None = None,
    proof_complete: bool = True,
) -> tuple[list[str], str]:
    """Only for a request whose source witnesses were explicitly reviewed offline.

    READ must add missing evidence and fit the same full return representation.
    SEARCH is preferred only when its observed result adds a missing witness.
    A reviewed partial chain can support progress, but never certifies sufficiency.
    View value is not inferred from availability, source count or a teacher action.
    """
    choices = row["questions"]["next"]["criteria"]
    if len(choices) == 1:
        return [], "forced_single_action_masked"
    if not proofs or any(not proof for proof in proofs):
        return [], "no_reviewed_source_proof_masked"
    bindings = row["metadata"]["actual_bindings"]
    opened = {int(i): item for i, item in bindings["opened_materials"].items()}
    known = bindings["known_materials"]
    covered = complete_originals([*opened.values(), *known], sources)
    kinds = row["metadata"]["action_kinds"]
    if any(proof <= covered for proof in proofs):
        if not proof_complete:
            return [], "reviewed_partial_evidence_only_masked"
        return [key for key in choices if kinds[key] == "HANDOFF"], "reviewed_originals_sufficient"
    if any(item["kind"] != "original_source" for item in opened.values()):
        return [], "nonoriginal_opened_material_requires_review"
    missing = set().union(*(proof - covered for proof in proofs)) if proofs else set()
    materials = bindings["candidate_materials"]
    actual = {i: original_binding_material(item, sources) for i, item in opened.items()}
    step = int(row["metadata"]["event_id"].rsplit("/", 1)[1])
    total_steps = row["state"]["budget"]["remaining_control_steps"] + step
    usage = {"control_steps": total_steps, "known_reference_reads": len(known),
             "operations": total_steps, "read_operations": total_steps,
             "material_budget_rejections": total_steps}
    preferred = []
    # The real typed options include bound parameters; no topic-specific route is added.
    for key in choices:
        if kinds[key] != "READ":
            continue
        parameters = row["metadata"]["action_parameters"][key]
        if parameters.get("history_directory") or "source_observation_cursor" in parameters:
            continue
        item: dict[str, Any]
        if "observed_source" in parameters:
            index = len(materials)  # Executor appends the selected source at this index.
            item = {"kind": "original_source", "source_ranges": [parameters["observed_source"]],
                    "source_observation_read": True}
        else:
            index = parameters["index"]
            item = materials[index]
        if item["kind"] != "original_source" or item.get("body_delivered") is False:
            continue
        candidate = original_binding_material(item, sources,
                                              expand=parameters.get("expand_context", False))
        if not (complete_originals([candidate], sources) & missing):
            continue
        trial = {**actual, index: candidate}
        if all(token_count(canonical(retrieval_packet(
            return_key, list(trial.values()), list(trial), list(range(len(trial))), reason,
            usage, ok=False))) <= row["state"]["budget"]["max_return_tokens"]
            for reason in ("policy_handoff", "budget_exhausted", "no_available_operation",
                           "operation_outcome_unknown")):
            preferred.append(key)
    if observed_search is not None:
        key, after_candidates = observed_search
        before_refs = complete_originals(materials, sources)
        new_refs = complete_originals(after_candidates, sources) - before_refs
        if key in choices and kinds[key] == "SEARCH" and new_refs & missing:
            preferred.append(key)
    return preferred, ("reviewed_missing_original_progress" if preferred
                       else "no_reviewed_progress_masked")


def annotate_decisions(
    rows: list[dict[str, Any]], reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """No observed teacher action or executable option becomes an automatic label.

    The review is an offline judgment, not a claim that every other action is
    illegal or that its probability is calibrated. Unreviewed states stay masked.
    """
    by_event = {review["event_id"]: review for review in reviews}
    if len(by_event) != len(reviews):
        raise ValueError("More than one review for the same decision")
    unknown = set(by_event) - {row["metadata"]["event_id"] for row in rows}
    if unknown:
        raise ValueError("Review does not identify an observed decision: " + str(sorted(unknown)))
    result = []
    for original in rows:
        row = copy.deepcopy(original)
        review = by_event.get(row["metadata"]["event_id"])
        choices = row["questions"]["next"]["criteria"]
        row["gold"] = {}
        if review is not None:
            row["metadata"]["source_review"] = copy.deepcopy(review)
            selected = list(dict.fromkeys(review["preferred_actions"]))
            if set(selected) - set(choices):
                raise ValueError("Preference is outside the actual executable action set")
            if selected and len(choices) > 1:
                row["gold"] = {"next": {"probabilities": {
                    key: 1 / len(selected) if key in selected else 0.0 for key in choices}}}
                row["metadata"]["label_status"] = "source_reviewed_preference"
            else:
                row["metadata"]["label_status"] = (
                    "forced_single_action_masked" if len(choices) == 1
                    else "reviewed_ambiguous_masked")
        else:
            row["metadata"]["label_status"] = "unreviewed_masked"
        result.append(row)
    return result

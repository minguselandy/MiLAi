"""Read-only maintenance views; no gold or evaluator result enters the Writer."""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

from milai_lab.analysis.edit_results import receipt_effect


def record_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row["value"] for row in rows if row.get("ok")}


def _unit_key(unit: dict[str, Any]) -> tuple[str, str]:
    return str(unit["role"]), str(unit["text"])


def _delta(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Actual state difference with unchanged attached conditions as context.

    Exact unchanged text is excluded from the new-claim list even when a whole
    rewrite assigns new IDs. This is a textual view, not a claim-equivalence oracle.
    """
    prior = (old or {}).get("edit_state") or {"units": [], "relations": []}
    current = new.get("edit_state") or {"units": [], "relations": []}
    old_units = {unit["unit_id"]: unit for unit in prior["units"]}
    new_units = {unit["unit_id"]: unit for unit in current["units"]}
    remaining = Counter(_unit_key(unit) for unit in prior["units"])
    added = []
    unchanged = []
    for unit in current["units"]:
        key = _unit_key(unit)
        if remaining[key]:
            remaining[key] -= 1
            unchanged.append(unit)
        else:
            added.append(unit)
    remaining_new = Counter(_unit_key(unit) for unit in current["units"])
    removed = []
    for unit in prior["units"]:
        key = _unit_key(unit)
        if remaining_new[key]:
            remaining_new[key] -= 1
        else:
            removed.append(unit)
    changed_ids = {unit["unit_id"] for unit in added}
    prior_relations = prior["relations"]
    current_relations = current["relations"]

    def relation_meaning(relation: dict[str, Any], units: dict[str, Any]) -> tuple[Any, ...]:
        return (
            relation["relation_type"],
            _unit_key(units[relation["source_unit"]]),
            _unit_key(units[relation["target_unit"]]),
        )

    old_meanings = Counter(relation_meaning(rel, old_units) for rel in prior_relations)
    added_relations = []
    for relation in current_relations:
        key = relation_meaning(relation, new_units)
        if old_meanings[key]:
            old_meanings[key] -= 1
        else:
            added_relations.append(relation)
            changed_ids.update((relation["source_unit"], relation["target_unit"]))
    new_meanings = Counter(relation_meaning(rel, new_units) for rel in current_relations)
    removed_relations = []
    for relation in prior_relations:
        key = relation_meaning(relation, old_units)
        if new_meanings[key]:
            new_meanings[key] -= 1
        else:
            removed_relations.append(relation)
    context_ids = set(changed_ids)
    # Existing one-level relations provide necessary scope, not unrelated bank text.
    for relation in current_relations:
        if relation["source_unit"] in changed_ids or relation["target_unit"] in changed_ids:
            context_ids.update((relation["source_unit"], relation["target_unit"]))
    return {
        "kind": "create" if old is None else "update",
        "prior_revision": (old or {}).get("revision"),
        "current_revision": new["revision"],
        "actual_operations": copy.deepcopy(new.get("edit_operations", [])),
        "new_or_changed_units": copy.deepcopy(added),
        "removed_or_replaced_units": copy.deepcopy(removed),
        "new_or_changed_relations": copy.deepcopy(added_relations),
        "removed_or_replaced_relations": copy.deepcopy(removed_relations),
        "necessary_current_context": [
            copy.deepcopy(unit) for unit in current["units"] if unit["unit_id"] in context_ids
        ],
        "unchanged_text_unit_count": len(unchanged),
        "old_target_present": old is not None,
        "limit": "Exact text/role/edge comparison; paraphrases are not semantic equivalents.",
    }


def maintenance_views(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    official_extracted: list[str],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keep official compatibility exact, no-change explicit and own state intact."""
    old, new = record_index(before), record_index(after)
    no_change = []
    rejected = []
    touched = []
    for receipt in receipts:
        if not receipt.get("ok"):
            rejected.append(copy.deepcopy(receipt))
            continue
        record_id = receipt.get("id")
        if (
            receipt_effect(receipt) == "no_change"
            or record_id is None
            or old.get(record_id) == new.get(record_id)
        ):
            no_change.append(copy.deepcopy(receipt))
        elif record_id not in touched:
            touched.append(record_id)
    deltas = [{"record_id": key, **_delta(old.get(key), new[key])} for key in touched]
    return {
        "official_extracted_compat": list(official_extracted),
        "delta_view": deltas,
        "no_change": no_change,
        "rejected": rejected,
        "state_before": copy.deepcopy(before),
        "state_after": copy.deepcopy(after),
        "new_sources_actually_delivered": copy.deepcopy(sources),
        "limit": (
            "Official extraction is unchanged. "
            "Delta/state are supplemental views, not author scores."
        ),
    }


def grounding_sources(
    rows: list[dict[str, Any]], sources: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Attach ONLY actual cited historical bodies; missing bodies remain UNKNOWN."""
    fragments: dict[str, dict[str, Any]] = {}
    missing = []
    for row in rows:
        if not row.get("ok"):
            continue
        state = row["value"].get("edit_state") or {"units": [], "relations": []}
        for item in [*state["units"], *state["relations"]]:
            for ref in item["evidence_refs"]:
                evidence_id = ref["evidence_id"]
                if evidence_id in fragments:
                    continue
                source = sources.get(ref["source_ref"])
                body = None if source is None else source.get("content")
                if not isinstance(body, str) or not 0 <= ref["start"] < ref["end"] <= len(body):
                    missing.append({"evidence_id": evidence_id, "status": "UNKNOWN"})
                    continue
                assert source is not None
                fragments[evidence_id] = {
                    **copy.deepcopy(ref),
                    "text": body[ref["start"] : ref["end"]],
                    "role": source["role"],
                    "observed_at": source["observed_at"],
                    "body_delivered_to_scorer": True,
                    "semantic_support": "unchecked",
                }
    return {"cited_bodies": list(fragments.values()), "missing_old_support": missing}

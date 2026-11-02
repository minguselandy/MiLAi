"""A declared finite auxiliary panel preserves complete known condition pairs."""
from __future__ import annotations

import copy
import random
from collections import Counter, defaultdict
from typing import Any

from milai_lab.datasets.conditional_reviews import binary_label


def condition_stratified_auxiliary_panel(
    matrix: list[dict[str, Any]], pairs: list[dict[str, Any]], *, seed: int,
) -> dict[str, Any]:
    """Retain rare pairs and known label coverage for every actual training condition.

    One known stable-negative pair per query anchors stability when available.
    Single-condition queries remain eligible. Missing labels stay missing, and
    each selected cell appears once. This changes data exposure, not the loss.
    """
    by_id = {row["metadata"]["event_id"]: i for i, row in enumerate(matrix)}
    if len(by_id) != len(matrix) or any(r["metadata"]["split"] != "train" for r in matrix):
        raise ValueError("Stratified exposure requires distinct cells in the training split")
    conditions: dict[tuple[str, str, str], dict[bool, list[int]]] = {}
    query_conditions: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for i, row in enumerate(matrix):
        meta = row["metadata"]
        key = (meta["family"], meta["query_unit"], meta["training_event"])
        if key not in conditions:
            query_conditions[meta["query_unit"]].append(key)
        strata = conditions.setdefault(key, {True: [], False: []})
        label = binary_label(row)
        if label is not None:
            strata[label].append(i)
    selected: set[int] = set()
    negative_pairs: dict[str, list[tuple[int, int]]] = defaultdict(list)
    known_pairs: list[dict[str, Any]] = []
    for pair in pairs:
        if pair["kind"] == "unknown":
            continue
        indices = tuple(by_id[pair[side + "_event"]] for side in ("left", "right"))
        left, right = [matrix[i] for i in indices]
        a, z = binary_label(left), binary_label(right)
        if (a is None or z is None or pair["left_label"] != a or pair["right_label"] != z
                or pair["kind"] != ("change" if a != z else "stable")
                or left["state"]["candidate"] != right["state"]["candidate"]
                or left["state"]["task"]["retrieval_request"]["query"]
                != right["state"]["task"]["retrieval_request"]["query"]
                or any(row["metadata"][key] != pair[key] for row in (left, right)
                       for key in ("family", "query_unit"))):
            raise ValueError("Known pairs require matching training query, material and labels")
        known_pairs.append(pair)
        if pair["kind"] == "change" or a:
            selected.update(indices)
        else:
            negative_pairs[pair["query_unit"]].append((indices[0], indices[1]))
    rng = random.Random(seed)  # noqa: S311 -- declared experimental sampling
    missing = []
    # Complete each query's draws before the next, so appended families do not
    # resample the existing prefix in a later scale level.
    for query, keys in query_conditions.items():
        if negative_pairs[query]:
            selected.update(rng.choice(negative_pairs[query]))
        for key in keys:
            family, _, event = key
            for label, positions in conditions[key].items():
                if not positions:
                    missing.append({"family": family, "query_unit": query,
                                    "training_event": event, "label": label})
                elif not selected.intersection(positions):
                    selected.add(rng.choice(positions))
    rows, slots = [], []
    for i in sorted(selected):
        row = copy.deepcopy(matrix[i])
        row["metadata"]["state_id"] = i
        rows.append(row)
        slots.append({"slot": len(rows), "source_matrix_position": i,
                      "event_id": row["metadata"]["event_id"]})
    exposed = [p for p in known_pairs if all(by_id[p[k]] in selected
               for k in ("left_event", "right_event"))]
    represented = {row["metadata"]["family"] for row in rows}
    return {"rows": rows, "pairs": copy.deepcopy(exposed), "slots": slots,
        "missing_condition_labels": missing,
        "counts": {"training_slots": len(rows), "distinct_cells": len(selected),
            "source_families": len({r["metadata"]["family"] for r in matrix}),
            "families": len(represented),
            "unrepresented_families": sorted({r["metadata"]["family"] for r in matrix}
                                             - represented),
            "query_units": len({r["metadata"]["query_unit"] for r in rows}),
            "source_conditions": len(conditions),
            "conditions": len({tuple(r["metadata"][key] for key in
                                     ("family", "query_unit", "training_event")) for r in rows}),
            "positive_slots": sum(binary_label(row) is True for row in rows),
            "negative_slots": sum(binary_label(row) is False for row in rows),
            "complete_known_pairs": len(exposed),
            "comparison_kind": dict(Counter(p["kind"] for p in exposed)),
            "stable_positive_pairs": sum(p["kind"] == "stable" and p["left_label"] is True
                                         for p in exposed),
            "stable_negative_pairs": sum(p["kind"] == "stable" and p["left_label"] is False
                                         for p in exposed),
            "label_provenance_slots": dict(Counter(r["metadata"]["label_status"] for r in rows))}}


def paired_auxiliary_panel(
    matrix: list[dict[str, Any]], pairs: list[dict[str, Any]], *, pair_budget: int, seed: int,
) -> dict[str, Any]:
    """Keep all known change/positive pairs and cover each pairable query before negatives.

    The resulting two rows per pair are a training exposure view, not new source
    examples. A full shuffled pass sees both conditions, without requiring them
    in one optimizer window. Original identities and labels remain attached;
    state_id is the original matrix position used for the existing slot shuffle.
    """
    by_id = {r["metadata"]["event_id"]: (i, r) for i, r in enumerate(matrix)}
    if len(by_id) != len(matrix):
        raise ValueError("Conditional matrix event identities must be unique")
    known: list[int] = []
    mandatory: list[int] = []
    queries: dict[str, list[int]] = defaultdict(list)
    for index, pair in enumerate(pairs):
        if pair["kind"] == "unknown":
            continue
        left, right = [by_id[pair[k]][1] for k in ("left_event", "right_event")]
        a, z = binary_label(left), binary_label(right)
        if (a is None or z is None or pair["left_label"] != a or pair["right_label"] != z
                or pair["kind"] != ("change" if a != z else "stable")):
            raise ValueError("Known pair labels must match the actual supervised cells")
        if (left["state"]["candidate"] != right["state"]["candidate"]
                or left["state"]["task"]["retrieval_request"]["query"]
                != right["state"]["task"]["retrieval_request"]["query"]
                or any(row["metadata"]["split"] != "train" for row in (left, right))
                or any(row["metadata"][key] != pair[key] for row in (left, right)
                       for key in ("family", "query_unit"))):
            raise ValueError("Auxiliary pairs require the same training query and candidate")
        known.append(index)
        queries[pair["query_unit"]].append(index)
        if pair["kind"] == "change" or a:
            mandatory.append(index)
    if pair_budget < 1 or pair_budget > len(known):
        raise ValueError("Pair budget must fit the available distinct known pairs")
    rng = random.Random(seed)  # noqa: S311 -- declared experimental allocation
    order = known.copy()
    rng.shuffle(order)
    rank = {index: position for position, index in enumerate(order)}
    selected = set(mandatory)
    for positions in queries.values():
        if not selected.intersection(positions):
            selected.add(min(positions, key=rank.__getitem__))
    if len(selected) > pair_budget:
        raise ValueError("Pair budget cannot retain all rare pairs and pairable queries")
    for index in order:
        if len(selected) == pair_budget:
            break
        selected.add(index)
    rows: list[dict[str, Any]] = []
    slots: list[dict[str, Any]] = []
    chosen = [pairs[i] for i in sorted(selected)]
    for index in sorted(selected):
        for side in ("left", "right"):
            position, original = by_id[pairs[index][side + "_event"]]
            row = copy.deepcopy(original)
            row["metadata"]["state_id"] = position
            rows.append(row)
            slots.append({"slot": len(slots), "source_pair_index": index, "side": side,
                          "source_matrix_position": position,
                          "event_id": original["metadata"]["event_id"]})
    positive = sum(p["kind"] == "stable" and p["left_label"] for p in chosen)
    return {"rows": rows, "pairs": copy.deepcopy(chosen), "slots": slots, "counts": {
        "pairs": len(chosen), "training_slots": len(rows),
        "distinct_cells": len({row["metadata"]["event_id"] for row in rows}),
        "families": len({p["family"] for p in chosen}), "query_units": len(queries),
        "known_query_units_without_pairs": len({r["metadata"]["query_unit"] for r in matrix
                                               if r["gold"]} - set(queries)),
        "comparison_kind": dict(Counter(p["kind"] for p in chosen)),
        "stable_positive_pairs": positive,
        "stable_negative_pairs": sum(p["kind"] == "stable" for p in chosen) - positive,
        "label_provenance_slots": dict(Counter(r["metadata"]["label_status"] for r in rows)),
    }}

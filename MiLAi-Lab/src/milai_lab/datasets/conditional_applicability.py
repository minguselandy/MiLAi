"""Native conditional candidate unions with explicit missing/conflicting judgment masks."""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from typing import Any, Literal

from milai_lab.datasets.followir import applicability_input
from milai_lab.datasets.promptriever import PASSAGES, base_query_id

Dataset = Literal["promptriever", "followir"]
OPTIONS = ("satisfies", "does_not_satisfy")


def native_observations(row: dict[str, Any], index: int, dataset: Dataset) -> list[dict[str, Any]]:
    """Each membership is a judgment only for its own native query/instruction row."""
    if dataset == "followir":
        return [{"base_query_id": str(row["id"]), "query": row["query"],
            "instruction": row["instruction"], "candidate": {"text": row["document"]},
            "judgment": {"native_row": index, "native_condition_id": str(row["id"]),
                "native_docid": None, "native_field": "label", "passage_index": None,
                "label": {"true": True, "false": False}[row["label"]]}}]
    observations = []
    for kind, field in PASSAGES:
        for position, passage in enumerate(row[field]):
            # A changed title/body is a different candidate even when a native docid is reused.
            candidate = {k: passage[k] for k in ("title", "text") if k in passage}
            observations.append({"base_query_id": base_query_id(row), "query": row["only_query"],
                "instruction": row["only_instruction"], "candidate": candidate,
                "judgment": {"native_row": index, "native_condition_id": str(row["query_id"]),
                    "native_docid": str(passage["docid"]), "native_field": field,
                    "passage_index": position, "label": kind == "positive"}})
    return observations


def compile_condition_union(
    source_rows: dict[int, dict[str, Any]], groups: list[dict[str, Any]], dataset: Dataset,
) -> dict[str, Any]:
    """Use an existing split allocation; retain every candidate before any supervision mask."""
    allocated = [i for group in groups for i in group["rows"]]
    if len(allocated) != len(set(allocated)) or set(allocated) != source_rows.keys():
        raise ValueError("Conditional export requires exactly the selected allocated source rows")
    matrix: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []
    for group in groups:
        by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for index in group["rows"]:
            for item in native_observations(source_rows[index], index, dataset):
                by_base[item["base_query_id"]].append(item)
        for base, observations in by_base.items():
            unit_id = f"{group['source_group']}/base-{len(units)}"
            conditions: list[tuple[str, str]] = []
            candidates: list[dict[str, Any]] = []
            judged: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
            aliases: dict[int, set[str]] = defaultdict(set)
            for item in observations:
                condition = (item["query"], item["instruction"])
                if condition not in conditions:
                    conditions.append(condition)
                if item["candidate"] not in candidates:
                    candidates.append(item["candidate"])
                ci, di = conditions.index(condition), candidates.index(item["candidate"])
                judged[ci, di].append(item["judgment"])
                if item["judgment"]["native_docid"] is not None:
                    aliases[di].add(item["judgment"]["native_docid"])
            cells = {}
            for ci, (query, instruction) in enumerate(conditions):
                for di, candidate in enumerate(candidates):
                    judgments = judged[ci, di]
                    labels = {j["label"] for j in judgments}
                    status = ("known" if len(labels) == 1 else
                              "conflicting_native_judgments" if labels else "unjudged")
                    label = next(iter(labels)) if len(labels) == 1 else None
                    event_id = f"{unit_id}/condition-{ci}/candidate-{di}"
                    cells[ci, di] = {"event_id": event_id, "label": label, "status": status}
                    gold = ({"applicability": {"probabilities": {
                        option: float(option == OPTIONS[0 if label else 1])
                        for option in OPTIONS}}} if label is not None else {})
                    matrix.append({**applicability_input(query, instruction, candidate),
                        "gold": gold, "metadata": {"task": "instruction_applicability",
                            "family": group["source_group"], "split": group["split"],
                            "row": len(matrix), "event_id": event_id,
                            "training_event": f"{unit_id}/condition-{ci}", "query_unit": unit_id,
                            "native_base_query_id": base, "condition_index": ci,
                            "candidate_index": di, "native_docids": sorted(aliases[di]),
                            "source": dataset, "label_status": status,
                            "native_judgments": judgments,
                            "supervision_scope": "published membership/label; not independently "
                                "reviewed factuality, operation value or Host sufficiency"}})
            for a, z in combinations(range(len(conditions)), 2):
                for di in range(len(candidates)):
                    left, right = cells[a, di], cells[z, di]
                    if conditions[a][0] != conditions[z][0]:
                        kind, reason = "unknown", "query_text_also_changed"
                    elif left["label"] is None or right["label"] is None:
                        kind = "unknown"
                        reason = ("conflicting_native_judgments" if any(
                            cell["status"] == "conflicting_native_judgments"
                            for cell in (left, right)) else "missing_cross_condition_judgment")
                    else:
                        kind = "change" if left["label"] != right["label"] else "stable"
                        reason = "both_native_conditions_judged"
                    pairs.append({"family": group["source_group"], "split": group["split"],
                        "query_unit": unit_id, "native_base_query_id": base,
                        "candidate_index": di, "left_event": left["event_id"],
                        "right_event": right["event_id"], "kind": kind, "reason": reason,
                        "left_label": left["label"], "right_label": right["label"]})
            units.append({"query_unit": unit_id, "native_base_query_id": base,
                "family": group["source_group"], "split": group["split"],
                "native_rows": sorted({o["judgment"]["native_row"] for o in observations}),
                "conditions": [{"query": q, "instruction": purpose} for q, purpose in conditions],
                "candidate_count": len(candidates),
                "native_docid_versions": {docid: [i for i in range(len(candidates))
                    if docid in aliases[i]] for docid in sorted(set().union(*aliases.values()))}})
    return {"matrix": matrix, "pairs": pairs, "units": units,
        "counts": {"allocated_families": len(groups), "native_rows": len(source_rows),
            "query_units": len(units), "multiple_condition_query_units": sum(
                len(u["conditions"]) > 1 for u in units),
            "matrix_cells": len(matrix),
            "cell_status": dict(Counter(row["metadata"]["label_status"] for row in matrix)),
            "comparison_kind": dict(Counter(pair["kind"] for pair in pairs)),
            "unknown_reason": dict(Counter(p["reason"] for p in pairs if p["kind"] == "unknown"))}}


def score_condition_pairs(
    matrix: list[dict[str, Any]], pairs: list[dict[str, Any]], predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Correct change/stability means both decisions are right; unknowns are not errors."""
    choices = {row["metadata"]["event_id"]: prediction["choice"]
               for row, prediction in zip(matrix, predictions, strict=True)}
    if len(choices) != len(matrix) or any(choice not in OPTIONS for choice in choices.values()):
        raise ValueError("Conditional predictions must cover distinct cells with legal choices")
    reports = {}
    for kind in ("change", "stable", "unknown"):
        selected = [pair for pair in pairs if pair["kind"] == kind]
        by_query: dict[tuple[str, str], list[int]] = defaultdict(list)
        prediction_changes = 0
        for pair in selected:
            a, z = choices[pair["left_event"]], choices[pair["right_event"]]
            prediction_changes += a != z
            if kind == "unknown":
                continue
            correct = (a == OPTIONS[0 if pair["left_label"] else 1]
                       and z == OPTIONS[0 if pair["right_label"] else 1])
            by_query[pair["family"], pair["query_unit"]].append(int(correct))
        by_family: dict[str, list[float]] = defaultdict(list)
        for (family, _), values in by_query.items():
            by_family[family].append(sum(values) / len(values))
        means = {family: sum(values) / len(values) for family, values in by_family.items()}
        reports[kind] = {"pairs": len(selected), "query_units_with_judged_pairs": len(by_query),
            "families_with_judged_pairs": len(means), "by_family_joint_accuracy": means,
            "family_macro_query_pair_joint_accuracy": sum(means.values()) / len(means)
                if means else None,
            "prediction_change_rate": prediction_changes / len(selected) if selected else None}
    return {"strata": reports,
        "scope": "Joint candidate classification over a fixed literal candidate under two "
                 "conditions; mean pairs inside query, then queries inside family, then families. "
                 "Unknown comparisons have no accuracy denominator. Prediction change is "
                 "descriptive. This is not native FollowIR p-MRR, retrieval ranking "
                 "or Host success."}

"""Published Promptriever candidate supervision, separate from memory operations."""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Any

from milai_lab.datasets.followir import applicability_row

PASSAGES = (("positive", "positive_passages"), ("ordinary_negative", "negative_passages"),
            ("instruction_negative", "new_negatives"))


def base_query_id(row: dict[str, Any]) -> str:
    return str(row["query_id"]).removesuffix("-instruct")


def source_keys(row: dict[str, Any]) -> set[tuple[str, str]]:
    """Native query/doc IDs and literal content identities, without content fingerprints."""
    keys = {("base_query", base_query_id(row)),
            ("query", " ".join(row["only_query"].casefold().split()))}
    for _, field in PASSAGES:
        for passage in row[field]:
            keys.update((("docid", str(passage["docid"])), ("document", passage["text"])))
    return keys


def group_promptriever(rows: list[dict[str, Any]], *, seed: int = 0,
                      dev_fraction: float = 0.2) -> list[dict[str, Any]]:
    """Connect all raw candidates before sampling; never split a connected component."""
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owners: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        for key in sorted(source_keys(row)):
            if key in owners:
                parent[find(index)] = find(owners[key])
            else:
                owners[key] = index
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        components[find(index)].append(index)
    ordered = sorted(components.values(), key=lambda ids: min(base_query_id(rows[i]) for i in ids))
    allocation = list(range(len(ordered)))
    random.Random(seed).shuffle(allocation)  # noqa: S311 -- declared source partition
    dev = set(allocation[:round(len(ordered) * dev_fraction)])
    return [{"source_group": f"promptriever-family-{index:04d}",
             "split": "dev" if index in dev else "train", "rows": indices,
             "base_query_ids": sorted({base_query_id(rows[i]) for i in indices})}
            for index, indices in enumerate(ordered)]


def candidate_rows(row: dict[str, Any], index: int, group: dict[str, Any], *,
                   ordinary_negatives: int = 1, instruction_negatives: int = 1,
                   ) -> list[dict[str, Any]]:
    """All positives and a declared prefix of each negative type; no teacher-score input."""
    limits = {"ordinary_negative": ordinary_negatives,
              "instruction_negative": instruction_negatives}
    examples = []
    for kind, field in PASSAGES:
        passages = row[field] if kind == "positive" else row[field][:limits[kind]]
        for position, passage in enumerate(passages):
            example = applicability_row({
                "id": row["query_id"], "query": row["only_query"],
                "instruction": row["only_instruction"], "document": passage["text"],
                "label": "true" if kind == "positive" else "false",
            }, index, group)
            example["metadata"].update(
                source="samaya-ai/msmarco-w-instructions", native_split="train",
                base_query_id=base_query_id(row), native_docid=str(passage["docid"]),
                has_instruction=row["has_instruction"], candidate_kind=kind,
                event_id=f"{group['source_group']}/row-{index}/{kind}-{position}",
                exposure="public_train_internal_partition",
                label_status="published_passage_membership_not_independently_reviewed",
            )
            examples.append(example)
    return examples


def extend_promptriever_allocation(
    rows: list[dict[str, Any]], prior_rows: list[dict[str, Any]],
    prior_groups: list[dict[str, Any]], *, allocation_id: str, seed: int = 0,
    dev_fraction: float = .2,
) -> dict[str, Any]:
    """Extend the complete source graph while locking old splits and excluding new bridges."""
    if rows[:len(prior_rows)] != prior_rows:
        raise ValueError("Expanded intake changed the previously allocated source prefix")
    if (sorted(i for group in prior_groups for i in group["rows"]) != list(range(len(prior_rows)))
            or any(g["split"] not in {"train", "dev", "excluded"} for g in prior_groups)):
        raise ValueError("Prior allocation must cover each old row once with a declared split")
    components = group_promptriever(rows, seed=seed, dev_fraction=0)
    row_component = {i: ci for ci, group in enumerate(components) for i in group["rows"]}
    parent = list(range(len(components)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    # A prior declared family can be broader than the current literal-key graph.
    # Its members remain indivisible even when no new literal edge joins them.
    for group in prior_groups:
        first = row_component[group["rows"][0]]
        for index in group["rows"][1:]:
            parent[find(row_component[index])] = find(first)
    merged: dict[int, list[int]] = defaultdict(list)
    for ci, component in enumerate(components):
        merged[find(ci)].extend(component["rows"])
    ordered = sorted((sorted(indices) for indices in merged.values()),
                     key=lambda indices: min(base_query_id(rows[i]) for i in indices))
    prior_by_row = {i: gi for gi, group in enumerate(prior_groups) for i in group["rows"]}
    groups: list[dict[str, Any]] = []
    unanchored = []
    for index, indices in enumerate(ordered):
        ancestors = [prior_groups[gi] for gi in sorted({prior_by_row[i] for i in indices
                                                       if i in prior_by_row})]
        splits = {g["split"] for g in ancestors}
        if "excluded" in splits:
            split, basis = "excluded", "prior_exclusion"
        elif len(splits) > 1:
            split, basis = "excluded", "bridge_between_prior_train_and_dev"
        elif splits:
            split, = splits
            basis = "prior_" + split + "_anchor"
        else:
            split, basis = "unallocated", "new_component"
            unanchored.append(index)
        groups.append({"source_group": f"{allocation_id}-family-{index:05d}",
            "split": split, "allocation_basis": basis, "rows": indices,
            "base_query_ids": sorted({base_query_id(rows[i]) for i in indices}),
            "prior_anchor_groups": [{"source_group": g["source_group"], "split": g["split"]}
                                    for g in ancestors],
            "prior_rows": sum(i < len(prior_rows) for i in indices),
            "new_rows": sum(i >= len(prior_rows) for i in indices)})
    allocation = list(unanchored)
    random.Random(seed).shuffle(allocation)  # noqa: S311 -- predeclared internal partition
    dev = set(allocation[:round(len(allocation) * dev_fraction)])
    for index in unanchored:
        groups[index]["split"] = "dev" if index in dev else "train"
    return {"groups": groups, "allocation_id": allocation_id, "seed": seed,
        "new_component_dev_fraction": dev_fraction,
        "counts": {"raw_rows": len(rows), "prior_rows": len(prior_rows),
            "prior_groups": len(prior_groups), "source_graph_components": len(components),
            "families_after_prior_family_links": len(groups),
            "base_queries": sum(len(g["base_query_ids"]) for g in groups),
            "split_families": dict(Counter(g["split"] for g in groups)),
            "allocation_basis": dict(Counter(g["allocation_basis"] for g in groups)),
            "largest_family_rows": max((len(g["rows"]) for g in groups), default=0),
            "largest_family_base_queries": max((len(g["base_query_ids"]) for g in groups),
                                                default=0)},
        "scope": "All native candidate links precede caps. Old files/splits are historical "
                 "inputs, never reassigned in place. New components touching both old train/dev "
                 "are excluded from new training/development estimates; prior exclusions persist. "
                 "Only unanchored components receive the new seeded internal split. No claim of "
                 "global, pretraining or formal-confirmation isolation."}

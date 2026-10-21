"""Published Promptriever candidate supervision, separate from memory operations."""
from __future__ import annotations

import random
from collections import defaultdict
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

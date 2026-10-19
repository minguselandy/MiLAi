"""Group the public FollowIR training rows before request/document expansion."""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Any


def group_followir(rows: list[dict[str, Any]], *, seed: int = 0,
                  dev_fraction: float = 0.2) -> list[dict[str, Any]]:
    """Keep topic IDs, repeated queries and literal repeated documents together.

    Query case/whitespace variants join the same component; this does not claim
    semantic paraphrase or pretraining isolation. Labels never determine splits.
    """
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owners: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        query = " ".join(row["query"].casefold().split())
        for key in (("topic", row["id"]), ("query", query), ("document", row["document"])):
            if key in owners:
                parent[find(index)] = find(owners[key])
            else:
                owners[key] = index
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        components[find(index)].append(index)
    ordered = sorted(components.values(), key=lambda ids: min(rows[i]["id"] for i in ids))
    allocation = list(range(len(ordered)))
    random.Random(seed).shuffle(allocation)  # noqa: S311 -- declared reproducible split
    dev = set(allocation[:round(len(ordered) * dev_fraction)])
    return [{"source_group": f"followir-topic-{index:04d}",
             "split": "dev" if index in dev else "train", "rows": indices,
             "topic_ids": sorted({rows[i]["id"] for i in indices}),
             "label_counts": dict(Counter(rows[i]["label"] for i in indices))}
            for index, indices in enumerate(ordered)]

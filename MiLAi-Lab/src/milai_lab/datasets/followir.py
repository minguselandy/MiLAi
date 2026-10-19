"""Group the public FollowIR training rows before request/document expansion."""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Any


def applicability_row(row: dict[str, Any], index: int,
                      group: dict[str, Any]) -> dict[str, Any]:
    """Preserve the published candidate task, separate from operation supervision.

    The release's label supplies a binary target, not calibrated confidence or
    evidence that a retrieval should stop. Teacher scores stay in the raw source.
    """
    answer = {"true": "satisfies", "false": "does_not_satisfy"}[row["label"]]
    return {
        "state": {
            "task": {"retrieval_request": {
                "query": row["query"], "read_goal": {"purpose": row["instruction"]}}},
            "candidate": {"text": row["document"]},
        },
        "questions": {"applicability": {
            "type": "choice",
            "instructions": "Judge whether the candidate document satisfies the query "
                            "and the stated retrieval requirements.",
            "criteria": {
                "satisfies": "The candidate satisfies the retrieval requirements.",
                "does_not_satisfy": "The candidate does not satisfy the retrieval requirements.",
            },
        }},
        "gold": {"applicability": {"probabilities": {
            option: float(option == answer) for option in ("satisfies", "does_not_satisfy")}}},
        "metadata": {
            "task": "instruction_applicability", "family": group["source_group"],
            "split": group["split"], "row": index,
            "event_id": f"{group['source_group']}/row-{index}", "training_event": index,
            "source": "jhu-clsp/FollowIR-train", "topic_id": row["id"],
            "label_status": "published_candidate_label",
        },
    }


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

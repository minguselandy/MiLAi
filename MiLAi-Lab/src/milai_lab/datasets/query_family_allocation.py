"""Query-linked extensions over a shared corpus, with every prior allocation anchored."""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Any

from milai_lab.datasets.promptriever import base_query_id


def extend_query_families(
    rows: list[dict[str, Any]], prior_groups: list[dict[str, Any]], *, prior_rows: int,
    allocation_id: str, seed: int = 0, dev_fraction: float = .2,
) -> dict[str, Any]:
    """Use query identities, not passage sharing, for new links in this separate protocol.

    Old families remain indivisible even when they were defined by document
    connectivity. The caller verifies literal old payloads before projecting the
    two query fields used here. No passage labels or bodies select a split.
    """
    if (not 0 < dev_fraction < 1 or not 0 < prior_rows <= len(rows)
            or sorted(i for group in prior_groups for i in group["rows"]) != list(range(prior_rows))
            or any(g["split"] not in {"train", "dev", "excluded"} for g in prior_groups)):
        raise ValueError("Query extension requires a complete prior allocation and valid fraction")
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owners: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        query = " ".join(row["only_query"].casefold().split())
        if not query:
            raise ValueError("An empty query is not a query-family identity")
        for key in (("base_query", base_query_id(row)), ("query", query)):
            if key in owners:
                parent[find(index)] = find(owners[key])
            else:
                owners[key] = index
    query_components = len({find(i) for i in range(len(rows))})
    for group in prior_groups:
        first = group["rows"][0]
        for index in group["rows"][1:]:
            parent[find(index)] = find(first)
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        components[find(index)].append(index)
    ordered = sorted(components.values(),
                     key=lambda indices: min(base_query_id(rows[i]) for i in indices))
    prior_by_row = {i: n for n, g in enumerate(prior_groups) for i in g["rows"]}
    groups: list[dict[str, Any]] = []
    unanchored = []
    for number, indices in enumerate(ordered):
        ancestors = [prior_groups[i] for i in sorted({prior_by_row[row] for row in indices
                                                    if row in prior_by_row})]
        splits = {g["split"] for g in ancestors}
        if "excluded" in splits:
            split, basis = "excluded", "prior_exclusion"
        elif len(splits) > 1:
            split, basis = "excluded", "query_bridge_between_prior_splits"
        elif splits:
            split, = splits
            basis = "prior_" + split + "_anchor"
        else:
            split, basis = "unallocated", "new_query_family"
            unanchored.append(number)
        groups.append({"source_group": f"{allocation_id}-family-{number:05d}", "split": split,
            "allocation_basis": basis, "rows": indices,
            "base_query_ids": sorted({base_query_id(rows[i]) for i in indices}),
            "prior_anchor_groups": [{"source_group": a["source_group"], "split": a["split"]}
                                    for a in ancestors],
            "prior_rows": sum(i < prior_rows for i in indices),
            "new_rows": sum(i >= prior_rows for i in indices)})
    shuffled = unanchored.copy()
    random.Random(seed).shuffle(shuffled)  # noqa: S311 -- declared local query allocation
    dev = set(shuffled[:round(len(shuffled) * dev_fraction)])
    for index in unanchored:
        groups[index]["split"] = "dev" if index in dev else "train"
    return {"allocation_id": allocation_id, "mode": "shared_corpus_query_families",
        "seed": seed, "new_query_dev_fraction": dev_fraction, "groups": groups,
        "counts": {"raw_rows": len(rows), "prior_rows": prior_rows,
            "prior_families": len(prior_groups),
            "query_components_before_prior_links": query_components,
            "families_after_prior_links": len(groups), "unanchored_query_families": len(unanchored),
            "base_queries": len({base_query_id(row) for row in rows}),
            "split_families": dict(Counter(g["split"] for g in groups)),
            "allocation_basis": dict(Counter(g["allocation_basis"] for g in groups))},
        "scope": "Shared-corpus query generalization only. Old train/dev/excluded families and "
                 "new versions of their queries retain their constraints. Candidate document "
                 "overlap is reported separately, not used as a new grouping edge. These are "
                 "not independent document/source histories or source-disjoint confirmation."}

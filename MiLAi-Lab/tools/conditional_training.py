"""Keep declared disjoint condition pairs together without dropping ordinary units."""
from __future__ import annotations

import random
from collections import Counter
from typing import Any

from milai_lab.datasets.conditional_reviews import binary_label


def conditional_training_groups(
    rows: list[dict[str, Any]], pairs: list[dict[str, Any]], seed: int,
) -> list[list[int]]:
    """Two-row groups for known pairs, then every remaining unit exactly once.

    This schedule supports disjoint pairs. Shared endpoints require an explicit
    repeated-exposure protocol instead of silently duplicating training rows.
    Labels and grouping metadata never enter model-visible input.
    """
    by_id = {r["metadata"]["event_id"]: i for i, r in enumerate(rows)}
    if len(by_id) != len(rows) or any(
            r["metadata"]["split"] != "train" or not r["gold"] for r in rows):
        raise ValueError("Conditional scheduling requires distinct labelled training units")
    used: set[int] = set()
    groups = []
    for pair in pairs:
        indices = [by_id[pair[side + "_event"]] for side in ("left", "right")]
        left, right = [rows[i] for i in indices]
        labels = [binary_label(r) for r in (left, right)]
        if (None in labels or labels != [pair["left_label"], pair["right_label"]]
                or pair["kind"] != ("change" if labels[0] != labels[1] else "stable")
                or left["state"]["candidate"] != right["state"]["candidate"]
                or left["state"]["task"]["retrieval_request"]["query"]
                != right["state"]["task"]["retrieval_request"]["query"]
                or any(r["metadata"][k] != pair[k] for r in (left, right)
                       for k in ("family", "query_unit"))):
            raise ValueError("Scheduled pairs require matching query, candidate and known labels")
        if len(set(indices)) != 2 or used.intersection(indices):
            raise ValueError("Shared pair endpoints require explicit repeated exposure")
        groups.append(indices)
        used.update(indices)
    remaining = [i for i in range(len(rows)) if i not in used]
    random.Random(seed).shuffle(remaining)  # noqa: S311 -- declared experimental order
    groups.extend(remaining[i:i + 2] for i in range(0, len(remaining), 2))
    return groups


def conditional_change_targets(
    rows: list[dict[str, Any]], pairs: list[dict[str, Any]],
) -> dict[tuple[int, ...], tuple[float, float]]:
    """Map already validated change groups to direction and mean-one family weight.

    Stable pairs keep their ordinary unit labels. Unknown and disputed pairs have
    already been excluded from the declared scheduling file; no labels are inferred.
    """
    changes = [pair for pair in pairs if pair["kind"] == "change"]
    families = Counter(pair["family"] for pair in changes)
    indices = {row["metadata"]["event_id"]: i for i, row in enumerate(rows)}
    return {
        (indices[pair["left_event"]], indices[pair["right_event"]]): (
            1.0 if pair["left_label"] else -1.0,
            len(changes) / (len(families) * families[pair["family"]]),
        ) for pair in changes
    }


def conditional_relative_loss(logits: Any, keys: list[list[str]], direction: float) -> Any:
    """Use the two existing forwards, with option identities after permutation."""
    import torch

    margins = [logits[i, names.index("satisfies")]
               - logits[i, names.index("does_not_satisfy")]
               for i, names in enumerate(keys)]
    return torch.nn.functional.softplus(-direction * (margins[0] - margins[1]))

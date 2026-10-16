"""Matched unary/joint questions and a consistency objective for native Laya heads.

Both trained conditions see identical questions, labels and alias permutations.
The added objective aligns joint-question marginals with the two unary decisions.
It does not add a learned head or introduce any outcome labels into model state.
"""
from __future__ import annotations

import copy
import itertools
import json
import math
import random
from typing import Any

from milai_lab.methods.laya_impact import CRITERIA, impact_payload

ROLES = tuple(CRITERIA)
CODES = dict(zip(ROLES, ("R", "P", "O"), strict=True))
ALIAS_FIELDS = {"id", "unit", "source", "target", "reuse", "target_unit", "source_unit",
                "alternatives", "changed_premises"}


def permute_aliases(row: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    result = copy.deepcopy(row)
    original = list(row["metadata"]["labels"])
    reordered = original.copy()
    rng.shuffle(reordered)
    aliases = dict(zip(original, reordered, strict=True))

    def rewrite(value: Any, field: str = "") -> Any:
        if isinstance(value, dict):
            return {key: rewrite(child, key) for key, child in value.items()}
        if isinstance(value, list):
            return [rewrite(child, field) for child in value]
        if isinstance(value, str) and field in ALIAS_FIELDS:
            return aliases.get(value, value)
        return value

    result["state"] = rewrite(row["state"])
    for record in result["state"]["delivery"]["records"]:
        rng.shuffle(record["clauses"])
    schema = {"properties": {"roots": {"items": {"enum": reordered}}}}
    result["questions"] = impact_payload([
        {"role": "user", "content": json.dumps(result["state"], ensure_ascii=False)}],
        schema)["questions"]
    result["metadata"]["augmentation"] = {"unit_aliases": aliases, "clause_order_shuffled": True}
    return result


def grouped_example(row: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    result = permute_aliases(row, rng)
    available = list(result["expected"])
    if len(available) == 1:
        chosen = available
    else:
        pairs = list(itertools.combinations(available, 2))
        rp = [p for p in pairs if {result["expected"][q] for q in p} == {
            "direct_root", "preserve_successor"}]
        changed = [p for p in pairs if any(result["expected"][q] != "other" for q in p)]
        chosen = list(rng.choice(rp or changed or pairs))
        rng.shuffle(chosen)
    questions = {key: result["questions"][key] for key in chosen}
    expected = {key: result["expected"][key] for key in chosen}
    if len(chosen) == 2:
        aliases = [result["questions"][qid]["instructions"].split(
            "For memory unit ", 1)[1].split(",", 1)[0] for qid in chosen]
        questions["joint_roles"] = {"type": "choice", "instructions": (
            f"What are the CURRENT event roles of {aliases[0]} then {aliases[1]}? "
            "R=directly changed claim/condition; P=specifically preserved downstream claim "
            "through disjoint scope or independent support; O=neither. Topic similarity "
            "alone does not mean change."), "criteria": {
                CODES[a] + "/" + CODES[b]: f"{aliases[0]}: {a}; {aliases[1]}: {b}"
                for a in ROLES for b in ROLES}}
        expected["joint_roles"] = "/".join(CODES[expected[q]] for q in chosen)
    result.update(questions=questions, expected=expected)
    result["metadata"]["sampled_questions"] = chosen
    result["metadata"]["sampling"] = (
        "one pair per event; root/preserve pair first, then any changed pair")
    return result


def epoch_examples(rows: list[dict[str, Any]], seed: int, epoch: int) -> list[dict[str, Any]]:
    rng = random.Random(seed + epoch)  # noqa: S311 -- reproducible training, not cryptography
    ordered = [row for row in rows if row["expected"]]
    rng.shuffle(ordered)
    return [grouped_example(row, rng) for row in ordered]


def marginal_consistency(logits: Any) -> Any:
    """Mean Jensen-Shannon divergence, with stable log-domain marginals."""
    import torch
    import torch.nn.functional as functional

    joint = torch.log_softmax(logits[2, :9], dim=-1).reshape(3, 3)
    marginals = (torch.logsumexp(joint, dim=1), torch.logsumexp(joint, dim=0))
    losses = []
    for index, marginal in enumerate(marginals):
        unary = torch.log_softmax(logits[index, :3], dim=-1)
        mean = torch.logaddexp(unary, marginal) - math.log(2)
        losses.append(0.5 * (functional.kl_div(mean, unary, log_target=True, reduction="sum")
                            + functional.kl_div(mean, marginal, log_target=True, reduction="sum")))
    return torch.stack(losses).mean()

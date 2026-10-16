"""Meaning-preserving augmentation and a nontrivial cross-question objective."""
import copy
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from laya_joint_training import epoch_examples, marginal_consistency, permute_aliases


def sample():
    return {"state": {"observed_date": "2033-04-02", "delivery": {
        "records": [{"id": "r1", "clauses": [
            {"id": "u1", "text": "u1", "conditions": [{"id": "u3", "text": "rule"}]},
            {"id": "u2", "text": "retained B", "conditions": [{"reuse": "u3"}]}],
            "support_groups": [{"target_unit": "u2", "alternatives": [["u1", "u3"]]}]}],
        "evidence": [{"id": "e1", "source": "s1", "text": "u1"}],
        "historical_support": [{"unit": "u1", "ranges": [{"source": "s1"}]}]}},
        "questions": {}, "expected": {"unit_0": "direct_root", "unit_1": "preserve_successor"},
        "metadata": {"event_id": "event", "family_id": "one-history", "split": "train",
                     "labels": {"u1": {}, "u2": {}, "u3": {"label": None}},
                     "private_review": "EVALUATOR_ONLY"}}


def test_alias_permutation_preserves_raw_text_relations_and_original_input():
    row = sample()
    original = copy.deepcopy(row)
    result = permute_aliases(row, random.Random(4))  # noqa: S311 -- deterministic test
    aliases = result["metadata"]["augmentation"]["unit_aliases"]
    record = result["state"]["delivery"]["records"][0]
    source_clause = next(c for c in record["clauses"] if c["id"] == aliases["u1"])
    assert source_clause["text"] == "u1"  # Literal source/claim text is not an alias field.
    assert result["state"]["delivery"]["evidence"][0]["text"] == "u1"
    assert record["support_groups"][0] == {"target_unit": aliases["u2"],
        "alternatives": [[aliases["u1"], aliases["u3"]]]}
    assert aliases["u1"] in result["questions"]["unit_0"]["instructions"]
    assert "EVALUATOR_ONLY" not in json.dumps(result["state"])
    assert row == original


def test_same_epoch_groups_for_both_objectives_and_masked_unit_not_supervised():
    first = epoch_examples([sample()], 0, 0)
    second = epoch_examples([sample()], 0, 0)
    assert first == second
    row = first[0]
    assert len(row["questions"]) == 3
    assert "unit_2" not in row["expected"]
    assert row["expected"]["joint_roles"] in {"R/P", "P/R"}
    assert len(row["questions"]["joint_roles"]["criteria"]) == 9
    assert row["metadata"]["family_id"] == "one-history"


def test_consistency_zero_at_matching_marginals_and_gradients_reach_both_views():
    torch = pytest.importorskip("torch")
    p, q = torch.tensor([0.7, 0.2, 0.1]), torch.tensor([0.1, 0.3, 0.6])
    logits = torch.zeros(3, 9)
    logits[0, :3], logits[1, :3] = p.log(), q.log()
    logits[2] = torch.outer(p, q).reshape(-1).log()
    assert abs(marginal_consistency(logits).item()) < 1e-7
    logits[2] = 0
    logits.requires_grad_(True)
    loss = marginal_consistency(logits)
    assert loss.item() > 0.01
    loss.backward()
    assert all(logits.grad[i].abs().sum() > 0 for i in range(3))
    # Unary padding columns do not participate in the objective.
    assert logits.grad[:2, 3:].abs().sum() == 0

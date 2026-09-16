"""Only top-level anyOf permutation is covered; never rewrite the actual request."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from v0221_http_admission_v2 import same_branches


def schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "anyOf": [
            {"type": "object", "properties": {"a": {"enum": ["x", "y"]}}, "required": ["a"]},
            {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        ],
    }


def test_top_level_permutation_keeps_exact_branch_contents_and_original_bytes():
    a = schema()
    b = copy.deepcopy(a)
    b["anyOf"].reverse()
    before_a, before_b = copy.deepcopy(a), copy.deepcopy(b)
    assert same_branches(a, b)
    assert a == before_a and b == before_b


@pytest.mark.parametrize("mutation", ["duplicate", "drop", "enum", "unique", "required", "root"])
def test_not_a_general_schema_equivalence_or_relaxation(mutation):
    a = schema()
    b = copy.deepcopy(a)
    if mutation == "duplicate":
        b["anyOf"].append(copy.deepcopy(b["anyOf"][0]))
    elif mutation == "drop":
        b["anyOf"].pop()
    elif mutation == "enum":
        b["anyOf"][0]["properties"]["a"]["enum"].reverse()
    elif mutation == "unique":
        b["anyOf"][1].pop("uniqueItems")
    elif mutation == "required":
        b["anyOf"][0]["required"] = []
    else:
        b["description"] = "new instruction"
    assert not same_branches(a, b)

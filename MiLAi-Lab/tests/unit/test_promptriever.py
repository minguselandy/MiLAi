"""Candidate sampling must not hide source connections or introduce teacher inputs."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

from milai_lab.datasets.promptriever import candidate_rows, group_promptriever, source_keys
from milai_lab.harness.artifact_io import read_jsonl


def source(index):
    return {"query_id": str(index), "only_query": f"query {index}", "query": "unused combined",
            "only_instruction": "", "has_instruction": False, "new_negatives": [],
            "positive_passages": [{"docid": f"p{index}", "text": f"positive {index}",
                                   "explanation": "TEACHER SECRET", "followir_score": 99}],
            "negative_passages": [{"docid": f"n{index}", "text": f"negative {index}"}]}


def test_full_candidate_graph_precedes_negative_caps_and_preserves_transitive_components():
    rows = [source(i) for i in range(8)]
    rows[1]["query_id"] = "0-instruct"
    rows[1]["has_instruction"] = True
    rows[1]["only_instruction"] = "historical facts"
    rows[2]["negative_passages"].append(copy.deepcopy(rows[1]["positive_passages"][0]))
    rows[3]["positive_passages"][0]["docid"] = "p2"
    rows[4]["positive_passages"][0]["text"] = rows[3]["positive_passages"][0]["text"]
    rows[5]["only_query"] = " QUERY   4 "
    original = copy.deepcopy(rows)
    groups = group_promptriever(rows, seed=0)
    assert rows == original
    assert sorted(g["rows"] for g in groups) == [list(range(6)), [6], [7]]
    keys = {split: {key for g in groups if g["split"] == split
                   for i in g["rows"] for key in source_keys(rows[i])}
            for split in ("train", "dev")}
    assert not keys["train"] & keys["dev"]
    g = next(g for g in groups if 2 in g["rows"])
    exported = candidate_rows(rows[2], 2, g, ordinary_negatives=1)
    assert {r["metadata"]["native_docid"] for r in exported} == {"p2", "n2"}


def test_real_cli_roundtrip_retains_unicode_content_and_uses_only_published_membership(tmp_path):
    rows = [source(i) for i in range(10)]
    rows[0]["positive_passages"][0]["text"] = "one\u0085two\u2028three\u2029four"
    raw = tmp_path / "raw.jsonl"
    raw.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    assert read_jsonl(raw) == rows
    root = Path(__file__).resolve().parents[2]
    prepared, mixture = tmp_path / "prepared", tmp_path / "mixture"
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    subprocess.run(  # noqa: S603 -- fixed repository CLI with test-owned paths
                   [sys.executable, str(root / "tools/prepare_promptriever_applicability.py"),
                    str(raw), str(prepared)], env=env, check=True, capture_output=True)
    recipe = tmp_path / "recipe.json"
    recipe.write_text(json.dumps({"components": [{"name": "aux",
        "task": "instruction_applicability",
        "loss_weight": 1, "files": [str(prepared / f"{s}.jsonl") for s in ("train", "dev")]}],
        "scope": "test intake"}))
    subprocess.run(  # noqa: S603 -- fixed repository CLI with test-owned paths
                   [sys.executable, str(root / "tools/prepare_retrieval_mixture.py"),
                    str(recipe), str(mixture)], env=env, check=True, capture_output=True)
    exported = []
    for split in ("train", "dev"):
        before = read_jsonl(prepared / f"{split}.jsonl")
        after = read_jsonl(mixture / f"{split}.jsonl")
        for left, right in zip(before, after, strict=True):
            assert all(left[k] == right[k] for k in ("state", "questions", "gold"))
            model_input = json.dumps(right["state"])
            assert "TEACHER SECRET" not in model_input and "followir_score" not in model_input
            assert set(right["questions"]) == {"applicability"}
        exported.extend(after)
    assert len(exported) == 20
    positive = next(r for r in exported if r["metadata"]["native_docid"] == "p0")
    assert positive["state"]["candidate"]["text"] == rows[0]["positive_passages"][0]["text"]
    assert positive["gold"]["applicability"]["probabilities"]["satisfies"] == 1

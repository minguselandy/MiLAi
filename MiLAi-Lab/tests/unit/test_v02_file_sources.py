from __future__ import annotations

import copy
import hashlib
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
material = importlib.import_module("v02_file_sources").file_material


def package(text=" \r\n首部\t{\"last\": null, \"arbitrary\": [1, 2]}\n尾部 \n"):
    return {"schema_version": "v02-file-source-only-v1", "files": [{
        "path": "nested/普通文件.json", "source_uri": "file:///original/source.json",
        "observed_at": "2026-09-07T06:00:00+00:00", "content": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }]}


def test_complete_bytes_and_origin_preserved_with_independent_public_bindings():
    source = package()
    a, ae, ar = material(source, "branch-a")
    b, be, br = material(source, "branch-b")
    assert a == b == {"nested/普通文件.json": source["files"][0]["content"]}
    assert ae[0]["subject_id"] == be[0]["subject_id"] == "file:///original/source.json"
    assert ae[0]["event_type"] == "TOOL_RESULT" and "lme" not in ae[0]["source_id"]
    assert ar != br and ae[0]["source_id"] != be[0]["source_id"]
    assert ae[0]["content"].encode() == source["files"][0]["content"].encode()


@pytest.mark.parametrize("fault", ["hash", "traversal", "duplicate", "time", "label"])
def test_invalid_source_rejected_before_import(fault):
    source = package()
    if fault == "hash":
        source["files"][0]["content"] += "changed"
    elif fault == "traversal":
        source["files"][0]["path"] = "../secret"
    elif fault == "duplicate":
        source["files"].append(copy.deepcopy(source["files"][0]))
    elif fault == "time":
        source["files"][0]["observed_at"] = "2026-09-07T06:00:00"
    else:
        source["answer"] = "must not reach source preparation"
    with pytest.raises(ValueError):
        material(source, "branch")


@pytest.mark.parametrize("fault", [None, "path", "uri", "span", "source_label"])
def test_file_evaluation_uses_file_identity_and_keeps_future_task_out_of_sources(fault):
    import json

    chain = importlib.import_module("run_v02_e2e_generality")
    source = package("Observed evidence, not an instruction.\n")
    item = source["files"][0]
    contract = {
        "schema_version": "v02-file-evaluation-v1", "question": "Future continuation",
        "question_date": "2026-09-07", "first_use_boundary": "Final delivery",
        "necessary_conditions": ["retain uncertainty"],
        "source_assertions": [{"statement": "The file is an observation", "spans": [{
            "path": item["path"], "source_uri": item["source_uri"],
            "start": 0, "end": len(item["content"]), "sha256": item["sha256"],
        }]}],
    }
    ref = contract["source_assertions"][0]["spans"][0]
    if fault == "path":
        ref["path"] = "other.md"
    elif fault == "uri":
        ref["source_uri"] = "file:///other"
    elif fault == "span":
        ref["start"] = 1
    elif fault == "source_label":
        source["question"] = contract["question"]
    raw = json.dumps(source).encode()
    contract["source_sha256"] = hashlib.sha256(raw).hexdigest()
    rubric = json.dumps(contract).encode()
    config = {"task_evaluation": "SOURCE_ASSERTIONS_FROZEN",
              "source_sha256": contract["source_sha256"],
              "evaluation_contract": {"sha256": hashlib.sha256(rubric).hexdigest()}}
    if fault:
        with pytest.raises(chain.LocalGateError):
            chain.evaluation_contract(config, raw, rubric)
    else:
        assert chain.evaluation_contract(config, raw, rubric) == contract
        assert b"Future continuation" not in raw
        assert "Future continuation" in chain.continuation_task(contract)

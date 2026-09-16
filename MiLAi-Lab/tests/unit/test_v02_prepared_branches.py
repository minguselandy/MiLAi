from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
runner = importlib.import_module("run_v02_local_vllm")


@pytest.fixture
def snapshot(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"source_mode": "PUBLIC_SOURCE_SNAPSHOT"}))
    branches = {
        arm: {
            "project": "project-" + arm,
            "task_ref": "task-" + arm,
            "file_evidence_refs": {"source": [arm + "-ref"]},
            "reference_mapping_from_g": {"G-ref": arm + "-ref"},
        }
        for arm in ("G", "A", "B")
    }
    value = {
        "status": "PUBLIC_SOURCES_VERIFIED",
        "source_files": {"source": "source-hash"},
        "branches": branches,
    }
    (tmp_path / "prepared-bindings.json").write_text(json.dumps(value))
    (tmp_path / "G").mkdir()
    (tmp_path / "G/file-evidence-refs.json").write_text(
        json.dumps({"source": ["G-ref"], "handoff": ["G-ref"]})
    )
    return tmp_path, value


def test_g_and_branches_keep_sources_and_remap_declared_state_only(snapshot):
    root, _ = snapshot
    g, _ = runner.branch_assignment(root, "G", "G normal task", {"source": "source-hash"}, None)
    original = {
        "text": "G-ref as literal text",
        "nested": {"evidence_id": "G-ref"},
        "evidence_refs": ["G-ref"],
        "unrelated": [False, 0, None],
    }
    for arm in ("A", "B"):
        binding, payload = runner.branch_assignment(
            root,
            arm,
            "continuation",
            {"source": "source-hash", "handoff": "actual-G-output"},
            copy.deepcopy(original),
        )
        assert binding["project"] != g["project"]
        assert binding["file_evidence_refs"]["handoff"] == [arm + "-ref"]
        assert payload["nested"]["evidence_id"] == arm + "-ref"
        assert payload["text"] == original["text"] and payload["unrelated"] == original["unrelated"]


@pytest.mark.parametrize("mode", ["drift", "extra_file", "shared_project", "unverified"])
def test_bad_source_binding_is_rejected(snapshot, mode):
    root, value = snapshot
    initial = {"source": "source-hash"}
    if mode == "drift":
        initial["source"] = "changed"
    elif mode == "extra_file":
        initial["future-answer"] = "not-G-input"
    elif mode == "shared_project":
        value["branches"]["A"]["project"] = "project-G"
    else:
        value["status"] = "UNKNOWN"
    (root / "prepared-bindings.json").write_text(json.dumps(value))
    with pytest.raises(runner.LocalGateError):
        runner.branch_assignment(root, "G", "task", initial, None)


@pytest.mark.parametrize("mode", ["state", "file", "unreferenced_capture"])
def test_new_unmapped_g_evidence_is_not_silently_dropped(snapshot, mode):
    root, _ = snapshot
    payload = {"evidence_refs": ["G-ref"]}
    if mode == "state":
        payload["evidence_refs"].append("new-G-ref")
    elif mode == "file":
        (root / "G/file-evidence-refs.json").write_text(
            json.dumps({"source": ["G-ref"], "handoff": ["new-G-ref"]})
        )
    else:
        event = {
            "action": {
                "tool": "mcp_call",
                "arguments_json": json.dumps({"name": "milai_evidence_capture"}),
            },
            "acquired": {"evidence_id": "new-G-ref"},
        }
        (root / "G/tool-events.jsonl").write_text(json.dumps(event) + "\n")
    with pytest.raises(runner.LocalGateError, match="UNMAPPED_G_EVIDENCE"):
        runner.branch_assignment(
            root, "A", "task", {"source": "source-hash", "handoff": "hash"}, payload
        )

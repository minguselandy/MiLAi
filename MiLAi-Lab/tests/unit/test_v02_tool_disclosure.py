from __future__ import annotations

import copy
import importlib
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
runner = importlib.import_module("run_v02_local_vllm")
state = importlib.import_module("v02_e2e_state")
deadline = importlib.import_module("v02_deadline")


@pytest.mark.parametrize("tool,response,refs", [
    ("milai_memory_get", {"schema_version": "memory-state-view-v0.1",
                          "evidence_refs": ["support"]}, ["support"]),
    ("milai_evidence_capture", {"evidence_id": "captured"}, ["captured"]),
    ("milai_proposal_get", {"supporting_evidence_refs": ["support"],
                            "contradicting_evidence_refs": ["counter"]}, ["counter", "support"]),
    ("milai_proposals_list", {"proposals": [
        {"supporting_evidence_refs": ["support"]},
        {"contradicting_evidence_refs": ["counter"]},
    ]}, ["counter", "support"]),
    ("milai_proposal_get", {"patch": {"evidence_id": "quoted"},
                            "description": "supporting_evidence_refs: [quoted]"}, []),
    ("milai_proposal_get", {"mcp_error": True, "supporting_evidence_refs": ["quoted"]}, []),
    ("milai_deletion_status_get", {"evidence_id": "status-only"}, []),
])
def test_published_tool_provenance_is_rechecked_and_inherited(tool, response, refs):
    revoked = False

    def metadata(ref):
        return {"evidence_id": ref, "retention_state": "READABLE",
                "revoked_at": "now" if revoked else None,
                "permission_snapshot": {"readable": True, "project_ids": ["project"]}}

    guard = state.FileDisclosure("project", {}, metadata)
    guard.acquired(response, tool_name=tool)
    guard.created("derived.md")
    assert guard.file_refs["derived.md"] == refs
    guard.before_request()
    revoked = True
    if refs:
        with pytest.raises(state.LocalGateError, match="FILE_DISCLOSURE_DENIED"):
            guard.before_request()
        with pytest.raises(state.LocalGateError, match="FILE_DISCLOSURE_DENIED"):
            guard.read("derived.md")
    else:
        guard.before_request()


@pytest.mark.parametrize("change", ["unchanged", "revoked", "scope", "metadata_failure"])
@pytest.mark.parametrize("mode", ["JSON_STRING", "ARGUMENT_OBJECT"])
def test_exact_claim_source_rechecked_before_next_host_request(tmp_path, monkeypatch, change, mode):
    config = json.loads(runner.CONFIG.read_text())
    # Isolated provider double only; no service or model endpoint is constructed.
    config.update(model_transport_enabled=True, new_model_allocations_authorized=1,
                  new_model_tokens_authorized=20000, host_budget_observation=True,
                  host_action_format=mode)
    (tmp_path / "config.json").write_text(json.dumps(config))
    directory = tmp_path / "B"
    (directory / "workspace").mkdir(parents=True)
    (directory / "assignment.json").write_text(json.dumps({
        "project": "project", "task_ref": "task", "task": "Continue", "file_evidence_refs": {},
    }))
    (directory / "initial-files.json").write_text("{}")
    head = {"schema_version": "host-cognitive-state-v1", "authority": "HOST_WORKING",
            "scope": "TASK", "status": "ABSENT", "version": 0, "payload": {}, "warnings": []}
    view = {"schema_version": "memory-state-view-v0.1", "status": "HIT",
            "evidence_refs": ["source"], "items": [{"kind": "MEMORY_STATE_VIEW",
                "claim_id": "claim", "evidence_ids": ["source"],
                "payload": {"text": "EXACT_CLAIM_CANARY"}}]}
    bodies, metadata_checks = [], []

    class Provider:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self):
            return {"kind": "NETWORK_FREE_TEST_DOUBLE"}

        def complete(self, messages, schema, output):
            bodies.append(copy.deepcopy(messages))
            args = {"name": "milai_memory_get", "arguments": {"claim_id": "claim"}}
            key, value = (("arguments", args) if mode == "ARGUMENT_OBJECT"
                          else ("arguments_json", json.dumps(args)))
            return json.dumps({
                "tool": "mcp_call" if len(bodies) == 1 else "finish",
                key: value,
                "answer": "fixture",
            })

        def close(self):
            pass

    @contextmanager
    def observer(*args):
        def call(tool, arguments):
            if tool is None:
                return {"tools": {"tools": [{"name": "milai_memory_get", "description": "Read"}]}}
            return view if tool == "milai_memory_get" else head
        yield call, {}

    def metadata(ref):
        metadata_checks.append(ref)
        subsequent = len(metadata_checks) > 1
        if subsequent and change == "metadata_failure":
            raise OSError("metadata unavailable")
        return {"evidence_id": ref, "retention_state": "READABLE",
                "revoked_at": "now" if subsequent and change == "revoked" else None,
                "permission_snapshot": {"readable": True, "project_ids": [
                    "another-project" if subsequent and change == "scope" else "project",
                ]}}

    class Guard(state.FileDisclosure):
        def __init__(self, project, refs, ignored_metadata, context_refs):
            super().__init__(project, refs, metadata, context_refs)

    monkeypatch.setattr(runner, "LocalProvider", Provider)
    monkeypatch.setattr(runner, "observer", observer)
    monkeypatch.setattr(runner, "FileDisclosure", Guard)
    runner._session(tmp_path, "B", deadline.Deadline(time.monotonic(), 30))
    result = json.loads((directory / "result.json").read_text())
    assert metadata_checks == ["source", "source"]
    assert all("HOST_BUDGET_OBSERVATION" in body[-1]["content"] for body in bodies)
    assert all(sum("HOST_BUDGET_OBSERVATION" in m["content"] for m in body) == 1
               for body in bodies)
    if change == "unchanged":
        assert result["status"] == "COMPLETED"
        assert len(bodies) == 2
        assert "EXACT_CLAIM_CANARY" in json.dumps(bodies[1])
    else:
        assert result["status"] == "FAILED"
        assert result["error"] == (
            "FILE_DISCLOSURE_UNKNOWN" if change == "metadata_failure" else "FILE_DISCLOSURE_DENIED"
        )
        assert len(bodies) == 1
        assert "EXACT_CLAIM_CANARY" not in json.dumps(bodies)

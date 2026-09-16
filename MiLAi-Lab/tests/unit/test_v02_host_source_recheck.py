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


@pytest.mark.parametrize("arm", ["A", "B"])
@pytest.mark.parametrize("outcome", [
    "allowed", "revoked", "revoked_before_send", "unknown", "tool_error",
])
def test_actual_host_rechecks_exact_task_once_before_first_request(
    tmp_path, monkeypatch, arm, outcome,
):
    config = json.loads(runner.CONFIG.read_text())
    config.update(model_transport_enabled=True, new_model_allocations_authorized=1,
                  new_model_tokens_authorized=20000, host_source_recheck="CURRENT_TASK_ONCE")
    runner.write_json(tmp_path / "config.json", config)
    directory = tmp_path / arm
    (directory / "workspace").mkdir(parents=True)
    task = "Continue the current task.\nPreserve its supplied time and scope."
    runner.write_json(directory / "assignment.json", {
        "project": "p", "task_ref": "t", "task": task, "file_evidence_refs": {}})
    runner.write_json(directory / "initial-files.json", {})
    head = {"schema_version": "host-cognitive-state-v1", "authority": "HOST_WORKING",
            "scope": "TASK", "status": "ABSENT", "version": 0, "payload": {}, "warnings": []}
    source = {"schema_version": "memory-evidence-context-v1", "retrieval_status": "DEGRADED",
              "warnings": [{"code": "RETRIEVAL_DEGRADED"}], "evidence": [
                  {"text": "PRIVATE_SOURCE_CANARY_697e", "evidence_ids": ["source"]}]}
    if outcome == "tool_error":
        source = {"mcp_error": True, "content": [{"type": "text", "text": "Unavailable"}]}
    requests, calls, checks = [], [], []

    class Provider:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self):
            return {"kind": "NETWORK_FREE_TEST_DOUBLE"}

        def complete(self, messages, schema, output):
            requests.append(copy.deepcopy(messages))
            return json.dumps({"tool": "finish", "arguments_json": "{}", "answer": "fixture"})

        def close(self):
            pass

    @contextmanager
    def observer(*args):
        def call(tool, arguments):
            calls.append((tool, arguments))
            if tool is None:
                return {"tools": {"tools": []}}
            return source if tool == "milai_memory_resolve" else head
        yield call, {}

    def metadata(ref):
        checks.append(ref)
        if outcome == "unknown":
            raise OSError("metadata unavailable")
        return {"evidence_id": ref, "retention_state": "READABLE",
                "revoked_at": "now" if outcome == "revoked" or (
                    outcome == "revoked_before_send" and len(checks) > 1) else None,
                "permission_snapshot": {"readable": True, "project_ids": ["p"]}}

    class Guard(state.FileDisclosure):
        def __init__(self, project, refs, ignored_metadata, context_refs):
            super().__init__(project, refs, metadata, context_refs)

    monkeypatch.setattr(runner, "LocalProvider", Provider)
    monkeypatch.setattr(runner, "observer", observer)
    monkeypatch.setattr(runner, "FileDisclosure", Guard)
    runner._session(tmp_path, arm, deadline.Deadline(time.monotonic(), 30))
    assert [(t, a) for t, a in calls if t == "milai_memory_resolve"] == [
        ("milai_memory_resolve", {"query": task})]
    record = runner.read_json(directory / "host-source-recheck.json")
    assert record["response"] == source and record["query"] == task
    if outcome in {"revoked", "revoked_before_send", "unknown"}:
        assert requests == []
        assert runner.read_json(directory / "result.json")["status"] == "FAILED"
    else:
        assert len(requests) == 1
        shown = requests[0][-1]["content"]
        assert shown.startswith("HOST_SOURCE_RECHECK_RESULT")
        assert json.loads(shown.split("\n", 1)[1]) == source
        assert checks == (["source", "source"] if outcome == "allowed" else [])


def test_recheck_never_queries_for_generator_or_off_mode(tmp_path):
    def forbidden(*args):
        raise AssertionError("unexpected public lookup")
    for config, arm in [({}, "A"), ({"host_source_recheck": "CURRENT_TASK_ONCE"}, "G")]:
        assert runner.source_recheck(config, arm, "task", forbidden, None, tmp_path) is None
    with pytest.raises(state.LocalGateError, match="UNKNOWN_SOURCE_RECHECK_MODE"):
        runner.source_recheck({"host_source_recheck": "unknown"}, "A", "task", forbidden,
                              None, tmp_path)

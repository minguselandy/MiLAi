from __future__ import annotations

import hashlib
import importlib
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
host = importlib.import_module("run_v02_local_vllm")
state = importlib.import_module("v02_e2e_state")


def setup_files(root):
    texts = {"first.md": 'FIRST\n"quoted"\n' + "资料\n" * 1200 + "LAST\n",
             "second.json": '{"first":null,"nested":["正文",{},false],"last":"END"}'}
    for name, text in texts.items():
        (root / name).write_bytes(text.encode())
    (root / "details.md").write_text("L2_SHOULD_NOT_BE_PRELOADED")
    versions = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in texts.items()}
    revoked = set()

    def metadata(ref):
        return {"evidence_id": ref, "retention_state": "READABLE",
                "revoked_at": "now" if ref in revoked else None,
                "permission_snapshot": {"project_ids": ["p"], "readable": True}}

    guard = state.FileDisclosure("p", {name: [name] for name in texts}, metadata)
    return texts, versions, guard, revoked


@pytest.mark.parametrize("arm", ["A", "B"])
def test_full_original_bytes_only_and_revocation_before_later_request(tmp_path, arm):
    texts, versions, guard, revoked = setup_files(tmp_path)
    result = host.source_file_backcheck({"host_file_backcheck": "ALL_IF_WITHIN_BOUND"},
                                      arm, tmp_path, versions, guard)
    assert result["status"] == "COMPLETE_DECLARED_FILE_SNAPSHOT"
    assert {f["path"]: f["text"] for f in result["files"]} == texts
    assert "L2_SHOULD_NOT_BE_PRELOADED" not in json.dumps(result)
    assert guard.context_refs == set(texts)
    revoked.add("second.json")
    with pytest.raises(state.LocalGateError, match="DISCLOSURE_DENIED"):
        guard.before_request()


@pytest.mark.parametrize("reason", ["count", "bytes", "encoding"])
def test_bounds_do_not_present_partial_bundle_or_add_dependencies(tmp_path, reason):
    _texts, versions, guard, _ = setup_files(tmp_path)
    config = {"host_file_backcheck": "ALL_IF_WITHIN_BOUND"}
    if reason == "count":
        config["backcheck_max_files"] = 1
    elif reason == "bytes":
        config["backcheck_max_output_bytes"] = 2048
    else:
        # Raw bytes fit, but JSON escapes make the actual presented object exceed the bound.
        (tmp_path / "first.md").write_text('"' * 1500)
        versions["first.md"] = hashlib.sha256(('"' * 1500).encode()).hexdigest()
        config["backcheck_max_output_bytes"] = 2048
    result = host.source_file_backcheck(config, "B", tmp_path, versions, guard)
    assert result["status"].startswith("SKIPPED_") and result["files"] == []
    assert not guard.context_refs


@pytest.mark.parametrize("reason", ["revoked", "unknown", "changed", "symlink", "growth"])
def test_unavailable_original_sources_do_not_disclose_body(tmp_path, monkeypatch, reason):
    texts, versions, guard, revoked = setup_files(tmp_path)
    if reason == "revoked":
        revoked.add("second.json")
    elif reason == "unknown":
        guard.metadata = lambda ref: {}
    elif reason == "changed":
        (tmp_path / "second.json").write_text("CHANGED_PRIVATE_BODY")
    elif reason == "symlink":
        (tmp_path / "second.json").unlink()
        (tmp_path / "second.json").symlink_to(tmp_path / "details.md")
    else:
        original = host.read_page

        def grow(*args, **kwargs):
            (tmp_path / "first.md").write_text("x" * 65537)
            return original(*args, **kwargs)

        monkeypatch.setattr(host, "read_page", grow)
    result = host.source_file_backcheck({"host_file_backcheck": "ALL_IF_WITHIN_BOUND"},
                                      "B", tmp_path, versions, guard)
    assert result == {"mode": "ALL_IF_WITHIN_BOUND", "status": "UNAVAILABLE", "files": []}
    assert all(text not in json.dumps(result) for text in texts.values())


def test_revocation_during_final_check_keeps_existing_context_dependencies(tmp_path):
    _, versions, guard, _ = setup_files(tmp_path)
    metadata = guard.metadata
    calls = {}
    guard.context_refs.add("previously_presented")

    def revoke_after_acquisition(ref):
        calls[ref] = calls.get(ref, 0) + 1
        record = metadata(ref)
        if ref == "second.json" and calls[ref] == 2:
            record["revoked_at"] = "now"
        return record

    guard.metadata = revoke_after_acquisition
    result = host.source_file_backcheck({"host_file_backcheck": "ALL_IF_WITHIN_BOUND"},
                                      "B", tmp_path, versions, guard)
    assert result == {"mode": "ALL_IF_WITHIN_BOUND", "status": "UNAVAILABLE", "files": []}
    assert calls == {"first.md": 2, "second.json": 2}
    assert guard.context_refs == {"previously_presented"}


def test_off_generator_and_invalid_limits(tmp_path):
    assert host.source_file_backcheck({}, "B", tmp_path, {}, None) is None
    assert host.source_file_backcheck({"host_file_backcheck": "ALL_IF_WITHIN_BOUND"},
                                     "G", tmp_path, {}, None) is None
    for extra in [{"backcheck_max_files": True}, {"backcheck_max_output_bytes": 200000},
                  {"backcheck_max_output_bytes": "32768"}]:
        with pytest.raises(state.LocalGateError, match="INVALID_FILE_BACKCHECK_BOUNDS"):
            host.source_file_backcheck({"host_file_backcheck": "ALL_IF_WITHIN_BOUND", **extra},
                                      "B", tmp_path, {}, None)


@pytest.mark.parametrize("arm", ["A", "B"])
@pytest.mark.parametrize("revoke", ["never", "before_first_send", "before_second_send"])
def test_actual_host_presents_original_source_and_rechecks_before_every_send(
    tmp_path, monkeypatch, arm, revoke,
):
    config = json.loads(host.CONFIG.read_text())
    config.update(model_transport_enabled=True, new_model_allocations_authorized=1,
                  new_model_tokens_authorized=20000, source_mode="PUBLIC_SOURCE_SNAPSHOT",
                  host_file_backcheck="ALL_IF_WITHIN_BOUND")
    host.write_json(tmp_path / "config.json", config)
    directory = tmp_path / arm
    workspace = directory / "workspace"
    workspace.mkdir(parents=True)
    original = "FIRST_ORIGINAL\n来源正文\nLAST_ORIGINAL"
    (workspace / "original.md").write_text(original)
    (workspace / config["l2_path"]).write_text("DETAIL_MEMORY_CANARY")
    versions = host.manifest(workspace)
    host.write_json(tmp_path / "prepared-bindings.json", {
        "source_files": {"original.md": versions["original.md"]}})
    host.write_json(directory / "initial-files.json", versions)
    host.write_json(directory / "assignment.json", {
        "project": "p", "task_ref": "t", "task": "Continue the task.",
        "file_evidence_refs": {"original.md": ["source"], config["l2_path"]: []}})
    head = {"status": "ACTIVE", "version": 1, "authority": "HOST_WORKING", "warnings": [],
            "scope": "TASK", "schema_version": "host-cognitive-state-v1",
            "state_id": "fixture-state", "state_version_id": "fixture-version",
            "payload": {config.get("state_field", host.FIELD): {
                "owner": config["experiment_id"], "l1": "Short state",
                "l2": {"path": config["l2_path"], "sha256": versions[config["l2_path"]]}}}}
    revoked = False
    requests = []

    class Provider:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self):
            return {"fixture": True}

        def complete(self, messages, schema, output):
            nonlocal revoked
            requests.append(json.loads(json.dumps(messages)))
            if revoke == "before_second_send":
                revoked = True
                return json.dumps({"tool": "list_files", "arguments_json": "{}", "answer": ""})
            return json.dumps({"tool": "finish", "arguments_json": "{}", "answer": "fixture"})

        def close(self):
            pass

    @contextmanager
    def observer(*args):
        yield (lambda tool, args: {"tools": {"tools": []}} if tool is None else head), {}

    def metadata(ref):
        return {"evidence_id": ref, "retention_state": "READABLE",
                "revoked_at": "now" if revoked else None,
                "permission_snapshot": {"project_ids": ["p"], "readable": True}}

    class Guard(state.FileDisclosure):
        def __init__(self, project, refs, unused_metadata, context_refs):
            super().__init__(project, refs, metadata, context_refs)

    original_backcheck = host.source_file_backcheck

    def backcheck(*args):
        nonlocal revoked
        result = original_backcheck(*args)
        if revoke == "before_first_send":
            revoked = True
        return result

    monkeypatch.setattr(host, "LocalProvider", Provider)
    monkeypatch.setattr(host, "observer", observer)
    monkeypatch.setattr(host, "FileDisclosure", Guard)
    monkeypatch.setattr(host, "source_file_backcheck", backcheck)
    host._session(tmp_path, arm, host.Deadline(time.monotonic(), 30))
    assert len(requests) == (0 if revoke == "before_first_send" else 1)
    if requests:
        data = next(m["content"] for m in requests[0] if m["content"].startswith(
            "HOST_FILE_BACKCHECK_RESULT"))
        shown = json.loads(data.split("\n", 1)[1])
        assert shown["files"][0]["text"] == original
        assert "DETAIL_MEMORY_CANARY" not in data
        assert ("DETAIL_MEMORY_CANARY" in json.dumps(requests[0])) == (arm == "A")
    assert host.read_json(directory / "result.json")["status"] == (
        "COMPLETED" if revoke == "never" else "FAILED")
    if revoke != "never":
        assert host.read_json(directory / "result.json")["error"] == "FILE_DISCLOSURE_DENIED"

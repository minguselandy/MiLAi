from __future__ import annotations

import copy
import hashlib
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
phase = importlib.import_module("v02_post_g_sources")
host = importlib.import_module("run_v02_local_vllm")
chain = importlib.import_module("run_v02_e2e_generality")


def observation(path, text):
    return {"path": path, "source_uri": "file:///observed/" + path,
            "content": text, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "observed_at": "2026-09-07T10:00:00+00:00"}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    initial = {"schema_version": "v02-file-source-only-v1", "files": [
        observation("sources/original.md", " 首部\r\n原任务条件\n尾部 \n")]}
    continuation = copy.deepcopy(initial)
    continuation["files"].append(observation("sources/new.md", "新决定\r\n完整尾部\n"))
    host.write_json(tmp_path / "input-source.json", initial)
    host.write_json(tmp_path / "continuation-source.json", continuation)
    config = {"source_mode": "PUBLIC_SOURCE_SNAPSHOT", "generator_task": "Original task",
              "source_sha256": phase.sha(tmp_path / "input-source.json"),
              "post_g_source": {"path": "future.json",
                                "sha256": phase.sha(tmp_path / "continuation-source.json")}}
    host.write_json(tmp_path / "config.json", config)
    files = phase.file_material(initial, "G")[0]
    workspace = tmp_path / "G/workspace"
    (workspace / "sources").mkdir(parents=True)
    for name, text in files.items():
        (workspace / name).write_bytes(text.encode())
    (workspace / "handoff.md").write_bytes(b"Old understanding, no new decision.\n")
    frozen = host.manifest(workspace)
    host.write_json(tmp_path / "frozen-g-files.json", frozen)
    host.write_json(tmp_path / "G/file-evidence-refs.json", {name: ["g-ref"] for name in frozen})
    host.write_json(tmp_path / "G/result.json", {"status": "COMPLETED"})
    host.write_json(tmp_path / "G/worker-exit.json", {"returncode": 0})
    host.append_event(tmp_path / "allocations.jsonl", {
        "session": "G", "event": "TERMINAL", "status": "COMPLETED"})
    payload = {"text": "Old understanding", "evidence_refs": ["g-ref"]}
    host.write_json(tmp_path / "checkpoint-result.json", {
        "status": "SAVED_CONFIRMED", "payload": payload})
    snapshot = {"status": "PUBLIC_SOURCES_VERIFIED",
                "source_files": {name: frozen[name] for name in files}, "branches": {}}
    for arm in ("G", "A", "B"):
        snapshot["branches"][arm] = {
            "project": arm, "task_ref": arm, "file_evidence_refs": {
                name: [arm.lower() + "-ref"] for name in files},
            "reference_mapping_from_g": {"g-ref": arm.lower() + "-ref"}}
    host.write_json(tmp_path / "prepared-bindings.json", snapshot)
    calls = []

    def capture(env, project, events, directory):
        assert project != "G"
        assert [e["content"] for e in events] == [continuation["files"][-1]["content"]]
        calls.append(project)
        return [project + "-new-ref"]

    monkeypatch.setattr(phase.base, "_load_environment", lambda _: {})
    monkeypatch.setattr(phase, "capture_verified", capture)
    return tmp_path, initial, continuation, payload, calls


def test_two_branches_get_same_new_bytes_without_rewriting_old_memory(prepared):
    root, _, continuation, payload, calls = prepared
    before = host.manifest(root / "G/workspace")
    bindings_before = (root / "prepared-bindings.json").read_bytes()
    result = phase.prepare_post_g_sources(root)
    assert calls == ["A", "B"] and result["new_generation_requests"] == 0
    manifests = []
    for arm in ("A", "B"):
        workspace = root / arm / "workspace"
        shutil.copytree(root / "G/workspace", workspace)
        phase.stage_post_g_files(root, workspace)
        manifests.append(host.manifest(workspace))
        assignment, memory = host.branch_assignment(
            root, arm, "Future task", manifests[-1], payload)
        assert memory == {**payload, "evidence_refs": [arm.lower() + "-ref"]}
        assert assignment["file_evidence_refs"]["sources/new.md"] == [arm + "-new-ref"]
        assert assignment["file_evidence_refs"]["handoff.md"] == [arm.lower() + "-ref"]
        assert (workspace / "sources/new.md").read_bytes() == continuation["files"][-1][
            "content"].encode()
    assert manifests[0] == manifests[1]
    assert host.manifest(root / "G/workspace") == before
    assert (root / "prepared-bindings.json").read_bytes() == bindings_before
    assert host.read_json(root / "checkpoint-result.json")["payload"] == payload
    with pytest.raises(FileExistsError):
        phase.prepare_post_g_sources(root)
    assert calls == ["A", "B"]


@pytest.mark.parametrize("fault", ["running", "exit", "result", "checkpoint", "collision"])
def test_premature_or_overwriting_update_has_no_public_writes(prepared, fault):
    root, _, _, _, calls = prepared
    if fault == "running":
        host.append_event(root / "allocations.jsonl", {"session": "G", "event": "ALLOCATED"})
    elif fault == "exit":
        host.write_json(root / "G/worker-exit.json", {"returncode": 1})
    elif fault == "result":
        host.write_json(root / "G/result.json", {"status": "FAILED"})
    elif fault == "checkpoint":
        host.write_json(root / "checkpoint-result.json", {"status": "UNKNOWN"})
    else:
        (root / "G/workspace/sources/new.md").write_text("G created a file at the same path")
        host.write_json(root / "frozen-g-files.json", host.manifest(root / "G/workspace"))
    with pytest.raises(host.LocalGateError):
        phase.prepare_post_g_sources(root)
    assert calls == [] and not (root / "post-g-source-update.json").exists()


@pytest.mark.parametrize("field", ["content", "source_uri", "observed_at", "delete"])
def test_old_observations_cannot_be_silently_changed(prepared, field):
    _, initial, continuation, _, _ = prepared
    if field == "delete":
        continuation["files"].pop(0)
    else:
        continuation["files"][0][field] += "changed"
        if field == "content":
            continuation["files"][0]["sha256"] = hashlib.sha256(
                continuation["files"][0][field].encode()).hexdigest()
    with pytest.raises((ValueError, host.LocalGateError)):
        phase.source_delta(initial, continuation)


def test_partial_capture_never_allows_branch_start_or_automatic_retry(prepared, monkeypatch):
    root, _, _, _, calls = prepared
    original = phase.capture_verified

    def interrupted(env, project, events, directory):
        if project == "B":
            (directory / "source-receipts.jsonl").write_text('{"status":"UNKNOWN"}\n')
            raise TimeoutError("response lost")
        return original(env, project, events, directory)

    monkeypatch.setattr(phase, "capture_verified", interrupted)
    with pytest.raises(TimeoutError):
        phase.prepare_post_g_sources(root)
    assert calls == ["A"]
    assert host.read_json(root / "post-g-source-preparation/result.json")["status"] == (
        "FAILED_NO_RETRY")
    assert not (root / "post-g-source-update.json").exists()
    with pytest.raises(FileNotFoundError):
        phase.stage_post_g_files(root, root / "A/workspace")
    with pytest.raises(FileExistsError):
        phase.prepare_post_g_sources(root)
    assert calls == ["A"]


def test_late_revocation_hides_new_file_and_blocks_reusing_presented_text(prepared):
    root, _, _, payload, _ = prepared
    phase.prepare_post_g_sources(root)
    workspace = root / "A/workspace"
    shutil.copytree(root / "G/workspace", workspace)
    phase.stage_post_g_files(root, workspace)
    assignment, _ = host.branch_assignment(root, "A", "Continue", host.manifest(workspace), payload)
    revoked = set()

    def metadata(ref):
        return {"evidence_id": ref, "retention_state": "READABLE",
                "revoked_at": "now" if ref in revoked else None,
                "permission_snapshot": {"readable": True, "project_ids": ["A"]}}

    guard = host.FileDisclosure("A", assignment["file_evidence_refs"], metadata)
    action = {"tool": "read_file", "arguments_json": json.dumps({"path": "sources/new.md"})}
    assert "新决定" in host.dispatch(workspace, {}, {}, None, action, guard)["text"]
    revoked.add("A-new-ref")
    assert "sources/new.md" not in guard.visible(host.manifest(workspace))
    with pytest.raises(host.LocalGateError, match="FILE_DISCLOSURE_DENIED"):
        host.dispatch(workspace, {}, {}, None, action, guard)
    with pytest.raises(host.LocalGateError, match="FILE_DISCLOSURE_DENIED"):
        guard.before_request()


def test_ready_update_invalidated_by_changed_binding(prepared):
    root, _, _, _, _ = prepared
    phase.prepare_post_g_sources(root)
    binding = host.read_json(root / "prepared-bindings.json")
    binding["branches"]["A"]["project"] = "B"
    host.write_json(root / "prepared-bindings.json", binding)
    with pytest.raises(host.LocalGateError, match="POST_G_UPDATE_NOT_VERIFIED"):
        phase.prepared_update(root)


def test_unchanged_continuation_is_a_noop_without_capture(prepared):
    root, initial, _, payload, calls = prepared
    host.write_json(root / "continuation-source.json", initial)
    config = host.read_json(root / "config.json")
    config["post_g_source"]["sha256"] = phase.sha(root / "continuation-source.json")
    host.write_json(root / "config.json", config)
    update = phase.prepare_post_g_sources(root)
    assert update["new_source_files"] == 0 and calls == []
    workspace = root / "A/workspace"
    shutil.copytree(root / "G/workspace", workspace)
    phase.stage_post_g_files(root, workspace)
    assert host.manifest(workspace) == host.manifest(root / "G/workspace")
    assignment, memory = host.branch_assignment(root, "A", "Continue", host.manifest(workspace),
                                                payload)
    assert memory["evidence_refs"] == ["a-ref"]
    assert set(assignment["file_evidence_refs"]) == set(host.manifest(workspace))


@pytest.mark.parametrize("fail_capture", [False, True])
def test_coordinator_completes_g_then_updates_both_before_launch(
    prepared, monkeypatch, fail_capture,
):
    root, initial, _, payload, calls = prepared
    host.write_json(root / "initial-source-files.json", phase.file_material(initial, "G")[0])
    host.write_json(root / "evaluation-contract.json", {
        "question": "Future continuation", "question_date": "2026-09-07"})
    launched = []
    capture = phase.capture_verified

    def public_capture(env, project, events, directory):
        assert launched == ["G"]
        if fail_capture and project == "B":
            raise TimeoutError("unknown")
        return capture(env, project, events, directory)

    def launch(directory, arm, task, files, memory):
        if arm == "G":
            assert "新决定" not in str(files) and memory is None
        else:
            assert calls == ["A", "B"] and memory == payload
            workspace = directory / arm / "workspace"
            shutil.copytree(directory / "G/workspace", workspace)
            phase.stage_post_g_files(directory, workspace)
            host.branch_assignment(directory, arm, task, host.manifest(workspace), memory)
        launched.append(arm)
        return {"status": "COMPLETED", "worker_kind": "SCRIPTED_NO_MODEL"}

    monkeypatch.setattr(phase, "capture_verified", public_capture)
    result = chain.run_chain(root, launch=launch)
    assert launched == (["G"] if fail_capture else ["G", "A", "B"])
    assert result["status"] == ("STOPPED_WITH_FAILURE" if fail_capture else
                                "LOCAL_CHAIN_COMPLETED_EFFECT_UNEVALUATED")
    assert result["formal_D4_D5"] == "NOT_ENTERED"


def test_phase_contract_checks_future_sources_without_accepting_changed_g(prepared):
    root, _, continuation, _, _ = prepared
    config = host.read_json(root / "config.json")
    item = continuation["files"][-1]
    rubric = {"schema_version": "v02-file-evaluation-v1", "question": "Continue",
              "question_date": "2026-09-07", "first_use_boundary": "Delivery",
              "source_sha256": config["post_g_source"]["sha256"],
              "necessary_conditions": ["Use new decision"], "source_assertions": [{
                  "statement": "New decision is available only after G", "spans": [{
                      "path": item["path"], "source_uri": item["source_uri"], "start": 0,
                      "end": len(item["content"]), "sha256": item["sha256"]}]}]}
    raw = json.dumps(rubric).encode()
    config.update(task_evaluation="SOURCE_ASSERTIONS_FROZEN",
                  evaluation_contract={"sha256": hashlib.sha256(raw).hexdigest()})
    initial = (root / "input-source.json").read_bytes()
    future = (root / "continuation-source.json").read_bytes()
    assert chain.phase_contract(config, initial, raw, future) == rubric
    with pytest.raises(host.LocalGateError, match="SOURCE_IDENTITY_CHANGED"):
        chain.phase_contract(config, initial + b" ", raw, future)
    with pytest.raises(host.LocalGateError, match="SOURCE_IDENTITY_CHANGED"):
        chain.phase_contract(config, initial, raw, future + b" ")

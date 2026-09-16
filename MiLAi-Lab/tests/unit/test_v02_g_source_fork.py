from __future__ import annotations

import copy
import hashlib
import importlib
import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
fork = importlib.import_module("v02_g_source_fork")
host = importlib.import_module("run_v02_local_vllm")


def receipt_summary(request, project):
    return {**{k: request[k] for k in ("source_type", "source_ref", "subject_id")},
        "content_chars": len(request["content"]), "canonical_changed": False,
        "content_sha256": hashlib.sha256(request["content"].encode()).hexdigest(),
        "project_id": project, "data_classification": "SYNTHETIC"}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    config = {"source_mode": "PUBLIC_SOURCE_SNAPSHOT", "memory_variants": {
        "B_representation": {"layer": "L1", "kind": "MARKDOWN_JSON_TEXT_WRAPPING_ONLY"},
        "B_structure": {"layer": "L2", "kind": "BODY_FIRST", "body_key": "body"}}}
    host.write_json(tmp_path / "config.json", config)
    workspace = tmp_path / "G/workspace"
    workspace.mkdir(parents=True)
    (workspace / "note.md").write_bytes(" 首\r\n真实捕获的观察\n尾 \n".encode())
    host.write_json(tmp_path / "frozen-g-files.json", host.manifest(workspace))
    host.write_json(tmp_path / "G/worker-exit.json", {"returncode": 0})
    host.write_json(tmp_path / "G/result.json", {"status": "COMPLETED"})
    host.append_event(tmp_path / "allocations.jsonl", {
        "session": "G", "event": "TERMINAL", "status": "COMPLETED"})
    refs = [str(uuid4()), str(uuid4())]
    payload = {"text": "A literal reference: " + refs[0], "evidence_refs": [refs[0]]}
    host.write_json(tmp_path / "checkpoint-result.json", {
        "status": "SAVED_CONFIRMED", "payload": payload})
    host.write_json(tmp_path / "G/file-evidence-refs.json", {"note.md": [refs[0]]})
    snapshot = {"status": "PUBLIC_SOURCES_VERIFIED", "source_files": {}, "branches": {}}
    for arm in fork.branches(config):
        snapshot["branches"][arm] = {"project": arm, "task_ref": arm,
            "file_evidence_refs": {}, "reference_mapping_from_g": {}}
    host.write_json(tmp_path / "prepared-bindings.json", snapshot)
    records, requests, calls = {}, {}, []
    for i, ref in enumerate(refs):
        request = {"source_type": "TOOL_RESULT", "source_ref": "file:///original/" + str(i),
            "subject_id": "fixture", "observed_at": "2026-09-07T10:00:00+00:00",
            "content": " 首\r\n观察" + str(i) + "\n尾 \n", "speaker": "tool",
            "source_context": {"session_id": "original-G", "turn_id": str(i),
                "turn_ordinal": i, "round_id": "round", "round_ordinal": 0},
            "operation_id": "actual-G-" + str(i), "confirmation": "CAPTURE"}
        requests[ref] = request
        record = {k: v for k, v in request.items() if k in fork.SOURCE_FIELDS}
        records[ref] = {**record, "evidence_id": ref,
            "permission_snapshot": {"readable": True, "project_ids": ["G"]},
            "retention_state": "READABLE", "revoked_at": None}
        host.append_event(tmp_path / "G/tool-events.jsonl", {
            "action": {"tool": "mcp_call", "arguments_json": json.dumps({
                "name": "milai_evidence_capture", "arguments": request})},
            "acquired": {"evidence_id": ref, "outbox_id": str(uuid4()),
                         "confirmation_summary": receipt_summary(request, "G")}})
    real_client = httpx.Client

    def transport(request):
        if request.method == "GET":
            return httpx.Response(200, json=records[request.url.path.split("/")[-1]])
        assert request.url.path == "/v1/system/projection-readiness"
        return httpx.Response(200, json={"status": "READY"})

    monkeypatch.setattr(fork.httpx, "Client", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(transport)))
    monkeypatch.setattr(fork.base, "_load_environment", lambda _: {
        "MILAI_BASE_URL": "http://fixture.invalid", "MILAI_API_TOKEN": "fixture",
        "MILAI_AGENT_READER_TOKEN": "fixture"})

    @contextmanager
    def observer(service, directory, project, task):
        def call(name, request):
            assert name == "milai_evidence_capture" and project != "G"
            calls.append((project, copy.deepcopy(request)))
            ref = str(uuid4())
            records[ref] = {k: v for k, v in request.items() if k in fork.SOURCE_FIELDS}
            records[ref].update(evidence_id=ref,
                retention_state="READABLE", revoked_at=None,
                permission_snapshot={"readable": True, "project_ids": [project]})
            return {"evidence_id": ref, "outbox_id": str(uuid4()),
                    "confirmation_summary": receipt_summary(request, project)}
        yield call, {}

    monkeypatch.setattr(fork, "observer", observer)
    return tmp_path, refs, requests, records, calls


def test_full_observations_fork_to_four_arms_without_inventing_support(prepared):
    root, refs, _, records, calls = prepared
    original = (root / "checkpoint-result.json").read_bytes()
    result = fork.complete_g_sources(root)
    assert result["status"] == "PUBLIC_G_CAPTURES_FORKED" and result["model_calls"] == 0
    assert len(calls) == 8  # Includes the second, unreferenced observation in every arm.
    snapshot = host.read_json(root / "prepared-bindings.json")
    all_ids = set(refs)
    for arm in fork.branches(host.read_json(root / "config.json")):
        mapping = snapshot["branches"][arm]["reference_mapping_from_g"]
        assert set(mapping) == set(refs)
        if arm == "G":
            assert mapping == {ref: ref for ref in refs}
            continue
        assert not all_ids.intersection(mapping.values())
        all_ids.update(mapping.values())
        for ref in refs:
            fork.require_same_observation(records[mapping[ref]], records[ref])
            assert records[mapping[ref]]["source_context"]["session_id"] == "original-G"
        shutil.copytree(root / "G/workspace", root / arm / "workspace")
        payload = host.read_json(root / "checkpoint-result.json")["payload"]
        assignment, memory = host.branch_assignment(root, arm, "Continue",
            host.manifest(root / arm / "workspace"), payload)
        assert memory["evidence_refs"] == [mapping[refs[0]]]
        assert memory["text"].endswith(refs[0])  # Arbitrary text is not an ID binding.
        assert assignment["file_evidence_refs"] == {"note.md": [mapping[refs[0]]]}
    assert (root / "checkpoint-result.json").read_bytes() == original
    assert fork.complete_g_sources(root)["status"] == "NO_NEW_G_CAPTURES"
    assert len(calls) == 8


def test_exact_receipt_replay_deduplicates_without_additional_capture(prepared):
    root, _, _, _, calls = prepared
    event = host.read_events(root / "G/tool-events.jsonl")[0]
    host.append_event(root / "G/tool-events.jsonl", event)
    assert fork.complete_g_sources(root)["new_source_count"] == 2
    assert len(calls) == 8


@pytest.mark.parametrize("fault", ["unknown", "missing_ref", "conflicting_receipt"])
def test_unproven_capture_or_reference_stops_before_public_write(prepared, fault):
    root, _, _, _, calls = prepared
    events = host.read_events(root / "G/tool-events.jsonl")
    if fault == "unknown":
        events[0]["acquired"] = {"mcp_error": True, "error": "timeout"}
    elif fault == "missing_ref":
        events.pop(0)
    else:
        event = copy.deepcopy(events[0])
        args = json.loads(event["action"]["arguments_json"])
        args["arguments"]["content"] = "conflicting request"
        event["action"]["arguments_json"] = json.dumps(args)
        events.append(event)
    (root / "G/tool-events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises(host.LocalGateError):
        fork.complete_g_sources(root)
    assert calls == [] and not (root / "g-source-preparation").exists()


@pytest.mark.parametrize("fault", ["content", "source_context", "revoked", "permission"])
def test_current_source_identity_and_eligibility_checked_before_copy(prepared, fault):
    root, refs, _, records, calls = prepared
    record = records[refs[0]]
    if fault == "revoked":
        record["revoked_at"] = "now"
    elif fault == "permission":
        record["permission_snapshot"]["project_ids"] = ["elsewhere"]
    elif fault == "source_context":
        record["source_context"] = {**record["source_context"], "session_id": "forged"}
    else:
        record["content"] = record["content"].strip()
    with pytest.raises(host.LocalGateError):
        fork.complete_g_sources(root)
    assert calls == []


@pytest.mark.parametrize("fault", ["timeout", "classification", "identity", "input_changed"])
def test_partial_fork_keeps_receipts_but_never_publishes_or_retries(
    prepared, monkeypatch, fault,
):
    root, refs, _, _records, calls = prepared
    initial = (root / "prepared-bindings.json").read_bytes()
    observer = fork.observer

    @contextmanager
    def changed(service, directory, project, task):
        with observer(service, directory, project, task) as (call, env):
            def failing(name, request):
                if project == "B":
                    if fault == "timeout":
                        raise TimeoutError("response lost")
                    receipt = call(name, request)
                    if fault == "classification":
                        receipt["confirmation_summary"]["data_classification"] = "PERSONAL"
                    elif fault == "identity":
                        receipt["evidence_id"] = refs[0]
                    else:
                        (root / "G/tool-events.jsonl").write_text("")
                    return receipt
                return call(name, request)
            yield failing, env

    monkeypatch.setattr(fork, "observer", changed)
    with pytest.raises((host.LocalGateError, TimeoutError)):
        fork.complete_g_sources(root)
    assert (root / "prepared-bindings.json").read_bytes() == initial
    assert not (root / "g-source-preparation/ready-bindings.json").exists()
    result = host.read_json(root / "g-source-preparation/result.json")
    assert result["status"] == "UNCONFIRMED_STOP_NO_RETRY"
    assert result["branches"]["A"]["operations"][0]["outcome"] == "CONFIRMED_AND_READABLE"
    if fault == "timeout":
        assert result["branches"]["B"]["operations"][0]["outcome"] == "UNKNOWN"
    count = len(calls)
    with pytest.raises((host.LocalGateError, FileExistsError)):
        fork.complete_g_sources(root)
    assert len(calls) == count


def test_api_null_context_defaults_and_iso_time_normalization_are_not_content_loss(prepared):
    _, refs, requests, records, _ = prepared
    record = copy.deepcopy(records[refs[0]])
    record["observed_at"] = "2026-09-07T10:00:00Z"
    record["source_context"]["next_turn_id"] = None
    fork.require_same_observation(record, requests[refs[0]])


@pytest.mark.parametrize("field", ["project_id", "content_sha256", "data_classification"])
def test_capture_receipt_must_confirm_original_request_before_fork(prepared, field):
    root, _, _, _, calls = prepared
    events = host.read_events(root / "G/tool-events.jsonl")
    events[0]["acquired"]["confirmation_summary"].pop(field)
    (root / "G/tool-events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises(host.LocalGateError, match="CONFIRMATION_SUMMARY_NOT_BOUND"):
        fork.complete_g_sources(root)
    assert calls == []

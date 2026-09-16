"""Public MCP captures in a scripted G, independent source forks, and cold read checks."""

# ruff: noqa: RUF001 -- Exact Chinese fixture punctuation is intentional.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import run_v02_local_vllm as host
import run_v02_memory_flow as base
from check_v02_e2e_live import metadata
from v02_e2e_state import FileDisclosure, LocalGateError, usable_head
from v02_g_source_fork import captures, complete_g_sources, require_same_observation
from v02_low_cost_public import observer
from v02_public_snapshot import prepare_snapshot


def generator(root: Path) -> None:
    config = base.read_json(root / "config.json")
    workspace = root / "G/workspace"
    for name, text in base.read_json(root / "initial-source-files.json").items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    frozen = host.manifest(workspace)
    assignment, _ = host.branch_assignment(root, "G", "SCRIPTED_ENGINEERING", frozen, None)
    host.write_json(root / "G/assignment.json", assignment)
    host.write_json(root / "G/initial-files.json", frozen)
    directory = root / "G/client"
    directory.mkdir()
    with observer(root / (root.name + "-product"), directory,
                  assignment["project"], assignment["task_ref"]) as (call, env):
        guard = FileDisclosure(assignment["project"], assignment["file_evidence_refs"],
                               partial(metadata, env))
        catalog = {"milai_evidence_capture": {}}

        def action(tool, args):
            action = {"tool": tool, "arguments_json": json.dumps(args, ensure_ascii=False)}
            acquired = host.dispatch(workspace, frozen, catalog, call, action, guard)
            host.append_event(root / "G/tool-events.jsonl", {"action": action,
                "acquired": acquired, "worker_kind": "SCRIPTED_NO_MODEL"})
            return acquired

        action("read_file", {"path": "sources/original.md"})
        for i in range(2):
            content = " 首\r\n脚本观察 " + str(i) + "；完整内容及尾部均须保存。\n尾 \n"
            receipt = action("mcp_call", {"name": "milai_evidence_capture", "arguments": {
                "operation_id": "actual-G-capture-" + str(i),
                "source_type": "TOOL_RESULT", "source_ref": "engineering://original/" + str(i),
                "subject_id": "engineering-observation",
                "observed_at": datetime.now(UTC).isoformat(),
                "content": content, "speaker": "tool", "source_context": {
                    "session_id": root.name + "-original-G", "turn_id": "turn-" + str(i),
                    "turn_ordinal": i, "round_id": "round-0", "round_ordinal": 0},
                "confirmation": "CAPTURE"}})
            assert receipt.get("evidence_id") and receipt.get("outbox_id")
            if i == 0:
                # The later capture remains in the corpus without becoming note support.
                action("write_file", {"path": config["l1_path"], "content": content})
                action("write_file", {"path": config["l2_path"], "content": content})
        host.write_json(root / "G/file-evidence-refs.json", guard.file_refs)
        saved = host.checkpoint(root, config, call=call)
        host.write_json(root / "checkpoint-result.json", saved)
        assert saved["status"] == "SAVED_CONFIRMED"
    host.write_json(root / "G/result.json", {"status": "COMPLETED", "pid": os.getpid(),
        "worker_kind": "SCRIPTED_ENGINEERING_NOT_AGENT", "model_calls": 0})


def cold(root: Path, request: Path) -> None:
    params = base.read_json(request)
    arm, revoked = params["arm"], params["revoked"]
    assignment = base.read_json(root / arm / "assignment.json")
    workspace = root / arm / "workspace"
    frozen = host.manifest(workspace)
    snapshot = base.read_json(root / "prepared-bindings.json")
    with observer(root / (root.name + "-product"), request.parent,
                  assignment["project"], assignment["task_ref"]) as (call, env):
        head = call("milai_working_state_get", {"scope": "TASK"})
        assert head["state_version_id"] == params["receipt"]["state_version_id"]
        guard = FileDisclosure(assignment["project"], assignment["file_evidence_refs"],
                               partial(metadata, env))
        if revoked:
            assert head["payload"] == {} and head["payload_withheld"]
            try:
                usable_head(head)
            except LocalGateError:
                pass
            else:
                raise AssertionError("Withheld State accepted")
        else:
            usable_head(head)
            assert head["payload"] == params["receipt"]["payload"]
        hidden = ["handoff.md", "details.md"] if revoked else []
        assert set(guard.visible(frozen)) == set(frozen) - set(hidden)
        read_hashes = {}
        for name, digest in frozen.items():
            action = {"tool": "read_file", "arguments_json": json.dumps({"path": name})}
            if name in hidden:
                try:
                    host.dispatch(workspace, frozen, {}, call, action, guard)
                except LocalGateError as exc:
                    assert str(exc) == "FILE_DISCLOSURE_DENIED"
                else:
                    raise AssertionError("Revoked source disclosed in file")
                continue
            page = host.dispatch(workspace, frozen, {}, call, action, guard)
            assert page["next"] is None
            assert page["text"].encode() == (workspace / name).read_bytes()
            read_hashes[name] = digest
        sources = []
        for i, (ref, capture) in enumerate(captures(root).items()):
            target = snapshot["branches"][arm]["reference_mapping_from_g"][ref]
            if revoked and i == 0:
                continue
            guard.check_refs([target])
            record = metadata(env, target)
            require_same_observation(record, capture["request"])
            sources.append({"evidence_id": target,
                "content_sha256": hashlib.sha256(record["content"].encode()).hexdigest()})
        guard.before_request()
        host.write_json(request.parent / "result.json", {
            "status": "COLD_G_CAPTURE_FORK_VERIFIED", "pid": os.getpid(), "arm": arm,
            "state_version_id": head["state_version_id"], "state_withheld": bool(revoked),
            "hidden": hidden, "read_hashes": read_hashes, "public_source_reads": sources,
            "model_calls": 0})


def run(root: Path, config_path: Path) -> None:
    config = base.read_json(config_path)
    assert config["model_transport_enabled"] is False
    pin = base.pin(config_path)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    service = root / (root.name + "-product")
    text = " 原始首部\r\n正常初始来源的完整内容。\n原始尾部 \n"
    source = {"schema_version": "v02-file-source-only-v1", "files": [{
        "path": "sources/original.md", "source_uri": "engineering://initial/source",
        "observed_at": datetime.now(UTC).isoformat(), "content": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest()}]}
    host.write_json(root / "input-source.json", source)
    config["source_sha256"] = host.sha(root / "input-source.json")
    host.write_json(root / "config.json", config)
    host.write_json(root / "preflight.json", {"pin": pin, "model_calls": 0,
        "runner_sha256": host.sha(Path(__file__)), "G": "SCRIPTED_ENGINEERING"})
    started = time.monotonic()
    report = {"status": "RUNNING", "model_calls": 0, "cold": [], "formal_D4_D5": "NOT_ENTERED"}
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, sorted(affinity)[:2])
    try:
        base.prepare(service, config_path=config_path,
            compose_override=base.LAB / "tools/containers/v02-local-bounded.compose.yaml",
            runtime_overrides={"MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED"})
        prepare_snapshot(root, source)
        host.append_event(root / "allocations.jsonl", {
            "session": "G", "event": "ALLOCATED", "kind": "SCRIPTED_NO_MODEL"})
        finished = base._command(
            [sys.executable, str(Path(__file__).resolve()), "--root", str(root), "--generator"],
            cwd=base.LAB, timeout=120)
        host.write_json(root / "G/worker-exit.json", {"returncode": finished.returncode})
        generated = base.read_json(root / "G/result.json")
        assert not Path("/proc", str(generated["pid"])).exists()
        host.append_event(root / "allocations.jsonl", {
            "session": "G", "event": "TERMINAL", "status": "COMPLETED"})
        frozen = host.manifest(root / "G/workspace")
        host.write_json(root / "frozen-g-files.json", frozen)
        original_checkpoint = (root / "checkpoint-result.json").read_bytes()
        original = base.read_json(root / "checkpoint-result.json")
        report["source_fork"] = complete_g_sources(root)
        receipts = {}
        for arm in ("A", "B"):
            workspace = root / arm / "workspace"
            shutil.copytree(root / "G/workspace", workspace)
            assignment, payload = host.branch_assignment(root, arm, "Continue", frozen,
                                                          original["payload"])
            host.write_json(root / arm / "assignment.json", assignment)
            directory = root / ("save-" + arm)
            directory.mkdir()
            with observer(service, directory, assignment["project"],
                          assignment["task_ref"]) as (call, _):
                assert call("milai_working_state_get", {"scope": "TASK"})["status"] == "ABSENT"
                receipts[arm] = call("milai_working_state_update", {
                    "scope": "TASK", "expected_version": 0, "operation_id": "seed-" + arm,
                    "payload": payload})
                head = call("milai_working_state_get", {"scope": "TASK"})
                assert receipts[arm]["payload"] == payload == head["payload"]
                assert receipts[arm]["state_version_id"] == head["state_version_id"]
                host.write_json(directory / "operation.json", receipts[arm])
                host.write_json(directory / "head.json", head)
        host.write_json(root / "state-receipts.json", receipts)
        assert (root / "checkpoint-result.json").read_bytes() == original_checkpoint
        assert host.manifest(root / "G/workspace") == frozen

        def verify(arm, label, revoked):
            directory = root / label
            directory.mkdir()
            request = directory / "request.json"
            host.write_json(request, {"arm": arm, "receipt": receipts[arm], "revoked": revoked})
            base._command([sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                "--cold", str(request)], cwd=base.LAB, timeout=120)
            value = base.read_json(directory / "result.json")
            assert not Path("/proc", str(value["pid"])).exists()
            report["cold"].append(value)

        verify("A", "cold-A", False)
        verify("B", "cold-B", False)
        directory = root / "revoke-A-new-source"
        directory.mkdir()
        binding = base.read_json(root / "prepared-bindings.json")["branches"]["A"]
        ref = next(iter(captures(root)))
        with observer(service, directory, binding["project"], binding["task_ref"]) as (call, _):
            receipt = call("milai_evidence_revoke", {
                "evidence_id": binding["reference_mapping_from_g"][ref],
                "operation_id": "revoke-fixture-A-support", "reason_code": "USER_REQUEST",
                "confirmation": "REVOKE"})
            assert not receipt.get("mcp_error")
            host.write_json(directory / "receipt.json", receipt)
        verify("A", "revoked-cold-A", True)
        verify("B", "unaffected-cold-B", False)
        report["status"] = "PUBLIC_G_CAPTURES_FORK_COLD_RECOVERY_AND_ISOLATION_VERIFIED"
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        if (service / "runtime.env").exists():
            report["cleanup"] = host.stop_owned(service)
        report["elapsed_seconds_including_cleanup"] = time.monotonic() - started
        os.sched_setaffinity(0, affinity)
        host.write_json(root / "result.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--generator", action="store_true")
    parser.add_argument("--cold", type=Path)
    args = parser.parse_args()
    if args.generator:
        generator(args.root.resolve())
    elif args.cold:
        cold(args.root.resolve(), args.cold.resolve())
    else:
        run(args.root.resolve(), args.config.resolve())

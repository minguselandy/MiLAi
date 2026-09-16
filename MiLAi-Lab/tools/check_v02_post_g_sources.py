"""Real public source-phase checks with scripted cold workers, no model transport."""

# ruff: noqa: RUF001 -- Exact Chinese fixture punctuation is intentional.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import run_v02_local_vllm as host
import run_v02_memory_flow as base
from check_v02_e2e_live import metadata
from v02_e2e_state import FileDisclosure, LocalGateError
from v02_low_cost_public import observer
from v02_post_g_sources import prepare_post_g_sources, stage_post_g_files
from v02_public_snapshot import prepare_snapshot


def generator(root: Path) -> None:
    """Engineering fixture, explicitly not an Agent-generated G or an experiment session."""
    config = base.read_json(root / "config.json")
    workspace = root / "G/workspace"
    files = base.read_json(root / "initial-source-files.json")
    for name, text in files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    initial = host.manifest(workspace)
    assignment, _ = host.branch_assignment(root, "G", "SCRIPTED_ENGINEERING_FIXTURE", initial, None)
    host.write_json(root / "G/assignment.json", assignment)
    host.write_json(root / "G/initial-files.json", initial)
    host.write_artifact(workspace, config["l1_path"],
                        "首\n工程旧理解；仅来源原文支持\n尾\n", initial)
    host.write_artifact(workspace, config["l2_path"], next(iter(files.values())), initial)
    refs = assignment["file_evidence_refs"]
    old_refs = [ref for values in refs.values() for ref in values]
    refs = {**refs, config["l1_path"]: old_refs, config["l2_path"]: old_refs}
    host.write_json(root / "G/file-evidence-refs.json", refs)
    saved = host.checkpoint(root, config)
    host.write_json(root / "checkpoint-result.json", saved)
    assert saved["status"] == "SAVED_CONFIRMED"
    host.write_json(root / "G/result.json", {
        "status": "COMPLETED", "worker_kind": "SCRIPTED_ENGINEERING_NOT_AGENT",
        "pid": os.getpid(), "model_calls": 0})


def cold(root: Path, request: Path) -> None:
    params = base.read_json(request)
    arm = params["arm"]
    assignment = base.read_json(root / arm / "assignment.json")
    workspace = root / arm / "workspace"
    frozen = host.manifest(workspace)
    with observer(root / (root.name + "-product"), request.parent,
                  assignment["project"], assignment["task_ref"]) as (call, env):
        head = call("milai_working_state_get", {"scope": "TASK"})
        # New source revocation does not revoke the old, independently supported State.
        assert head["payload"] == params["receipt"]["payload"]
        assert head["state_version_id"] == params["receipt"]["state_version_id"]
        guard = FileDisclosure(assignment["project"], assignment["file_evidence_refs"],
                               partial(metadata, env))

        def action(tool, args):
            return host.dispatch(workspace, frozen, {}, call,
                                 {"tool": tool, "arguments_json": json.dumps(args)}, guard)

        assert set(action("list_files", {})["files"]) == set(frozen) - set(params["hidden"])
        read_hashes = {}
        for name, digest in frozen.items():
            if name in params["hidden"]:
                try:
                    action("read_file", {"path": name})
                except LocalGateError as exc:
                    assert str(exc) == "FILE_DISCLOSURE_DENIED"
                else:
                    raise AssertionError("Revoked source disclosed")
                continue
            text, offset = "", 0
            while True:
                page = action("read_file", {"path": name, "offset": offset,
                                            "expected_sha256": digest})
                text += page["text"]
                if page["next"] is None:
                    break
                assert page["next"]["offset"] > offset
                offset = page["next"]["offset"]
            assert text.encode() == (workspace / name).read_bytes()
            read_hashes[name] = hashlib.sha256(text.encode()).hexdigest()
        guard.before_request()
        host.write_json(request.parent / "result.json", {
            "status": "COLD_PHASE_FILES_AND_OLD_STATE_VERIFIED", "pid": os.getpid(),
            "hidden": params["hidden"], "read_hashes": read_hashes,
            "state_version_id": head["state_version_id"], "model_calls": 0})


def run(root: Path, config_path: Path) -> dict:
    config = base.read_json(config_path)
    assert config["model_transport_enabled"] is False
    pin = base.pin(config_path)
    service = root / (root.name + "-product")
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    initial = {"schema_version": "v02-file-source-only-v1", "files": []}
    text = "  原始首部\r\n工程观察，仅测试完整读取，不是实际任务结论。\n原始尾部 \n"
    observed = datetime.now(UTC).isoformat()
    initial["files"].append({"path": "sources/original.md", "source_uri": "file:///fixture/old",
                             "observed_at": observed, "content": text,
                             "sha256": hashlib.sha256(text.encode()).hexdigest()})
    newer = " 新增首部\r\nG结束后的新观察，尚未被旧记忆理解。\n新增尾部 \n"
    continuation = {**initial, "files": [*initial["files"], {
        "path": "sources/new.md", "source_uri": "file:///fixture/new", "observed_at": observed,
        "content": newer, "sha256": hashlib.sha256(newer.encode()).hexdigest()}]}
    host.write_json(root / "input-source.json", initial)
    host.write_json(root / "continuation-source.json", continuation)
    config.update(source_sha256=host.sha(root / "input-source.json"),
                  post_g_source={"path": "continuation-source.json",
                                 "sha256": host.sha(root / "continuation-source.json")})
    host.write_json(root / "config.json", config)
    host.write_json(root / "preflight.json", {"pin": pin, "model_calls": 0,
                    "runner_sha256": host.sha(Path(__file__)), "G": "SCRIPTED_ENGINEERING"})
    report = {"status": "RUNNING", "model_calls": 0, "cold": [], "formal_D4_D5": "NOT_ENTERED"}
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, sorted(affinity)[:2])
    try:
        base.prepare(service, config_path=config_path,
                     compose_override=base.LAB / "tools/containers/v02-local-bounded.compose.yaml",
                     runtime_overrides={"MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED"})
        snapshot = prepare_snapshot(root, initial)
        host.append_event(root / "allocations.jsonl", {
            "session": "G", "event": "ALLOCATED", "kind": "SCRIPTED_NO_MODEL"})
        finished = base._command(
            [sys.executable, str(Path(__file__).resolve()), "--root", str(root), "--generator"],
            cwd=base.LAB, timeout=120)
        host.write_json(root / "G/worker-exit.json", {
            "returncode": finished.returncode, "boundary": "SUBPROCESS_RUN_RETURNED"})
        generator_result = base.read_json(root / "G/result.json")
        assert not Path("/proc", str(generator_result["pid"])).exists()
        host.append_event(root / "allocations.jsonl", {
            "session": "G", "event": "TERMINAL", "status": "COMPLETED", "kind": "SCRIPTED"})
        frozen = host.manifest(root / "G/workspace")
        host.write_json(root / "frozen-g-files.json", frozen)
        update = prepare_post_g_sources(root)
        report["source_update"] = update
        assert "sources/new.md" not in frozen
        old = base.read_json(root / "checkpoint-result.json")["payload"]
        receipts = {}
        for arm in ("A", "B"):
            workspace = root / arm / "workspace"
            shutil.copytree(root / "G/workspace", workspace)
            stage_post_g_files(root, workspace)
            assignment, payload = host.branch_assignment(root, arm, "Continue",
                                                        host.manifest(workspace), old)
            host.write_json(root / arm / "assignment.json", assignment)
            directory = root / ("save-" + arm)
            directory.mkdir()
            with observer(service, directory, assignment["project"],
                          assignment["task_ref"]) as (call, _):
                receipts[arm] = call("milai_working_state_update", {
                    "scope": "TASK", "expected_version": 0, "operation_id": "seed-" + arm,
                    "payload": payload})
                assert receipts[arm]["payload"] == payload
        host.write_json(root / "state-receipts.json", receipts)
        assert host.manifest(root / "A/workspace") == host.manifest(root / "B/workspace")
        assert host.manifest(root / "G/workspace") == frozen

        def verify(arm, label, hidden):
            directory = root / label
            directory.mkdir()
            request = directory / "request.json"
            host.write_json(request, {"arm": arm, "receipt": receipts[arm], "hidden": hidden})
            base._command([sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                           "--cold", str(request)], cwd=base.LAB, timeout=120)
            value = base.read_json(directory / "result.json")
            assert not Path("/proc", str(value["pid"])).exists()
            report["cold"].append(value)

        verify("A", "cold-A", [])
        verify("B", "cold-B", [])
        directory = root / "revoke-A-new-source"
        directory.mkdir()
        binding = snapshot["branches"]["A"]
        with observer(service, directory, binding["project"], binding["task_ref"]) as (call, _):
            receipt = call("milai_evidence_revoke", {
                "evidence_id": update["branches"]["A"]["file_evidence_refs"]["sources/new.md"][0],
                "operation_id": "revoke-fixture-A-new", "reason_code": "USER_REQUEST",
                "confirmation": "REVOKE"})
            assert not receipt.get("mcp_error")
            host.write_json(directory / "receipt.json", receipt)
        verify("A", "revoked-cold-A", ["sources/new.md"])
        verify("B", "unaffected-cold-B", [])
        report["status"] = "PUBLIC_POST_G_CAPTURE_COLD_RECOVERY_AND_REVOCATION_VERIFIED"
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        if (service / "runtime.env").exists():
            report["cleanup"] = host.stop_owned(service)
        os.sched_setaffinity(0, affinity)
        host.write_json(root / "result.json", report)
    return report


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

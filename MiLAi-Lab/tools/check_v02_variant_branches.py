"""Five-branch public storage and real cold Host requests to a network-ineligible mock model."""

# ruff: noqa: RUF001 -- Exact Host message delimiter.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx

import run_v02_e2e_generality as chain
import run_v02_local_vllm as host
import run_v02_memory_flow as base
from v02_local_provider import LocalProvider
from v02_public_snapshot import prepare_snapshot
from v02_variant_plan import ALL_ARMS


def generator(root: Path) -> None:
    config = base.read_json(root / "config.json")
    workspace = root / "G/workspace"
    for path, text in base.read_json(root / "initial-source-files.json").items():
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode())
    frozen = host.manifest(workspace)
    assignment, _ = host.branch_assignment(root, "G", config["generator_task"], frozen, None)
    host.write_json(root / "G/assignment.json", assignment)
    host.write_json(root / "G/initial-files.json", frozen)
    structured = json.dumps({"prefix": "", "topic": "Engineering fixture",
        "body": " 首部\r\n完整正文\t尾部 \n", "evidence_refs": [], "count": 0, "suffix": None},
        ensure_ascii=False)
    text = "  首部\r\nScripted memory, not a model result.\n尾部\t \n"
    structure_layer = config["memory_variants"]["B_structure"]["layer"]
    host.write_artifact(workspace, config["l1_path"],
                        structured if structure_layer == "L1" else text, frozen)
    host.write_artifact(workspace, config["l2_path"],
                        structured if structure_layer == "L2" else text, frozen)
    refs = assignment["file_evidence_refs"]
    sources = [ref for values in refs.values() for ref in values]
    host.write_json(root / "G/file-evidence-refs.json", {
        **refs, config["l1_path"]: sources, config["l2_path"]: sources})
    saved = host.checkpoint(root, config)
    host.write_json(root / "checkpoint-result.json", saved)
    assert saved["status"] == "SAVED_CONFIRMED"
    host.write_json(root / "G/result.json", {"status": "COMPLETED", "pid": os.getpid(),
                    "worker_kind": "SCRIPTED_ENGINEERING_NOT_AGENT", "new_model_requests": 0})


def cold(root: Path, arm: str) -> None:
    config = base.read_json(root / "config.json")
    assert config["transport_kind"] == "MOCK_ONLY"
    observed = []
    completions = 0

    def factory(*args, **kwargs):
        def handle(request):
            nonlocal completions
            observed.append(request.url.path)
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": config["model"]}]})
            if request.url.path == "/tokenize":
                return httpx.Response(200, json={"count": 100})
            assert request.url.path == "/v1/chat/completions"
            actual = json.loads(request.content)
            if completions == 0:
                bootstrap = json.loads(actual["messages"][1]["content"].split(
                    "\n恢复内容及文件入口：\n", 1)[1])
                detail = bootstrap["payload"][config["state_field"]]["l2"]["path"]
                action = {"tool": "read_file", "arguments_json": json.dumps({"path": detail}),
                          "answer": ""}
            else:
                assert completions == 1
                assert any(message["content"].startswith("TOOL_RESULT")
                           for message in actual["messages"])
                action = {"tool": "finish", "arguments_json": "{}",
                          "answer": "Mock transport receipt; semantic task not evaluated"}
            completions += 1
            return httpx.Response(200, json={"id": "MOCK_ONLY_" + str(completions),
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
                "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps(action, ensure_ascii=False)}}]})

        return LocalProvider(*args, **kwargs, transport=httpx.MockTransport(handle))

    host.LocalProvider = factory
    try:
        host.session(root, arm)
    finally:
        host.write_json(root / arm / "mock-transport.json", {
            "mode": "HTTPX_MOCK_TRANSPORT_NO_MODEL_NETWORK", "paths": observed,
            "mock_completion_requests": completions, "real_model_calls": 0})


def scripted_launch(root, arm, task, files, payload):
    if arm == "G":
        host.append_event(root / "allocations.jsonl", {
            "session": "G", "event": "ALLOCATED", "kind": "SCRIPTED_ENGINEERING"})
        completed = base._command([sys.executable, str(Path(__file__).resolve()),
                                  "--root", str(root), "--generator"], cwd=base.LAB, timeout=120)
        result = base.read_json(root / "G/result.json")
        assert not Path("/proc", str(result["pid"])).exists()
        host.write_json(root / "G/worker-exit.json", {"returncode": completed.returncode,
                        "boundary": "SUBPROCESS_RUN_RETURNED"})
        host.append_event(root / "allocations.jsonl", {
            "session": "G", "event": "TERMINAL", "status": result["status"]})
        return result
    original = host.subprocess

    def execute(command, **kwargs):
        assert command == [sys.executable, str(Path(host.__file__).resolve()), "--worker", arm,
                           "--root", str(root)]
        # Only the fixed engineering worker changes; all real launch/seed/deadline logic is used.
        return subprocess.run(  # noqa: S603 -- fixed cold worker; mock-only Provider
            [sys.executable, str(Path(__file__).resolve()), "--root", str(root), "--cold", arm],
            **kwargs)

    host.subprocess = SimpleNamespace(run=execute, STDOUT=subprocess.STDOUT)
    try:
        return host.launch(root, arm, task, files, payload)
    finally:
        host.subprocess = original


def run_case(root: Path, config_path: Path, kind: str, structure_layer: str) -> dict:
    started = time.monotonic()
    config = {**base.read_json(host.CONFIG), **base.read_json(config_path),
              "model_transport_enabled": True, "new_model_allocations_authorized": 5,
              "new_model_tokens_authorized": 100000, "local_sessions": list(ALL_ARMS),
              "batch_token_limit": 100000, "state_field": "milai_lab_layered_v2",
              "l1_path": "handoff.md", "l2_path": "details.md", "session_timeout_seconds": 120,
              "l1_format": "json" if structure_layer == "L1" else "text",
              "generator_task": "Create scripted engineering artifacts; no model or future task",
              "memory_variants": {
                  "B_representation": {"layer": "L2" if structure_layer == "L1" else "L1",
                                       "kind": "MARKDOWN_JSON_TEXT_WRAPPING_ONLY"},
                  "B_structure": {"layer": structure_layer, "kind": kind,
                                  "source_format": "json"}}}
    structure = config["memory_variants"]["B_structure"]
    if kind in {"BODY_FIRST", "BODY_LAST"}:
        structure["body_key"] = "body"
    elif kind == "DROP_EMPTY_EDGE_WRAPPERS":
        structure["empty_wrapper_keys"] = ["prefix", "suffix"]
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    service = root / (root.name + "-product")
    original = " 首部\r\nOriginal source observation.\n尾部 \n"
    new = " 首部\nNew observation provided only after G exits.\r\n尾部 \n"
    observed = datetime.now(UTC).isoformat()

    def item(path, text):
        return {"path": path, "content": text, "source_uri": "file:///fixture/" + path,
                "observed_at": observed, "sha256": hashlib.sha256(text.encode()).hexdigest()}

    initial = {"schema_version": "v02-file-source-only-v1", "files": [item("source.md", original)]}
    future = {**initial, "files": [*initial["files"], item("new-source.md", new)]}
    host.write_json(root / "input-source.json", initial)
    host.write_json(root / "continuation-source.json", future)
    host.write_json(root / "evaluation-contract.json", {
        "question": "Read the restored detail for an engineering input check",
        "question_date": "2026-09-07", "semantic_evaluation": "NOT_RUN"})
    config.update(source_sha256=host.sha(root / "input-source.json"),
                  post_g_source={"path": "continuation-source.json",
                                 "sha256": host.sha(root / "continuation-source.json")})
    host.write_json(root / "config.json", config)
    report = {"status": "RUNNING", "real_model_calls": 0, "kind": kind}
    try:
        base.prepare(service, config_path=config_path,
                     compose_override=base.LAB / "tools/containers/v02-local-bounded.compose.yaml",
                     runtime_overrides={"MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED"})
        prepare_snapshot(root, initial)
        result = chain.run_chain(root, launch=scripted_launch)
        assert result["status"] == "LOCAL_CHAIN_COMPLETED_EFFECT_UNEVALUATED", result["status"]
        assert len(result["sessions"]) == 5
        frozen = base.read_json(root / "frozen-g-files.json")
        for arm in ALL_ARMS:
            assert all(host.sha(root / arm / "workspace" / name) == digest
                       for name, digest in frozen.items())
            assert not Path("/proc", str(result["sessions"][arm]["pid"])).exists()
        for arm in ALL_ARMS[1:]:
            seed = base.read_json(root / arm / "setup/receipt.json")
            restored = base.read_json(root / arm / "restored-head.json")
            assert restored["payload"] == seed["payload"]
            assert restored["state_version_id"] == seed["state_version_id"]
        observations = result["variant_observations"]
        for value in observations.values():
            assert value["status"] == "INPUT_OBSERVATIONS_RECORDED"
            assert value["B"]["target_presented"] and value["variant"]["target_presented"]
            assert not value["variant"]["initial_detail_prefetched"]
        assert not result["accounting"]["pending"] and not result["accounting"]["violations"]
        report.update(status="FIVE_BRANCH_PUBLIC_COLD_MOCK_INPUT_VERIFIED",
                      observations=observations, mock_requests=result["accounting"]["requests"],
                      mock_ledger_only=True, model_robustness="NOT_EVALUATED")
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        if (service / "runtime.env").exists():
            report["cleanup"] = host.stop_owned(service)
        report["elapsed_seconds"] = time.monotonic() - started
        host.write_json(root / "engineering-result.json", report)
    return report


def run(root: Path, config_path: Path) -> None:
    assert base.read_json(config_path)["model_transport_enabled"] is False
    pin = base.pin(config_path)
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    host.write_json(root / "preflight.json", {
        "pin": pin, "runner_sha256": host.sha(Path(__file__)), "real_model_calls": 0,
        "transport": "MOCK_ONLY", "formal_D4_D5": "NOT_ENTERED"})
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, sorted(affinity)[:2])
    results = []
    try:
        for index, kind in enumerate(("BODY_FIRST", "BODY_LAST", "NON_RESERVED_KEY_REORDER",
                                      "DROP_EMPTY_EDGE_WRAPPERS"), 1):
            case = root / (root.name + "-c" + str(index))
            result = run_case(case, config_path, kind, "L1" if index % 2 else "L2")
            results.append({"root": str(case), **result})
            host.write_json(root / "results.json", results)
            print(json.dumps({"kind": kind, "status": result["status"],
                              "mock_requests": result["mock_requests"]}), flush=True)
    finally:
        os.sched_setaffinity(0, affinity)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--generator", action="store_true")
    parser.add_argument("--cold", choices=ALL_ARMS[1:])
    args = parser.parse_args()
    if args.generator:
        generator(args.root.resolve())
    elif args.cold:
        cold(args.root.resolve(), args.cold)
    else:
        run(args.root.resolve(), args.config.resolve())

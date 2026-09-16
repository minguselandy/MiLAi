"""Zero-generation public MCP isolation check on a new owned PostgreSQL instance."""

from __future__ import annotations

import argparse
import json
import tarfile
import time
import uuid
import zipfile
from pathlib import Path

import run_v02_memory_flow as base
from check_v0210_control import LAB, verify_baseline, write
from milai_lab.methods.state_control import digest
from v02_local_provider import append_event
from v0210_v05_product import observer


def installed_pin(root: Path, installed: Path) -> dict:
    baseline = json.loads((LAB / "configs/v0210-control-e1.json").read_text())
    result = verify_baseline(baseline)
    delivery = LAB.parent / (
        "MiLAi-Product/integrations/mcp/dist/delivery/v0209-final/"
        "milai-mcp-delivery-0.1.15.tar.gz"
    )
    with tarfile.open(delivery) as archive:
        archive.extractall(root, filter="data")
    bundle = root / "milai-mcp-delivery-0.1.15"
    result["installed"] = {}
    for venv, wheel_dir in [("mcp-venv", bundle / "packages"),
                            ("runtime-venv", bundle / "runtime/packages")]:
        for wheel in wheel_dir.glob("*.whl"):
            count = 0
            with zipfile.ZipFile(wheel) as archive:
                for name in archive.namelist():
                    if name.endswith(".py"):
                        actual = installed / venv / "lib/python3.11/site-packages" / name
                        assert actual.read_bytes() == archive.read(name), name
                        count += 1
            result["installed"][wheel.name] = {"sha256": digest(wheel.read_bytes()),
                                               "matching_python_files": count}
        (root / venv).symlink_to(installed / venv, target_is_directory=True)
    with tarfile.open(bundle / "runtime/packages/milai_runtime-0.1.4.tar.gz") as archive:
        archive.extractall(root, filter="data")
    write(root / "product-pin.json", result)
    return result


def isolation(root: Path) -> dict:
    run_id = uuid.uuid4().hex
    receipts = {}
    calls = 0
    snapshot = json.loads((LAB.parent / "MiLAi-Product/contracts/mcp/"
                           "compact-memory-v1.release-0.1.15.tools.json").read_text())
    expected_tools = {row["name"]: row["inputSchema"] for row in
                      snapshot["catalogs"]["compact-memory-v1"]["tools"]}

    def connect(question: str, stage: str):
        return observer(root, root / stage, task=f"synthetic-{run_id}-{question}",
                        principal=f"v0211-{run_id}-{question}",
                        project=f"v0211-{run_id}-{question}")

    def recorded(public, question, tool, arguments):
        nonlocal calls
        started = time.monotonic()
        result = public(tool, arguments)
        calls += 1
        append_event(root / "mcp-calls.jsonl", {
            "question": question, "tool": tool, "arguments": arguments,
            "result": result, "seconds": time.monotonic() - started,
            "accounting_class": "SYNTHETIC_BACKEND_PREFLIGHT",
        })
        return result

    for question in ("a", "b"):
        with connect(question, f"create-{question}") as public:
            catalog = recorded(public, question, None, {})
            assert {row["name"]: row["inputSchema"] for row in
                    catalog["tools"]["tools"]} == expected_tools
            write(root / f"catalog-{question}.json", catalog)
            before_state = recorded(public, question, "milai_working_state_get", {"scope": "TASK"})
            before_notes = recorded(public, question, "milai_memory_list", {
                "selection": {"kind": "NOTE"}, "limit": 100})
            assert run_id not in json.dumps([before_state, before_notes])
            marker = f"synthetic-{run_id}-{question}"
            note = recorded(public, question, "milai_memory_save", {
                "content": marker, "operation_id": f"{question}-note",
                "options": {"action": "ADD_NOTE"}})
            assert not note.get("mcp_error"), note
            state = recorded(public, question, "milai_working_state_update", {
                "scope": "TASK", "expected_version": 0,
                "operation_id": f"{question}-state", "payload": {"marker": marker}})
            assert state["status"] == "ACTIVE" and state["payload"] == {"marker": marker}
            receipts[question] = {"marker": marker, "note": note, "state": state}

    for question, other in (("a", "b"), ("b", "a")):
        with connect(question, f"reopen-{question}") as public:
            state = recorded(public, question, "milai_working_state_get", {"scope": "TASK"})
            assert state["payload"] == {"marker": receipts[question]["marker"]}
            notes = recorded(public, question, "milai_memory_list", {
                "selection": {"kind": "NOTE"}, "limit": 100})
            assert receipts[question]["marker"] in json.dumps(notes)
            assert receipts[other]["marker"] not in json.dumps(notes)
            read = recorded(public, question, "milai_memory_read", {
                "target": {"kind": "NOTE", "id": receipts[question]["note"]["memory_id"]}})
            assert receipts[question]["marker"] in json.dumps(read)
            cross = recorded(public, question, "milai_memory_read", {
                "target": {"kind": "NOTE", "id": receipts[other]["note"]["memory_id"]}})
            assert receipts[other]["marker"] not in json.dumps(cross)
            assert cross.get("mcp_error"), cross
    return {"status": "PASS", "synthetic_scopes": 2, "public_mcp_calls": calls,
            "synthetic_note_writes": 2, "synthetic_state_writes": 2,
            "fresh_mcp_reopen": "PASS", "cross_scope_note_id_read": "DENIED_BOTH_DIRECTIONS",
            "benchmark_agent_memory_mutations": 0, "benchmark_generations": 0,
            "benchmark_judge_requests": 0, "benchmark_raw_tokens": 0,
            "per_question_backend_fit": "FIT_UNVERIFIED_NO_QUALIFIED_FIRST_WAVE",
            "actual_model_image_presentation": "NOT_RUN"}


def run(root: Path, installed: Path) -> dict:
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    pin = installed_pin(root, installed)
    runtime = root / "milai_runtime-0.1.4"
    binary = root / "runtime-venv/bin"
    base._command([str(binary / "milai-ops"), "init", "--env-file", str(root / "runtime.env"),
                   "--blob-root", str(root / "blobs"), "--postgres-port", str(base._free_port()),
                   "--api-port", str(base._free_port())], cwd=runtime)
    with (root / "runtime.env").open("a") as output:
        output.write("\nMILAI_EMBEDDING_PROVIDER=deterministic_hash\n"
                     "MILAI_EMBEDDING_PREWARM=false\n")
    env = base._load_environment(root / "runtime.env")
    override = root / "compose-loopback.yaml"
    override.write_text("services:\n  postgres:\n    network_mode: bridge\n")
    compose = ["docker", "compose", "--project-name", f"v0211-{uuid.uuid4().hex[:12]}-pg",
               "--env-file", str(root / "runtime.env"), "--file", str(runtime / "compose.yaml"),
               "--file", str(override)]
    write(root / "compose-command.json", compose)
    group = base.ProcessGroup(root)
    started = time.monotonic()
    try:
        base._command([*compose, "up", "--detach", "--wait", "postgres"],
                      cwd=runtime, timeout=120)
        migration = base._command([str(binary / "alembic"), "-c", "alembic.ini", "upgrade", "head"],
                                  cwd=runtime, env=base._clean_environment(env), timeout=180)
        (root / "migration.log").write_text(migration.stdout + migration.stderr)
        api = group.start("api", [str(binary / "milai-api")],
                          cwd=root, env=base._clean_environment(env))
        write(root / "services.json", {"api": api.pid})
        base._wait_http(env["MILAI_BASE_URL"] + "/health/ready", api)
        result = isolation(root)
        result.update(seconds=time.monotonic() - started, product_pin=pin,
                      embedding_provider="deterministic_hash", embedding_prewarm=False,
                      worker="NOT_STARTED", external_embedding_model_requests=0)
        write(root / "result.json", result)
        return result
    except Exception as exc:
        write(root / "failure.json", {"type": type(exc).__name__, "message": str(exc),
                                       "benchmark_generations": 0})
        raise
    finally:
        group.stop()
        stopped = base._command([*compose, "stop"], cwd=runtime, check=False)
        write(root / "cleanup.json", {"api_stopped": True,
                                       "compose_stop_returncode": stopped.returncode,
                                       "owned_volume": "RETAINED"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--installed", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve(), args.installed.resolve())))

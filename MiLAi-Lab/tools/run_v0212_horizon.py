"""One frozen Horizon discovery first wave using public MCP and exact source files."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import run_v02_memory_flow as base
from check_v0210_control import LAB, write
from check_v0211_backend import installed_pin
from milai_lab.methods.state_control import digest
from v02_deadline import Deadline, DeadlineExpired
from v02_local_provider import accounting, append_event, read_events
from v02_read_file import read_page
from v02_search_files import search_files
from v0210_v05_product import observer
from v0210_v05_provider import V05Provider

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["tools", "answer"]},
        "answer": {"type": "string"},
        "calls": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object", "additionalProperties": True},
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["action", "answer", "calls"],
    "additionalProperties": False,
}


@contextmanager
def product(root: Path, installed: Path, *, runtime_overrides: dict[str, str] | None = None):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    installed_pin(root, installed)
    runtime = root / "milai_runtime-0.1.4"
    binary = root / "runtime-venv/bin"
    base._command(
        [
            str(binary / "milai-ops"),
            "init",
            "--env-file",
            str(root / "runtime.env"),
            "--blob-root",
            str(root / "blobs"),
            "--postgres-port",
            str(base._free_port()),
            "--api-port",
            str(base._free_port()),
        ],
        cwd=runtime,
    )
    with (root / "runtime.env").open("a") as stream:
        stream.write(
            "\nMILAI_EMBEDDING_PROVIDER=deterministic_hash\nMILAI_EMBEDDING_PREWARM=false\n"
        )
    env = base._load_environment(root / "runtime.env")
    env.update(runtime_overrides or {})
    override = root / "compose-loopback.yaml"
    override.write_text("services:\n  postgres:\n    network_mode: bridge\n")
    compose = [
        "docker",
        "compose",
        "--project-name",
        "v0212-" + uuid.uuid4().hex[:12],
        "--env-file",
        str(root / "runtime.env"),
        "--file",
        str(runtime / "compose.yaml"),
        "--file",
        str(override),
    ]
    write(root / "compose-command.json", compose)
    group = base.ProcessGroup(root)
    try:
        base._command([*compose, "up", "--detach", "--wait", "postgres"], cwd=runtime, timeout=120)
        migration = base._command(
            [str(binary / "alembic"), "-c", "alembic.ini", "upgrade", "head"],
            cwd=runtime,
            env=base._clean_environment(env),
        )
        (root / "migration.log").write_text(migration.stdout + migration.stderr)
        api = group.start(
            "api", [str(binary / "milai-api")], cwd=root, env=base._clean_environment(env)
        )
        write(root / "services.json", {"api": api.pid})
        base._wait_http(env["MILAI_BASE_URL"] + "/health/ready", api)
        yield root
    finally:
        group.stop()
        result = base._command([*compose, "stop"], cwd=runtime, check=False)
        write(
            root / "cleanup.json",
            {
                "api_stopped": True,
                "compose_stop_returncode": result.returncode,
                "owned_volume": "RETAINED",
            },
        )


def initial_page(source: Path) -> dict:
    raw = (source / "history.txt").read_bytes()
    offset = max(0, len(raw) - 4096)
    while offset < len(raw) and raw[offset] & 0xC0 == 0x80:
        offset += 1
    return {
        "path": "history.txt",
        "offset": offset,
        "end_offset": len(raw),
        "total_bytes": len(raw),
        "source_sha256": digest(raw),
        "text": raw[offset:].decode(),
        "view": "PARTIAL_FINAL_PAGE_ENTIRE_SOURCE_READABLE",
    }


def source_call(source: Path, frozen: dict, name: str, args: dict) -> dict:
    if name == "source_read":
        path = args.get("path", "history.txt")
        return read_page(source, path, args.get("offset", 0), 4096, frozen[path])
    result = search_files(source, frozen, args["queries"], args.get("offset", 0))
    # Bound the ordinary search page while preserving a cursor for undisclosed matches.
    while len(json.dumps(result, ensure_ascii=False).encode()) > 8192 and result["hits"]:
        result["hits"].pop()
        result["next_offset"] = args.get("offset", 0) + len(result["hits"])
        result["status"] = "MORE"
    return result


def assemble(profile: dict, catalog: dict, source: Path) -> list[dict]:
    frozen = json.loads((source / "source-index.json").read_text())
    question = json.loads((source / "question.json").read_text())["question"]
    descriptions = [
        {"name": row["name"], "description": row["description"], "inputSchema": row["inputSchema"]}
        for row in catalog["tools"]["tools"]
    ]
    source_tools = [
        {
            "name": "source_search",
            "arguments": {
                "queries": "1 to 8 literal strings",
                "offset": "optional match cursor, default 0",
            },
        },
        {
            "name": "source_read",
            "arguments": {"path": "history.txt", "offset": "optional byte offset, default 0"},
        },
    ]
    return [
        {"role": "system", "content": profile["system"]},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "source_files": frozen,
                    "source_view": initial_page(source),
                    "memory_tools": descriptions,
                    "source_tools": source_tools,
                },
                ensure_ascii=False,
            ),
        },
    ]


@contextmanager
def tool_window(deadline: Deadline):
    signal.setitimer(signal.ITIMER_REAL, min(40, deadline.check("tool_40_seconds")))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, max(0.000001, deadline.end - deadline.clock()))


def cold(root: Path, source: Path, owned: Path, key: str, remaining: float) -> None:
    directory = root / key
    directory.mkdir(mode=0o700, exist_ok=False)
    profile = json.loads((root / "a0-profile.json").read_text())
    frozen = json.loads((source / "source-index.json").read_text())
    assert all(digest((source / path).read_bytes()) == sha for path, sha in frozen.items())
    result = {
        "status": "NOT_RUN",
        "query": key,
        "pid": os.getpid(),
        "tool_calls": 0,
        "memory_mutations": 0,
        "answer": None,
    }
    try:
        with (
            Deadline(time.monotonic(), remaining) as deadline,
            observer(
                owned,
                directory / "mcp",
                task=f"v0212-{key}",
                principal=f"v0212-{key}",
                project=f"v0212-{key}",
            ) as public,
        ):
            catalog = public(None, {})
            tools = catalog["tools"]["tools"]
            assert len(tools) == 8
            tool_names = {row["name"] for row in tools}
            page = initial_page(source)
            write(directory / "catalog.json", catalog)
            write(directory / "initial-presentation.json", page)
            messages = assemble(profile, catalog, source)
            provider = V05Provider(
                directory,
                {"sessions": {key: 3}, "max_generations": 3, "max_raw_tokens": 20000, "seed": 212},
                deadline,
            )
            try:
                write(directory / "model.json", provider.verify())
                for turn in range(3):
                    if turn == 2:
                        messages.append(
                            {"role": "user", "content": "Final turn: deliver your answer now."}
                        )
                    output = provider.generate(key, messages, schema=ACTION_SCHEMA)
                    action = json.loads(output)
                    messages.append({"role": "assistant", "content": output})
                    if action["action"] == "answer":
                        result.update(status="ANSWERED", answer=action["answer"])
                        break
                    if turn == 2:
                        result["status"] = "NO_FINAL_ANSWER"
                        break
                    outputs = []
                    for call in action["calls"]:
                        if result["tool_calls"] >= 6:
                            raise ValueError("TOOL_LIMIT")
                        name, args = call["name"], call["arguments"]
                        result["tool_calls"] += 1
                        started = time.monotonic()
                        with tool_window(deadline):
                            if name in ("source_read", "source_search"):
                                response = source_call(source, frozen, name, args)
                            elif name in tool_names:
                                response = public(name, args)
                            else:
                                response = {"error": "UNKNOWN_TOOL"}
                        mutation = name in (
                            "milai_memory_save",
                            "milai_memory_delete",
                            "milai_working_state_update",
                        )
                        result["memory_mutations"] += int(mutation)
                        row = {
                            "tool": name,
                            "arguments": args,
                            "result": response,
                            "seconds": time.monotonic() - started,
                            "accounting_class": "AGENT_MEMORY_MUTATION"
                            if mutation
                            else "QUERY_READ",
                        }
                        append_event(directory / "tool-ledger.jsonl", row)
                        outputs.append({"name": name, "result": response})
                    messages.append(
                        {
                            "role": "user",
                            "content": json.dumps({"tool_results": outputs}, ensure_ascii=False),
                        }
                    )
            finally:
                provider.close()
    except (Exception, DeadlineExpired) as exc:
        result.update(status="STOPPED_RESOURCE_OR_PROTOCOL_LIMIT", reason=str(exc))
    finally:
        result["accounting"] = accounting(read_events(directory / "provider-ledger.jsonl"))
        result["source_immutable"] = all(
            digest((source / path).read_bytes()) == sha for path, sha in frozen.items()
        )
        write(directory / "result.json", result)


def run(root: Path, admission: Path, installed: Path) -> dict:
    body = (admission / "seal-b.json").read_bytes()
    assert digest(body) == json.loads((admission / "seal-b-sha256.json").read_text())["sha256"]
    seal = json.loads(body)
    assert seal["status"] == "POOL_AND_CONTRACT_READY" and len(seal["first_wave_queries"]) == 4
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    (root / "a0-profile.json").write_bytes((admission / "a0-profile.json").read_bytes())
    write(
        root / "allocation.json",
        {
            "seal_b_sha256": digest(body),
            "queries": seal["first_wave_queries"],
            "max_generations": 12,
            "max_raw_tokens": 80000,
            "max_seconds": 1200,
            "extra_wave_allocation": 0,
        },
    )
    write(
        root / "implementation-pin.json",
        {
            str(path.relative_to(LAB)): digest(path.read_bytes())
            for path in [
                Path(__file__).resolve(),
                LAB / "tools/v0210_v05_provider.py",
                LAB / "tools/v0210_v05_product.py",
                LAB / "tools/v02_read_file.py",
                LAB / "tools/v02_search_files.py",
            ]
        },
    )
    results = {}
    started = time.monotonic()
    try:
        with product(root / "product", installed) as owned:
            for key in seal["first_wave_queries"]:
                remaining = 1200 - (time.monotonic() - started)
                if remaining <= 0:
                    break
                subprocess.run(  # noqa: S603 -- fixed local Host executable and sealed query paths
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--root",
                        str(root),
                        "--cold",
                        key,
                        "--source",
                        str(admission / "online" / key),
                        "--owned",
                        str(owned),
                        "--remaining",
                        str(remaining),
                    ],
                    cwd=LAB,
                    check=True,
                    timeout=remaining,
                )
                results[key] = json.loads((root / key / "result.json").read_text())
                if (
                    results[key]["accounting"]["pending"]
                    or results[key]["accounting"]["violations"]
                ):
                    break
    finally:
        for key in seal["first_wave_queries"]:
            results.setdefault(key, {"status": "NOT_RUN", "reason": "BATCH_STOP"})
        write(
            root / "result.json",
            {
                "queries": results,
                "seconds": time.monotonic() - started,
                "actual_generations": sum(
                    r.get("accounting", {}).get("requests", 0) for r in results.values()
                ),
                "actual_raw_tokens": sum(
                    r.get("accounting", {}).get("raw_tokens", 0) for r in results.values()
                ),
                "scoring": "PENDING_OFFLINE",
            },
        )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--installed", type=Path)
    parser.add_argument("--cold")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--owned", type=Path)
    parser.add_argument("--remaining", type=float)
    args = parser.parse_args()
    if args.cold:
        cold(
            args.root.resolve(),
            args.source.resolve(),
            args.owned.resolve(),
            args.cold,
            args.remaining,
        )
    else:
        print(
            json.dumps(run(args.root.resolve(), args.admission.resolve(), args.installed.resolve()))
        )

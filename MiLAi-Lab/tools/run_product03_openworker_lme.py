#!/usr/bin/env python3
"""Run one opened-development LongMemEval case through real OpenWorker MCP."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from milai_lab.context_preflight import (  # noqa: E402
    material_turn_ordinals,
    source_session_instance_keys,
)

DEFAULT_DATASET_MANIFEST = ROOT / "data/manifests/longmemeval-s-cleaned-500.json"
DEFAULT_SELECTION_MANIFEST = (
    ROOT / "data/labels/product03-opportunity-probe-selection.v0.1.json"
)
DEFAULT_SCOPE_PROJECT = "orchid-release"


class OpenWorkerLmeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]


def _observed_at(value: object) -> str:
    if not isinstance(value, str):
        raise OpenWorkerLmeError("LongMemEval observation date is invalid")
    normalized = re.sub(r"\s+\([^)]+\)", "", value).strip()
    return datetime.strptime(normalized, "%Y/%m/%d %H:%M").replace(tzinfo=UTC).isoformat()


def _load_case(
    dataset_manifest: Path,
    selection_manifest: Path,
    case_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(dataset_manifest.read_text(encoding="utf-8"))
    selection = json.loads(selection_manifest.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("dataset_id") != "LongMemEval-S-cleaned"
        or manifest.get("schema_version") != 1
        or not isinstance(selection, Mapping)
        or selection.get("opened_development_only") is not True
        or selection.get("formal_holdout_consumed") is not False
    ):
        raise OpenWorkerLmeError("opened-development input contract is invalid")
    selected = selection.get("cases")
    if not isinstance(selected, list) or case_id not in {
        str(item.get("case_id")) for item in selected if isinstance(item, Mapping)
    }:
        raise OpenWorkerLmeError("case is not in the opened-development selection")
    root = manifest.get("external_root")
    split_files = manifest.get("split_files")
    file_hashes = manifest.get("file_sha256")
    if (
        not isinstance(root, str)
        or not isinstance(split_files, Mapping)
        or not isinstance(file_hashes, Mapping)
        or not isinstance(split_files.get("population_500"), str)
    ):
        raise OpenWorkerLmeError("dataset manifest is invalid")
    filename = str(split_files["population_500"])
    dataset = Path(root) / filename
    if not dataset.is_file() or _sha256(dataset) != file_hashes.get(filename):
        raise OpenWorkerLmeError("LongMemEval dataset identity mismatch")
    population = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(population, list) or len(population) != 500:
        raise OpenWorkerLmeError("LongMemEval population shape is invalid")
    matches = [item for item in population if item.get("question_id") == case_id]
    if len(matches) != 1 or not isinstance(matches[0], dict):
        raise OpenWorkerLmeError("selected case identity is invalid")
    selection_row = next(
        dict(item)
        for item in selected
        if isinstance(item, Mapping) and item.get("case_id") == case_id
    )
    return dict(matches[0]), selection_row


def _history_events(
    record: Mapping[str, Any], scope_project: str = DEFAULT_SCOPE_PROJECT
) -> list[dict[str, Any]]:
    case_id = str(record["question_id"])
    sessions = record.get("haystack_sessions")
    session_ids = record.get("haystack_session_ids")
    dates = record.get("haystack_dates")
    if (
        not isinstance(sessions, list)
        or not isinstance(session_ids, list)
        or not isinstance(dates, list)
        or not (len(sessions) == len(session_ids) == len(dates))
    ):
        raise OpenWorkerLmeError("LongMemEval session identity is invalid")
    try:
        instances = source_session_instance_keys(session_ids)
    except ValueError as exc:
        raise OpenWorkerLmeError("LongMemEval source session identity is invalid") from exc
    events: list[dict[str, Any]] = []
    for source_session, instance, session, date in zip(
        session_ids, instances, sessions, dates, strict=True
    ):
        if not isinstance(source_session, str):
            raise OpenWorkerLmeError("LongMemEval source session is invalid")
        try:
            ordinals = material_turn_ordinals(session)
        except ValueError as exc:
            raise OpenWorkerLmeError("LongMemEval turn material is invalid") from exc
        if not isinstance(session, list):
            raise AssertionError("validated session changed type")
        session_id = f"lme:{_stable(case_id, 12)}:{_stable(instance, 20)}"
        turn_ids = {ordinal: f"{session_id}:turn:{ordinal}" for ordinal in ordinals}
        for index, ordinal in enumerate(ordinals):
            turn = session[ordinal]
            if not isinstance(turn, Mapping):
                raise AssertionError("validated turn changed type")
            role = turn.get("role")
            content = turn.get("content")
            if role not in {"user", "assistant", "system", "tool"} or not isinstance(
                content, str
            ):
                raise OpenWorkerLmeError("LongMemEval material turn is invalid")
            events.append(
                {
                    "operation_id": "p03-ow-lme-capture-"
                    + _stable(f"{case_id}:{instance}:{ordinal}"),
                    "source_type": "RUNTIME_OBSERVATION",
                    "source_ref": (
                        f"lme://{_stable(case_id, 12)}/{_stable(instance, 20)}/turn/{ordinal}"
                    ),
                    "subject_id": f"longmemeval:{case_id}",
                    "speaker": role,
                    "source_context": {
                        "session_id": session_id,
                        "turn_id": turn_ids[ordinal],
                        "turn_ordinal": ordinal,
                        "round_id": f"{session_id}:round:{ordinal // 2}",
                        "round_ordinal": ordinal // 2,
                        "previous_turn_id": turn_ids[ordinals[index - 1]] if index else None,
                        "next_turn_id": (
                            turn_ids[ordinals[index + 1]]
                            if index + 1 < len(ordinals)
                            else None
                        ),
                    },
                    "observed_at": _observed_at(date),
                    "content": content,
                    "permission_snapshot": {
                        "readable": True,
                        "project_ids": [scope_project],
                    },
                    "confirmation": "CAPTURE",
                    "retention_state": "READABLE",
                    "data_classification": "DEIDENTIFIED",
                }
            )
    return events


def _environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MILAI_") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
    return values


async def _capture(
    args: argparse.Namespace,
    events: Sequence[Mapping[str, Any]],
    environment: Mapping[str, str],
) -> list[dict[str, str]]:
    from mcp import Client, StdioServerParameters, stdio_client

    queue: asyncio.Queue[Mapping[str, Any]] = asyncio.Queue()
    for event in events:
        queue.put_nowait(event)
    receipts: list[dict[str, str]] = []
    lock = asyncio.Lock()

    async def worker() -> None:
        parameters = StdioServerParameters(
            command=str(args.mcp_executable),
            args=["--profile", "submitter", "--max-retries", "0"],
            env={
                "MILAI_BASE_URL": environment["MILAI_BASE_URL"],
                "MILAI_AGENT_TOKEN": environment["MILAI_AGENT_SUBMITTER_TOKEN"],
                "MILAI_AGENT_SCOPE_JSON": json.dumps(
                    {"project_ids": [args.scope_project]}, separators=(",", ":")
                ),
                "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
                "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
                "MILAI_AGENT_MAX_LIMIT": "50",
            },
        )
        async with Client(stdio_client(parameters), mode="2026-07-28") as client:
            while not queue.empty():
                try:
                    event = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                result = await client.call_tool("milai_evidence_capture", dict(event))
                if result.is_error or not isinstance(result.structured_content, dict):
                    raise OpenWorkerLmeError("submitter MCP evidence capture failed")
                evidence_id = result.structured_content.get("evidence_id")
                outbox_id = result.structured_content.get("outbox_id")
                if not isinstance(evidence_id, str) or not isinstance(outbox_id, str):
                    raise OpenWorkerLmeError("capture receipt lost evidence identity")
                async with lock:
                    receipts.append(
                        {
                            "evidence_id": evidence_id,
                            "outbox_id": outbox_id,
                            "source_ref": str(event["source_ref"]),
                        }
                    )
                queue.task_done()

    await asyncio.gather(*(worker() for _ in range(args.capture_concurrency)))
    if len(receipts) != len(events):
        raise OpenWorkerLmeError("capture cardinality mismatch")
    return receipts


async def _wait_projection(
    args: argparse.Namespace,
    receipts: Sequence[Mapping[str, str]],
    environment: Mapping[str, str],
) -> None:
    from mcp import Client, StdioServerParameters, stdio_client

    parameters = StdioServerParameters(
        command=str(args.mcp_executable),
        args=["--profile", "reader-detail", "--max-retries", "0"],
        env={
            "MILAI_BASE_URL": environment["MILAI_BASE_URL"],
            "MILAI_AGENT_TOKEN": environment["MILAI_AGENT_READER_TOKEN"],
            "MILAI_AGENT_SCOPE_JSON": json.dumps(
                {"project_ids": [args.scope_project]}, separators=(",", ":")
            ),
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_AGENT_MAX_LIMIT": "50",
        },
    )
    outbox_ids = [str(item["outbox_id"]) for item in receipts]
    async with Client(stdio_client(parameters), mode="2026-07-28") as client:
        for offset in range(0, len(outbox_ids), 256):
            result = await client.call_tool(
                "milai_projection_readiness_wait",
                {
                    "target_outbox_ids": outbox_ids[offset : offset + 256],
                    "required_projections": ["evidence"],
                    "expected_versions": {"evidence": "evidence-search-v1"},
                    "timeout_ms": 30000,
                    "poll_interval_ms": 50,
                },
            )
            if result.is_error or not isinstance(result.structured_content, dict):
                raise OpenWorkerLmeError("projection readiness MCP call failed")
            if result.structured_content.get("status") != "READY":
                raise OpenWorkerLmeError("evidence projection did not become ready")


def _command(arguments: list[str], timeout: int = 240) -> bytes:
    completed = subprocess.run(  # noqa: S603 - bounded local Docker argv
        arguments, check=False, capture_output=True, timeout=timeout
    )
    if completed.returncode != 0:
        raise OpenWorkerLmeError(f"command failed: {arguments[0]}")
    return completed.stdout


def _native_answer(container: str, title: str, prompt: str) -> tuple[str, str]:
    created = _command(
        [
            "docker",
            "exec",
            container,
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--user",
            "opencode:openworker-local",
            "--request",
            "POST",
            "--header",
            "Content-Type: application/json",
            "--data-binary",
            json.dumps({"title": title}, separators=(",", ":")),
            "http://127.0.0.1:4096/session?directory=%2Fopenworker%2Fruntime",
        ],
        30,
    )
    value = json.loads(created)
    session_id = value.get("id") if isinstance(value, Mapping) else None
    if not isinstance(session_id, str):
        raise OpenWorkerLmeError("OpenCode session identity is missing")
    _command(
        [
            "docker",
            "exec",
            "--workdir",
            "/openworker/runtime",
            "--env",
            "OPENCODE_CONFIG_DIR=/openworker/runtime",
            container,
            "opencode",
            "run",
            "--attach",
            "http://127.0.0.1:4096",
            "--password",
            "openworker-local",
            "--format",
            "json",
            "--model",
            "openworker/Qwen3.6-35B-A3B-FP8",
            "--session",
            session_id,
            "--dir",
            "/openworker/runtime",
            prompt,
        ],
    )
    messages = json.loads(
        _command(
            [
                "docker",
                "exec",
                container,
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--user",
                "opencode:openworker-local",
                (
                    f"http://127.0.0.1:4096/session/{session_id}/message?"
                    "directory=%2Fopenworker%2Fruntime"
                ),
            ],
            30,
        )
    )
    answers = [
        part.get("text")
        for message in messages
        if isinstance(message, Mapping)
        and isinstance(message.get("info"), Mapping)
        and message["info"].get("role") == "assistant"
        for part in message.get("parts", [])
        if isinstance(part, Mapping)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    ]
    if not answers:
        raise OpenWorkerLmeError("native OpenCode operation returned no answer")
    return session_id, str(answers[-1])


def _answer_matches(answer: str, reference: object) -> bool:
    try:
        typed_answer = json.loads(answer)
    except json.JSONDecodeError:
        typed_answer = None
    if isinstance(typed_answer, Mapping) and (
        typed_answer.get("status") == "MEMORY_INSUFFICIENT"
        or typed_answer.get("memory_outcome") == "MEMORY_INSUFFICIENT"
        or typed_answer.get("memory_used") is False
    ):
        return False
    normalized_answer = " ".join(answer.casefold().split())
    normalized_reference = " ".join(str(reference).casefold().split())
    if not normalized_reference:
        return False
    return re.search(
        rf"(?<!\w){re.escape(normalized_reference)}(?!\w)", normalized_answer
    ) is not None


def _write_private(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.capture_concurrency <= 8:
        raise OpenWorkerLmeError("capture concurrency must be 1..8")
    if args.output.exists():
        raise OpenWorkerLmeError("run output already exists")
    if args.scope_project != DEFAULT_SCOPE_PROJECT:
        raise OpenWorkerLmeError("current locked Host fixture permits only orchid-release")
    record, selection = _load_case(
        args.dataset_manifest, args.selection_manifest, args.case_id
    )
    events = _history_events(record, args.scope_project)
    environment = _environment(args.runtime_env)
    if environment.get("MILAI_DATA_MODE") != "DEIDENTIFIED_ALLOWED":
        raise OpenWorkerLmeError("Runtime must explicitly allow deidentified evidence")
    started = time.perf_counter()
    capture_path = args.output.with_name(args.output.stem + ".captures.private.json")
    if capture_path.exists():
        raw_receipts = json.loads(capture_path.read_text(encoding="utf-8"))
        if not isinstance(raw_receipts, list) or len(raw_receipts) != len(events):
            raise OpenWorkerLmeError("capture checkpoint is invalid")
        receipts = [
            {str(key): str(value) for key, value in item.items()}
            for item in raw_receipts
            if isinstance(item, Mapping)
        ]
        if len(receipts) != len(events):
            raise OpenWorkerLmeError("capture checkpoint lost receipt rows")
    else:
        receipts = await _capture(args, events, environment)
        _write_private(capture_path, receipts)
    await _wait_projection(args, receipts, environment)
    prompt = (
        f"Reference date: {record['question_date']}\n"
        f"{record['question']}\n"
        "Answer concisely using only the governed memory supplied for this operation."
    )
    session_id, answer = _native_answer(
        args.container, f"Product03 LME {args.case_id}", prompt
    )
    passed = _answer_matches(answer, record["answer"])
    private = {
        "schema": "milai.product03.openworker-lme.private.v1",
        "run_id": args.run_id,
        "case_id": args.case_id,
        "question_type": record.get("question_type"),
        "family": selection.get("family"),
        "question": record["question"],
        "question_date": record["question_date"],
        "reference_answer": record["answer"],
        "openworker_answer": answer,
        "openworker_session_id": session_id,
        "source_session_count": len(record["haystack_sessions"]),
        "source_turn_count": len(events),
        "evidence_count": len(receipts),
        "evidence_ids_sha256": hashlib.sha256(
            "\n".join(sorted(item["evidence_id"] for item in receipts)).encode()
        ).hexdigest(),
        "passed": passed,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "reference_answer_hidden_until_scoring": True,
        "formal_holdout_consumed": False,
    }
    _write_private(args.output, private)
    return {
        "schema": "milai.product03.openworker-lme.summary.v1",
        "run_id": args.run_id,
        "case_id_sha256": hashlib.sha256(args.case_id.encode()).hexdigest(),
        "question_type": record.get("question_type"),
        "family": selection.get("family"),
        "source_sessions": len(record["haystack_sessions"]),
        "source_turns": len(events),
        "evidence_captured": len(receipts),
        "native_openworker_operations": 1,
        "passed": passed,
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "answer_chars": len(answer),
        "elapsed_ms": private["elapsed_ms"],
        "formal_holdout_consumed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runtime-env", type=Path, required=True)
    parser.add_argument("--mcp-executable", type=Path, required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_DATASET_MANIFEST)
    parser.add_argument("--selection-manifest", type=Path, default=DEFAULT_SELECTION_MANIFEST)
    parser.add_argument("--scope-project", default=DEFAULT_SCOPE_PROJECT)
    parser.add_argument("--capture-concurrency", type=int, default=4)
    return parser


def main() -> None:
    try:
        summary = asyncio.run(_run(_parser().parse_args()))
    except Exception as exc:
        raise SystemExit(
            f"Product-03 OpenWorker LME failed: {type(exc).__name__}: {exc}"
        ) from None
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

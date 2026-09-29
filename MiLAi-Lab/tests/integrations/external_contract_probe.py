"""Native contract replay; real SDK/assets are explicit local_artifacts owners."""

from __future__ import annotations

import copy
import importlib
import itertools
import json
import os
import runpy
import sqlite3
import sys
import tempfile
import time
import uuid
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

LAB = Path(__file__).resolve().parents[2]
SIMPLEMEM_SOURCE = Path(
    os.environ.get("SIMPLEMEM_TEXT_SOURCE", "artifacts/simplemem-text/source")
).resolve()


def encode(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def outcome(action: Any) -> dict[str, Any]:
    try:
        returned = action()
        if hasattr(returned, "model_dump"):
            return {
                "model_dump": returned.model_dump(mode="json"),
                "json_bytes": returned.model_dump_json(),
            }
        return {"returned": encode(returned)}
    except Exception as error:
        return {"exception": type(error).__name__, "message": str(error)}


def fixture_stack(stack: ExitStack) -> None:
    ids = itertools.count(1)
    stack.enter_context(
        patch.object(uuid, "uuid4", lambda: uuid.UUID(f"00000000-0000-4000-8000-{next(ids):012d}"))
    )
    stack.enter_context(patch.object(time, "perf_counter_ns", lambda: 1000))
    stack.enter_context(patch.object(time, "process_time_ns", lambda: 1000))
    stack.enter_context(patch.object(time, "perf_counter", lambda: 1000.0))
    stack.enter_context(patch.object(time, "monotonic", lambda: 1000.0))
    stack.enter_context(patch.object(time, "sleep", lambda _seconds: None))


def mem0_capture(module: Any, directory: Path) -> dict[str, Any]:
    import httpx
    from langchain_core.messages import AIMessage

    from milai_lab.baselines.benchmark_memories import GenerationAdmission, mem0_dependency_identity
    from milai_lab.contracts.scope import FoundationScope
    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
    from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            return datetime(2026, 9, 29, tzinfo=tz)

    import mem0.memory.main as main
    import mem0.memory.storage as storage

    wires, events, configurations = [], [], []
    mode = {"fail": False}

    def send(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        wires.append({"path": request.url.path, "body": body})
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [0.02] * 1024}
                        for index, _value in enumerate(body["input"])
                    ],
                    "usage": {"total_tokens": 3},
                },
            )
        if mode["fail"]:
            raise httpx.ReadTimeout("synthetic native provider outcome unknown")
        return httpx.Response(
            200,
            json={
                "id": "actual-sdk-mock",
                "object": "chat.completion",
                "model": "host",
                "created": 1,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "memory": [
                                        {
                                            "text": "Alice plans Cobalt meeting in Lab REF-A.",
                                            "attributed_to": "user",
                                        }
                                    ]
                                }
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            },
        )

    original = main.Memory.from_config

    def configured(config: Any) -> Any:
        configurations.append(copy.deepcopy(config))
        return original(config)

    budget = RunBudget(RunLimits(), directory / "budget.json")
    result = {
        "sdk_identity": mem0_dependency_identity(),
        "policy": module.MEM0_POLICY,
        "prompt": module.MEM0_SYSTEM_PROMPT,
        "prompt_sha256": module.MEM0_SYSTEM_PROMPT_SHA256,
        "schema": module.MEM0_SEARCH_SCHEMA,
        "schema_sha256": module.MEM0_SEARCH_CONTRACT_SHA256,
    }
    with ExitStack() as stack:
        fixture_stack(stack)
        stack.enter_context(patch.object(main, "datetime", FixedDatetime))
        stack.enter_context(patch.object(storage, "datetime", FixedDatetime))
        stack.enter_context(patch.object(main.Memory, "from_config", configured))
        host = stack.enter_context(
            VLLMClient(
                VLLMConfig("http://mock/v1/", "host", max_tokens=4096, enable_thinking=False),
                budget=budget,
                emit=events.append,
                transport=httpx.MockTransport(send),
            )
        )
        embed = stack.enter_context(
            VLLMClient(
                VLLMConfig("http://mock/v1/", "bge-m3"),
                budget=budget,
                emit=events.append,
                transport=httpx.MockTransport(send),
            )
        )
        admission = GenerationAdmission(1)
        native = module.Mem0NativeRuntime(
            directory / "native", "r", "mem0_native", host, embed, admit_generation=admission
        )
        source = [
            {"role": "user", "id": "u", "content": "Original completed request"},
            {
                "role": "assistant",
                "id": "a",
                "content": "Proposal",
                "tool_calls": [{"id": "c", "name": "business", "args": {}}],
            },
            {
                "role": "tool",
                "id": "t",
                "tool_call_id": "c",
                "status": "success",
                "content": '{"ok":false,"status":"partial","actual_id":"REF-A"}',
            },
            {"role": "assistant", "id": "f", "content": "Actual partial outcome"},
        ]
        try:
            result["add_archive"] = outcome(lambda: native.add_archive("owner", source))
            result["snapshot_owner"] = native.snapshot("owner")
            result["snapshot_foreign"] = native.snapshot("foreign")
            result["admission"] = outcome(lambda: native.add_archive("owner", source))
            scope = FoundationScope("r", "mem0_native", "owner", "query")
            tool = native.archive_tools(scope)[0]
            result["search_tool"] = outcome(lambda: tool.invoke({"query": "REF-A"}, scope.config()))
            result["scope_error"] = outcome(
                lambda: tool.invoke(
                    {"query": "REF-A"},
                    FoundationScope("r", "mem0_native", "foreign", "query").config(),
                )
            )
            connection = native.memory.db.connection
            connection.row_factory = sqlite3.Row
            result["history_schema"] = [
                dict(row)
                for row in connection.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
                )
            ]
            result["history_rows"] = [
                dict(row) for row in connection.execute("SELECT * FROM history")
            ]
        finally:
            native.close()
        reopened = module.Mem0NativeRuntime(directory / "native", "r", "mem0_native", host, embed)
        try:
            result["reopened_snapshot"] = reopened.snapshot("owner")
            result["reopened_search"] = reopened.search_archive("owner", "REF-A")
            result["read_only_snapshot"] = reopened.snapshot("owner")
        finally:
            reopened.close()
        unknown = module.Mem0NativeRuntime(directory / "unknown", "r", "mem0_native", host, embed)
        try:
            mode["fail"] = True
            live_scope = FoundationScope("r", "mem0_native", "diagnostic:case", "s")
            def action() -> Any:
                return unknown.after_turn(
                    "case", live_scope, 0, "Unknown receipt", [AIMessage(content="Actual final")]
                )
            result["unknown_first"] = outcome(action)
            result["unknown_repeat"] = outcome(action)
            result["unknown_ledger_bytes"] = (directory / "unknown/mem0-ingestion.json").read_text()
        finally:
            unknown.close()
        result["provider_errors"] = [
            outcome(
                lambda change=change: module._ChatCompletions(host, native.lock).create(
                    **{
                        "model": "host",
                        "messages": [],
                        "temperature": 0,
                        "max_tokens": 4096,
                        "top_p": 1.0,
                        **change,
                    }
                )
            )
            for change in (
                {"seed": 7},
                {"model": "other"},
                {"temperature": 0.5},
                {"max_tokens": 2},
                {"top_p": 0.5},
            )
        ]
        result["embedding_errors"] = [
            outcome(
                lambda change=change: module._Embeddings(embed, native.lock).create(
                    **{
                        "model": "bge-m3",
                        "input": ["one", "two"],
                        "encoding_format": "float",
                        **change,
                    }
                )
            )
            for change in ({"model": "other"}, {"encoding_format": "base64"}, {"dimensions": 4})
        ]
        mode["fail"] = False
        result["embedding_order"] = encode(
            module._Embeddings(embed, native.lock)
            .create(model="bge-m3", input=["one", "two"], encoding_format="float")
            .data
        )
        result["configurations"] = configurations
        result["wires"], result["events"], result["budget"] = wires, events, budget.state
    return encode(result)


def simplemem_capture(module: Any, directory: Path) -> dict[str, Any]:
    import httpx

    from milai_lab.contracts.scope import FoundationScope

    sys.path.insert(0, str(LAB / "tests/unit"))
    helper = runpy.run_path(str(LAB / "tests/unit/test_simplemem_native.py"))
    # Select the owner under test while retaining the existing native MockHTTP fixture.
    helper["sdk"].__globals__["SimpleMemTextRuntime"] = module.SimpleMemTextRuntime
    helper["sdk"].__globals__["POLICY"] = module.POLICY
    policy = {**module.POLICY, "source_root": str(SIMPLEMEM_SOURCE)}
    result = {
        "sdk_identity": module.dependency_identity(policy),
        "policy": module.POLICY,
        "schema": module.SEARCH_SCHEMA,
        "description": module.SEARCH_DESCRIPTION,
    }
    with ExitStack() as stack:
        fixture_stack(stack)
        for case, replies in (
            ("success", [helper["entry"](), *helper["plans"](reflection=True), *helper["plans"]()]),
            ("legal_empty", [[]]),
            (
                "recovered_transport",
                [httpx.ReadTimeout("synthetic transport failure"), helper["entry"]()],
            ),
            ("recovered_parse", ["bad JSON", helper["entry"]()]),
            ("exhausted", ["bad JSON"] * 3),
            ("admission", []),
            ("store_search_error", [helper["entry"](), *helper["plans"]()]),
            ("store_insert_error", [helper["entry"]()]),
        ):

            def reject() -> None:
                raise ValueError("PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED")

            with helper["sdk"](
                directory / case, replies, admission=reject if case == "admission" else None
            ) as (native, host, _embed, wires, events):
                row = {}
                if case == "store_insert_error":

                    def broken(*_args: Any, **_kwargs: Any) -> Any:
                        raise OSError("synthetic local store error")

                    stack.enter_context(patch.object(native.vector.backend.table, "add", broken))
                row["add"] = outcome(
                    lambda: native.add_archive(
                        "owner",
                        [
                            {
                                "role": "user",
                                "event_id": "source",
                                "content": "Archived Cobalt meeting",
                            }
                        ],
                    )
                )
                row["snapshot"] = native.snapshot("owner")
                if case in {"success", "store_search_error"}:
                    if case == "store_search_error":

                        def broken_search(*_args: Any, **_kwargs: Any) -> Any:
                            raise OSError("synthetic local store error")

                        stack.enter_context(
                            patch.object(native.vector.backend.table, "search", broken_search)
                        )
                    row["search"] = outcome(
                        lambda: native.search_archive("owner", "Cobalt meeting")
                    )
                if case == "success":
                    tool = native.archive_tools(
                        FoundationScope("r", "simplemem_text", "owner", "s")
                    )[0]
                    row["tool"] = outcome(
                        lambda tool=tool: tool.invoke(
                            {"query": "Cobalt meeting"},
                            FoundationScope("r", "simplemem_text", "owner", "s").config(),
                        )
                    )
                    row["owner_error"] = outcome(lambda: native.snapshot("foreign"))
                    row["database_schema"] = str(native.vector.backend.table.schema)
                    row["database_rows"] = native.vector.backend.table.to_arrow().to_pylist()
                    row["read_only_snapshot"] = native.snapshot("owner")
                    reopened = module.SimpleMemTextRuntime(
                        directory / case / "native",
                        "r",
                        "simplemem_text",
                        "owner",
                        host,
                        _embed,
                        policy,
                        admit_generation=lambda: None,
                    )
                    row["reopened_snapshot"] = reopened.snapshot("owner")
                    row["reopened_builder_previous"] = reopened.builder.previous_entries
                    row["scope_file_bytes"] = (directory / case / "native/scope.json").read_text()
                    reopened.close()
                row["wires"], row["events"], row["budget"] = wires, events, host.budget.state
                result[case] = row
        result["policy_errors"] = [
            outcome(
                lambda drift=drift: module.validate_simplemem(
                    {
                        "embedding": {"model": "bge-m3"},
                        "embedding_dimension": 1024,
                        "second_external": {"simplemem_text": {**policy, **drift}},
                    }
                )
            )
            for drift in ({"window_size": 10}, {"enable_planning": False}, {"extra": True})
        ]
    return encode(result)


def io_capture(directory: Path) -> dict[str, Any]:
    from milai_lab.harness.contextual_artifacts import digest, read_json, write_json

    value = {"unknown": {"retain": True}, "unicode": "保留原文", "ordered": [2, 1]}
    target = directory / "nested/artifact.json"
    write_json(target, value)
    return {
        "digest": digest(value),
        "json_bytes": target.read_text(),
        "roundtrip": read_json(target),
        "temporary_left": target.with_suffix(target.suffix + ".tmp").exists(),
        "missing": outcome(lambda: read_json(directory / "missing.json")),
    }


def capture(component: str, canonical: bool) -> dict[str, Any]:
    module_name = (
        "milai_lab.integrations.memory." + component
        if canonical
        else "milai_lab.runners." + ("mem0_native" if component == "mem0" else "simplemem_native")
    )
    module = importlib.import_module(module_name)
    with tempfile.TemporaryDirectory(prefix="milai-v12-native-") as temporary:
        directory = Path(temporary)
        captured = (mem0_capture if component == "mem0" else simplemem_capture)(module, directory)
        captured["artifact_io"] = io_capture(directory)
        # Temporary roots are fixed fixture inputs; runtime values are retained.
        return json.loads(json.dumps(captured, ensure_ascii=False).replace(str(directory), "<TMP>"))

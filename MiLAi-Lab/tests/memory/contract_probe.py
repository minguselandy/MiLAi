"""Synthetic pre-move contracts; clocks and UUIDs are fixed only by this fixture."""

from __future__ import annotations

import asyncio
import copy
import importlib
import json
import tempfile
import time
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

STAMP = "2026-09-29T00:00:00Z"
MEMORY_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000099"


def encode(value: Any) -> Any:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
        )
    )


def outcome(action: Any) -> dict[str, Any]:
    try:
        result = action()
        if hasattr(result, "model_dump"):
            return {
                "model_dump": result.model_dump(mode="json"),
                "json_bytes": result.model_dump_json(),
            }
        return {"returned": encode(result)}
    except Exception as error:
        return {"exception": type(error).__name__, "message": str(error)}


def imports(canonical: bool) -> SimpleNamespace:
    stem = "milai_lab.memory." if canonical else "milai_lab.baselines.langmem_"
    strict = importlib.import_module(stem + "strict_tools")
    revision = importlib.import_module(stem + "revision_store")
    mcp = importlib.import_module(stem + "mcp")
    scope = importlib.import_module(
        "milai_lab.contracts.scope" if canonical else "milai_lab.baselines.langmem_agent"
    )
    read = importlib.import_module(
        "milai_lab.memory.read_tools" if canonical else "milai_lab.baselines.langmem_agent"
    )
    return SimpleNamespace(
        strict=strict,
        revision=revision,
        mcp=mcp,
        Scope=scope.FoundationScope,
        read=read.create_memory_read_tool,
    )


def store_class() -> Any:
    from langgraph.store.memory import InMemoryStore

    class RecordingStore(InMemoryStore):
        def __init__(self, failure: str | None = None) -> None:
            super().__init__()
            self.calls: list[dict[str, Any]] = []
            self.failure = failure

        def record(self, name: str, args: Any, kwargs: Any) -> None:
            self.calls.append({"method": name, "args": encode(args), "kwargs": encode(kwargs)})
            if self.failure == name:
                raise OSError("synthetic Store " + name + " failed")

        def get(self, *args: Any, **kwargs: Any) -> Any:
            self.record("get", args, kwargs)
            return super().get(*args, **kwargs)

        def put(self, *args: Any, **kwargs: Any) -> Any:
            self.record("put", args, kwargs)
            return super().put(*args, **kwargs)

        def delete(self, *args: Any, **kwargs: Any) -> Any:
            self.record("delete", args, kwargs)
            return super().delete(*args, **kwargs)

        def search(self, *args: Any, **kwargs: Any) -> Any:
            self.record("search", args, kwargs)
            return super().search(*args, **kwargs)

        async def aget(self, *args: Any, **kwargs: Any) -> Any:
            self.record("aget", args, kwargs)
            return await super().aget(*args, **kwargs)

        async def aput(self, *args: Any, **kwargs: Any) -> Any:
            self.record("aput", args, kwargs)
            return await super().aput(*args, **kwargs)

        async def adelete(self, *args: Any, **kwargs: Any) -> Any:
            self.record("adelete", args, kwargs)
            return await super().adelete(*args, **kwargs)

        def batch(self, ops: Any) -> Any:
            operations = list(ops)
            self.record(
                "batch", [dict(type=type(op).__name__, **op._asdict()) for op in operations], {}
            )
            return super().batch(operations)

        async def abatch(self, ops: Any) -> Any:
            operations = list(ops)
            self.record(
                "abatch", [dict(type=type(op).__name__, **op._asdict()) for op in operations], {}
            )
            return await super().abatch(operations)

    return RecordingStore


def strict_capture(modules: SimpleNamespace, Store: Any) -> dict[str, Any]:
    from langchain_core.utils.function_calling import convert_to_openai_tool

    result: dict[str, Any] = {}
    config = {"configurable": {"user_id": "synthetic-owner"}}
    steps = [
        ("create-no-content", "manage_memory", {}),
        ("create-null", "manage_memory", {"content": None}),
        ("create-with-id", "manage_memory", {"content": "rejected", "id": MEMORY_ID}),
        ("create", "manage_memory", {"content": "保留原文"}),
        ("read-found", "read_memory", {"id": MEMORY_ID}),
        ("update-null", "manage_memory", {"action": "update", "id": MEMORY_ID}),
        ("update-no-id", "manage_memory", {"action": "update", "content": "rejected"}),
        ("update-unknown", "manage_memory", {"action": "update", "id": UNKNOWN_ID, "content": "x"}),
        (
            "update-noop",
            "manage_memory",
            {"action": "update", "id": MEMORY_ID, "content": "保留原文"},
        ),
        ("update", "manage_memory", {"action": "update", "id": MEMORY_ID, "content": "新原文"}),
        ("delete-no-id", "manage_memory", {"action": "delete"}),
        ("delete", "manage_memory", {"action": "delete", "id": MEMORY_ID}),
        ("delete-unknown", "manage_memory", {"action": "delete", "id": MEMORY_ID}),
        ("read-missing", "read_memory", {"id": MEMORY_ID}),
        ("invalid-id", "read_memory", {"id": "invalid"}),
    ]
    for asynchronous in (False, True):
        store = Store()
        strict = modules.strict.create_strict_manage_memory_tool(("langmem", "{user_id}"), store)
        read = modules.read(("langmem", "{user_id}"), store)
        tools = {"manage_memory": strict, "read_memory": read}
        cases = []
        for label, name, args in steps:
            store.calls.clear()
            tool = tools[name]
            call = {"type": "tool_call", "name": name, "id": label, "args": args}
            action = (
                (lambda tool=tool, call=call: asyncio.run(tool.ainvoke(call, config=config)))
                if asynchronous
                else (lambda tool=tool, call=call: tool.invoke(call, config=config))
            )
            cases.append(
                {
                    "case_id": label,
                    "outcome": outcome(action),
                    "store_calls": copy.deepcopy(store.calls),
                }
            )
        result["async" if asynchronous else "sync"] = {
            "catalog": [convert_to_openai_tool(strict), convert_to_openai_tool(read)],
            "cases": cases,
        }
        failures = []
        for method, args in (
            ("put", {"content": "store failure"}),
            ("get", {"action": "update", "id": MEMORY_ID, "content": "store failure"}),
            ("delete", {"action": "delete", "id": MEMORY_ID}),
        ):
            store = Store()
            store.put(("langmem", "synthetic-owner"), MEMORY_ID, {"content": "unchanged"})
            store.calls.clear()
            store.failure = ("a" + method) if asynchronous else method
            strict = modules.strict.create_strict_manage_memory_tool(
                ("langmem", "{user_id}"), store
            )
            call = {"type": "tool_call", "name": "manage_memory", "id": method, "args": args}
            action = (
                (lambda strict=strict, call=call: asyncio.run(strict.ainvoke(call, config=config)))
                if asynchronous
                else (lambda strict=strict, call=call: strict.invoke(call, config=config))
            )
            failures.append(
                {
                    "case_id": method,
                    "outcome": outcome(action),
                    "store_calls": copy.deepcopy(store.calls),
                }
            )
        result["async" if asynchronous else "sync"]["failures"] = failures
    return result


def direct_peer(peer: Any) -> None:
    class Portal:
        def call(self, action: Any) -> Any:
            return asyncio.run(action())

    class Client:
        async def call_tool(self, name: str, args: Any, meta: Any) -> Any:
            return await peer._call_tool(
                SimpleNamespace(meta=meta), SimpleNamespace(name=name, arguments=args)
            )

        async def read_resource(self, uri: str, meta: Any) -> Any:
            return await peer._read_resource(SimpleNamespace(meta=meta), SimpleNamespace(uri=uri))

    peer.portal, peer.client = Portal(), Client()


def mcp_capture(modules: SimpleNamespace, Store: Any) -> dict[str, Any]:
    scope = modules.Scope("synthetic-run", "synthetic-arm", "synthetic-owner", "session")
    config = scope.config()
    store = Store()
    events: list[dict[str, Any]] = []
    peer = modules.mcp.MemoryMCP(
        store, scope.run_id, scope.arm_id, scope.user_id, emit=events.append
    )
    result = {
        "protocol": modules.mcp.MCP_PROTOCOL,
        "resource": modules.mcp.RECORDS_RESOURCE,
        "scope": peer.scope,
        "namespace": peer.namespace,
        "catalog": peer.catalog,
        "list_tools": outcome(lambda: asyncio.run(peer._list_tools(None, None))),
    }
    direct_peer(peer)
    cases = []
    for label, name, args in (
        ("create", "manage_memory", {"content": "synthetic memory"}),
        (
            "update-noop",
            "manage_memory",
            {"action": "update", "id": MEMORY_ID, "content": "synthetic memory"},
        ),
        ("read", "read_memory", {"id": MEMORY_ID}),
        ("read-invalid", "read_memory", {"id": "invalid"}),
        ("missing-content", "manage_memory", {"action": "update", "id": MEMORY_ID}),
        ("search", "search_memory", {"query": "memory", "limit": 3}),
        ("delete", "manage_memory", {"action": "delete", "id": MEMORY_ID}),
        ("read-missing", "read_memory", {"id": MEMORY_ID}),
    ):
        store.calls.clear()
        cases.append(
            {
                "case_id": label,
                "outcome": outcome(
                    lambda name=name, args=args, label=label: peer.call(
                        name, args, label, origin="host", config=config
                    )
                ),
                "store_calls": copy.deepcopy(store.calls),
            }
        )
    result["calls"] = cases
    result["scope_errors"] = [
        outcome(
            lambda: peer.records(
                modules.Scope(scope.run_id, scope.arm_id, "foreign", "session").config()
            )
        ),
        outcome(lambda: peer.tools[0].invoke({"name": "manage_memory"}, config=config)),
    ]
    for index in range(65):
        store.put(
            peer.namespace,
            str(uuid.UUID(int=index + 1)),
            {"content": f"synthetic-{index}", "unknown": {"retain": True}},
        )
    store.put((*peer.namespace[:3], "foreign"), UNKNOWN_ID, {"content": "foreign"})
    store.calls.clear()
    result["records"] = peer.records(config)
    result["pagination_store_calls"] = copy.deepcopy(store.calls)
    result["pagination_event"] = events[-1]
    result["async_read"] = outcome(
        lambda: asyncio.run(
            peer.tools[2].ainvoke(
                {
                    "type": "tool_call",
                    "name": "read_memory",
                    "id": "async-read",
                    "args": {"id": str(uuid.UUID(int=1))},
                },
                config=config,
            )
        )
    )
    readonly = modules.mcp.MemoryMCP(
        store, scope.run_id, scope.arm_id, scope.user_id, read_only=True
    )
    direct_peer(readonly)
    result["readonly_catalog"] = readonly.catalog
    store.calls.clear()
    result["readonly_write"] = outcome(
        lambda: readonly.call(
            "manage_memory", {"content": "forbidden"}, "forbidden", origin="host", config=config
        )
    )
    result["readonly_write_store_calls"] = copy.deepcopy(store.calls)
    transport_calls = []

    class BrokenClient:
        async def call_tool(self, *args: Any, **kwargs: Any) -> Any:
            transport_calls.append(encode([args, kwargs]))
            raise RuntimeError("synthetic uncertain transport outcome")

    readonly.client = BrokenClient()
    result["transport_failure"] = outcome(
        lambda: readonly.call(
            "read_memory", {"id": MEMORY_ID}, "transport-failure", origin="host", config=config
        )
    )
    result["transport_attempts"] = len(transport_calls)
    result["bindings_after_failure"] = len(readonly._bindings)
    return result


def schema(conn: Any) -> list[Any]:
    return [
        list(row)
        for row in conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        )
    ]


def revision_capture(modules: SimpleNamespace, Store: Any, directory: Path) -> dict[str, Any]:
    from langchain_core.messages import AIMessage
    from langgraph.prebuilt.tool_node import ToolCallRequest

    from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver

    sidecar = modules.revision.RevisionSidecar(directory / "revision.sqlite")
    sidecar.conn.create_function("datetime", 1, lambda _value: "2026-09-29 00:00:00")
    observer = ProvenanceObserver(sidecar, "synthetic-run", "synthetic-arm")
    scope = modules.Scope("synthetic-run", "synthetic-arm", "synthetic-owner", "session")
    observer.begin_public_message(scope, 0, "Synthetic only")
    inner = Store()
    observed = modules.revision.ObservedStore(inner, observer)
    strict = modules.strict.create_strict_manage_memory_tool(("langmem", "{user_id}"), observed)
    receipts = []
    for index, args in enumerate(
        (
            {"content": "first"},
            {"action": "update", "id": MEMORY_ID, "content": "first"},
            {"action": "update", "id": MEMORY_ID, "content": "second"},
            {"action": "delete", "id": MEMORY_ID},
            {"action": "delete", "id": MEMORY_ID},
            {"content": "recreated"},
        )
    ):
        call = {
            "name": "manage_memory",
            "args": args,
            "id": f"revision-call-{index}",
            "type": "tool_call",
        }
        request = ToolCallRequest(
            tool_call=call,
            tool=strict,
            state={
                "messages": [AIMessage(content="", id=f"generation-{index}", tool_calls=[call])]
            },
            runtime=SimpleNamespace(config=scope.config()),
        )
        receipts.append(
            outcome(
                lambda request=request, call=call: observer.run_tool(
                    request, lambda _request: strict.invoke(call, config=scope.config())
                )
            )
        )
    tables = (
        "bodies",
        "observations",
        "tool_calls",
        "operations",
        "revisions",
        "searches",
        "requests",
        "request_material",
        "assistant_lineage",
    )
    result = {
        "receipts": receipts,
        "store_calls": inner.calls,
        "rows": {table: sidecar.rows(table) for table in tables},
        "schema": schema(sidecar.conn),
        "costs": sidecar.costs(),
        "async_failure": outcome(lambda: asyncio.run(observed.abatch([]))),
    }
    sidecar.close()
    reopened = modules.revision.RevisionSidecar(directory / "revision.sqlite")
    result["reopen_rows"] = {table: reopened.rows(table) for table in tables}
    result["unresolved"] = reopened.unresolved()
    reopened.close()
    return result


def application_capture(modules: SimpleNamespace, directory: Path) -> dict[str, Any]:
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.prebuilt.tool_node import ToolCallRequest

    from milai_lab.application.journal import BusinessActionJournal
    from milai_lab.application.recovery import recover_pending_application_call
    from milai_lab.application.tools import BUSINESS_NAMES, BUSINESS_SCHEMAS, _business_tools
    from milai_lab.application.world import ApplicationWorld
    from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver

    world_path = directory / "application.sqlite"
    world = ApplicationWorld(world_path, False)
    scope = modules.Scope("synthetic-business", "arm", "owner", "application:session")
    tools = {tool.name: tool for tool in _business_tools(world, scope.user_id)}
    target = {
        "item_key": "Synthetic item",
        "quantity": 2,
        "destination": "Synthetic destination",
        "packing": "Synthetic packing",
    }
    binding = {
        "run_id": scope.run_id,
        "arm_id": scope.arm_id,
        "owner": scope.user_id,
        "thread_id": scope.config()["configurable"]["thread_id"],
        "public_index": 0,
        "message_id": "synthetic-public",
        "task_id": "synthetic-task",
        "operations": [
            {
                "operation_id": "reserve",
                "tool": "reserve_and_label",
                "args": target,
                "target": target,
            },
            {
                "operation_id": "query",
                "tool": "get_reservation",
                "args": {"item_key": target["item_key"]},
                "target": target,
            },
            {
                "operation_id": "label",
                "tool": "complete_label",
                "args": {},
                "target": target,
                "reservation_from": "query",
                "depends_on": ["query"],
                "retry": "no_effect",
            },
        ],
    }
    journal_path = directory / "business.json"
    journal = BusinessActionJournal(journal_path, BUSINESS_NAMES, application_protection=True)
    journal.bind_request(binding)

    def request(name: str, args: Any, call_id: str) -> Any:
        call = {"name": name, "args": args, "id": call_id, "type": "tool_call"}
        return ToolCallRequest(
            tool_call=call,
            tool=tools[name],
            state={
                "messages": [
                    HumanMessage(content="Synthetic task", id="synthetic-public"),
                    AIMessage(content="", id="generation-" + call_id, tool_calls=[call]),
                ]
            },
            runtime=SimpleNamespace(config=scope.config()),
        )

    def execute(item: Any) -> Any:
        return tools[item.tool_call["name"]].invoke(item.tool_call)

    receipts = []
    for name, args, call_id in (
        ("reserve_and_label", target, "reserve"),
        ("get_reservation", {"item_key": target["item_key"]}, "query"),
        ("complete_label", {"reservation_id": "RSV-" + MEMORY_ID}, "label-no-effect"),
    ):
        receipts.append(
            outcome(
                lambda name=name, args=args, call_id=call_id: journal(
                    request(name, args, call_id), execute
                )
            )
        )
    world.set_label_available("synthetic-availability", True)
    receipts.append(
        outcome(
            lambda: journal(
                request("complete_label", {"reservation_id": "RSV-" + MEMORY_ID}, "label-retry"),
                execute,
            )
        )
    )
    result = {
        "schemas": BUSINESS_SCHEMAS,
        "receipts": receipts,
        "world": world.snapshot(),
        "schema": schema(world.conn),
        "journal_json_bytes": journal_path.read_text(),
    }
    world.close()
    world = ApplicationWorld(world_path, False)
    result["world_reopened"] = world.snapshot()
    world.close()

    world = ApplicationWorld(directory / "unknown.sqlite", False)
    tools = {tool.name: tool for tool in _business_tools(world, scope.user_id)}
    unknown_path = directory / "unknown-business.json"

    def lost_receipt(_row: Any, _response: Any) -> None:
        raise RuntimeError("synthetic receipt lost after committed reservation")

    unknown = BusinessActionJournal(
        unknown_path, BUSINESS_NAMES, application_protection=True, response_hook=lost_receipt
    )
    unknown.bind_request(binding)
    original = request("reserve_and_label", target, "unknown-reserve")
    result["unknown_call"] = outcome(lambda: unknown(original, execute))
    unknown.response_hook = None
    sidecar = modules.revision.RevisionSidecar(directory / "recovery.sqlite")
    sidecar.conn.create_function("datetime", 1, lambda _value: "2026-09-29 00:00:00")
    observer = ProvenanceObserver(sidecar, scope.run_id, scope.arm_id)
    updates = []
    checkpoint = SimpleNamespace(
        get_state=lambda _config: SimpleNamespace(values=original.state, next=("tools",)),
        update_state=lambda config, state, **kwargs: updates.append(
            {
                "config": config,
                "messages": [message.model_dump(mode="json") for message in state["messages"]],
                "kwargs": kwargs,
            }
        ),
    )
    result["real_query_recovery"] = outcome(
        lambda: recover_pending_application_call(
            checkpoint, scope, unknown, world, SimpleNamespace(observer=observer)
        )
    )
    result["recovery_updates"] = updates
    result["unknown_journal_json_bytes"] = unknown_path.read_text()
    result["unknown_world"] = world.snapshot()
    sidecar.close()
    world.close()
    return result


def capture_contracts(canonical: bool = False) -> dict[str, Any]:
    import langgraph.store.memory as store_module

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            return datetime(2026, 9, 29, tzinfo=UTC)

    modules = imports(canonical)
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        stack.enter_context(patch.object(store_module, "datetime", FixedDatetime))
        stack.enter_context(patch.object(uuid, "uuid4", lambda: uuid.UUID(MEMORY_ID)))
        stack.enter_context(patch.object(time, "strftime", lambda *_args: STAMP))
        stack.enter_context(patch.object(time, "perf_counter_ns", lambda: 1000))
        stack.enter_context(patch.object(time, "process_time_ns", lambda: 1000))
        Store = store_class()
        directory = Path(temporary)
        result = {
            "strict": strict_capture(modules, Store),
            "mcp": mcp_capture(modules, Store),
            "revision": revision_capture(modules, Store, directory),
            "application": application_capture(modules, directory),
            "scope": {
                "config": modules.Scope("run", "arm", "owner", "session").config(),
                "empty_error": outcome(
                    lambda: modules.Scope("", "arm", "owner", "session").config()
                ),
            },
        }
        return encode(result)

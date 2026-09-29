"""Scope-bound MCP HTTP transport over the existing ordinary-memory tools/Store."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import Context, copy_context
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import anyio
import httpx2
import uvicorn
from anyio.from_thread import start_blocking_portal
from jsonschema import ValidationError, validate  # type: ignore[import-untyped]
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.store.base import BaseStore
from langmem import create_search_memory_tool  # type: ignore[import-untyped]
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    ReadResourceResult,
    TextContent,
    TextResourceContents,
    Tool,
)
from pydantic import ValidationError as ArgumentValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from milai_lab.baselines.langmem_strict_tools import create_strict_manage_memory_tool

MCP_PROTOCOL = "2026-07-28"
RECORDS_RESOURCE = "milai://memory/records"


class _RemoteTool(BaseTool):
    peer: Any

    def _run(self, **kwargs: Any) -> Any:
        raise ValueError("MCP_FULL_TOOL_CALL_REQUIRED")

    def invoke(self, input: Any, config: RunnableConfig | None = None,
               **kwargs: Any) -> ToolMessage:
        if (not isinstance(input, dict) or input.get("type") != "tool_call"
                or input.get("name") != self.name or not isinstance(input.get("id"), str)
                or not input["id"] or not isinstance(input.get("args"), dict)):
            raise ValueError("MCP_FULL_TOOL_CALL_REQUIRED")
        self.peer.check_scope(config)
        return cast(ToolMessage, self.peer.call(
            self.name, input["args"], input["id"], origin="host", config=config))

    async def ainvoke(self, input: Any, config: RunnableConfig | None = None,
                      **kwargs: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(lambda: self.invoke(input, config, **kwargs))


class MemoryMCP:
    """One owner, actual loopback HTTP, and the runtime's existing Store and budget owner.

    The short-lived binding carries execution context across HTTP, never record bodies.
    Unknown transport outcomes are raised; calls are not automatically resubmitted.
    """

    def __init__(self, store: BaseStore, run_id: str, arm_id: str, user_id: str, *,
                 emit: Callable[[dict[str, Any]], None] | None = None,
                 history_tool: BaseTool | None = None, timeout: float = 180,
                 read_only: bool = False) -> None:
        # Local import avoids a module cycle with build_agent's optional peer parameter.
        from milai_lab.baselines.langmem_agent import create_memory_read_tool

        self.store = store
        self.scope = {"foundation_run_id": run_id, "arm_id": arm_id, "user_id": user_id}
        self.namespace = ("langmem", run_id, arm_id, user_id)
        self.emit = emit
        self.timeout = timeout
        if type(read_only) is not bool:
            raise ValueError("MCP_MEMORY_READ_ONLY_INVALID")
        self.read_only = read_only
        local = [*([] if read_only else [
                     create_strict_manage_memory_tool(self.namespace, store)]),
                 create_search_memory_tool(namespace=self.namespace, store=store),
                 create_memory_read_tool(self.namespace, store)]
        if history_tool is not None:
            local.append(history_tool)
        self.local_tools = {tool.name: tool for tool in local}
        self.catalog = [convert_to_openai_tool(tool) for tool in local]
        self.tools = tuple(_RemoteTool(name=row["function"]["name"],
            description=row["function"]["description"],
            args_schema=row["function"]["parameters"], peer=self) for row in self.catalog)
        self._bindings: dict[str, tuple[Context, dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._stack: ExitStack | None = None
        self.client: Any = None
        self.portal: Any = None

    def check_scope(self, config: RunnableConfig | None) -> None:
        cfg = (config or {}).get("configurable", {})
        if any(cfg.get(key) != value for key, value in self.scope.items()):
            raise ValueError("MCP_MEMORY_SCOPE_CHANGED")

    def _emit(self, event: dict[str, Any]) -> None:
        if self.emit is not None:
            self.emit({"event": "langmem_mcp", "scope": self.scope, **event})

    def _binding(self, ctx: Any) -> tuple[Context, dict[str, Any]]:
        meta = ctx.meta or {}
        if meta.get("milai_scope") != self.scope:
            raise ValueError("MCP_MEMORY_SCOPE_CHANGED")
        binding = self._bindings.pop(meta.get("milai_binding", ""), None)
        if binding is None:
            raise ValueError("MCP_MEMORY_BINDING_UNKNOWN")
        return binding

    async def _list_tools(self, ctx: Any, params: Any) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name=row["function"]["name"],
            description=row["function"]["description"],
            input_schema=row["function"]["parameters"]) for row in self.catalog])

    async def _call_tool(self, ctx: Any, params: Any) -> CallToolResult:
        context, binding = self._binding(ctx)
        if params.name not in self.local_tools or binding["name"] != params.name:
            raise ValueError("MCP_MEMORY_TOOL_UNKNOWN")
        args = params.arguments or {}
        schema = next(row["function"]["parameters"] for row in self.catalog
                      if row["function"]["name"] == params.name)
        try:
            validate(args, schema)
            # Match the canonical tool's typed arguments before touching the Store.
            # Hidden call identity is injected here just as in ToolNode's full call.
            self.local_tools[params.name].args_schema.model_validate(
                {**args, "tool_call_id": binding["call_id"]})
        except (ValidationError, ArgumentValidationError):
            body = json.dumps({"ok": False, "status": "invalid_arguments"})
            self._emit({"kind": "tool_result", "origin": binding["origin"],
                        "name": params.name, "tool_call_id": binding["call_id"],
                        "content": body, "status": "error"})
            return CallToolResult(content=[TextContent(type="text", text=body)], is_error=True)
        call = {"name": params.name, "args": args, "id": binding["call_id"], "type": "tool_call"}
        result = await anyio.to_thread.run_sync(lambda: context.run(
            self.local_tools[params.name].invoke, call, binding["config"]))
        if not isinstance(result, ToolMessage) or result.tool_call_id != binding["call_id"]:
            raise ValueError("MCP_MEMORY_RECEIPT_INVALID")
        if not isinstance(result.content, str):
            raise ValueError("MCP_MEMORY_RECEIPT_CONTENT_INVALID")
        if params.name == "search_memory" and any(
            tuple(row["namespace"]) != self.namespace for row in json.loads(result.content)
        ):
            raise ValueError("MCP_MEMORY_STORE_SCOPE_CHANGED")
        self._emit({"kind": "tool_result", "origin": binding["origin"],
                    "name": params.name, "tool_call_id": result.tool_call_id,
                    "content": result.content, "status": result.status})
        return CallToolResult(content=[TextContent(type="text", text=result.content)],
                              is_error=result.status == "error")

    async def _read_resource(self, ctx: Any, params: Any) -> ReadResourceResult:
        context, binding = self._binding(ctx)
        uri = str(params.uri)
        parsed = urlparse(uri)
        if (f"{parsed.scheme}://{parsed.netloc}{parsed.path}" != RECORDS_RESOURCE
                or binding["name"] != "records"):
            raise ValueError("MCP_MEMORY_RESOURCE_UNKNOWN")
        query = parse_qs(parsed.query, strict_parsing=True)
        if set(query) != {"offset"} or len(query["offset"]) != 1:
            raise ValueError("MCP_MEMORY_RESOURCE_CURSOR_INVALID")
        offset = int(query["offset"][0])
        if offset < 0:
            raise ValueError("MCP_MEMORY_RESOURCE_CURSOR_INVALID")
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        page = await anyio.to_thread.run_sync(lambda: context.run(
            self.store.search, self.namespace, limit=64, offset=offset))
        if any(tuple(item.namespace) != self.namespace for item in page):
            raise ValueError("MCP_MEMORY_STORE_SCOPE_CHANGED")
        rows = [{"id": item.key, "value": item.value} for item in page]
        body = json.dumps({"records": rows, "next_offset": offset + len(page)
                          if len(page) == 64 else None}, ensure_ascii=False)
        self._emit({"kind": "resource_result", "origin": binding["origin"],
                    "calls": 1, "logical_bytes": len(body.encode("utf-8")),
                    "cpu_ns": time.process_time_ns() - start_cpu,
                    "wall_ns": time.perf_counter_ns() - start_wall})
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri,
            mime_type="application/json", text=body)])

    def __enter__(self) -> MemoryMCP:
        if self._stack is not None:
            raise ValueError("MCP_MEMORY_ALREADY_OPEN")
        stack = self._stack = ExitStack()
        try:
            token = secrets.token_urlsafe(32)
            peer = self

            class WireMiddleware(BaseHTTPMiddleware):
                async def dispatch(self, request: Any, call_next: Any) -> Response:
                    if request.headers.get("authorization") != "Bearer " + token:
                        return JSONResponse({"error": "unauthorized"}, status_code=401)
                    body = await request.body()
                    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
                    response = await call_next(request)
                    output = b"".join([chunk async for chunk in response.body_iterator])
                    peer._emit({"kind": "http", "method": request.method,
                        "request_body": body.decode("utf-8"),
                        "response_body": output.decode("utf-8"),
                        "request_sha256": hashlib.sha256(body).hexdigest(),
                        "response_sha256": hashlib.sha256(output).hexdigest(),
                        "http_status": response.status_code,
                        "cpu_ns": time.process_time_ns() - start_cpu,
                        "wall_ns": time.perf_counter_ns() - start_wall})
                    return Response(output, status_code=response.status_code,
                                    headers=dict(response.headers))

            server = Server("milai-lab-ordinary-memory", on_list_tools=self._list_tools,
                            on_call_tool=self._call_tool, on_read_resource=self._read_resource)
            app = server.streamable_http_app(json_response=True, stateless_http=True)
            app.add_middleware(WireMiddleware)
            listener = socket.socket()
            stack.callback(listener.close)
            listener.bind(("127.0.0.1", 0))
            self.url = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"
            http_server = uvicorn.Server(uvicorn.Config(app, log_level="critical",
                                                      access_log=False, lifespan="on"))
            failures: list[BaseException] = []

            def serve() -> None:
                try:
                    asyncio.run(http_server.serve(sockets=[listener]))
                except BaseException as error:
                    failures.append(error)

            thread = threading.Thread(target=serve, name="milai-mcp-http", daemon=True)
            thread.start()

            def stop() -> None:
                http_server.should_exit = True
                thread.join(timeout=5)
                if thread.is_alive():
                    raise RuntimeError("MCP_MEMORY_SERVER_CLOSE_TIMEOUT")

            stack.callback(stop)
            deadline = time.monotonic() + 5
            while not http_server.started:
                if failures:
                    raise RuntimeError("MCP_MEMORY_SERVER_START_FAILED") from failures[0]
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("MCP_MEMORY_SERVER_START_TIMEOUT")
                time.sleep(0.01)
            self.portal = stack.enter_context(start_blocking_portal())
            http_client = stack.enter_context(self.portal.wrap_async_context_manager(
                httpx2.AsyncClient(headers={"Authorization": "Bearer " + token},
                                   timeout=self.timeout)))
            self.client = stack.enter_context(self.portal.wrap_async_context_manager(Client(
                streamable_http_client(self.url, http_client=http_client), mode=MCP_PROTOCOL,
                read_timeout_seconds=self.timeout)))
            discovered = self.portal.call(self.client.list_tools)
            actual = [{"type": "function", "function": {"name": tool.name,
                "description": tool.description, "parameters": tool.input_schema}}
                for tool in discovered.tools]
            if actual != self.catalog:
                raise ValueError("MCP_MEMORY_CATALOG_CHANGED")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_: Any) -> None:
        stack, self._stack = self._stack, None
        try:
            if stack is not None:
                stack.close()
        finally:
            self.client, self.portal = None, None
            self._bindings.clear()

    @contextmanager
    def _request(self, name: str, call_id: str, origin: str,
                 config: RunnableConfig | None) -> Iterator[dict[str, Any]]:
        if self.client is None:
            raise ValueError("MCP_MEMORY_CLOSED")
        self.check_scope(config)
        with self._lock:
            key = secrets.token_hex(16)
            self._bindings[key] = (copy_context(), {"name": name, "call_id": call_id,
                                                   "origin": origin, "config": config})
            try:
                yield {"milai_scope": self.scope, "milai_binding": key}
            finally:
                self._bindings.pop(key, None)

    def call(self, name: str, args: dict[str, Any], call_id: str, *, origin: str,
             config: RunnableConfig | None) -> ToolMessage:
        with self._request(name, call_id, origin, config) as meta:
            result = self.portal.call(lambda: self.client.call_tool(name, args, meta=meta))
        if len(result.content) != 1 or not isinstance(result.content[0], TextContent):
            raise ValueError("MCP_MEMORY_RECEIPT_INVALID")
        return ToolMessage(name=name, tool_call_id=call_id, content=result.content[0].text,
                           status="error" if result.is_error else "success")

    def records(self, config: RunnableConfig) -> list[dict[str, Any]]:
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        rows: list[dict[str, Any]] = []
        offset: int | None = 0
        calls = 0
        while offset is not None:
            with self._request("records", "", "material", config) as meta:
                result = self.portal.call(lambda cursor=offset: self.client.read_resource(
                    f"{RECORDS_RESOURCE}?offset={cursor}", meta=meta))
            if (len(result.contents) != 1 or
                    not isinstance(result.contents[0], TextResourceContents)):
                raise ValueError("MCP_MEMORY_RESOURCE_INVALID")
            page = json.loads(result.contents[0].text)
            calls += 1
            rows.extend(page["records"])
            offset = page["next_offset"]
        rows.sort(key=lambda row: row["id"])
        if self.emit is not None:
            self.emit({"event": "lsa_writer_memory_read", "user_id": self.scope["user_id"],
                "calls": calls, "records": len(rows), "transport": "mcp_http",
                "logical_bytes": len(json.dumps(rows, ensure_ascii=False).encode("utf-8")),
                "wall_ns": time.perf_counter_ns() - start_wall,
                "cpu_ns": time.process_time_ns() - start_cpu})
        return rows

    def retrieve(self, query: str, limit: int, config: RunnableConfig) -> list[dict[str, Any]]:
        receipt = self.call("search_memory", {"query": query, "limit": limit},
                            "material:search", origin="material", config=config)
        if receipt.status != "success":
            raise ValueError("MCP_MEMORY_MATERIAL_SEARCH_REJECTED")
        rows = json.loads(str(receipt.content))
        if any(tuple(row["namespace"]) != self.namespace for row in rows):
            raise ValueError("MCP_MEMORY_STORE_SCOPE_CHANGED")
        return [{"id": row["key"], "value": row["value"]} for row in rows]

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import time
from collections.abc import Iterator
from dataclasses import dataclass as dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from milai_client import (
    TaskBindingContext as TaskBindingContext,
)
from milai_client import (
    TaskMemoryIdentity as TaskMemoryIdentity,
)
from milai_client import (
    TaskMemoryState as TaskMemoryState,
)
from milai_client.models import PrepareContextEvent as PrepareContextEvent

from milai_openworker_mcp.host import provider_bridge as _provider_bridge
from milai_openworker_mcp.host.ingress import (
    _HEADER_NAMES,
    _SETTLEMENT_HEADER_NAMES,
    _authenticate_ingress,
    _load_ingress_token,
    _task_metadata_from_values,
    _validate_listen_host,
)
from milai_openworker_mcp.host.ingress import StartupTaskPolicy as StartupTaskPolicy
from milai_openworker_mcp.host.memory_flow import (
    _HOST_PREFETCH_MODES as _HOST_PREFETCH_MODES,
)
from milai_openworker_mcp.host.memory_flow import (
    _completion as _completion,
)
from milai_openworker_mcp.host.memory_flow import (
    _last_user_content as _last_user_content,
)
from milai_openworker_mcp.host.memory_flow import (
    _memory_answer_eligible as _memory_answer_eligible,
)
from milai_openworker_mcp.host.memory_flow import (
    _memory_insufficient_outcome as _memory_insufficient_outcome,
)
from milai_openworker_mcp.host.memory_flow import (
    _memory_terminal_completion as _memory_terminal_completion,
)
from milai_openworker_mcp.host.memory_flow import (
    _messages as _messages,
)
from milai_openworker_mcp.host.memory_flow import (
    _native_user_content as _native_user_content,
)
from milai_openworker_mcp.host.memory_flow import (
    _prepared_prefetch as _prepared_prefetch,
)
from milai_openworker_mcp.host.memory_flow import (
    _question as _question,
)
from milai_openworker_mcp.host.memory_flow import (
    _recall_from_messages as _recall_from_messages,
)
from milai_openworker_mcp.host.memory_flow import (
    _recall_object as _recall_object,
)
from milai_openworker_mcp.host.memory_flow import (
    _recall_query as _recall_query,
)
from milai_openworker_mcp.host.memory_flow import (
    _resolve_prepared_context as _resolve_prepared_context,
)
from milai_openworker_mcp.host.memory_flow import (
    _should_recall as _should_recall,
)
from milai_openworker_mcp.host.memory_flow import (
    _text as _text,
)
from milai_openworker_mcp.host.memory_flow import (
    _transport_unavailable_outcome as _transport_unavailable_outcome,
)
from milai_openworker_mcp.host.provider_bridge import (
    _EVIDENCE_USE_MODES as _EVIDENCE_USE_MODES,
)
from milai_openworker_mcp.host.provider_bridge import (
    OpenWorkerProviderAdapter as OpenWorkerProviderAdapter,
)
from milai_openworker_mcp.host.request_contract import (
    _MEMORY_READING_POLICY as _MEMORY_READING_POLICY,
)
from milai_openworker_mcp.host.request_contract import (
    MAX_BODY_BYTES,
    MODEL_ID,
    OpenAIChatRequest,
    OpenWorkerAdapterError,
    StreamingCompletion,
)
from milai_openworker_mcp.host.request_contract import _tool_choice_name as _tool_choice_name
from milai_openworker_mcp.host.request_contract import (
    _tool_definition_name as _tool_definition_name,
)
from milai_openworker_mcp.host.task_state import (
    _TASK_EVENTS as _TASK_EVENTS,
)
from milai_openworker_mcp.host.task_state import (
    _BoundTaskState as _BoundTaskState,
)
from milai_openworker_mcp.host.tool_compat import (
    _ORDINARY_READ_PATH as _ORDINARY_READ_PATH,
)
from milai_openworker_mcp.host.tool_compat import (
    _VLLM_JSON_SCHEMA_NAMED_TOOL as _VLLM_JSON_SCHEMA_NAMED_TOOL,
)
from milai_openworker_mcp.host.tool_compat import (
    OrdinaryToolCompatibilityError,
    _canonical,
    _sse,
)
from milai_openworker_mcp.host.tool_compat import (
    _ordinary_read_completion as _ordinary_read_completion,
)
from milai_openworker_mcp.host.trace import (
    _evidence_use_trace_result as _evidence_use_trace_result,
)
from milai_openworker_mcp.host.trace import (
    _host_access_trace_link as _host_access_trace_link,
)
from milai_openworker_mcp.host.trace import (
    _native_request_observation as _native_request_observation,
)
from milai_openworker_mcp.host.trace import (
    _nonnegative_difference as _nonnegative_difference,
)
from milai_openworker_mcp.host.trace import (
    _progressive_l1_trace as _progressive_l1_trace,
)
from milai_openworker_mcp.host.trace import (
    _query_only_intent_shadow_trace as _query_only_intent_shadow_trace,
)
from milai_openworker_mcp.host.trace import (
    _requested_memory_route as _requested_memory_route,
)
from milai_openworker_mcp.host.trace import (
    _shadow_route_trace as _shadow_route_trace,
)
from milai_openworker_mcp.provider_execution import (
    BudgetError,
    CapabilityError,
    ProviderCallError,
)
from milai_openworker_mcp.provider_execution import (
    ProviderTransportError as ProviderTransportError,
)
from milai_openworker_mcp.provider_execution import (
    _SseObserver as _SseObserver,
)
from milai_openworker_mcp.task_binding import (
    HostTaskRelationEvent as HostTaskRelationEvent,
)
from milai_openworker_mcp.task_binding import (
    NativeTaskMetadata,
)
from milai_openworker_mcp.task_binding import (
    TaskBindingConflict as TaskBindingConflict,
)
from milai_openworker_mcp.task_binding import (
    TaskResolution as TaskResolution,
)
from milai_openworker_mcp.task_binding import (
    bind_host_task as bind_host_task,
)

# Preserve the historical orchestrator/host_adapter symbol surface while the
# implementation class lives in its bounded provider module.
for _name in dir(_provider_bridge):
    if not _name.startswith("__") and _name not in globals():
        globals()[_name] = getattr(_provider_bridge, _name)

class Handler(BaseHTTPRequestHandler):
    server_version = "MiLAiOpenWorkerU1Adapter/1"
    protocol_version = "HTTP/1.1"

    @property
    def adapter(self) -> OpenWorkerProviderAdapter:
        value = getattr(self.server, "adapter", None)
        if not isinstance(value, OpenWorkerProviderAdapter):
            raise OpenWorkerAdapterError("adapter is unavailable")
        return value

    @property
    def ingress_token(self) -> str:
        value = getattr(self.server, "ingress_token", None)
        if not isinstance(value, str):
            raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID")
        return value

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _write(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _write_error(self, status: int, reason_code: str) -> None:
        self._write(
            status,
            _canonical(
                {
                    "error": {
                        "message": "OpenWorker Host request failed",
                        "type": "local_adapter_error",
                        "reason_code": reason_code,
                    }
                }
            ),
            "application/json",
        )

    def _authenticate(self) -> bool:
        try:
            _authenticate_ingress(self.headers.get_all("Authorization", []), self.ingress_token)
        except OpenWorkerAdapterError:
            self._write_error(401, "AUTHENTICATION_REQUIRED")
            return False
        return True

    def _metadata(self) -> NativeTaskMetadata:
        return _task_metadata_from_values(
            {
                name: self.headers.get_all(name, [])
                for name in (*_HEADER_NAMES, *_SETTLEMENT_HEADER_NAMES)
            },
            require_settlement=self.adapter.settlement_enabled,
        )

    def _write_stream(self, chunks: Iterator[bytes]) -> None:
        try:
            first_chunk = next(chunks)
        except StopIteration as exc:
            raise ProviderCallError("PROVIDER_STREAM_DONE_MISSING") from exc
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(first_chunk)
            self.wfile.flush()
            for chunk in chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
        except (ProviderCallError, BudgetError, OSError) as exc:
            self.adapter._record_stream_terminal(exc)
        finally:
            close = getattr(chunks, "close", None)
            if callable(close):
                close()
            self.close_connection = True

    def do_GET(self) -> None:
        if not self._authenticate():
            return
        if self.path != "/v1/models":
            self._write(404, b"{}", "application/json")
            return
        payload = {
            "object": "list",
            "data": [{"id": MODEL_ID, "object": "model", "owned_by": "milai-local"}],
        }
        self._write(200, _canonical(payload), "application/json")

    def do_POST(self) -> None:
        parse_started = time.perf_counter()
        if not self._authenticate():
            return
        try:
            if self.path != "/v1/chat/completions":
                raise OpenWorkerAdapterError("path is not allowlisted")
            metadata = self._metadata()
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES:
                raise OpenWorkerAdapterError("request body boundary failed")
            incoming = OpenAIChatRequest.parse(json.loads(self.rfile.read(length)))
            request_parse_ms = (time.perf_counter() - parse_started) * 1000
            completion, route = self.adapter.complete(
                incoming,
                metadata,
                request_parse_ms=request_parse_ms,
            )
            print(
                json.dumps({"event": "OPENWORKER_U1_ROUTE", "route": route}, sort_keys=True),
                flush=True,
            )
            if isinstance(completion, StreamingCompletion):
                self._write_stream(completion.chunks)
                return
            payload = _sse(completion) if incoming.stream else _canonical(completion)
            content_type = "text/event-stream" if incoming.stream else "application/json"
            self._write(200, payload, content_type)
        except (OpenWorkerAdapterError, ValueError, json.JSONDecodeError) as exc:
            status = 422 if isinstance(exc, OrdinaryToolCompatibilityError) else 400
            self.adapter._record_ingress_terminal(status, exc)
            self._write_error(status, str(exc))
        except ProviderCallError as exc:
            match = re.fullmatch(r"PROVIDER_HTTP_(\d{3})", str(exc))
            status = 422 if match is not None and 400 <= int(match.group(1)) < 500 else 502
            self.adapter._record_ingress_terminal(status, exc)
            self._write_error(status, str(exc))
        except (BudgetError, CapabilityError) as exc:
            self.adapter._record_ingress_terminal(502, exc)
            self._write_error(502, str(exc))


class _IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def _build_http_server(host: str, port: int) -> ThreadingHTTPServer:
    server_type = (
        _IPv6ThreadingHTTPServer
        if ipaddress.ip_address(host).version == 6
        else ThreadingHTTPServer
    )
    return server_type((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve OpenWorker through the U1 Host adapter")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--listen-host", required=True)
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument(
        "--memory-mode",
        choices=("auto", "none", "prefetch", "query-first"),
        default="auto",
    )
    parser.add_argument("--prefetch-socket", type=Path)
    parser.add_argument("--submitter-socket", type=Path)
    parser.add_argument("--memory-subject-id")
    parser.add_argument(
        "--memory-data-classification",
        choices=("SYNTHETIC", "DEIDENTIFIED", "PERSONAL"),
        default="SYNTHETIC",
    )
    parser.add_argument(
        "--evidence-use-mode",
        choices=tuple(sorted(_EVIDENCE_USE_MODES)),
        default="direct",
    )
    parser.add_argument("--tokenizer-json", type=Path)
    parser.add_argument("--broker-policy", type=Path)
    parser.add_argument("--task-fixture", type=Path)
    parser.add_argument("--ingress-token-file", type=Path, required=True)
    parser.add_argument("--task-session-id")
    parser.add_argument("--provider-timeout-seconds", type=float, default=60.0)
    parser.add_argument(
        "--single-ordinary-tool-required-once",
        choices=("read",),
        help=(
            "Enable the explicit SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE "
            "compatibility contract for one OpenCode read call"
        ),
    )
    parser.add_argument(
        "--ordinary-tool-provider-compatibility",
        choices=(_VLLM_JSON_SCHEMA_NAMED_TOOL,),
        help=(
            "Adapt the forced read round through vLLM JSON Schema when the "
            "protected server has no tool parser"
        ),
    )
    args = parser.parse_args()
    if not 1 <= args.listen_port <= 65535:
        raise SystemExit("listen port is invalid")
    listen_host = _validate_listen_host(args.listen_host)
    adapter = OpenWorkerProviderAdapter(
        args.manifest,
        args.ledger,
        args.trace,
        memory_mode=args.memory_mode,
        prefetch_socket=args.prefetch_socket,
        tokenizer_json=args.tokenizer_json,
        broker_policy=args.broker_policy,
        task_fixture=args.task_fixture,
        task_session_id=args.task_session_id,
        provider_timeout_seconds=args.provider_timeout_seconds,
        single_ordinary_tool_required_once=args.single_ordinary_tool_required_once,
        ordinary_tool_provider_compatibility=(args.ordinary_tool_provider_compatibility),
        submitter_socket=args.submitter_socket,
        memory_subject_id=args.memory_subject_id,
        memory_data_classification=args.memory_data_classification,
        evidence_use_mode=args.evidence_use_mode,
    )
    server = _build_http_server(listen_host, args.listen_port)
    server.adapter = adapter  # type: ignore[attr-defined]
    server.ingress_token = _load_ingress_token(args.ingress_token_file)  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    finally:
        adapter.close()
        server.server_close()


if __name__ == "__main__":
    main()

"""Official Hindsight SDK/service adapter; retain and recall remain native.

Use hindsight-client==0.10.3 with an independently configured native service.
https://hindsight.vectorize.io/developer/api/retain
https://hindsight.vectorize.io/developer/api/recall

This module does not import the server, alter extraction/retrieval, invoke
reflect, run a MiLAi Editor/Selector, or delete banks. The caller owns service
configuration, resource admission and accounting of its internal model calls.
Missing internal costs stay unobserved. Native responses are journaled before
presentation so saved responses can be projected again without another call.
"""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from socket import socket
from threading import Lock, Thread
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from milai_lab.contracts.memory_backend import IngestionResult, MemorySession, RetrievalResult
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.providers.contextual_vllm import VLLMClient

SDK_VERSION = "0.10.3"


class HindsightClient(Protocol):
    def retain(self, **kwargs: Any) -> Any: ...
    def recall(self, **kwargs: Any) -> Any: ...
    def status(self, bank_id: str, *, timeout: float) -> dict[str, Any]: ...
    def close(self) -> Any: ...


class UnconfirmedHindsightOperation(RuntimeError):
    """A dispatched operation has no durable response; do not blindly retry."""


class HindsightIngestionIncomplete(RuntimeError):
    """The saved native response does not certify synchronous completion."""

    def __init__(self, message: str, *, resources_settled: bool = False) -> None:
        super().__init__(message)
        self.resources_settled = resources_settled


class HindsightModelBridge:
    """Two loopback model routes using Root's exact clients and original ledger.

    Root starts the native service separately, with its LLM/embedding base URLs
    set to base_url and keys set to api_key. This bridge never creates a model
    client or budget, adds retries, changes model parameters, or serves rerank.
    Root must declare native rrf for the first local adaptation. Artifacts contain
    complete actual model HTTP, including requests that consume no new budget.
    """

    def __init__(
        self, root: str | Path, *, generation_client: VLLMClient,
        embedding_client: VLLMClient, generation_output_bound: int | None = None,
    ) -> None:
        if (generation_client.budget is None
                or generation_client.budget is not embedding_client.budget):
            raise ValueError("HINDSIGHT_BRIDGE_EXACT_SHARED_BUDGET_REQUIRED")
        for client in (generation_client, embedding_client):
            url = urlsplit(client.config.base_url)
            if (url.scheme != "http" or url.hostname != "127.0.0.1"
                    or url.username is not None or url.password is not None
                    or url.query or url.fragment or url.path.rstrip("/") != "/v1"):
                raise ValueError("HINDSIGHT_BRIDGE_FIXED_LOOPBACK_CLIENT_REQUIRED")
        owner = generation_client.budget.http_owner
        if owner is not None:
            owner.assert_budget(generation_client.budget)
        if generation_output_bound is not None and (
            type(generation_output_bound) is not int or generation_output_bound <= 0
        ):
            raise ValueError("HINDSIGHT_BRIDGE_OUTPUT_BOUND_INVALID")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.clients = {"/v1/chat/completions": generation_client,
                        "/v1/embeddings": embedding_client}
        self.generation_output_bound = generation_output_bound
        self.api_key = secrets.token_urlsafe(32)
        self._lock = Lock()
        self._server: ThreadingHTTPServer | None = None
        self._worker: Thread | None = None
        self._closed = False
        self._serial = max((int(path.name) for path in self.root.iterdir()
                            if path.is_dir() and path.name.isdecimal()), default=0)
        blocked = self.root / "transport-blocked.json"
        self.failure: dict[str, Any] | None = read_json(blocked) if blocked.exists() else None
        if self.failure is None:
            for folder in sorted(self.root.iterdir()):
                trace = folder / "transport.json"
                if not folder.name.isdecimal() or not folder.is_dir() or not trace.exists():
                    continue
                event = read_json(trace)
                if event.get("request_sent") is True and (
                    not self._response_recorded(event) or event.get("usage_confirmed") is not True
                    or event.get("event") == "vllm_error"
                ):
                    self._block(folder, "saved_native_response_unconfirmed",
                                resources_settled=self._response_recorded(event))
                    break

    @property
    def base_url(self) -> str:
        if self._server is None or self._closed:
            raise ValueError("HINDSIGHT_BRIDGE_NOT_RUNNING")
        return f"http://127.0.0.1:{self._server.server_port}/v1"

    def start(self) -> HindsightModelBridge:
        bridge = self

        class Server(ThreadingHTTPServer):
            def get_request(self) -> tuple[socket, Any]:
                connection, address = super().get_request()
                connection.settimeout(10.0)
                return connection, address

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                if self.path not in bridge.clients:
                    self.reply(404, b'{"error":"unsupported model route"}')
                    return
                if self.headers.get("Authorization") != f"Bearer {bridge.api_key}":
                    self.reply(401, b'{"error":"bridge authorization required"}')
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or self.headers.get("Transfer-Encoding") is not None:
                        raise ValueError("HINDSIGHT_BRIDGE_BODY_INVALID")
                    self.connection.settimeout(10.0)
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError("HINDSIGHT_BRIDGE_BODY_INCOMPLETE")
                    status, response = bridge._forward(self.path, body, list(self.headers.items()))
                    self.reply(status, response)
                except (ValueError, KeyError):
                    self.reply(400, b'{"error":"invalid native model request"}')
                except (OSError, TimeoutError):
                    # No upstream retry. A completed model response remains in
                    # the artifacts even if the native caller disconnected.
                    return

            def reply(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        with self._lock:
            if self._closed or self._server is not None or self.failure is not None:
                raise ValueError("HINDSIGHT_BRIDGE_ALREADY_CLOSED_OR_BLOCKED")
            self._server = Server(("127.0.0.1", 0), Handler)
            self._worker = Thread(target=self._server.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
            self._worker.start()
        return self

    def _forward(
        self, path: str, body: bytes, headers: list[tuple[str, str]],
    ) -> tuple[int, bytes]:
        with self._lock:
            self._serial += 1
            folder = self.root / f"{self._serial:06d}"
            folder.mkdir()
            write_json(folder / "native-request.json", {
                "path": path, "headers": headers, "body": body.decode("utf-8"),
            })
            if self._closed or self.failure is not None:
                write_json(folder / "rejected.json", {"request_sent": False,
                                                       "reason": "bridge already stopped"})
                return 503, b'{"error":"native model bridge stopped"}'
            event: dict[str, Any] = {}
            invoked = False

            def observed(value: dict[str, Any]) -> None:
                event.update(value)
                write_json(folder / "transport.json", value)
                if "receipt" in value:
                    write_json(folder / "native-response.json", value["receipt"])

            try:
                request = json.loads(body)
                if not isinstance(request, dict):
                    raise ValueError("HINDSIGHT_BRIDGE_JSON_OBJECT_REQUIRED")
                invoked = True
                self.clients[path].native_post(
                    path.removeprefix("/v1/"), request,
                    generation_output_bound=self.generation_output_bound, on_event=observed,
                )
                if event.get("usage_confirmed") is not True:
                    self._block(folder, "native_usage_unconfirmed", resources_settled=True)
            except Exception as error:
                write_json(folder / "failure.json", {"type": type(error).__name__,
                                                       "message": str(error)})
                self._block(folder, type(error).__name__,
                            resources_settled=not invoked or event.get("request_sent") is False
                            or self._response_recorded(event))
            if "response_body_base64" in event:
                return event["http_status"], base64.b64decode(event["response_body_base64"])
            return 502, b'{"error":"native model request unconfirmed or refused"}'

    @staticmethod
    def _response_recorded(event: dict[str, Any]) -> bool:
        status, body = event.get("http_status"), event.get("response_body_base64")
        if type(status) is not int or not 100 <= status <= 599 or not isinstance(body, str):
            return False
        try:
            base64.b64decode(body, validate=True)
        except ValueError:
            return False
        return True

    def _block(self, folder: Path, reason: str, *, resources_settled: bool) -> None:
        self.failure = {"reason": reason, "attempt": folder.name,
                        "resources_settled": resources_settled,
                        "no_automatic_retry": True}
        write_json(self.root / "transport-blocked.json", self.failure)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        try:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
            if self._worker is not None:
                self._worker.join(timeout=5)
                if self._worker.is_alive():
                    raise HindsightIngestionIncomplete("native_model_bridge_close_unconfirmed")
        except BaseException as error:
            if isinstance(error, HindsightIngestionIncomplete):
                error.resources_settled = False
            raise
        if self.failure is not None:
            raise HindsightIngestionIncomplete(
                f"native_model_bridge:{self.failure['reason']}",
                resources_settled=self.failure["resources_settled"] is True,
            )


class _OfficialClient:
    """Public SDK HTTP-info methods preserve the actual complete response JSON.

    The high-level response model can drop unknown fields or supply usage
    defaults. ApiResponse.raw_data avoids both without changing server logic.
    All requests use one persistent loop/session and make one POST attempt.
    """

    def __init__(self, base_url: str, api_key: str | None) -> None:
        if version("hindsight-client") != SDK_VERSION:
            raise ValueError("HINDSIGHT_SDK_VERSION_CHANGED")
        self.native = import_module("hindsight_client").Hindsight(
            base_url=base_url, api_key=api_key, max_attempts=1,
        )
        self.models = import_module("hindsight_client_api.models")
        self.loop = asyncio.new_event_loop()

    def retain(self, **kwargs: Any) -> dict[str, Any]:
        item = self.models.MemoryItem(
            content=self.models.Content(actual_instance=kwargs["content"]),
            timestamp=self.models.Timestamp(actual_instance=kwargs["timestamp"]),
            context=kwargs["context"], metadata=kwargs["metadata"],
            document_id=kwargs["document_id"],
        )
        request = self.models.RetainRequest(items=[item], var_async=False)
        response = self.loop.run_until_complete(self.native.memory.retain_memories_with_http_info(
            kwargs["bank_id"], request, _request_timeout=300.0,
        ))
        return cast(dict[str, Any], json.loads(response.raw_data))

    def recall(self, **kwargs: Any) -> dict[str, Any]:
        include = self.models.IncludeOptions(
            chunks=self.models.ChunkIncludeOptions(max_tokens=kwargs["max_chunk_tokens"])
            if kwargs["include_chunks"] else None,
            source_facts=self.models.SourceFactsIncludeOptions(
                max_tokens=kwargs["max_source_facts_tokens"],
            ) if kwargs["include_source_facts"] else None,
        )
        request = self.models.RecallRequest(
            query=kwargs["query"], query_timestamp=kwargs["query_timestamp"],
            budget=kwargs["budget"], max_tokens=kwargs["max_tokens"], include=include,
        )
        response = self.loop.run_until_complete(self.native.memory.recall_memories_with_http_info(
            kwargs["bank_id"], request, _request_timeout=300.0,
        ))
        return cast(dict[str, Any], json.loads(response.raw_data))

    def status(self, bank_id: str, *, timeout: float) -> dict[str, Any]:
        async def read() -> dict[str, Any]:
            stats = await self.native.banks.get_agent_stats_with_http_info(
                bank_id, refresh=True, _request_timeout=timeout,
            )
            pending = await self.native.operations.list_operations_with_http_info(
                bank_id, status="pending", limit=1, _request_timeout=timeout,
            )
            processing = await self.native.operations.list_operations_with_http_info(
                bank_id, status="processing", limit=1, _request_timeout=timeout,
            )
            return {"bank_stats": json.loads(stats.raw_data),
                    "pending": json.loads(pending.raw_data),
                    "processing": json.loads(processing.raw_data)}

        return self.loop.run_until_complete(asyncio.wait_for(read(), timeout))

    def close(self) -> None:
        try:
            self.loop.run_until_complete(self.native.aclose())
        finally:
            self.loop.close()


def _timestamp(value: str) -> datetime:
    """Parse public source/query anchors, never substitute machine current time."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for pattern in ("%b %d, %Y, %H:%M:%S", "%Y/%m/%d (%a) %H:%M"):
            try:
                return datetime.strptime(value, pattern)
            except ValueError:
                pass
    raise ValueError("HINDSIGHT_PUBLIC_TIMESTAMP_INVALID")


def _native_json(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return cast(dict[str, Any], json.loads(json.dumps(response)))
    # exclude_unset avoids manufacturing usage=0 from SDK model defaults.
    value = response.model_dump(mode="json", by_alias=True, exclude_unset=True)
    if not isinstance(value, dict):
        raise ValueError("HINDSIGHT_NATIVE_RESPONSE_INVALID")
    return cast(dict[str, Any], value)


def _usage(response: dict[str, Any]) -> dict[str, Any]:
    native = response.get("usage")
    return {
        "native": native,
        "generation": "reported_native_usage" if isinstance(native, dict) else "unobserved",
        "embedding": "unobserved", "rerank": "unobserved",
        "scope": "native_response_only; service_internal_accounting_required",
    }


def project_recall(response: dict[str, Any]) -> RetrievalResult:
    """Project one saved native response with all text, order and fields intact.

    Facts remain retrieved memories. Raw chunks and contributing facts keep
    their native IDs/truncation flags; no claim of verified user/tool identity
    is synthesized. Auxiliary collections retain native insertion order.
    """
    native = _native_json(response)
    results = native.get("results")
    if not isinstance(results, list):
        raise ValueError("HINDSIGHT_NATIVE_RESULTS_INVALID")
    materials: list[dict[str, Any]] = []
    for row in results:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            raise ValueError("HINDSIGHT_NATIVE_RESULT_TEXT_INVALID")
        materials.append({**row, "provenance": "retrieved_memory"})
    for collection, provenance in (("chunks", "native_source_chunk"),
                                   ("source_facts", "retrieved_source_fact")):
        rows = native.get(collection)
        if rows is None:
            continue
        if not isinstance(rows, dict):
            raise ValueError("HINDSIGHT_NATIVE_AUXILIARY_INVALID")
        for native_id, row in rows.items():
            if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                raise ValueError("HINDSIGHT_NATIVE_AUXILIARY_TEXT_INVALID")
            materials.append({**row, "native_collection": collection,
                              "native_collection_key": native_id, "provenance": provenance})
    # Entities/trace and all other native fields are retained as actual metadata,
    # not transformed into extra answer facts. The Reader receives them as well.
    extras = {name: value for name, value in native.items()
              if name not in {"results", "chunks", "source_facts"}}
    if extras:
        materials.append({"provenance": "native_recall_metadata", "native_fields": extras})
    return {"materials": materials, "native_return": native, "returned_count": len(results),
            "source_mapping": "native_document_chunk_and_source_fact_ids_when_returned",
            "usage": _usage(native)}


class HindsightBackend:
    """One independent native bank with synchronous per-session documents.

    The bank contains only arrived sessions; query_timestamp is a query anchor,
    not a future-access filter. A stable session ID is the native document ID.
    Server persistence survives client close/reopen; this journal only retains
    actual requests and responses and cannot recreate lost server state.
    """

    def __init__(
        self, root: str | Path, *, bank_id: str, base_url: str,
        api_key: str | None = None, recall_max_tokens: int = 4096,
        recall_budget: str = "mid", include_chunks: bool = True,
        max_chunk_tokens: int = 8192, include_source_facts: bool = True,
        max_source_facts_tokens: int = 4096, client: HindsightClient | None = None,
        on_status: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if not bank_id or not base_url:
            raise ValueError("HINDSIGHT_BANK_OR_URL_INVALID")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.bank_id = bank_id
        self.on_status = on_status
        self.last_status: dict[str, Any] | None = None
        self.recall_options = {
            "max_tokens": recall_max_tokens, "budget": recall_budget,
            "include_chunks": include_chunks, "max_chunk_tokens": max_chunk_tokens,
            "include_source_facts": include_source_facts,
            "max_source_facts_tokens": max_source_facts_tokens,
        }
        self.db = sqlite3.connect(self.root / "hindsight-journal.sqlite3")
        self.db.execute("CREATE TABLE IF NOT EXISTS binding (value TEXT NOT NULL)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS operations (kind TEXT NOT NULL, key TEXT NOT NULL, "
            "request TEXT NOT NULL, response TEXT, PRIMARY KEY (kind, key))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS status_checks "
            "(ordinal INTEGER PRIMARY KEY, stage TEXT NOT NULL, response TEXT NOT NULL)"
        )
        binding = json.dumps({"bank_id": bank_id, "base_url": base_url,
                              "sdk_version": SDK_VERSION, "recall": self.recall_options})
        saved = self.db.execute("SELECT value FROM binding").fetchone()
        if saved is not None and saved[0] != binding:
            self.db.close()
            raise ValueError("HINDSIGHT_BANK_BINDING_CHANGED")
        if saved is None:
            self.db.execute("INSERT INTO binding VALUES (?)", (binding,))
        self.db.commit()
        if client is None:
            try:
                client = _OfficialClient(base_url, api_key)
            except Exception:
                self.db.close()
                raise
        self.client = client

    def _wait_native(self, stage: str) -> dict[str, Any]:
        """Observe real public completion state; do not retry retain or recall.

        Each poll is a fresh read, not a guessed completion after fixed sleep.
        A 300s total deadline and one-second maximum interval let Root observe
        progress while the native worker retains its original model lease.
        """
        deadline = time.monotonic() + 300.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HindsightIngestionIncomplete(f"{stage}:native_completion_deadline")
            try:
                status = self.client.status(self.bank_id, timeout=remaining)
            except Exception as error:
                raise HindsightIngestionIncomplete(f"{stage}:native_status_unconfirmed") from error
            self.last_status = status
            self.db.execute(
                "INSERT INTO status_checks (stage, response) VALUES (?, ?)",
                (stage, json.dumps(status, ensure_ascii=False)),
            )
            self.db.commit()
            if self.on_status is not None:
                self.on_status(status)
            stats, pending, processing = (status["bank_stats"], status["pending"],
                                          status["processing"])
            counts = [stats.get("pending_operations"), stats.get("pending_consolidation"),
                      pending.get("total"), processing.get("total")]
            failures = [stats.get("failed_operations"), stats.get("failed_consolidation")]
            if (any(type(count) is not int or count < 0 for count in [*counts, *failures])
                    or any(row.get("bank_id") != self.bank_id
                           for row in (stats, pending, processing))):
                raise HindsightIngestionIncomplete(f"{stage}:native_status_fields_unconfirmed")
            if all(count == 0 for count in counts):
                # Drain actual work before reporting a known permanent failure.
                if any(count > 0 for count in failures):
                    raise HindsightIngestionIncomplete(
                        f"{stage}:native_background_failure", resources_settled=True,
                    )
                return status
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    def _call(
        self, kind: str, key: str, request: dict[str, Any], invoke: Callable[[], Any],
    ) -> dict[str, Any]:
        serialized = json.dumps(request, ensure_ascii=False)
        saved = self.db.execute(
            "SELECT request, response FROM operations WHERE kind = ? AND key = ?", (kind, key),
        ).fetchone()
        if saved is not None:
            if saved[0] != serialized:
                raise ValueError("HINDSIGHT_OPERATION_KEY_REUSED")
            if saved[1] is None:
                raise UnconfirmedHindsightOperation(f"{kind}:{key}")
            return cast(dict[str, Any], json.loads(saved[1]))
        pending = self.db.execute(
            "SELECT kind, key FROM operations WHERE response IS NULL LIMIT 1"
        ).fetchone()
        if pending is not None:
            raise UnconfirmedHindsightOperation(f"{pending[0]}:{pending[1]}")
        self.db.execute(
            "INSERT INTO operations (kind, key, request) VALUES (?, ?, ?)",
            (kind, key, serialized),
        )
        self.db.commit()
        try:
            native = _native_json(invoke())
        except Exception as error:
            # Leave the pre-dispatch journal entry pending. No SDK/model retry.
            raise UnconfirmedHindsightOperation(f"{kind}:{key}") from error
        self.db.execute(
            "UPDATE operations SET response = ? WHERE kind = ? AND key = ?",
            (json.dumps(native, ensure_ascii=False), kind, key),
        )
        self.db.commit()
        return native

    def ingest(self, session: MemorySession, *, key: str) -> IngestionResult:
        timestamp = _timestamp(session.date)
        turns = [{field: turn[field] for field in ("role", "content", "timestamp")}
                 for turn in session.turns]
        content = json.dumps(turns, ensure_ascii=False)
        request = {
            "bank_id": self.bank_id, "content": content,
            "timestamp": timestamp.isoformat(), "document_id": session.session_id,
            # Neutral source context; it is model input, not hidden evaluation metadata.
            "context": "Conversation transcript; timestamp is the reporting anchor. "
                       "Fact occurrence and effective dates are stated in the transcript.",
            "metadata": {"session_id": session.session_id, "source_date": session.date},
            "retain_async": False,
        }
        native = self._call(
            "retain", key, request,
            lambda: self.client.retain(**{**request, "timestamp": timestamp}),
        )
        if (native.get("bank_id") != self.bank_id or native.get("success") is not True
                or native.get("async") is not False):
            raise HindsightIngestionIncomplete(f"retain:{key}")
        # A cached confirmed retain may safely re-read status, never re-send it.
        status = self._wait_native(f"retain:{key}")
        usage = _usage(native)
        usage["native_completion"] = status
        return {"session_id": session.session_id, "completed": True, "native_return": native,
                "session_output": None, "usage": usage}

    def retrieve(self, question: str, date: str, *, key: str, limit: int) -> RetrievalResult:
        # Hindsight has token budgets, not top-k: never truncate native output to limit.
        request = {"bank_id": self.bank_id, "query": question,
                   "query_timestamp": _timestamp(date).isoformat(), **self.recall_options}
        native = self._call("recall", key, request, lambda: self.client.recall(**request))
        result = project_recall(native)
        result["usage"]["requested_count_not_applicable"] = limit
        return result

    def close(self) -> None:
        try:
            attempted = self.db.execute("SELECT 1 FROM operations LIMIT 1").fetchone()
            if attempted is not None:
                self._wait_native("close")
        finally:
            try:
                try:
                    self.client.close()
                finally:
                    self.db.close()
            except BaseException as error:
                # A drained native failure certifies closure only when both
                # local resources close successfully as well.
                if isinstance(error, HindsightIngestionIncomplete):
                    error.resources_settled = False
                raise

"""Mechanical persistence/native-wire checks; no model semantic acceptance."""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from milai_lab.baselines.rawrag_local import RawRAGLocal
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, http_budget_scope
from milai_lab.integrations.memory.hindsight import (
    HindsightBackend,
    HindsightIngestionIncomplete,
    HindsightModelBridge,
    UnconfirmedHindsightOperation,
    project_recall,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig


@dataclass(frozen=True)
class Session:
    session_id: str
    date: str
    turns: tuple[dict[str, str], ...]


def session(identifier: str, date: str, text: str) -> Session:
    return Session(identifier, date, (
        {"role": "user", "content": text, "timestamp": date},
        {"role": "assistant", "content": "I have heard your update.", "timestamp": date},
    ))


@pytest.mark.parametrize("granularity", ["session", "turn"])
def test_rawrag_original_prefix_persists_without_character_truncation(
    tmp_path: Path, granularity: Any,
) -> None:
    first = session("s1", "2024-01-01T10:00:00", "coffee " * 3000)
    future = session("s2", "2024-01-02T10:00:00", "tea instead")
    backend = RawRAGLocal(tmp_path, bank_id="raw-u1-r1", granularity=granularity)
    ingestion = backend.ingest(first, key="ingest/0")
    assert ingestion["completed"] and ingestion["session_output"] is None
    backend.close()
    backend = RawRAGLocal(tmp_path, bank_id="raw-u1-r1", granularity=granularity)
    old = backend.retrieve("tea", first.date, key="qa/0", limit=20)
    assert old["returned_count"] == 1
    assert old["materials"][0]["session_id"] == "s1"
    assert json.loads(old["materials"][0]["text"]) == list(first.turns)
    assert "turns" not in old["materials"][0]
    assert len(old["materials"][0]["text"]) > 16000
    assert old["materials"][0]["truncated"] is False
    backend.ingest(future, key="ingest/1")
    current = backend.retrieve("tea", future.date, key="qa/1", limit=20)
    assert current["returned_count"] == 2
    assert {row["session_id"] for row in current["materials"]} == {"s1", "s2"}
    assert current["usage"]["generation_tokens"] == 0
    backend.close()
    with pytest.raises(ValueError, match="BANK_BINDING_CHANGED"):
        RawRAGLocal(tmp_path, bank_id="raw-u2-r1", granularity=granularity)


def test_official_hindsight_sdk_wire_reopen_and_saved_response_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, dict[str, Any]]] = []
    documents: dict[str, dict[str, Any]] = {}
    returned: list[dict[str, Any]] = []
    status_calls: list[str] = []
    background_failed = False
    monkeypatch.setattr("milai_lab.integrations.memory.hindsight.time.sleep", lambda seconds: None)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            status_calls.append(self.path)
            if "/stats" in self.path:
                response = {"bank_id": "h-u1-r1", "total_nodes": len(documents),
                            "total_links": 0, "total_documents": len(documents),
                            "nodes_by_fact_type": {}, "links_by_link_type": {},
                            "links_by_fact_type": {}, "links_breakdown": {},
                            "pending_operations": 0, "failed_operations": 0,
                            "pending_consolidation": int(len(status_calls) == 1),
                            "failed_consolidation": int(background_failed)}
            else:
                assert "/operations?" in self.path
                response = {"bank_id": "h-u1-r1", "total": 0, "limit": 1, "offset": 0,
                            "operations": []}
            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            if self.path.endswith("/recall"):
                rows = [
                    {"id": f"native-{identifier}", "text": row["content"], "type": "world",
                     "document_id": identifier, "mentioned_at": row["timestamp"],
                     "chunk_id": f"chunk-{identifier}", "metadata": row["metadata"],
                     "source_fact_ids": [f"source-{identifier}"]}
                    for identifier, row in reversed(list(documents.items()))
                ]
                response = {
                    "results": rows,
                    "chunks": {f"chunk-{identifier}": {
                        "id": f"chunk-{identifier}", "text": row["content"],
                        "chunk_index": 0, "truncated": identifier == "s1",
                    } for identifier, row in documents.items()},
                    "source_facts": {"source-s1": {"id": "source-s1", "text": "coffee",
                                                    "document_id": "s1"}},
                    "source_facts_truncated": True,
                    # An SDK model would drop this field; raw_data must preserve it.
                    "native_extension": {"opaque": ["second", "first"]},
                }
                returned.append(response)
            else:
                assert self.path.endswith("/memories")
                for row in body["items"]:
                    documents[row["document_id"]] = row
                response = {"success": True, "bank_id": "h-u1-r1",
                            "items_count": len(body["items"]), "async": False,
                            "usage": {"input_tokens": 9, "output_tokens": 3, "total_tokens": 12}}
            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"
    first = session("s1", "Jan 01, 2024, 10:00:00", "coffee")
    second = session("s2", "Jan 02, 2024, 10:00:00", "tea instead")
    try:
        observed: list[dict[str, Any]] = []
        backend = HindsightBackend(tmp_path, bank_id="h-u1-r1", base_url=url,
                                   on_status=observed.append)
        ingested = backend.ingest(first, key="ingest/0")
        assert ingested["completed"]
        assert ingested["usage"]["native_completion"]["bank_stats"]["pending_consolidation"] == 0
        assert [row["bank_stats"]["pending_consolidation"] for row in observed] == [1, 0]
        backend.ingest(second, key="ingest/1")
        backend.close()
        backend = HindsightBackend(tmp_path, bank_id="h-u1-r1", base_url=url)
        # The confirmed retain reuses its response but observes fresh completion.
        backend.ingest(second, key="ingest/1")
        result = backend.retrieve("drink?", second.date, key="qa/1", limit=20)
        assert result["returned_count"] == 2  # Native facts, not manufactured K20.
        assert result["native_return"] == returned[0]
        assert [row["id"] for row in result["materials"][:2]] == ["native-s2", "native-s1"]
        assert result["materials"][0]["text"] == json.dumps(list(second.turns), ensure_ascii=False)
        assert next(row for row in result["materials"] if row.get("id") == "chunk-s1")[
            "truncated"] is True
        assert result["usage"]["generation"] == "unobserved"
        assert result["usage"]["embedding"] == "unobserved"
        saved = tmp_path / "saved-native-recall.json"
        saved.write_text(json.dumps(result["native_return"]))
        assert project_recall(json.loads(saved.read_text()))["materials"] == result["materials"]
        # Cached delivery cannot create another native request or test-answer write.
        again = backend.retrieve("drink?", second.date, key="qa/1", limit=20)
        assert again == result and len(requests) == 3
        assert [request["items"][0]["document_id"] for _, request in requests[:2]] == ["s1", "s2"]
        assert requests[0][1]["async"] is False
        assert requests[0][1]["items"][0]["timestamp"].startswith("2024-01-01T10:00:00")
        assert requests[-1][1]["query_timestamp"] == "2024-01-02T10:00:00"
        assert "tags" not in requests[0][1]["items"][0]
        backend.close()
        assert len(status_calls) == 18  # Both writes, cached write, pending poll and both closes.
        background_failed = True
        backend = HindsightBackend(tmp_path, bank_id="h-u1-r1", base_url=url)
        with pytest.raises(
            HindsightIngestionIncomplete, match="native_background_failure",
        ) as failed:
            backend.ingest(second, key="ingest/1")
        assert failed.value.resources_settled is True
        with pytest.raises(
            HindsightIngestionIncomplete, match="native_background_failure",
        ) as failed:
            backend.close()
        assert failed.value.resources_settled is True
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            backend.db.execute("SELECT 1")
        for resource_name in ("client", "db"):
            backend = HindsightBackend(tmp_path, bank_id="h-u1-r1", base_url=url)
            resource = getattr(backend, resource_name)
            wrapper = Mock(wraps=resource)
            original_close = resource.close

            def fail_cleanup(close: Callable[[], None] = original_close) -> None:
                close()
                raise HindsightIngestionIncomplete("cleanup_failed", resources_settled=True)

            wrapper.close.side_effect = fail_cleanup
            monkeypatch.setattr(backend, resource_name, wrapper)
            with pytest.raises(HindsightIngestionIncomplete, match="cleanup_failed") as failed:
                backend.close()
            assert failed.value.resources_settled is False
            with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
                backend.db.execute("SELECT 1")
        backend = HindsightBackend(tmp_path, bank_id="h-u1-r1", base_url=url)

        def unconfirmed_status(bank_id: str, *, timeout: float) -> dict[str, Any]:
            raise TimeoutError("native completion is unknown")

        monkeypatch.setattr(backend.client, "status", unconfirmed_status)
        with pytest.raises(
            HindsightIngestionIncomplete, match="native_status_unconfirmed",
        ) as failed:
            backend.close()
        assert failed.value.resources_settled is False
        assert len(requests) == 3  # Known failure must not trigger another retain/recall.
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_hindsight_unconfirmed_operation_is_not_retried_after_reopen(tmp_path: Path) -> None:
    calls = 0

    class LostResponse:
        def retain(self, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            raise TimeoutError("a write may have happened")

        def recall(self, **kwargs: Any) -> Any:
            raise AssertionError("no recall admitted after an unconfirmed write")

        def status(self, bank_id: str, *, timeout: float) -> dict[str, Any]:
            return {"bank_stats": {"bank_id": bank_id, "pending_operations": 0,
                                   "pending_consolidation": 0, "failed_operations": 0,
                                   "failed_consolidation": 0},
                    "pending": {"bank_id": bank_id, "total": 0},
                    "processing": {"bank_id": bank_id, "total": 0}}

        def close(self) -> None:
            pass

    first = session("s1", "2024-01-01T10:00:00", "coffee")
    for _ in range(2):
        backend = HindsightBackend(tmp_path, bank_id="h-u1-r1", base_url="http://fixture",
                                   client=LostResponse())
        with pytest.raises(UnconfirmedHindsightOperation):
            backend.ingest(first, key="ingest/0")
        with pytest.raises(UnconfirmedHindsightOperation):
            backend.retrieve("drink?", first.date, key="new-qa", limit=20)
        backend.close()
    assert calls == 1


@pytest.mark.parametrize(("completion_timeout", "completion_after", "completed"), [
    (None, 324.0, False),
    (1800.0, 324.0, True),
    (1800.0, 1801.0, False),
])
def test_hindsight_completion_deadline_covers_cumulative_native_work_and_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    completion_timeout: float | None, completion_after: float, completed: bool,
) -> None:
    clock = SimpleNamespace(now=0.0)

    def sleep(seconds: float) -> None:
        clock.now += seconds

    monkeypatch.setattr("milai_lab.integrations.memory.hindsight.time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=sleep,
    ))
    timeouts: list[float] = []
    writes, closes = [], []

    class Native:
        def retain(self, **kwargs: Any) -> dict[str, Any]:
            writes.append(kwargs)
            return {"success": True, "bank_id": kwargs["bank_id"], "async": False}

        def recall(self, **kwargs: Any) -> Any:
            raise AssertionError("completion polling must not dispatch recall")

        def status(self, bank_id: str, *, timeout: float) -> dict[str, Any]:
            timeouts.append(timeout)
            # Public reads consume elapsed time while original native work progresses.
            clock.now += min(60.0, max(0.0, completion_after - clock.now), timeout)
            pending = int(clock.now < completion_after)
            return {"bank_stats": {"bank_id": bank_id, "pending_operations": 0,
                                   "pending_consolidation": pending, "failed_operations": 0,
                                   "failed_consolidation": 0},
                    "pending": {"bank_id": bank_id, "total": 0},
                    "processing": {"bank_id": bank_id, "total": pending}}

        def close(self) -> None:
            closes.append(True)

    options = {} if completion_timeout is None else {"completion_timeout": completion_timeout}
    backend = HindsightBackend(tmp_path, bank_id="h-u1-r1", base_url="http://fixture",
                               client=Native(), **options)
    first = session("s1", "2024-01-01T10:00:00", "coffee")
    deadline_error = None
    if completed:
        ingested = backend.ingest(first, key="ingest/0")
        assert ingested["completed"] is True
        assert ingested["usage"]["native_completion"]["processing"]["total"] == 0
        assert clock.now == completion_after > 300.0
    else:
        with pytest.raises(
            HindsightIngestionIncomplete, match="native_completion_deadline",
        ) as error:
            backend.ingest(first, key="ingest/0")
        deadline_error = error.value
        assert deadline_error.resources_settled is False
        assert clock.now == (300.0 if completion_timeout is None else completion_timeout)
        assert backend.last_status is not None and backend.last_status["processing"]["total"] == 1
    assert timeouts[0] == (300.0 if completion_timeout is None else completion_timeout)
    assert all(timeout > 0 for timeout in timeouts) and len(timeouts) > 1
    assert len(writes) == 1 and not closes
    assert backend.db.execute("SELECT COUNT(*) FROM status_checks").fetchone()[0] == len(timeouts)
    # Closing observes the remaining original work; it never re-sends retain.
    backend.close()
    assert clock.now == completion_after and closes == [True] and len(writes) == 1
    assert backend.last_status is not None and backend.last_status["processing"]["total"] == 0
    if deadline_error is not None:
        # Cleanup cannot turn ingestion into success.
        assert deadline_error.resources_settled is False
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        backend.db.execute("SELECT 1")


@pytest.mark.parametrize("timeout", [0.0, float("nan"), float("inf")])
def test_hindsight_completion_deadline_requires_a_positive_finite_bound(
    tmp_path: Path, timeout: float,
) -> None:
    with pytest.raises(ValueError, match="COMPLETION_TIMEOUT_INVALID"):
        HindsightBackend(tmp_path, bank_id="h-u1-r1", base_url="http://fixture",
                         client=Mock(), completion_timeout=timeout)
    assert not (tmp_path / "hindsight-journal.sqlite3").exists()


def bridge_settings(tmp_path: Path) -> tuple[dict[str, Any], VLLMConfig, VLLMConfig]:
    generation = VLLMConfig("http://127.0.0.1:9/v1/", "synthetic-qwen", max_tokens=4)
    embedding = VLLMConfig("http://127.0.0.1:10/v1/", "synthetic-bge")
    ledger = tmp_path / "synthetic-original-budget.json"
    seed = RunBudget(RunLimits(generation_requests=10), ledger)
    write_json(ledger, seed.state)
    return ({"budget_path": str(ledger),
             "http_ownership_profile": "serialized_ledger_owner_v1",
             "http_ownership_domain": {
                 "deployment_id": "synthetic-native-test",
                 "clients": [asdict(generation), asdict(embedding)],
             }}, generation, embedding)


def test_native_model_bridge_preserves_wire_and_uses_exact_original_owner(tmp_path: Path) -> None:
    from milai_lab.runners.edit_benchmarks import BenchmarkRun

    settings, generation_config, embedding_config = bridge_settings(tmp_path)
    wires: list[dict[str, Any]] = []
    entered, release = threading.Event(), threading.Event()
    responses: list[httpx.Response] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        wires.append(body)
        if len(wires) == 1:
            entered.set()
            assert release.wait(3)
        response = httpx.Response(200, json={
            "opaque_native": {"untouched": ["b", "a"]},
            "data": [{"index": 1, "embedding": "native-base64"},
                     {"index": 0, "embedding": "second-native-base64"}],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "actual"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
            if request.url.path.endswith("chat/completions")
            else {"prompt_tokens": 2, "total_tokens": 2},
        })
        responses.append(response)
        return response

    original = {"model": generation_config.model,
                "messages": [{"role": "user", "content": "original native question"}],
                "max_completion_tokens": 8, "temperature": 0.75,
                "chat_template_kwargs": {"enable_thinking": True},
                "tools": [{"type": "function", "function": {"name": "native",
                           "parameters": {"type": "array", "uniqueItems": True}}}],
                "response_format": {"type": "json_object"}, "seed": 29, "n": 2}
    embedded = {"model": embedding_config.model, "input": ["literal", "other"],
                "dimensions": 1024, "encoding_format": "base64"}
    runner = BenchmarkRun.__new__(BenchmarkRun)
    runner.root, runner._embedding_serial = tmp_path / "runner", 1
    old_trace = runner.root / "http/embedding/000001/transport.json"
    write_json(old_trace, {"receipt": "previous ordinary embedding"})
    old_bytes = old_trace.read_bytes()
    with http_budget_scope(settings) as budget:
        assert budget is not None and budget.http_owner is not None
        generation = VLLMClient(generation_config, budget=budget,
                                transport=httpx.MockTransport(upstream))
        embedding = VLLMClient(embedding_config, emit=runner._embedding_trace, budget=budget,
                               transport=httpx.MockTransport(upstream))
        bridge = HindsightModelBridge(
            tmp_path / "http", generation_client=generation,
            embedding_client=embedding, generation_output_bound=32,
        ).start()
        returned: list[httpx.Response] = []
        errors: list[BaseException] = []

        def call(route: str, body: dict[str, Any]) -> None:
            try:
                returned.append(httpx.post(
                    bridge.base_url + route, json=body,
                    headers={"Authorization": f"Bearer {bridge.api_key}"}, timeout=5,
                ))
            except BaseException as error:
                errors.append(error)

        first = threading.Thread(target=call, args=("/chat/completions", original))
        second = threading.Thread(target=call, args=("/embeddings", embedded))
        try:
            first.start()
            assert entered.wait(3)
            second.start()
            assert len(wires) == 1  # Both routes share the original serialized owner.
            release.set()
            for thread in (first, second):
                thread.join(timeout=5)
                assert not thread.is_alive()
            assert not errors and len(returned) == 2
            assert wires == [original, embedded]
            assert sorted(row.content for row in returned) == sorted(
                row.content for row in responses
            )
            omitted = {"model": generation_config.model,
                       "messages": [{"role": "user", "content": "native omitted limit"}]}
            call("/chat/completions", omitted)
            assert wires[-1] == omitted and "max_tokens" not in wires[-1]
            first_trace = read_json(tmp_path / "http/000001/transport.json")
            assert first_trace["request"] == original
            assert json.loads(first_trace["request_body"]) == original
            assert first_trace["accounting_request"]["max_tokens"] == 16
            assert first_trace["receipt"] == responses[0].json()
            omitted_trace = read_json(tmp_path / "http/000003/transport.json")
            assert omitted_trace["accounting_request"]["max_tokens"] == 32
            assert omitted_trace["usage_confirmed"] is True
            assert budget.state["generation_requests"] == 2
            assert budget.state["generation"]["known_tokens"] == 10
            assert budget.state["embedding"]["known_tokens"] == 2
            assert budget.state["generation"]["unknown_usage"] == 0
            assert runner._embedding_serial == 2 and old_trace.read_bytes() == old_bytes
            new_embedding = runner.root / "http/embedding/000002"
            assert read_json(new_embedding / "request.json") == {
                "model": embedding_config.model, "input": embedded["input"],
            }
            assert read_json(new_embedding / "response.json") == responses[1].json()
            assert read_json(new_embedding / "transport.json")["request"] == embedded
            assert bridge.failure is None
            assert httpx.post(bridge.base_url + "/rerank", json=original).status_code == 404
            assert httpx.post(bridge.base_url + "/embeddings", json=embedded).status_code == 401
            assert len(wires) == 3
        finally:
            release.set()
            bridge.close()
            generation.close()
            embedding.close()


@pytest.mark.parametrize("status", [400, 429, 500])
@pytest.mark.parametrize("has_usage", [True, False])
def test_native_model_bridge_preserves_http_errors_and_actual_usage(
    tmp_path: Path, status: int, has_usage: bool,
) -> None:
    settings, generation_config, embedding_config = bridge_settings(tmp_path)
    receipt: dict[str, Any] = {"error": {"native": "actual error"}, "opaque": ["b", "a"]}
    if has_usage:
        receipt["usage"] = {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
    calls = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json=receipt)

    with http_budget_scope(settings) as budget:
        assert budget is not None
        generation = VLLMClient(generation_config, budget=budget,
                                transport=httpx.MockTransport(upstream))
        embedding = VLLMClient(embedding_config, budget=budget,
                               transport=httpx.MockTransport(upstream))
        bridge = HindsightModelBridge(tmp_path / "http", generation_client=generation,
                                      embedding_client=embedding).start()
        headers = {"Authorization": f"Bearer {bridge.api_key}"}
        try:
            response = httpx.post(bridge.base_url + "/chat/completions", headers=headers,
                                  json={"model": generation_config.model,
                                        "messages": [], "max_tokens": 8})
            assert response.status_code == status and response.json() == receipt
            trace = read_json(tmp_path / "http/000001/transport.json")
            assert trace["receipt"] == receipt and trace["http_status"] == status
            assert trace["exception"]["type"] == "HTTPStatusError"
            assert trace["usage_confirmed"] is has_usage
            assert bridge.failure is not None and bridge.failure["resources_settled"] is True
            assert httpx.post(bridge.base_url + "/chat/completions", headers=headers,
                              json={"model": generation_config.model,
                                    "messages": [], "max_tokens": 8}).status_code == 503
            assert calls == 1 and budget.state["generation_requests"] == 1
            assert budget.state["generation"]["unknown_usage"] == (0 if has_usage else 1)
            assert budget.state["generation"]["known_tokens"] == (5 if has_usage else 0)
            if has_usage:
                assert budget.state["generation"]["charged_tokens"] == 5
            else:
                assert budget.state["generation"]["charged_tokens"] > 8
        finally:
            with pytest.raises(HindsightIngestionIncomplete) as closed:
                bridge.close()
            assert closed.value.resources_settled is True
            generation.close()
            embedding.close()


@pytest.mark.parametrize("receipt_state", [
    "request_only", "usage_missing", "confirmed", "http_error",
])
def test_native_model_bridge_reopen_checks_crash_receipts_before_dispatch(
    tmp_path: Path, receipt_state: str,
) -> None:
    settings, generation_config, embedding_config = bridge_settings(tmp_path)
    folder = tmp_path / "http/000001"
    saved: dict[str, Any] = {"event": "vllm_request", "path": "chat/completions",
                             "request_sent": True}
    if receipt_state != "request_only":
        receipt: dict[str, Any] = {"choices": [], "opaque": "actual native response"}
        if receipt_state in {"confirmed", "http_error"}:
            receipt["usage"] = {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
        saved.update(http_status=200, response_body_base64=base64.b64encode(
            json.dumps(receipt).encode()).decode(), receipt=receipt,
                     usage_confirmed=receipt_state in {"confirmed", "http_error"})
        if receipt_state == "http_error":
            saved.update(event="vllm_error", http_status=500,
                         exception={"type": "HTTPStatusError", "message": "original HTTP error"})
    write_json(folder / "transport.json", saved)
    actual_bytes = (folder / "transport.json").read_bytes()
    # A previous process reserved this request, then exited before ledger finish.
    old_budget = RunBudget(RunLimits(generation_requests=10), Path(settings["budget_path"]))
    old_budget.reserve("chat/completions", {"model": generation_config.model,
                       "messages": [], "max_tokens": 8})

    def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError("recovery never replays a model request")

    with http_budget_scope(settings) as budget:
        assert budget is not None
        original_budget = json.dumps(budget.state, sort_keys=True)
        assert budget.state["generation"]["unknown_usage"] == 1
        assert budget.state["generation"]["charged_tokens"] > 8
        generation = VLLMClient(generation_config, budget=budget,
                                transport=httpx.MockTransport(upstream))
        embedding = VLLMClient(embedding_config, budget=budget,
                               transport=httpx.MockTransport(upstream))
        bridge = HindsightModelBridge(tmp_path / "http", generation_client=generation,
                                      embedding_client=embedding)
        try:
            if receipt_state == "confirmed":
                bridge.start()
                assert bridge.failure is None
            else:
                with pytest.raises(ValueError, match="BLOCKED"):
                    bridge.start()
                assert bridge.failure is not None
                assert bridge.failure["resources_settled"] is (receipt_state != "request_only")
                assert read_json(tmp_path / "http/transport-blocked.json") == bridge.failure
            assert (folder / "transport.json").read_bytes() == actual_bytes
            assert json.dumps(budget.state, sort_keys=True) == original_budget
            assert not (tmp_path / "http/000002").exists()
        finally:
            if receipt_state == "confirmed":
                bridge.close()
            else:
                with pytest.raises(HindsightIngestionIncomplete) as closed:
                    bridge.close()
                assert closed.value.resources_settled is (receipt_state != "request_only")
            generation.close()
            embedding.close()


@pytest.mark.parametrize("failure", ["missing_usage", "http_unknown"])
def test_native_model_bridge_stops_new_requests_and_retains_reservation(
    tmp_path: Path, failure: str,
) -> None:
    settings, generation_config, embedding_config = bridge_settings(tmp_path)
    calls = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "http_unknown":
            raise httpx.ReadTimeout("a model may have received the request", request=request)
        return httpx.Response(200, json={"choices": [], "opaque_native": {"usage_absent": True}})

    with http_budget_scope(settings) as budget:
        assert budget is not None
        generation = VLLMClient(generation_config, budget=budget,
                                transport=httpx.MockTransport(upstream))
        embedding = VLLMClient(embedding_config, budget=budget,
                               transport=httpx.MockTransport(upstream))
        bridge = HindsightModelBridge(tmp_path / "http", generation_client=generation,
                                      embedding_client=embedding).start()
        url = bridge.base_url
        headers = {"Authorization": f"Bearer {bridge.api_key}"}
        request = {"model": generation_config.model, "messages": [], "max_tokens": 8}
        try:
            first = httpx.post(url + "/chat/completions", json=request, headers=headers)
            assert first.status_code == (200 if failure == "missing_usage" else 502)
            assert bridge.failure is not None
            assert httpx.post(url + "/embeddings", headers=headers, json={
                "model": embedding_config.model, "input": ["must not be sent"],
            }).status_code == 503
            assert calls == 1 and budget.state["generation_requests"] == 1
            assert budget.state["generation"]["unknown_usage"] == 1
            assert budget.state["generation"]["known_tokens"] == 0
            assert budget.state["generation"]["charged_tokens"] > 8
            assert budget.state["embedding"]["charged_tokens"] == 0
            trace = read_json(tmp_path / "http/000001/transport.json")
            assert trace["request"] == request
            if failure == "missing_usage":
                assert trace["receipt"] == first.json() and "usage" not in first.json()
                assert trace["usage_confirmed"] is False
            else:
                assert trace["exception"]["type"] == "ReadTimeout"
        finally:
            with pytest.raises(HindsightIngestionIncomplete) as closed:
                bridge.close()
            assert closed.value.resources_settled is (failure == "missing_usage")
            generation.close()
            embedding.close()

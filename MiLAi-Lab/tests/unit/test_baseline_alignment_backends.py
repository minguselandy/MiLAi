"""Mechanical persistence/native-wire checks; no model semantic acceptance."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from milai_lab.baselines.rawrag_local import RawRAGLocal
from milai_lab.integrations.memory.hindsight import (
    HindsightBackend,
    UnconfirmedHindsightOperation,
    project_recall,
)


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
    assert old["materials"][0]["turns"] == list(first.turns)
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


def test_official_hindsight_sdk_wire_reopen_and_saved_response_projection(tmp_path: Path) -> None:
    requests: list[tuple[str, dict[str, Any]]] = []
    documents: dict[str, dict[str, Any]] = {}
    returned: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

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
        backend = HindsightBackend(tmp_path, bank_id="h-u1-r1", base_url=url)
        backend.ingest(first, key="ingest/0")
        backend.ingest(second, key="ingest/1")
        backend.close()
        backend = HindsightBackend(tmp_path, bank_id="h-u1-r1", base_url=url)
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

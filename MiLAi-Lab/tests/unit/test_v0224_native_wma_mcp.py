"""Persistent public MCP protocol with local simulated responses, no HTTP."""

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0224_native_wma_mcp as m


class Client:
    def __init__(self, *, sse=False, error=False, protocol=m.PROTOCOL):
        self.requests, self.closed = [], False
        self.sse, self.error, self.protocol = sse, error, protocol

    @contextmanager
    def stream(self, method, url, *, content, headers):
        assert url == m.URL
        body = json.loads(content) if content is not None else None
        self.requests.append((method, body, dict(headers)))
        if method == "DELETE":
            yield httpx.Response(204)
            return
        if body["method"] == "notifications/initialized":
            yield httpx.Response(202)
            return
        if body["method"] == "initialize":
            result = {"protocolVersion": self.protocol}
        else:
            assert headers["Mcp-Session-Id"] == "session-1"
            result = {
                "isError": self.error,
                "structuredContent": {"memory_id": "note", "version": 1},
            }
        reply = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        headers = {"Mcp-Session-Id": "session-1"}
        if self.sse:
            headers["Content-Type"] = "text/event-stream"
            yield httpx.Response(
                200,
                headers=headers,
                content=("event: message\ndata: " + json.dumps(reply) + "\n\n").encode(),
            )
        else:
            yield httpx.Response(200, headers=headers, json=reply)

    def close(self):
        self.closed = True


def setup(tmp_path, monkeypatch, *, cap=8, **kwargs):
    credential = tmp_path / "principal.json"
    credential.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "milai": {
                        "type": "http",
                        "url": m.URL,
                        "headers": {"Authorization": "Bearer private-issued-token"},
                    }
                }
            }
        )
    )
    credential.chmod(0o600)
    client = Client(**kwargs)

    def constructor(**options):
        assert options["trust_env"] is False and options["follow_redirects"] is False
        assert options["timeout"].read == 60
        return client

    def transport(**options):
        assert options == {"retries": 0, "trust_env": False}
        return object()

    monkeypatch.setattr(m.httpx, "Client", constructor)
    monkeypatch.setattr(m.httpx, "HTTPTransport", transport)
    return m.NoteMCP(credential, tmp_path / "raw", cap), client, credential


@pytest.mark.parametrize("sse", [False, True])
def test_persistent_handshake_public_result_raw_log_and_delete(tmp_path, monkeypatch, sse):
    note, client, _ = setup(tmp_path, monkeypatch, sse=sse)
    assert client.requests == []
    assert note.call("milai_note_get", {"memory_id": "note"}) == {"memory_id": "note", "version": 1}
    note.call("milai_note_operation_get", {"operation_id": "op"})
    note.close()
    note.close()
    assert [body["method"] if body else method for method, body, _ in client.requests] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
        "tools/call",
        "DELETE",
    ]
    assert note.http_requests == 5 and client.closed
    logs = (tmp_path / "raw/mcp-http.jsonl").read_text()
    assert (
        "private-issued-token" not in logs
        and "Authorization" not in logs
        and "session-1" not in logs
    )
    rows = [json.loads(line) for line in logs.splitlines()]
    assert len([r for r in rows if r["event"] == "HTTP_OBSERVED"]) == 5
    assert all(r["elapsed_ns"] >= 0 for r in rows if r["event"] == "HTTP_OBSERVED")


def test_scope_and_other_tools_cannot_change_principal_or_trigger_http(tmp_path, monkeypatch):
    note, client, _ = setup(tmp_path, monkeypatch)
    for tool, args in [
        ("milai_state_get", {}),
        ("milai_note_get", {"memory_id": "note", "scope": "other"}),
        ("milai_note_add", {"content": "x", "operation_id": "op", "principal": "other"}),
    ]:
        with pytest.raises(ValueError):
            note.call(tool, args)
    note.close()
    assert client.requests == []


def test_cap_counts_initialize_notification_tool_and_reserved_cleanup(tmp_path, monkeypatch):
    note, client, _ = setup(tmp_path, monkeypatch, cap=4)
    note.call("milai_note_get", {"memory_id": "note"})
    with pytest.raises(ValueError, match="REAL_HTTP_CAP_EXCEEDED"):
        note.call("milai_note_get", {"memory_id": "note"})
    note.close()
    assert note.http_requests == len(client.requests) == 4


def test_public_tool_errors_not_interpreted_as_results(tmp_path, monkeypatch):
    note, client, _ = setup(tmp_path, monkeypatch, error=True)
    with pytest.raises(ValueError, match="PUBLIC_NOTE_TOOL_ERROR"):
        note.call("milai_note_get", {"memory_id": "note"})
    note.close()
    assert len(client.requests) == 4


def test_bad_protocol_cannot_reinitialize_but_closes_allocated_session(tmp_path, monkeypatch):
    note, client, _ = setup(tmp_path, monkeypatch, protocol="other")
    with pytest.raises(ValueError, match="EXACT_PUBLIC_MCP_PROTOCOL_REQUIRED"):
        note.call("milai_note_get", {"memory_id": "note"})
    with pytest.raises(ValueError, match="FAILED_INITIALIZATION_CANNOT_RETRY"):
        note.call("milai_note_get", {"memory_id": "note"})
    note.close()
    assert len(client.requests) == 2 and client.requests[-1][0] == "DELETE"


def test_wrong_endpoint_or_public_credential_file_refused_before_http(tmp_path, monkeypatch):
    note, client, credential = setup(tmp_path, monkeypatch)
    note.close()
    credential.chmod(0o644)
    with pytest.raises(ValueError, match="PRIVATE_CREDENTIAL_FILE_REQUIRED"):
        m.NoteMCP(credential, tmp_path / "second", 8)
    credential.chmod(0o600)
    value = json.loads(credential.read_text())
    value["mcpServers"]["milai"]["url"] = "http://example.com/mcp"
    credential.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="FIXED_PUBLIC_NOTE_ENDPOINT"):
        m.NoteMCP(credential, tmp_path / "third", 8)
    assert client.requests == []


def test_transport_failure_consumes_attempt_without_retry(tmp_path, monkeypatch):
    note, client, _ = setup(tmp_path, monkeypatch)
    original = client.stream
    primary = httpx.ReadTimeout("synthetic timeout")
    attempts = []

    @contextmanager
    def failing(method, url, *, content, headers):
        body = json.loads(content) if content else None
        if body and body["method"] == "tools/call":
            attempts.append(body)
            raise primary
        with original(method, url, content=content, headers=headers) as response:
            yield response

    client.stream = failing
    with pytest.raises(httpx.ReadTimeout) as caught:
        note.call("milai_note_get", {"memory_id": "note"})
    assert caught.value is primary and len(attempts) == 1 and note.http_requests == 3
    note.close()
    assert note.http_requests == 4
    logs = [json.loads(line) for line in (tmp_path / "raw/mcp-http.jsonl").read_text().splitlines()]
    assert any(r.get("exception_type") == "ReadTimeout" for r in logs)


def test_delete_primary_survives_client_close_failure(tmp_path, monkeypatch):
    note, client, _ = setup(tmp_path, monkeypatch)
    note.call("milai_note_get", {"memory_id": "note"})
    primary = RuntimeError("delete failure")

    @contextmanager
    def failing(*args, **kwargs):
        raise primary
        yield  # pragma: no cover

    def close_failure():
        raise OSError("client close failure")

    client.stream, client.close = failing, close_failure
    with pytest.raises(RuntimeError) as caught:
        note.close()
    assert caught.value is primary
    assert primary.__notes__ == ["SECONDARY_MCP_CLIENT_CLOSE_FAILURE: OSError"]
    note.close()  # No second DELETE.

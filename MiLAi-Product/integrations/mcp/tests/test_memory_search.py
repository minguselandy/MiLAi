import asyncio
from contextlib import asynccontextmanager

import pytest
from mcp.types import CallToolResult, TextContent

from milai_mcp.auth_policy import ALL_SCOPES, AdmissionPolicy
from milai_mcp.memory_search import memory_search_tool
from test_aigcit_full import private_fixture
from test_aigcit_http import edge, rpc


def result(body):
    return CallToolResult(content=[], structured_content=body)


def test_discovery_runs_both_reads_concurrently_and_keeps_source_contracts():
    async def run():
        calls, arrived = [], asyncio.Event()
        note_page = {"items": [{"memory_id": "note-one", "authority": "HOST_WORKING"}],
                     "next_cursor": "note-cursor", "truncated": True}
        governed_page = {"retrieval_status": "HIT", "evidence": [{"kind": "CANONICAL_STATE"}],
                         "context_id": "context-one", "continuation": {"query": "same-query"}}

        async def invoke(name, arguments, ctx):
            calls.append((name, arguments))
            if len(calls) == 2:
                arrived.set()
            await asyncio.wait_for(arrived.wait(), 1)
            return result(note_page if name == "milai_note_search" else governed_page)

        value = await memory_search_tool(invoke)(None, "this week's meetings", note_query="会议")
        assert value["retrieval_status"] == "HIT"
        assert value["coverage"] == "BOUNDED_QUERIES_COMPLETED"
        assert value["absence_confirmed"] is False
        assert value["sources"]["notes"]["result"] == note_page
        assert value["sources"]["governed"]["result"] == governed_page
        assert calls == [("milai_note_search", {"query": "会议", "limit": 3}),
                         ("milai_memory_resolve", {"query": "this week's meetings"})]

    asyncio.run(run())


@pytest.mark.parametrize("note_hit,governed_hit", [(True, False), (False, True), (False, False)])
def test_one_source_miss_does_not_hide_the_other_or_prove_absence(note_hit, governed_hit):
    async def invoke(name, args, ctx):
        if name == "milai_note_search":
            return result({"items": [{"memory_id": "n"}] if note_hit else []})
        return result({"retrieval_status": "HIT" if governed_hit else "MISS",
                       "evidence": [{"text": "evidence"}] if governed_hit else []})

    value = asyncio.run(memory_search_tool(invoke)(None, "query"))
    assert value["retrieval_status"] == ("HIT" if note_hit or governed_hit else "MISS")
    assert value["absence_confirmed"] is False


@pytest.mark.parametrize("failure,status", [
    ("denied", "NOT_AUTHORIZED"), ("exception", "ERROR"),
    ("timeout", "TIMEOUT"), ("error_result", "UNAVAILABLE"),
])
def test_partial_failures_are_not_empty_history_and_do_not_leak_errors(failure, status):
    async def invoke(name, args, ctx):
        if name == "milai_note_search":
            return result({"items": []})
        if failure == "denied":
            return CallToolResult(is_error=True, content=[
                TextContent(type="text", text="insufficient_scope")])
        if failure == "exception":
            raise RuntimeError("private transport detail must not be returned")
        if failure == "timeout":
            await asyncio.Event().wait()
        return result({"retrieval_status": "ERROR", "evidence": [{"text": "must withhold"}]})

    value = asyncio.run(memory_search_tool(invoke, timeout_seconds=0.02)(None, "query"))
    assert value["retrieval_status"] == "INCOMPLETE"
    assert value["coverage"] == "PARTIAL"
    assert value["sources"]["governed"]["status"] == status
    assert value["sources"]["governed"]["result"] is None
    assert "private transport" not in str(value) and "must withhold" not in str(value)
    assert value["absence_confirmed"] is False


def test_cancellation_propagates_to_both_reads_without_retry():
    async def run():
        calls, cancelled, started = [], [], asyncio.Event()

        async def invoke(name, args, ctx):
            calls.append(name)
            if len(calls) == 2:
                started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(name)

        task = asyncio.create_task(memory_search_tool(invoke)(None, "query"))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 2 and sorted(cancelled) == sorted(calls)

    asyncio.run(run())


def test_note_service_unavailable_is_not_treated_as_no_notes():
    async def invoke(name, args, ctx):
        if name == "milai_note_search":
            return CallToolResult(is_error=True, content=[TextContent(
                type="text", text='Error executing tool: {"code":"NOTE_UNAVAILABLE"}')])
        return result({"retrieval_status": "MISS", "evidence": []})

    value = asyncio.run(memory_search_tool(invoke)(None, "query"))
    assert value["sources"]["notes"]["status"] == "UNAVAILABLE"
    assert value["retrieval_status"] == "INCOMPLETE"
    assert value["absence_confirmed"] is False


def test_oauth_catalog_retains_routing_and_dispatch_checks_each_source(tmp_path):
    fixture = private_fixture(tmp_path / "policy.json")
    note_calls = []

    class Notes:
        async def browse_notes(self, payload):
            note_calls.append(payload)
            return {"items": [{"memory_id": "private-note", "snippet": "synthetic meeting"}]}

    @asynccontextmanager
    async def factory():
        yield Notes()

    with edge(fixture, scopes=ALL_SCOPES, catalog="ordinary-memory-v1",
              working_state_client_factory=factory) as (http, _server, roles):
        token = fixture.token(sub="alice", scope=" ".join(ALL_SCOPES))
        initialized = rpc(http, "initialize", token=token, params={
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "routing-test", "version": "1"},
        }).json()["result"]
        assert "milai_memory_search" in initialized["instructions"]
        assert "milai_note_search searches Notes only" in initialized["instructions"]
        assert "Only tools and scopes granted" in initialized["instructions"]
        for scopes in [{"milai.note.read"}, {"milai.memory.read"},
                       {"milai.note.read", "milai.memory.read"}]:
            token = fixture.token(sub="alice", scope=" ".join(sorted(scopes)))
            tools = rpc(http, "tools/list", token=token).json()["result"]["tools"]
            search = next(tool for tool in tools if tool["name"] == "milai_memory_search")
            assert search["annotations"]["readOnlyHint"] is True
            before_notes, before_roles = len(note_calls), len(roles[0].calls)
            response = rpc(http, "tools/call", token=token, params={
                "name": "milai_memory_search", "arguments": {"query": "meeting"},
            }).json()["result"]
            assert not response.get("isError"), response
            value = response["structuredContent"]
            assert value["sources"]["notes"]["status"] == (
                "OK" if "milai.note.read" in scopes else "NOT_AUTHORIZED")
            assert value["sources"]["governed"]["status"] == (
                "OK" if "milai.memory.read" in scopes else "NOT_AUTHORIZED")
            assert len(note_calls) - before_notes == int("milai.note.read" in scopes)
            assert (len(roles[0].calls) > before_roles) == ("milai.memory.read" in scopes)
        for payload in note_calls:
            assert payload["project_id"].startswith("private:")
            assert len(payload["principal_binding_digest"]) == 64
        assert len({p["principal_binding_digest"] for p in note_calls}) == 1
        token = fixture.token(sub="alice", scope="milai.note.write")
        denied = rpc(http, "tools/call", token=token, params={
            "name": "milai_memory_search", "arguments": {"query": "meeting"},
        }).json()["result"]
        assert denied["isError"]
        assert not AdmissionPolicy.allows_tool("milai_memory_search", {"milai.note.write"})

"""Signed HTTP facade contracts. Persistence is tested separately against real PG."""

import json
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest
from milai_client import ConflictError, UnavailableError

from milai_mcp.auth_policy import (
    ALL_SCOPES,
    COMPACT_CATALOG_TOOL_SCOPES,
    ORDINARY_CATALOG_TOOL_SCOPES,
    AdmissionPolicy,
    private_project_for,
)
from milai_mcp.compact_memory import COMPACT_BACKENDS
from milai_mcp.input_contracts import CAPTURE_EXAMPLE
from support.auth import ISSUER
from support.http import edge, rpc
from support.private_catalog import private_fixture
from support.profile import CLAIM_ID, EVIDENCE_ID

NOTE_ID = "00000000-0000-4000-8000-000000000099"
NOTE_REF = {"target": {"kind": "NOTE", "id": NOTE_ID, "version": 1}}
EVIDENCE_REF = {"target": {"kind": "EVIDENCE", "id": EVIDENCE_ID}}
CAPTURE = {
    "content": CAPTURE_EXAMPLE["content"], "operation_id": "compact-capture",
    "options": {"action": "CAPTURE_EVIDENCE", **{
        k: v for k, v in CAPTURE_EXAMPLE.items() if k not in {"content", "operation_id"}
    }},
}


class Spy:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.note = {
            "memory_id": NOTE_ID, "version": 1, "object_type": "HOST_NOTE",
            "authority": "HOST_WORKING", "read_tool": "milai_note_get",
            "read_arguments": {"memory_id": NOTE_ID, "version": 1}, "content": "会议记录",
        }

    async def write_note(self, payload, *, operation_id):
        self.calls.append(("write", payload, operation_id))
        if self.failure:
            raise self.failure
        return {**self.note, "durable": True, "commit_status": "COMMITTED"}

    async def get_note(self, payload):
        self.calls.append(("get", payload))
        return dict(self.note)

    async def get_note_operation(self, payload):
        self.calls.append(("operation", payload))
        return {**self.note, "commit_status": "COMMITTED"}

    async def browse_notes(self, payload):
        self.calls.append(("list", payload))
        return {"items": [dict(self.note)], "next_cursor": "note-cursor"}

    async def browse_evidence(self, payload):
        self.calls.append(("evidence_list", payload))
        return {"items": [{"evidence_id": EVIDENCE_ID, "read_tool": "milai_evidence_get",
                           "read_arguments": {"evidence_id": EVIDENCE_ID}}], "next_cursor": None}

    async def get_evidence_content(self, evidence_id, *, project_id):
        self.calls.append(("evidence_get", {"project_id": project_id, "evidence_id": evidence_id}))
        return {"content": "Synthetic source observation", "source_ref": "manual://synthetic"}


@contextmanager
def compact_edge(tmp_path, catalog="compact-memory-v1", scopes=ALL_SCOPES):
    fixture, spy = private_fixture(tmp_path / "policy.json"), Spy()

    @asynccontextmanager
    async def factory():
        yield spy

    with edge(fixture, scopes=scopes, catalog=catalog,
              working_state_client_factory=factory) as (http, server, roles):
        roles[0].project_id = private_project_for(ISSUER, "alice", "project-one")
        yield fixture, http, server, roles, spy


def tool_call(http, token, name, arguments, *, error=False):
    response = rpc(http, "tools/call", token=token, params={"name": name, "arguments": arguments})
    assert response.status_code == 200, response.text
    value = response.json()["result"]
    assert bool(value.get("isError")) == error, value
    if error:
        message = value["content"][0]["text"]
        return json.loads(message[message.index("{"):])
    return value["structuredContent"]


def test_compact_directory_schemas_cost_and_no_cached_advanced_dispatch(tmp_path):
    catalogs = {}
    for catalog in ["ordinary-memory-v1", "compact-memory-v1"]:
        with compact_edge(tmp_path, catalog) as (fixture, http, server, roles, spy):
            token = fixture.token(sub="alice", scope=" ".join(ALL_SCOPES))
            tools = rpc(http, "tools/list", token=token).json()["result"]["tools"]
            catalogs[catalog] = tools
            expected = (COMPACT_CATALOG_TOOL_SCOPES if catalog == "compact-memory-v1"
                        else ORDINARY_CATALOG_TOOL_SCOPES)
            assert {t["name"] for t in tools} == set(expected)
            if catalog != "compact-memory-v1":
                continue
            assert len(tools) == 8
            init = rpc(http, "initialize", token=token, params={
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "compact-test", "version": "1"},
            }).json()["result"]
            assert "milai_memory_save defaults" in init["instructions"]
            assert "Only tools and scopes granted" in init["instructions"]
            assert set(t.name for t in server._tool_manager.list_tools()) == set(expected)
            for name in COMPACT_BACKENDS | {"milai_proposal_create", "milai_memory_review",
                                           "milai_namespace_cleanup_submit"}:
                response = rpc(http, "tools/call", token=token,
                               params={"name": name, "arguments": CAPTURE_EXAMPLE}).json()
                assert "error" in response or response["result"]["isError"]
            assert not spy.calls and not any(role.calls for role in roles)
            for tool in tools:
                assert "$ref" not in json.dumps(tool["inputSchema"])
                assert tool["inputSchema"]["additionalProperties"] is False
                assert tool["annotations"]["destructiveHint"] == (
                    tool["name"] == "milai_memory_delete")
            save = next(t for t in tools if t["name"] == "milai_memory_save")
            assert set(save["inputSchema"]["required"]) == {"content", "operation_id"}
            branches = save["inputSchema"]["properties"]["options"]["oneOf"]
            capture = next(b for b in branches
                           if b["properties"]["action"]["const"] == "CAPTURE_EVIDENCE")
            assert capture["properties"]["source_type"]["pattern"] == "^[A-Z][A-Z0-9_]*$"
            assert "confirmation" in capture["required"]
    assert len(json.dumps(catalogs["compact-memory-v1"])) < len(
        json.dumps(catalogs["ordinary-memory-v1"]))


def test_shared_save_read_list_update_and_status_routes(tmp_path):
    with compact_edge(tmp_path) as (fixture, http, _server, roles, spy):
        token = fixture.token(sub="alice", scope=" ".join(ALL_SCOPES))
        saved = tool_call(http, token, "milai_memory_save", {
            "content": "会议记录", "operation_id": "shared-save",
        })
        assert saved["read_tool"] == "milai_memory_read"
        assert saved["read_arguments"] == NOTE_REF
        assert saved["durable"] and saved["authority"] == "HOST_WORKING"
        assert tool_call(http, token, "milai_memory_read", saved["read_arguments"])["content"]
        capture = tool_call(http, token, "milai_memory_save", CAPTURE)
        assert capture["reference"]["read_tool"] == "milai_memory_read"
        assert capture["reference"]["read_arguments"] == EVIDENCE_REF
        assert "next_tool" not in capture["suggested_next_step"]
        assert tool_call(http, token, "milai_memory_read", EVIDENCE_REF)["content"]
        for kind in ["NOTE", "EVIDENCE"]:
            listed = tool_call(http, token, "milai_memory_list", {"selection": {"kind": kind}})
            assert listed["items"][0]["read_tool"] == "milai_memory_read"
            tool_call(http, token, "milai_memory_read", listed["items"][0]["read_arguments"])
        tool_call(http, token, "milai_memory_save", {
            "content": "updated", "operation_id": "update", "options": {
                "action": "UPDATE_NOTE", "memory_id": NOTE_ID, "expected_version": 1, "tags": [],
            },
        })
        update = spy.calls[-1][1]
        assert update["operation"] == "UPDATE" and update["expected_version"] == 1
        assert update["tags"] == [] and "source_refs" not in update and "format" not in update
        tool_call(http, token, "milai_memory_status", {
            "target": {"kind": "NOTE_WRITE", "operation_id": "update"},
        })
        assert spy.calls[-1][1]["operation_id"] == "update"
        assert not any(name in {"review", "proposal_create"}
                       for role in roles for name, _ in role.calls)


@pytest.mark.parametrize("name,arguments,required_scope", [
    ("milai_memory_save", {"content": "note", "operation_id": "op"}, "milai.note.write"),
    ("milai_memory_save", {"content": "edit", "operation_id": "op", "options": {
        "action": "UPDATE_NOTE", "memory_id": NOTE_ID, "expected_version": 1,
    }}, "milai.note.write"),
    ("milai_memory_save", CAPTURE, "milai.evidence.capture"),
    ("milai_memory_read", NOTE_REF, "milai.note.read"),
    ("milai_memory_read", EVIDENCE_REF, "milai.evidence.read"),
    ("milai_memory_read", {"target": {"kind": "CLAIM", "id": EVIDENCE_ID}}, "milai.memory.read"),
    ("milai_memory_list", {}, "milai.note.read"),
    ("milai_memory_list", {"selection": {"kind": "EVIDENCE"}}, "milai.evidence.read"),
    ("milai_memory_delete", {"operation_id": "op", "target": {
        "kind": "NOTE", "id": NOTE_ID, "expected_version": 1, "confirmation": "DELETE",
    }}, "milai.note.delete"),
    ("milai_memory_delete", {"operation_id": "op", "target": {
        "kind": "EVIDENCE", "id": EVIDENCE_ID, "reason_code": "USER_REQUEST",
        "confirmation": "REVOKE",
    }}, "milai.evidence.revoke"),
    ("milai_memory_status", {"target": {"kind": "NOTE_WRITE", "operation_id": "op"}},
     "milai.note.read"),
    ("milai_memory_status", {"target": {"kind": "EVIDENCE_DELETION", "id": EVIDENCE_ID}},
     "milai.memory.read"),
])
def test_each_selected_operation_rechecks_scope_even_when_facade_visible(
    tmp_path, name, arguments, required_scope,
):
    with compact_edge(tmp_path) as (fixture, http, _server, roles, spy):
        for scope in ALL_SCOPES:
            token = fixture.token(sub="alice", scope=scope)
            before = len(spy.calls) + sum(len(role.calls) for role in roles)
            response = rpc(http, "tools/call", token=token,
                           params={"name": name, "arguments": arguments}).json()["result"]
            after = len(spy.calls) + sum(len(role.calls) for role in roles)
            if scope == required_scope:
                assert not response.get("isError"), response
                assert after > before
            else:
                assert response["isError"] and after == before
        visible = rpc(http, "tools/list", token=token).json()["result"]["tools"]
        assert {t["name"] for t in visible} == {
            t for t in COMPACT_CATALOG_TOOL_SCOPES if AdmissionPolicy.allows_tool(t, {scope})
        }


@pytest.mark.parametrize("name,args", [
    ("milai_memory_save", {**CAPTURE, "options": {**CAPTURE["options"], "source_type": "bad"}}),
    ("milai_memory_save", {"content": "x", "operation_id": "op", "options": {
        "action": "UPDATE_NOTE", "memory_id": NOTE_ID,
    }}),
    ("milai_memory_save", {"content": "x", "operation_id": "op", "options": {
        "action": "UPDATE_EVIDENCE", "evidence_id": EVIDENCE_ID,
    }}),
    ("milai_memory_delete", {"operation_id": "op", "target": {
        "kind": "EVIDENCE", "id": EVIDENCE_ID, "reason_code": "USER_REQUEST",
        "confirmation": "DELETE",
    }}),
    ("milai_memory_read", {"target": {"kind": "EVIDENCE", "id": EVIDENCE_ID,
                                       "version": 1, "project_id": "foreign"}}),
    ("milai_memory_list", {"selection": {"kind": "EVIDENCE", "query": "unsupported"}}),
])
def test_discriminated_schemas_reject_invented_operations_and_ignored_fields(tmp_path, name, args):
    with compact_edge(tmp_path) as (fixture, http, _server, roles, spy):
        token = fixture.token(sub="alice", scope=" ".join(ALL_SCOPES))
        error = tool_call(http, token, name, args, error=True)
        assert error["code"] == "INVALID_ARGUMENT"
        assert not error["retryable"] and error["fields"]
        assert not spy.calls and not any(role.calls for role in roles)


@pytest.mark.parametrize("unknown", [False, True])
def test_recovery_uses_available_compact_tools_without_retry(tmp_path, unknown):
    with compact_edge(tmp_path) as (fixture, http, _server, _roles, spy):
        token = fixture.token(sub="alice", scope=" ".join(ALL_SCOPES))
        spy.failure = (UnavailableError("private transport error") if unknown else
                       ConflictError("private error", code="STALE_NOTE", status_code=409))
        error = tool_call(http, token, "milai_memory_save", {
            "content": "updated", "operation_id": "original", "options": {
                "action": "UPDATE_NOTE", "memory_id": NOTE_ID, "expected_version": 1,
            },
        }, error=True)
        assert len(spy.calls) == 1 and "private" not in json.dumps(error)
        assert not error["retryable"]
        assert error["next_tool"] == ("milai_memory_status" if unknown else "milai_memory_read")
        expected = ({"kind": "NOTE_WRITE", "operation_id": "original"} if unknown else
                    {"kind": "NOTE", "id": NOTE_ID})
        assert error["next_arguments"] == {"target": expected}


def test_compact_search_reads_through_refs_and_keeps_partial_scope_status(tmp_path):
    with compact_edge(tmp_path) as (fixture, http, _server, roles, spy):
        token = fixture.token(sub="alice", scope=" ".join(ALL_SCOPES))
        result = tool_call(http, token, "milai_memory_search", {
            "query": "上次会议讨论了什么", "note_query": "会议", "previous_context_id": "prior",
        })
        assert not result["absence_confirmed"] and "mcp_guidance" not in result
        assert result["suggested_next_step"]["optional"]
        note = result["sources"]["notes"]["result"]["items"][0]
        assert note["read_arguments"] == NOTE_REF
        governed = result["sources"]["governed"]["result"]["evidence"][0]
        assert governed["read_references"][0]["read_arguments"] == EVIDENCE_REF
        tool_call(http, token, "milai_memory_read", note["read_arguments"])
        assert roles[0].calls[0][1][1]["previous_context_id"] == "prior"
        for sub in ["alice", "bob"]:
            token = fixture.token(sub=sub, scope="milai.note.read")
            partial = tool_call(http, token, "milai_memory_search", {"query": "会议"})
            assert partial["coverage"] == "PARTIAL"
            assert partial["sources"]["governed"]["status"] == "NOT_AUTHORIZED"
        assert len({payload["project_id"] for _method, payload, *_ in spy.calls}) == 2
        tool_call(http, token, "milai_memory_list", {
            "selection": {"kind": "NOTE", "query": "会议"}, "cursor": "note-cursor", "limit": 3,
        })
        assert spy.calls[-1][1]["cursor"] == "note-cursor"


def test_compact_does_not_rewrite_host_content_sources_or_claim_payload(tmp_path):
    # Tool-like strings/objects inside user data are data, not routing instructions.
    embedded = {"read_tool": "milai_note_get", "read_arguments": {"memory_id": NOTE_ID},
                "suggested_next_step": {"next_tool": "milai_proposal_create"}}
    content = " \r\n" + json.dumps(embedded, ensure_ascii=False) + "\t 🧠 "
    sources = [{"kind": "FILE", "locator": "milai_note_get", "revision": "milai_note_add",
                "content_digest": None}]
    with compact_edge(tmp_path) as (fixture, http, _server, roles, spy):
        token = fixture.token(sub="alice", scope=" ".join(ALL_SCOPES))
        spy.note.update(content=content, source_refs=sources, payload=embedded)
        saved = tool_call(http, token, "milai_memory_save", {
            "content": content, "operation_id": "fidelity", "options": {
                "action": "ADD_NOTE", "source_refs": sources,
            },
        })
        assert spy.calls[-1][1]["content"] == content
        assert spy.calls[-1][1]["source_refs"] == sources
        read = tool_call(http, token, saved["read_tool"], saved["read_arguments"])
        assert read["content"] == content and read["source_refs"] == sources
        assert read["payload"] == embedded
        ordinary_get = roles[0].get_memory

        def get_memory(**options):
            value = ordinary_get(**options).raw
            value["items"][0]["payload"] = embedded
            return SimpleNamespace(raw=value)

        roles[0].get_memory = get_memory
        ordinary_resolve = roles[0].resolve_memory

        def resolve_memory(query, **options):
            value = ordinary_resolve(query, **options).raw
            value.pop("memory_context")
            value["items"] = [{"claim_id": CLAIM_ID, "payload": embedded}]
            return SimpleNamespace(raw=value)

        roles[0].resolve_memory = resolve_memory
        found = tool_call(http, token, "milai_memory_search", {"query": "synthetic claim"})
        unit = found["sources"]["governed"]["result"]["evidence"][0]
        reference = unit["read_references"][0]
        assert reference["read_tool"] == "milai_memory_read"
        assert reference["read_arguments"] == {"target": {"kind": "CLAIM", "id": CLAIM_ID}}
        assert json.loads(unit["text"]) == embedded
        claim = tool_call(http, token, reference["read_tool"], reference["read_arguments"])
        assert claim["items"][0]["payload"] == embedded


def test_every_scope_filters_all_three_catalogs_and_search_keeps_both_partial_routes(tmp_path):
    for catalog, total in [("legacy", 13), ("ordinary-memory-v1", 22), ("compact-memory-v1", 8)]:
        with compact_edge(tmp_path, catalog) as (fixture, http, _server, _roles, _spy):
            all_token = fixture.token(sub="alice", scope=" ".join(ALL_SCOPES))
            full = rpc(http, "tools/list", token=all_token).json()["result"]["tools"]
            assert len(full) == total
            for scope in ALL_SCOPES:
                token = fixture.token(sub="alice", scope=scope)
                tools = rpc(http, "tools/list", token=token).json()["result"]["tools"]
                assert {t["name"] for t in tools} == {
                    t["name"] for t in full if AdmissionPolicy.allows_tool(t["name"], {scope})
                }
            if catalog != "compact-memory-v1":
                continue
            token = fixture.token(sub="alice", scope="milai.memory.read")
            search = tool_call(http, token, "milai_memory_search", {"query": "meeting"})
            assert search["sources"]["notes"]["status"] == "NOT_AUTHORIZED"
            assert search["sources"]["governed"]["status"] == "OK"
            assert search["coverage"] == "PARTIAL" and not search["absence_confirmed"]


def test_compact_search_reports_note_unavailability_not_generic_error(tmp_path):
    with compact_edge(tmp_path) as (fixture, http, _server, _roles, spy):
        async def unavailable(payload):
            raise UnavailableError("synthetic secret transport details")

        spy.browse_notes = unavailable
        token = fixture.token(sub="alice", scope=" ".join(ALL_SCOPES))
        result = tool_call(http, token, "milai_memory_search", {"query": "question"})
        assert result["sources"]["notes"]["status"] == "UNAVAILABLE"
        assert result["sources"]["governed"]["status"] == "OK"
        assert result["sources"]["notes"]["result"] is None
        assert "synthetic secret" not in json.dumps(result)


@pytest.mark.parametrize("tool,args,method", [
    ("milai_memory_read", EVIDENCE_REF, "get_evidence_content"),
    ("milai_memory_list", {"selection": {"kind": "EVIDENCE"}}, "browse_evidence"),
])
def test_evidence_unavailability_has_complete_compact_recovery(tmp_path, tool, args, method):
    with compact_edge(tmp_path) as (fixture, http, _server, _roles, spy):
        async def unavailable(*args, **kwargs):
            spy.calls.append(("failed-once", {}))
            raise UnavailableError("synthetic private backend detail")

        setattr(spy, method, unavailable)
        token = fixture.token(sub="alice", scope=" ".join(ALL_SCOPES))
        error = tool_call(http, token, tool, args, error=True)
        assert error["code"] == "EVIDENCE_UNAVAILABLE"
        assert error["retryable"] is False
        assert error["recovery_action"] == "RESTORE_AVAILABILITY"
        assert len(spy.calls) == 1 and "synthetic private" not in json.dumps(error)

"""Exercise the public schema and tool parser with the shipped examples."""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from mcp import Client
from milai_client import MilaiClientError

from milai_mcp.input_contracts import CAPTURE_EXAMPLE, CREATE_EXAMPLE, PROPOSAL_EXAMPLES
from milai_mcp.recovery import recovery_error
from milai_mcp.server import CodexFullRuntimeClients, build_server
from test_codex_full_profile import _as_client, _RoleClient


def test_public_capture_contract_examples_and_safe_errors() -> None:
    async def run() -> None:
        role = _RoleClient("all")
        api = _as_client(role)
        server = build_server(
            "codex-full", api, default_scope={"project_ids": ["project-one"]},
            codex_full_clients=CodexFullRuntimeClients(api, api, api, api),
        )
        async with Client(server, mode="2026-07-28") as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            schema = tools["milai_evidence_capture"].input_schema
            assert schema["properties"]["source_type"]["pattern"] == "^[A-Z][A-Z0-9_]*$"
            assert schema["properties"]["subject_id"]["maxLength"] == 512
            assert schema["properties"]["observed_at"]["format"] == "date-time"
            body = " \r\n用户原文 🧠\n```py\nx = 1\n```\t "
            result = await client.call_tool(
                "milai_evidence_capture", {**CAPTURE_EXAMPLE, "content": body},
            )
            assert not result.is_error
            assert role.calls[-1][1][0]["content"] == body
            for change, path in (
                ({"source_type": "private_invalid_value"}, "source_type"),
                ({"observed_at": "2026-09-08T00:00:00"}, "observed_at"),
                ({"source_context": {"session_id": "private_source"}}, "source_context.turn_id"),
            ):
                before = len(role.calls)
                result = await client.call_tool(
                    "milai_evidence_capture", {**CAPTURE_EXAMPLE, **change, "content": body},
                )
                assert result.is_error
                text = result.content[0].text
                error = json.loads(text)
                assert any(field["path"] == path for field in error["fields"])
                assert "private_" not in text and body not in text
                assert len(role.calls) == before
            result = await client.call_tool("milai_proposal_create", CREATE_EXAMPLE)
            assert not result.is_error
            incomplete = {**CREATE_EXAMPLE, "proposal": {
                "operation": "CREATE", "proposed_patch": {"subject_id": "example"},
            }}
            result = await client.call_tool("milai_proposal_create", incomplete)
            assert result.is_error
            assert "proposal.proposed_patch.predicate" in result.content[0].text

    asyncio.run(run())


@pytest.mark.parametrize("operation", list(PROPOSAL_EXAMPLES))
@pytest.mark.parametrize("catalog", ["legacy", "ordinary-memory-v1"])
def test_all_enabled_proposal_examples_match_wire_and_parser(operation: str, catalog: str) -> None:
    @asynccontextmanager
    async def unused_state_client():
        # Proposal dispatch uses the synthetic role client, never State transport.
        yield None

    async def run() -> None:
        role = _RoleClient("all")
        api = _as_client(role)
        server = build_server(
            "codex-full", api, default_scope={"project_ids": ["project-one"]},
            codex_full_clients=CodexFullRuntimeClients(api, api, api, api),
            catalog=catalog,
            working_state_client_factory=(
                unused_state_client if catalog == "ordinary-memory-v1" else None
            ),
        )
        async with Client(server, mode="2026-07-28") as client:
            tool = next(t for t in (await client.list_tools()).tools
                        if t.name == "milai_proposal_create")
            assert tool.input_schema["properties"]["proposal"]["type"] == "object"
            assert "$ref" not in json.dumps(tool.input_schema)
            validator = Draft202012Validator(tool.input_schema, format_checker=FormatChecker())
            example = PROPOSAL_EXAMPLES[operation]
            validator.validate(example)
            assert not (await client.call_tool(tool.name, example)).is_error
            draft = next(call[1][0] for call in role.calls if call[0] == "proposal_create")
            assert draft.operation == operation
            for key in ["supporting_evidence_refs", "contradicting_evidence_refs"]:
                if example["proposal"].get(key):
                    bad = {**example, "proposal": {**example["proposal"], key: []}}
                    assert list(validator.iter_errors(bad))
                    before = len(role.calls)
                    result = await client.call_tool(tool.name, bad)
                    assert result.is_error and key in result.content[0].text
                    assert len(role.calls) == before

    asyncio.run(run())


@pytest.mark.parametrize("change,field", [
    ({"supporting_evidence_refs": ["private-invalid-uuid"]}, "supporting_evidence_refs.0"),
    ({"supporting_evidence_refs": ["00000000-0000-4000-8000-000000000001"] * 2},
     "supporting_evidence_refs"),
    ({"contradicting_evidence_refs": ["00000000-0000-4000-8000-000000000001"]},
     "contradicting_evidence_refs"),
    ({"proposed_patch": {"resolve_issue_id": "00000000-0000-4000-8000-000000000004"}},
     "expected_issue_revision"),
    ({"proposed_patch": {"authority": "USER_CONFIRMED"}}, "proposed_patch"),
    ({"target_claim_id": "private-invalid-uuid"}, "target_claim_id"),
])
def test_proposal_errors_name_safe_fields_and_do_not_dispatch(change, field) -> None:
    async def run() -> None:
        role = _RoleClient("all")
        api = _as_client(role)
        server = build_server(
            "codex-full", api, default_scope={"project_ids": ["project-one"]},
            codex_full_clients=CodexFullRuntimeClients(api, api, api, api),
        )
        example = PROPOSAL_EXAMPLES["SUPERSEDE"]
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool("milai_proposal_create", {
                **example, "proposal": {**example["proposal"], **change},
            })
        assert result.is_error and field in result.content[0].text
        assert "private-invalid-uuid" not in result.content[0].text
        assert not any(call[0] in {"proposal_create", "evidence_metadata_get", "claim_get"}
                       for call in role.calls)

    asyncio.run(run())


def test_runtime_field_details_reach_mcp_without_backend_payload() -> None:
    class RejectedClient(_RoleClient):
        def capture_evidence(self, payload: dict[str, Any], *, operation_id: str) -> Any:
            raise MilaiClientError(
                "private backend input", status_code=400, code="INVALID_REQUEST",
                details={"fields": [{
                    "path": "source_type", "type": "string_pattern_mismatch",
                    "input": "private input", "msg": "private message",
                }], "token": "private credential"},
            )

    async def run() -> None:
        api = _as_client(RejectedClient("all"))
        server = build_server(
            "codex-full", api, default_scope={"project_ids": ["project-one"]},
            codex_full_clients=CodexFullRuntimeClients(api, api, api, api),
        )
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool("milai_evidence_capture", CAPTURE_EXAMPLE)
        assert result.is_error
        assert "source_type" in result.content[0].text
        assert "uppercase identifier" in result.content[0].text
        assert "private" not in result.content[0].text

    asyncio.run(run())


@pytest.mark.parametrize("catalog", ["legacy", "ordinary-memory-v1"])
@pytest.mark.parametrize("payload", [None, [], "private-invalid-payload"])
def test_create_payload_hint_excludes_working_state_constraints(catalog, payload) -> None:
    @asynccontextmanager
    async def unused_state_client():
        yield None

    async def run() -> None:
        role = _RoleClient("all")
        api = _as_client(role)
        server = build_server(
            "codex-full", api, default_scope={"project_ids": ["project-one"]},
            codex_full_clients=CodexFullRuntimeClients(api, api, api, api),
            catalog=catalog,
            working_state_client_factory=(
                unused_state_client if catalog == "ordinary-memory-v1" else None
            ),
        )
        patch = {**CREATE_EXAMPLE["proposal"]["proposed_patch"]}
        if payload is None:
            del patch["payload"]
        else:
            patch["payload"] = payload
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool("milai_proposal_create", {
                **CREATE_EXAMPLE,
                "proposal": {**CREATE_EXAMPLE["proposal"], "proposed_patch": patch},
            })
        assert result.is_error
        error = json.loads(result.content[0].text)
        assert error["retryable"] is False
        field = next(f for f in error["fields"] if f["path"] == "proposal.proposed_patch.payload")
        assert field["expected"] == "business JSON object"
        assert "Working State" not in result.content[0].text
        assert "65536" not in result.content[0].text
        assert "1024" not in result.content[0].text
        assert "private-invalid-payload" not in result.content[0].text
        assert not role.calls

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["WORKING_STATE", "NOTE"])
def test_backend_payload_hint_uses_trusted_operation_context(kind) -> None:
    error = recovery_error(MilaiClientError(
        "private backend message", status_code=400, code="INVALID_ARGUMENT",
        details={"fields": [{"path": "payload", "type": "value_error",
                             "input": "private input", "working_state": kind != "WORKING_STATE"}]},
    ), kind=kind, write=True)
    expected = error["fields"][0]["expected"]
    assert ("Working State" in expected) == (kind == "WORKING_STATE")
    assert ("65536" in expected) == (kind == "WORKING_STATE")
    assert ("1024" in expected) == (kind == "WORKING_STATE")
    assert error["retryable"] is False
    assert "private" not in json.dumps(error)

from milai_mcp import server
from milai_mcp import server_contracts as contracts
from milai_mcp import server_middleware as middleware
from milai_mcp import server_wire as wire


def test_server_facade_preserves_contract_objects() -> None:
    assert server.Profile is contracts.Profile
    assert server.CodexFullRuntimeClients is contracts.CodexFullRuntimeClients
    assert server.CodexFullProposalInput is contracts.CodexFullProposalInput
    assert server.StateKeyInput is contracts.StateKeyInput
    assert server.TaskContextInput is contracts.TaskContextInput
    assert server.TOOL_COMPATIBILITY_VNEXT is contracts.TOOL_COMPATIBILITY_VNEXT
    assert server.SERVER_DESCRIPTION is contracts.SERVER_DESCRIPTION
    assert server._tool_annotations is contracts._tool_annotations


def test_server_facade_preserves_middleware_objects() -> None:
    assert server._StrictArguments is middleware._StrictArguments
    assert server._RequestAccessTokenMiddleware is middleware._RequestAccessTokenMiddleware
    assert server._StrictSchemaMCPServer is middleware._StrictSchemaMCPServer
    assert server._request_access_token is middleware._request_access_token


def test_server_facade_preserves_wire_digest() -> None:
    assert server._wire_sha256 is wire._wire_sha256

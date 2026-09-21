from milai_mcp import server
from milai_mcp import server_contracts as contracts
from milai_mcp import server_middleware as middleware
from milai_mcp import server_reader as reader
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
    assert server._MAX_OUTPUT_BYTES == wire._MAX_OUTPUT_BYTES
    assert server._WIDE_MAX_OUTPUT_BYTES == wire._WIDE_MAX_OUTPUT_BYTES
    assert server._wire_sha256 is wire._wire_sha256
    assert server._bounded is wire._bounded
    assert server._with_mcp_guidance is wire._with_mcp_guidance
    assert server._wire_operand_pointer is wire._wire_operand_pointer
    assert server._wire_receipt is wire._wire_receipt
    assert server._deduplicate_resolve_proof_trace is wire._deduplicate_resolve_proof_trace
    assert server._compact_resolve_operands is wire._compact_resolve_operands
    assert server._compact_mapping_diagnostics is wire._compact_mapping_diagnostics
    assert server._compact_raw_evidence_items is wire._compact_raw_evidence_items
    assert server._compact_context_compile_diagnostics is wire._compact_context_compile_diagnostics
    assert server._compact_context_windows is wire._compact_context_windows
    assert server._wire_proof_pointer is wire._wire_proof_pointer
    assert server._compact_top_level_resolve_proof is wire._compact_top_level_resolve_proof
    assert server._compact_derived_operator_trace is wire._compact_derived_operator_trace
    assert server._wire_field_sizes is wire._wire_field_sizes
    assert server._wire_size_diagnostics is wire._wire_size_diagnostics
    assert server._bounded_memory_resolve is wire._bounded_memory_resolve


def test_server_facade_preserves_reader_helpers() -> None:
    assert server.ReaderToolset is reader.ReaderToolset
    assert server.build_reader_toolset is reader.build_reader_toolset
    assert server._bind_effective_need_policy is reader._bind_effective_need_policy
    assert server._mcp_access_trace is reader._mcp_access_trace

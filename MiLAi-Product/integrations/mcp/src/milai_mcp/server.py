"""Compatibility facade for the modular MCP server implementation."""

from __future__ import annotations

from milai_client import MilaiClient as MilaiClient

from milai_mcp.auth_policy import AdmissionPolicy as AdmissionPolicy
from milai_mcp.server_codex import (
    extend_codex_governance_tools as extend_codex_governance_tools,
)
from milai_mcp.server_contracts import (
    _CODEX_FULL_GOVERNANCE_MODE as _CODEX_FULL_GOVERNANCE_MODE,
)
from milai_mcp.server_contracts import (
    _CODEX_FULL_REQUIRED_CAPABILITIES as _CODEX_FULL_REQUIRED_CAPABILITIES,
)
from milai_mcp.server_contracts import (
    _CODEX_WORKING_STATE_USAGE_CONTRACT as _CODEX_WORKING_STATE_USAGE_CONTRACT,
)
from milai_mcp.server_contracts import (
    _DESTRUCTIVE_TOOL_NAMES as _DESTRUCTIVE_TOOL_NAMES,
)
from milai_mcp.server_contracts import (
    _READ_ONLY_TOOL_NAMES as _READ_ONLY_TOOL_NAMES,
)
from milai_mcp.server_contracts import _TOOL_TITLES as _TOOL_TITLES
from milai_mcp.server_contracts import SERVER_DESCRIPTION as SERVER_DESCRIPTION
from milai_mcp.server_contracts import (
    TOOL_COMPATIBILITY_VNEXT as TOOL_COMPATIBILITY_VNEXT,
)
from milai_mcp.server_contracts import (
    CodexFullProposalInput as CodexFullProposalInput,
)
from milai_mcp.server_contracts import (
    CodexFullRuntimeClients as CodexFullRuntimeClients,
)
from milai_mcp.server_contracts import Profile as Profile
from milai_mcp.server_contracts import StateKeyInput as StateKeyInput
from milai_mcp.server_contracts import TaskContextInput as TaskContextInput
from milai_mcp.server_contracts import _tool_annotations as _tool_annotations
from milai_mcp.server_factory import (
    _DEFAULT_MAX_RETRIES as _DEFAULT_MAX_RETRIES,
)
from milai_mcp.server_factory import _LOGGER as _LOGGER
from milai_mcp.server_factory import (
    _RUNTIME_HTTP_TIMEOUT_SECONDS as _RUNTIME_HTTP_TIMEOUT_SECONDS,
)
from milai_mcp.server_factory import (
    _codex_full_clients_from_environment as _codex_full_clients_from_environment,
)
from milai_mcp.server_factory import (
    _is_loopback_host as _is_loopback_host,
)
from milai_mcp.server_factory import (
    _non_negative_int as _non_negative_int,
)
from milai_mcp.server_factory import (
    _required_environment_secret as _required_environment_secret,
)
from milai_mcp.server_factory import build_server as build_server
from milai_mcp.server_factory import main as main
from milai_mcp.server_factory import (
    resolve_budget_profile_by_name as resolve_budget_profile_by_name,
)
from milai_mcp.server_governance import GovernanceToolset as GovernanceToolset
from milai_mcp.server_governance import (
    build_governance_toolset as build_governance_toolset,
)
from milai_mcp.server_middleware import (
    _request_access_token as _request_access_token,
)
from milai_mcp.server_middleware import (
    _RequestAccessTokenMiddleware as _RequestAccessTokenMiddleware,
)
from milai_mcp.server_middleware import _StrictArguments as _StrictArguments
from milai_mcp.server_middleware import (
    _StrictSchemaMCPServer as _StrictSchemaMCPServer,
)
from milai_mcp.server_reader import ReaderToolset as ReaderToolset
from milai_mcp.server_reader import (
    _bind_effective_need_policy as _bind_effective_need_policy,
)
from milai_mcp.server_reader import _mcp_access_trace as _mcp_access_trace
from milai_mcp.server_reader import build_reader_toolset as build_reader_toolset
from milai_mcp.server_wire import _MAX_OUTPUT_BYTES as _MAX_OUTPUT_BYTES
from milai_mcp.server_wire import (
    _WIDE_MAX_OUTPUT_BYTES as _WIDE_MAX_OUTPUT_BYTES,
)
from milai_mcp.server_wire import _bounded as _bounded
from milai_mcp.server_wire import (
    _bounded_memory_resolve as _bounded_memory_resolve,
)
from milai_mcp.server_wire import (
    _compact_context_compile_diagnostics as _compact_context_compile_diagnostics,
)
from milai_mcp.server_wire import (
    _compact_context_windows as _compact_context_windows,
)
from milai_mcp.server_wire import (
    _compact_derived_operator_trace as _compact_derived_operator_trace,
)
from milai_mcp.server_wire import (
    _compact_mapping_diagnostics as _compact_mapping_diagnostics,
)
from milai_mcp.server_wire import (
    _compact_raw_evidence_items as _compact_raw_evidence_items,
)
from milai_mcp.server_wire import (
    _compact_resolve_operands as _compact_resolve_operands,
)
from milai_mcp.server_wire import (
    _compact_top_level_resolve_proof as _compact_top_level_resolve_proof,
)
from milai_mcp.server_wire import (
    _deduplicate_resolve_proof_trace as _deduplicate_resolve_proof_trace,
)
from milai_mcp.server_wire import _wire_field_sizes as _wire_field_sizes
from milai_mcp.server_wire import _wire_operand_pointer as _wire_operand_pointer
from milai_mcp.server_wire import _wire_proof_pointer as _wire_proof_pointer
from milai_mcp.server_wire import _wire_receipt as _wire_receipt
from milai_mcp.server_wire import _wire_sha256 as _wire_sha256
from milai_mcp.server_wire import _wire_size_diagnostics as _wire_size_diagnostics
from milai_mcp.server_wire import _with_mcp_guidance as _with_mcp_guidance

"""Public DG-14 LongMemEval MCP adapter surface.

Keep the adapter import lazy: the narrow MCP dispatcher environment needs the
contracts but intentionally does not carry Reader tokenization dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from evals.dg14.contracts import (
    MCP_PROTOCOL_MODE,
    METHOD_ID,
    DG14AdapterConfig,
    DG14AdapterStats,
    DG14CallRecord,
    DG14CaseNamespace,
    DG14ContextBudgetError,
    DG14ContractError,
    DG14Error,
    DG14HistoryEvent,
    DG14LabelBoundaryError,
    DG14LifecycleError,
    DG14McpTransport,
    DG14Provenance,
    DG14QueryResult,
    DG14ReadinessError,
    DG14ReadinessRequest,
    DG14StageRecord,
    DG14TransportError,
    deterministic_event_id,
    deterministic_history_session_id,
    deterministic_project_id,
    normalize_lme_timestamp,
    validate_label_free,
)
from evals.dg14.mcp_stdio import StdioMcpTransport

if TYPE_CHECKING:
    from evals.dg14.milai_mcp_adapter import DG14MilaiMcpAdapter


def __getattr__(name: str) -> Any:
    if name == "DG14MilaiMcpAdapter":
        from evals.dg14.milai_mcp_adapter import DG14MilaiMcpAdapter

        return DG14MilaiMcpAdapter
    raise AttributeError(name)

__all__ = [
    "MCP_PROTOCOL_MODE",
    "METHOD_ID",
    "DG14AdapterConfig",
    "DG14AdapterStats",
    "DG14CallRecord",
    "DG14CaseNamespace",
    "DG14ContextBudgetError",
    "DG14ContractError",
    "DG14Error",
    "DG14HistoryEvent",
    "DG14LabelBoundaryError",
    "DG14LifecycleError",
    "DG14McpTransport",
    "DG14MilaiMcpAdapter",
    "DG14Provenance",
    "DG14QueryResult",
    "DG14ReadinessError",
    "DG14ReadinessRequest",
    "DG14StageRecord",
    "DG14TransportError",
    "StdioMcpTransport",
    "deterministic_event_id",
    "deterministic_history_session_id",
    "deterministic_project_id",
    "normalize_lme_timestamp",
    "validate_label_free",
]

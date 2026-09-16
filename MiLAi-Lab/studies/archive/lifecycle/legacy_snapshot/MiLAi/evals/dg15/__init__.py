"""DG-15 governed projection pipeline benchmark surfaces.

The product adapter is lazy so the MCP bridge can run in its deliberately
minimal client environment without importing Reader-only dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from evals.dg15.contracts import (
    METHOD_ID,
    DG15AdapterConfig,
    DG15AdapterStats,
    DG15CallRecord,
    DG15Provenance,
    DG15QueryResult,
)
from evals.dg15.mcp_stdio import McpBatchOutcome, MultiplexedStdioMcpTransport

if TYPE_CHECKING:
    from evals.dg15.milai_mcp_adapter import DG15MilaiMcpAdapter


def __getattr__(name: str) -> Any:
    if name == "DG15MilaiMcpAdapter":
        from evals.dg15.milai_mcp_adapter import DG15MilaiMcpAdapter

        return DG15MilaiMcpAdapter
    raise AttributeError(name)

__all__ = [
    "METHOD_ID",
    "DG15AdapterConfig",
    "DG15AdapterStats",
    "DG15CallRecord",
    "DG15MilaiMcpAdapter",
    "DG15Provenance",
    "DG15QueryResult",
    "McpBatchOutcome",
    "MultiplexedStdioMcpTransport",
]

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals.dg14.contracts import DG14AdapterConfig, DG14ContractError
from evals.dg14.mcp_stdio import _BRIDGE_TIMEOUT_SECONDS
from evals.dg15.mcp_stdio import (
    McpBatchCall,
    MultiplexedStdioMcpTransport,
    _execute_many,
)


def test_outer_bridge_timeout_exceeds_runtime_readiness_client_envelope() -> None:
    assert _BRIDGE_TIMEOUT_SECONDS > 35.0


class _ConcurrentClient:
    def __init__(self) -> None:
        self.active = 0
        self.maximum_active = 0
        self.calls: list[int] = []

    async def call_tool(self, _tool_name: str, arguments: dict[str, object]) -> Any:
        ordinal_value = arguments["ordinal"]
        assert isinstance(ordinal_value, int)
        ordinal = ordinal_value
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        self.calls.append(ordinal)
        await asyncio.sleep((8 - ordinal) / 1_000)
        self.active -= 1
        if arguments.get("fail") is True:
            return SimpleNamespace(is_error=True, structured_content=None)
        return SimpleNamespace(
            is_error=False,
            structured_content={"receipt_ordinal": ordinal},
        )


def _calls(count: int) -> list[dict[str, object]]:
    return [
        {
            "ordinal": ordinal,
            "profile": "submitter",
            "tool_name": "milai_evidence_capture",
            "arguments": {"ordinal": ordinal},
        }
        for ordinal in range(count)
    ]


@pytest.mark.parametrize("concurrency", [1, 2, 4, 8])
def test_execute_many_bounds_physical_concurrency_and_preserves_logical_order(
    concurrency: int,
) -> None:
    client = _ConcurrentClient()

    outcomes = asyncio.run(
        _execute_many(
            {"submitter": client},
            _calls(8),
            concurrency,
        )
    )

    assert [outcome["ordinal"] for outcome in outcomes] == list(range(8))
    assert [outcome["structured"]["receipt_ordinal"] for outcome in outcomes] == list(  # type: ignore[index]
        range(8)
    )
    assert client.maximum_active == concurrency
    assert sorted(client.calls) == list(range(8))


def test_execute_many_returns_per_item_typed_failure_without_retry() -> None:
    client = _ConcurrentClient()
    calls = _calls(3)
    arguments = calls[1]["arguments"]
    assert isinstance(arguments, dict)
    arguments["fail"] = True

    outcomes = asyncio.run(
        _execute_many(
            {"submitter": client},
            calls,
            2,
        )
    )

    assert [outcome["ok"] for outcome in outcomes] == [True, False, True]
    assert outcomes[1]["error_code"] == "MCP_TOOL_ERROR"
    assert client.calls.count(1) == 1


def test_transport_rejects_non_sweep_concurrency_before_writing() -> None:
    config = DG14AdapterConfig(
        base_url="http://127.0.0.1:18080",
        executable=Path("/does/not/need/to/exist"),
        profile_tokens={
            "submitter": "s" * 32,
            "reviewer": "r" * 32,
            "reader-detail": "d" * 32,
            "operator": "o" * 32,
        },
    )
    transport = MultiplexedStdioMcpTransport(config)
    transport._process = object()  # type: ignore[assignment]

    with pytest.raises(DG14ContractError, match="1, 2, 4, or 8"):
        transport.call_many(
            [
                McpBatchCall(
                    "submitter",
                    "milai_evidence_capture",
                    {"operation_id": "logical-item-1"},
                )
            ],
            max_concurrency=3,
        )


def test_transport_rejects_more_than_one_bounded_call_wave() -> None:
    config = DG14AdapterConfig(
        base_url="http://127.0.0.1:18080",
        executable=Path("/does/not/need/to/exist"),
        profile_tokens={
            "submitter": "s" * 32,
            "reviewer": "r" * 32,
            "reader-detail": "d" * 32,
            "operator": "o" * 32,
        },
    )
    transport = MultiplexedStdioMcpTransport(config)
    transport._process = object()  # type: ignore[assignment]

    with pytest.raises(DG14ContractError, match="one bounded concurrency wave"):
        transport.call_many(
            [
                McpBatchCall(
                    "submitter",
                    "milai_evidence_capture",
                    {"operation_id": f"logical-item-{ordinal}"},
                )
                for ordinal in range(5)
            ],
            max_concurrency=4,
        )

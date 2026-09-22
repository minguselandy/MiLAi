"""Diagnosis-only continuity checks; no model or Runtime fixture is contacted."""

from __future__ import annotations

from pathlib import Path

import pytest

from milai_openworker_mcp.host_adapter import OpenWorkerAdapterError
from milai_openworker_mcp.task_binding import (
    HostTaskRegistry,
    NativeTaskMetadata,
    SameProcessTaskRegistry,
    TaskBindingConflict,
)
from milai_openworker_mcp.transport import McpUnixClientError
from test_task_binding import _bind, _components, _state
from test_trace_testkit import _adapter, _incoming, _metadata, _QueryFirstMcp, _Transport


def test_new_host_registry_does_not_bind_old_execution_token() -> None:
    registry, resolver, validator = _components()
    origin, _ = _bind(registry, resolver, validator, _state("old-task"), None)
    token = registry.begin_operation(origin, "old-operation")
    restarted = HostTaskRegistry()
    _bind(restarted, resolver, validator, _state("new-task"), None)
    result = restarted.bind_tool_result(token)
    assert result.status == "ORPHAN_TASK_MISSING"
    assert result.bound_task_id is None


def test_retired_host_instance_cannot_replay_an_old_operation() -> None:
    registry = SameProcessTaskRegistry()
    old = NativeTaskMetadata("123e4567-e89b-12d3-a456-426614174000", "session", "op-1")
    new = NativeTaskMetadata("123e4567-e89b-12d3-a456-426614174001", "session", "op-2")
    registry.bind(old)
    registry.bind(new)
    before = registry.snapshot()
    with pytest.raises(TaskBindingConflict):
        registry.bind(old)
    assert registry.snapshot() == before


def test_actual_adapter_rejects_duplicate_before_mcp_and_provider(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "host", observed=False, mode="query-first")
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    mcp, transport = _QueryFirstMcp(), _Transport()
    adapter.host_mcp = mcp  # type: ignore[assignment]
    adapter.transport = transport
    try:
        adapter.complete(_incoming(), _metadata())
        before = adapter.native_task_registry.snapshot()
        with pytest.raises(OpenWorkerAdapterError, match="TASK_OPERATION_REPLAY"):
            adapter.complete(_incoming(), _metadata())
        assert adapter.native_task_registry.snapshot() == before
        assert len(mcp.calls) == len(transport.requests) == 1
    finally:
        adapter.close()


def test_retired_host_replay_is_rejected_before_mcp_and_provider(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "host", observed=False, mode="query-first")
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    mcp, transport = _QueryFirstMcp(), _Transport()
    adapter.host_mcp = mcp  # type: ignore[assignment]
    adapter.transport = transport
    try:
        adapter.complete(_incoming(), _metadata())
        adapter.complete(
            _incoming(),
            NativeTaskMetadata(
                "123e4567-e89b-12d3-a456-426614174001",
                "session-1",
                "op-new-host",
            ),
        )
        native_before = adapter.native_task_registry.snapshot()
        graph_before = adapter.task_registry.snapshot()
        locators_before = dict(adapter.task_free_context_locators)
        rejected = False
        try:
            adapter.complete(_incoming(), _metadata())
        except OpenWorkerAdapterError:
            rejected = True
        assert (rejected, len(mcp.calls), len(transport.requests)) == (True, 2, 2)
        assert adapter.native_task_registry.snapshot() == native_before
        assert adapter.task_registry.snapshot() == graph_before
        assert adapter.task_free_context_locators == locators_before
    finally:
        adapter.close()


@pytest.mark.parametrize("continuation", [False, True])
@pytest.mark.parametrize("session,operation", [("session", "op-1"), ("new-session", "new-op")])
def test_retired_instance_rejection_preserves_current_graph_and_new_replacements(
    continuation: bool,
    session: str,
    operation: str,
) -> None:
    registry = SameProcessTaskRegistry()
    hosts = [f"123e4567-e89b-12d3-a456-42661417400{index}" for index in range(3)]
    registry.bind(NativeTaskMetadata(hosts[0], "session", "op-1"))
    current = registry.bind(NativeTaskMetadata(hosts[1], "session", "op-2"))
    before = registry.snapshot()
    with pytest.raises(TaskBindingConflict, match="retired native host instance"):
        registry.bind(
            NativeTaskMetadata(hosts[0], session, operation),
            allow_operation_continuation=continuation,
        )
    assert registry.snapshot() == before
    continued = registry.bind(NativeTaskMetadata(hosts[1], "session", "op-3"))
    assert continued.relation == "CONTINUE"
    assert continued.task_generation == current.task_generation
    replacement = registry.bind(NativeTaskMetadata(hosts[2], "session", "op-1"))
    assert replacement.relation == "TASK_START"
    assert replacement.task_generation == current.task_generation + 1
    assert replacement.invalidated_task_count == 1
    for retired in hosts[:2]:
        before = registry.snapshot()
        with pytest.raises(TaskBindingConflict, match="retired native host instance"):
            registry.bind(NativeTaskMetadata(retired, "session", "never-used"))
        assert registry.snapshot() == before


def test_cached_locator_never_authorizes_offline_provider_dispatch(tmp_path: Path) -> None:
    class UnavailableMcp(_QueryFirstMcp):
        def resolve_memory(
            self,
            query: str,
            *,
            previous_context_id: str | None = None,
        ) -> dict[str, object]:
            if self.calls:
                self.calls.append(previous_context_id)
                raise McpUnixClientError("SYNTHETIC_RUNTIME_UNAVAILABLE")
            return super().resolve_memory(query, previous_context_id=previous_context_id)

    adapter = _adapter(tmp_path / "host", observed=False, mode="query-first")
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    mcp, transport = UnavailableMcp(), _Transport()
    adapter.host_mcp = mcp  # type: ignore[assignment]
    adapter.transport = transport
    try:
        adapter.complete(_incoming(), _metadata())
        completion, route = adapter.complete(_incoming(), _metadata("op-2"))
        assert route == "HOST_MEMORY_REQUIRED_BUT_UNAVAILABLE"
        assert completion["choices"]
        assert len(mcp.calls) == 2 and mcp.calls[1] is not None
        assert len(transport.requests) == 1
    finally:
        adapter.close()

"""Finite operations over actual observations, shared by Host and experiments."""
from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

Operation = Literal["SEARCH", "READ", "USE_VIEW", "REFRESH_VIEW", "HANDOFF"]


@dataclass(frozen=True)
class MemoryAction:
    id: str
    kind: Operation
    target: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryControlState:
    task: dict[str, Any]
    visible_evidence: list[dict[str, Any]] = field(default_factory=list)
    pending_candidates: list[dict[str, Any]] = field(default_factory=list)
    views: list[dict[str, Any]] = field(default_factory=list)
    new_events: list[dict[str, Any]] = field(default_factory=list)
    last_result: dict[str, Any] | None = None
    budget: dict[str, Any] = field(default_factory=dict)

    def project(self) -> dict[str, Any]:
        return asdict(self)


class MemoryPolicy(Protocol):
    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str: ...


class MemoryOperations(Protocol):
    def actions(self, state: MemoryControlState) -> list[MemoryAction]: ...

    def execute(self, action: MemoryAction, state: MemoryControlState) -> dict[str, Any]: ...


def run_memory_control(
    state: MemoryControlState, policy: MemoryPolicy, operations: MemoryOperations, *,
    max_steps: int = 8,
    record: Callable[[dict[str, Any]], None] = lambda event: None,
    can_continue: Callable[[], bool] = lambda: True,
) -> dict[str, Any]:
    """Each next decision sees the completed operation, never a predicted result."""
    reason = "budget_exhausted"
    trace = []
    for step in range(max_steps):
        state.budget.update(remaining_control_steps=max_steps - step,
                            reader_capacity_reserved=True)
        if not can_continue():
            break
        actions = operations.actions(state)
        if not actions:
            reason = "no_available_operation"
            break
        before = state.project()
        event: dict[str, Any] = {"event": "memory_control_step", "step": step, "before": before,
                                "actions": [asdict(a) for a in actions]}
        record({"phase": "decision_input", **copy.deepcopy(event)})
        started = time.perf_counter()
        forced = len(actions) == 1
        selected = actions[0].id if forced else policy.choose(state, actions)
        # The sole action boundary binds the returned ID to actual supplied parameters.
        action = next((a for a in actions if a.id == selected), None)
        if action is None:
            raise ValueError(f"Unknown memory operation ID: {selected}")
        event.update(selected=selected,
                     selection_mode="only_available_action" if forced else "policy",
                     control_wall_seconds=time.perf_counter() - started)
        record({"phase": "decision_output", **copy.deepcopy(event)})
        if action.kind == "HANDOFF":
            reason = "no_available_operation" if forced else "policy_handoff"
            trace.append(event)
            break
        started = time.perf_counter()
        result = operations.execute(action, state)
        state.last_result = {"action": asdict(action), **result}
        event.update(result=copy.deepcopy(result),
                     operation_wall_seconds=time.perf_counter() - started)
        trace.append(event)
        record({"phase": "operation_result", **copy.deepcopy(event)})
        if result.get("status") in {"read_outcome_unknown", "read_integrity_error"}:
            reason = "operation_outcome_unknown"
            break
    return {"reason": reason, "trace": trace, "state": state.project()}


@dataclass
class FixedMemoryPolicy:
    reads: int = 4

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        for action in actions:
            if action.kind == "SEARCH" or (action.kind == "READ"
                    and not action.parameters.get("expand_context")
                    and not action.parameters.get("history_directory")
                    and len(state.visible_evidence) < self.reads):
                return action.id
        return next(a.id for a in actions if a.kind == "HANDOFF")


@dataclass
class FixedContextMemoryPolicy:
    """Fixed complete-context reads; no semantic selector or hidden sufficiency label."""

    reads: int = 4

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        search = next((a for a in actions if a.kind == "SEARCH"), None)
        if search is not None:
            return search.id
        if len(state.visible_evidence) < self.reads:
            for expanded in (True, False):
                read = next((a for a in actions if a.kind == "READ"
                    and bool(a.parameters.get("expand_context")) == expanded
                    and not a.parameters.get("history_directory")), None)
                if read is not None:
                    return read.id
        return next(a.id for a in actions if a.kind == "HANDOFF")


@dataclass
class RulesMemoryPolicy:
    reads: int = 4

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        if state.last_result and state.last_result["action"]["kind"] in {
            "USE_VIEW", "REFRESH_VIEW"
        } and state.last_result.get("ok"):
            return next(a.id for a in actions if a.kind == "HANDOFF")
        read_goal = state.task.get("read_goal") or {}
        wants_history = (isinstance(read_goal, dict)
                         and "saved_history" in read_goal.get("evidence", []))
        if wants_history:
            history = next((a for a in actions if a.parameters.get("history_directory")), None)
            if history is not None:
                return history.id
            historical = {p["item_index"] for p in state.pending_candidates
                          if p.get("version_view") == "historical_exact_revision"}
            read = next((a for a in actions if a.kind == "READ"
                         and a.parameters.get("index") in historical), None)
            if read is not None:
                return read.id
        matching = [v for v in state.views if v.get("built_for") == state.task["request"]]
        reusable = {v["id"] for v in matching if not v["pending_events"]}
        if not wants_history and reusable:
            use = next((a for a in actions if a.kind == "USE_VIEW" and a.target in reusable), None)
            if use is not None:
                return use.id
        for action in actions:
            if action.kind == "SEARCH" or (action.kind == "READ"
                    and not action.parameters.get("expand_context")
                    and not action.parameters.get("history_directory")
                    and len(state.visible_evidence) < self.reads):
                return action.id
        target_views = {v["id"] for v in matching}
        refresh = next((a for a in actions if a.kind == "REFRESH_VIEW" and (
            a.target in target_views or (not matching and a.parameters.get("new_scope")))), None)
        if refresh is None:
            refresh = next((a for a in actions if a.kind == "REFRESH_VIEW"), None)
        if refresh is not None:
            return refresh.id
        return next(a.id for a in actions if a.kind == "HANDOFF")

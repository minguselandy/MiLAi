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


@dataclass(frozen=True)
class FirstActionIntervention:
    """One actual bound action, then a bounded number of ordinary policy decisions."""

    first_action: MemoryAction
    continuation_steps: int = 0

    def __post_init__(self) -> None:
        if self.continuation_steps < 0:
            raise ValueError("Intervention continuation steps must be nonnegative")


@dataclass
class MemoryControlState:
    task: dict[str, Any]
    visible_evidence: list[dict[str, Any]] = field(default_factory=list)
    pending_candidates: list[dict[str, Any]] = field(default_factory=list)
    views: list[dict[str, Any]] = field(default_factory=list)
    new_events: list[dict[str, Any]] = field(default_factory=list)
    last_result: dict[str, Any] | None = None
    budget: dict[str, Any] = field(default_factory=dict)
    observed_materials: list[dict[str, Any]] | None = None
    observed_evidence: list[dict[str, Any]] | None = None

    def project(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("observed_materials", "observed_evidence"):
            if result[key] is None:
                del result[key]
        return result


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
    intervention: FirstActionIntervention | None = None,
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
        intervened = intervention is not None and (
            step == 0 or step > intervention.continuation_steps)
        if intervened:
            assert intervention is not None
            requested = (intervention.first_action if step == 0 else
                         next(a for a in actions if a.kind == "HANDOFF"))
            if requested not in actions:
                raise ValueError("Intervention action is unavailable with these bindings")
            selected = requested.id
            selection_mode = "intervention_first_action" if step == 0 else "intervention_handoff"
        else:
            selected = actions[0].id if forced else policy.choose(state, actions)
            selection_mode = "only_available_action" if forced else "policy"
        # The sole action boundary binds the returned ID to actual supplied parameters.
        action = next((a for a in actions if a.id == selected), None)
        if action is None:
            raise ValueError(f"Unknown memory operation ID: {selected}")
        event.update(selected=selected,
                     selection_mode=selection_mode,
                     control_wall_seconds=time.perf_counter() - started)
        record({"phase": "decision_output", **copy.deepcopy(event)})
        if action.kind == "HANDOFF":
            reason = ("intervention_handoff" if intervened else
                      "no_available_operation" if forced else "policy_handoff")
            if not action.parameters:
                trace.append(event)
                break
        started = time.perf_counter()
        result = operations.execute(action, state)
        state.last_result = {"action": asdict(action), **result}
        event.update(result=copy.deepcopy(result),
                     operation_wall_seconds=time.perf_counter() - started)
        trace.append(event)
        record({"phase": "operation_result", **copy.deepcopy(event)})
        if action.kind == "HANDOFF":
            if not result["ok"]:
                reason = "budget_exhausted"
            break
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
                    and "source_observation_cursor" not in action.parameters
                    and "observed_source" not in action.parameters
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
                    and not a.parameters.get("history_directory")
                    and "source_observation_cursor" not in a.parameters
                    and "observed_source" not in a.parameters), None)
                if read is not None:
                    return read.id
        return next(a.id for a in actions if a.kind == "HANDOFF")


@dataclass
class PursuitMemoryPolicy:
    """One largest offered request search, then the upstream-selected READ prefix."""

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        if state.last_result is None and not state.pending_candidates:
            searches = [a for a in actions if a.kind == "SEARCH" and (
                a.parameters.get("query_from") == "request"
                or a.parameters.get("query") == state.task["request"])]
            if searches:
                return max(searches, key=lambda a: a.parameters["limit"]).id
        selected = sorted((p for p in state.pending_candidates
                           if p.get("control_pool_selected")), key=lambda p: p["control_pool_rank"])
        for candidate in selected:
            read = next((a for a in actions if a.kind == "READ"
                         and a.parameters == {"index": candidate["item_index"]}), None)
            if read is not None:
                return read.id
        return next(a.id for a in actions if a.kind == "HANDOFF" and not a.parameters)


@dataclass
class OneShotMemoryPolicy:
    """One learned route, then a fixed read budget or a successful view handoff.

    Definite view rejection falls back to the same fixed reads. No subsequent
    model decision sees the retrieved text or generated interpretation.
    """

    initial: MemoryPolicy
    reads: int = 4
    routed: bool = field(default=False, init=False)

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        if not self.routed:
            self.routed = True
            return self.initial.choose(state, actions)
        result = state.last_result
        if result and result.get("ok") and result["action"]["kind"] in {
            "USE_VIEW", "REFRESH_VIEW"
        }:
            return next(a.id for a in actions if a.kind == "HANDOFF")
        return FixedMemoryPolicy(self.reads).choose(state, actions)


@dataclass
class RulesMemoryPolicy:
    reads: int = 4
    reuse_views: bool = True
    expand_context: bool = False

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
        matching = [v for v in state.views if v.get("built_for") == state.task["request"]
                    and v.get("retrieval_request") == state.task.get("retrieval_request")]
        reusable = {v["id"] for v in matching
                    if not v.get("pending_event_count", len(v["pending_events"]))}
        if self.reuse_views and not wants_history and reusable:
            use = next((a for a in actions if a.kind == "USE_VIEW" and a.target in reusable), None)
            if use is not None:
                return use.id
        reading = (FixedContextMemoryPolicy(self.reads) if self.expand_context
                   else FixedMemoryPolicy(self.reads))
        selected = reading.choose(state, actions)
        if next(a for a in actions if a.id == selected).kind != "HANDOFF":
            return selected
        target_views = {v["id"] for v in matching}
        refresh = next((a for a in actions if a.kind == "REFRESH_VIEW" and (
            a.target in target_views or (not matching and a.parameters.get("new_scope")))), None)
        if refresh is None:
            refresh = next((a for a in actions if a.kind == "REFRESH_VIEW"), None)
        if refresh is not None:
            return refresh.id
        return next(a.id for a in actions if a.kind == "HANDOFF")

"""Graph v1 input view; checkpoint messages and business ToolMessages stay intact."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import LocalStateController
from milai_lab.methods.local_state_attention.history import HistoryAccess
from milai_lab.methods.local_state_attention.history import source_id as _source_id
from milai_lab.methods.local_state_attention.summary import HistorySummaryController
from milai_lab.methods.local_state_attention.writers import (
    WriterTools,
    scoped_memory_records,
)

SOURCE_VIEW_HEADER = "Referenced source events from delivered States:"


def make_pre_model_hook(controller: LocalStateController,
                        system_prompt: str, read_policy: str = "focus",
                        source_view_max_bytes: int | None = None,
                        update_epoch: str = "pre_model") -> Any:
    if read_policy not in {"focus", "all", "all_sources", "focus_sources"}:
        raise ValueError("LSA_READ_POLICY_UNKNOWN")
    if read_policy in {"all_sources", "focus_sources"} and (
        type(source_view_max_bytes) is not int or source_view_max_bytes <= 0
    ):
        raise ValueError("LSA_SOURCE_VIEW_BUDGET_INVALID")
    if update_epoch not in {"pre_model", "turn_end"}:
        raise ValueError("LSA_UPDATE_EPOCH_UNKNOWN")
    if update_epoch == "turn_end" and read_policy not in {"all", "all_sources"}:
        raise ValueError("LSA_TURN_END_REQUIRES_ALL_READ")

    def hook(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        cfg = config["configurable"]
        scope = StateScope(cfg["foundation_run_id"], cfg["arm_id"], cfg["user_id"])
        thread_id = cfg["thread_id"]
        messages: list[BaseMessage] = state["messages"]
        latest_user, input_messages, current_source_ids = collect_observations(
            controller.bank, scope, thread_id, messages)
        if latest_user is None:
            raise ValueError("LSA_CURRENT_USER_MISSING")
        public_index = sum(isinstance(message, HumanMessage) for message in messages) - 1
        if update_epoch == "turn_end":
            snapshot = controller.bank.epoch_snapshot(scope, thread_id, public_index)
            states = snapshot["states"]
            controller_focus: list[str] = []
            result: dict[str, Any] = {"degraded": False}
        else:
            result = controller.prepare(scope, *latest_user,
                                        message_key=f"{thread_id}:{public_index}")
            controller_focus = result["focus"]
            states = controller.bank.states(scope)
        if read_policy in {"focus", "focus_sources"}:
            selected = set(controller_focus)
            states = [row for row in states if row["id"] in selected]
        all_pending = controller.bank.pending(scope)
        pending = ([row for row in all_pending if row["id"] not in current_source_ids]
                   if update_epoch == "turn_end" else all_pending)
        source_lines: list[str] = []
        source_trace: dict[str, Any] = {}
        if read_policy in {"all_sources", "focus_sources"}:
            assert source_view_max_bytes is not None
            source_lines, source_trace = _source_view(
                controller.bank, scope, states, source_view_max_bytes)
        view = _render_view(states, pending, source_lines,
                            turn_start_snapshot=update_epoch == "turn_end")
        if controller.emit is not None:
            controller.emit({"event": "lsa_view", "message_key":
                             f"{thread_id}:{public_index}", "user_id": scope.user_id,
                             "focus": controller_focus, "controller_focus": controller_focus,
                             "delivered_state_ids": [row["id"] for row in states],
                             "read_policy": read_policy, "states": states,
                             "pending_source_ids": [row["id"] for row in pending],
                             "current_pending_source_ids": (
                                 [row["id"] for row in all_pending
                                  if row["id"] in current_source_ids]
                                 if update_epoch == "turn_end" else []),
                             "update_epoch": update_epoch,
                             "snapshot_reused": (snapshot["reused"]
                                                 if update_epoch == "turn_end" else None),
                             "degraded": result["degraded"], "view": view,
                             **source_trace})
        prompt = system_prompt + ("\n" + view if view else "")
        # One first system copy, just as the ordinary prompt path delivers. All graph
        # messages remain their original objects and IDs; no synthetic tool evidence.
        return {"llm_input_messages": [SystemMessage(content=prompt), *input_messages]}

    return hook


def collect_observations(bank: LocalStateBank, scope: StateScope,
                         thread_id: str, messages: list[BaseMessage],
                         *, skip_before: int = 0,
                         include_tool_status: bool = False,
                         ) -> tuple[tuple[str, str] | None, list[BaseMessage], set[str]]:
    """Collect actual checkpoint user/tool sources without creating tool evidence."""
    latest_user: tuple[str, str] | None = None
    input_messages: list[BaseMessage] = []
    forgotten_positions: list[int] = []
    current_source_ids: set[str] = set()
    for position, message in enumerate(messages):
        if position < skip_before:
            input_messages.append(message)
            continue
        if not isinstance(message, (HumanMessage, ToolMessage)):
            input_messages.append(message)
            continue
        source_id = _source_id(thread_id, position, message)
        current_source_ids.add(source_id)
        if bank.is_forgotten(scope, source_id):
            forgotten_positions.append(position)
            input_messages.append(message.model_copy(
                update={"content": "[authorized source deletion]"}))
            continue
        input_messages.append(message)
        kind = "user" if isinstance(message, HumanMessage) else "tool"
        event = {"id": source_id, "kind": kind,
                 "content": message.content, "thread_id": thread_id,
                 "actor": (scope.user_id if kind == "user"
                           else message.name or "tool"),
                 "tool_call_id": (message.tool_call_id
                                  if isinstance(message, ToolMessage) else None)}
        if include_tool_status and isinstance(message, ToolMessage):
            event["status"] = message.status
        bank.record_event(scope, event)
        if isinstance(message, HumanMessage):
            latest_user = (source_id, str(message.content))
    if forgotten_positions:
        restart = next((index for index, message in enumerate(messages)
                        if index > max(forgotten_positions)
                        and isinstance(message, HumanMessage)), None)
        if restart is not None:
            input_messages = input_messages[restart:]
    return latest_user, input_messages, current_source_ids


def make_writer_view_hook(toolset: WriterTools, system_prompt: str, *,
                          source_view_max_bytes: int | None = None,
                          known_prefix_messages: int = 0,
                          initial_boundary: dict[str, Any] | None = None,
                          history: HistoryAccess | None = None,
                          state_body_prefill: str = "all",
                          emit: Any = None) -> Any:
    """Expose actual State without invoking automatic semantic maintenance."""
    if (type(known_prefix_messages) is not int or known_prefix_messages < 0
            or (source_view_max_bytes is not None and
                (type(source_view_max_bytes) is not int or source_view_max_bytes <= 0))):
            raise ValueError("LSA_WRITER_VIEW_CONFIG_INVALID")
    if type(state_body_prefill) is not str or state_body_prefill not in {"all", "none"}:
        raise ValueError("LSA_WRITER_BODY_PREFILL_INVALID")

    def hook(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        cfg = config["configurable"]
        scope = StateScope(cfg["foundation_run_id"], cfg["arm_id"], cfg["user_id"])
        bank = toolset.bank
        messages: list[BaseMessage] = state["messages"]
        _, delivered, _ = collect_observations(
            bank, scope, cfg["thread_id"], messages,
            skip_before=known_prefix_messages, include_tool_status=True)
        states = bank.states(scope)
        pending = bank.pending(scope)
        events = bank.events(scope)
        memories = scoped_memory_records(toolset, scope, emit=emit)
        source_lines: list[str] = []
        source_trace: dict[str, Any] = {}
        if source_view_max_bytes is not None:
            source_lines, source_trace = _source_view(
                bank, scope, states, source_view_max_bytes)
        selected_states = states if state_body_prefill == "all" else []
        view = _render_view(selected_states, pending, source_lines)
        directory = [{key: row[key] for key in ("id", "title", "revision")}
                     for row in states]
        if directory:
            view = ("[Scoped State directory for exact writer targets:]\n" +
                    json.dumps(directory, ensure_ascii=False) + "\n" + view)
        catalog = [{**{key: row.get(key) for key in (
            "id", "kind", "actor", "tool_call_id", "content")},
            "pending": row["pending"],
            **({"status": row["status"]} if "status" in row else {})}
            for row in events]
        common = ["[Actual scoped ordinary memory records (id and value):]",
                  json.dumps(memories, ensure_ascii=False),
                  "[Actual scoped source events; pending=true means not yet acknowledged:]",
                  json.dumps(catalog, ensure_ascii=False)]
        if initial_boundary is not None:
            actual_boundary = {key: initial_boundary.get(key) for key in (
                "status", "reason", "receipts", "pending_event_ids",
                "acknowledged_event_ids") if key in initial_boundary}
            common.extend([
                "[Actual automatic maintenance result before this Host turn; "
                "NO_CHANGE is not a user answer and a degraded result is not saved:]",
                json.dumps(actual_boundary, ensure_ascii=False)])
        view = "\n".join([*common, view] if view else common)
        if history is not None:
            if (scope.run_id, scope.arm_id, scope.user_id) != (
                    history.scope.run_id, history.scope.arm_id, history.scope.user_id):
                raise ValueError("HISTORY_OWNER_SCOPE_MISMATCH")
            delivered, incomplete, suppressed = history.project(cfg["thread_id"], delivered)
            view += _incomplete_appendix(incomplete)
            if emit is not None:
                emit({"event": "lsa_history_view", "suppressed": suppressed,
                      "native_messages": len(delivered),
                      "incomplete_turns": len(incomplete)})
        if emit is not None:
            emit({"event": "lsa_writer_view", "user_id": scope.user_id,
                  "state_ids": [row["id"] for row in states],
                  "state_body_prefill": state_body_prefill,
                  "delivered_state_ids": [row["id"] for row in selected_states],
                  "state_directory": directory,
                  "memory_ids": [row["id"] for row in memories],
                  "source_catalog_ids": [row["id"] for row in catalog],
                  "source_catalog_bytes": len(json.dumps(
                      catalog, ensure_ascii=False).encode("utf-8")),
                  "view_bytes": len(view.encode("utf-8")),
                  "initial_boundary": initial_boundary,
                  "pending_source_ids": [row["id"] for row in pending],
                  "view": view, **source_trace})
        return {"llm_input_messages": [SystemMessage(
            content=system_prompt + ("\n" + view if view else "")), *delivered]}

    return hook


def make_full_history_hook(history: HistoryAccess, system_prompt: str) -> Any:
    """Project only visited owner turns and the current graph prefix into Host input."""
    def hook(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        cfg = config["configurable"]
        if (cfg["foundation_run_id"], cfg["arm_id"], cfg["user_id"]) != (
                history.scope.run_id, history.scope.arm_id, history.scope.user_id):
            raise ValueError("HISTORY_OWNER_SCOPE_MISMATCH")
        messages, incomplete, suppressed = history.project(
            cfg["thread_id"], state["messages"])
        appendix = _incomplete_appendix(incomplete)
        if history.emit is not None:
            history.emit({"event": "lsa_history_view", "suppressed": suppressed,
                          "native_messages": len(messages),
                          "incomplete_turns": len(incomplete)})
        return {"llm_input_messages": [SystemMessage(content=system_prompt + appendix),
                                        *messages]}
    return hook


def make_window_summary_hook(history: HistoryAccess,
                             controller: HistorySummaryController,
                             system_prompt: str) -> Any:
    """Show a committed summary, recent complete turns, and the live graph prefix."""
    def hook(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        cfg = config["configurable"]
        if (cfg["foundation_run_id"], cfg["arm_id"], cfg["user_id"]) != (
                history.scope.run_id, history.scope.arm_id, history.scope.user_id):
            raise ValueError("HISTORY_OWNER_SCOPE_MISMATCH")
        messages: list[BaseMessage] = state["messages"]
        public_index = sum(isinstance(message, HumanMessage) for message in messages) - 1
        view = controller.prepare(history, cfg["thread_id"], messages,
                                  f"{cfg['thread_id']}:{public_index}")
        appendix = _incomplete_appendix(view.incomplete, full_owner_history=True)
        if view.summary:
            appendix += ("\n[Model-generated summary of earlier completed turns "
                         f"through owner ordinal {view.covered_ordinal}. "
                         "Original records remain available through read_history.]\n" +
                         view.summary)
        if history.emit is not None:
            history.emit({"event": "lsa_history_view", "suppressed": view.suppressed,
                          "native_messages": len(view.messages),
                          "incomplete_turns": len(view.incomplete),
                          "summary_covered_ordinal": view.covered_ordinal,
                          "summary_chars": len(view.summary),
                          "summary_degraded": view.degraded,
                          "history_policy": "window_summary"})
        return {"llm_input_messages": [SystemMessage(content=system_prompt + appendix),
                                        *view.messages]}
    return hook


def _incomplete_appendix(incomplete: list[dict[str, Any]],
                         *, full_owner_history: bool = False) -> str:
    return ("\n[Incomplete previously visited turns; factual checkpoint and "
            "business-journal data, not completed tool conversations. "
            + ("completed_before counts completed turns in the full owner history, "
               "including turns covered by the summary; it is not a window index.]\n"
               if full_owner_history else
               "completed_before places each among the completed turns below.]\n") +
            json.dumps(incomplete, ensure_ascii=False, default=str)
            if incomplete else "")


def _source_view(bank: LocalStateBank, scope: StateScope,
                 states: list[dict[str, Any]], max_bytes: int,
                 ) -> tuple[list[str], dict[str, Any]]:
    source_ids: list[str] = []
    invalid_refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for state in states:
        refs = state.get("evidence_refs", [])
        if not isinstance(refs, list):
            invalid_refs.append({"state_id": state["id"], "reference": repr(refs)})
            continue
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                invalid_refs.append({"state_id": state["id"], "reference": repr(ref)})
            elif ref not in seen:
                seen.add(ref)
                source_ids.append(ref)
    resolution = bank.resolve_evidence(scope, source_ids)
    events = sorted(resolution.events, key=lambda row: (row["arrival_index"], row["id"]))
    lines = [SOURCE_VIEW_HEADER]
    used_bytes = len(("\n" + SOURCE_VIEW_HEADER).encode("utf-8"))
    delivered_ids: list[str] = []
    omitted: list[dict[str, int | str]] = []
    for event in events:
        visible = {key: event.get(key) for key in (
            "id", "kind", "actor", "tool_call_id", "content")}
        line = json.dumps(visible, ensure_ascii=False)
        line_bytes = len(("\n" + line).encode("utf-8"))
        if used_bytes + line_bytes > max_bytes:
            omitted.append({"id": event["id"], "bytes": line_bytes})
            continue
        lines.append(line)
        delivered_ids.append(event["id"])
        used_bytes += line_bytes
    if not delivered_ids:
        lines = []
        used_bytes = 0
    trace = {"source_view_max_bytes": max_bytes,
             "source_view_bytes": used_bytes,
             "source_requested_ids": source_ids,
             "source_delivered_ids": delivered_ids,
             "source_deleted_ids": resolution.deleted_source_ids,
             "source_missing_ids": resolution.missing_source_ids,
             "source_invalid_refs": invalid_refs,
             "source_omitted": omitted}
    return lines, trace


def _render_view(states: list[dict[str, Any]], pending: list[dict[str, Any]],
                 source_lines: list[str] | None = None,
                 *, turn_start_snapshot: bool = False) -> str:
    if not states and not pending and not source_lines and not turn_start_snapshot:
        return ""
    rows = ["[Local State working view: model estimates, source IDs are references. "
            "Current user and tool messages below remain authoritative observations.] "]
    if turn_start_snapshot:
        rows.append("Snapshot captured before the current public user turn.")
    for state in states:
        rows.append(json.dumps({key: state[key] for key in (
            "title", "content", "needs", "evidence_refs")},
            ensure_ascii=False))
    if source_lines:
        rows.extend(source_lines)
    if pending:
        rows.append("Unmerged prior observations; snapshot may not incorporate them:"
                    if turn_start_snapshot else
                    "Unprocessed current observations; stored States may not incorporate them:")
        keys = (("id", "kind", "actor", "tool_call_id", "content")
                if turn_start_snapshot else ("id", "kind", "content"))
        rows.extend(json.dumps({key: row.get(key) for key in keys},
                               ensure_ascii=False) for row in pending)
    return "\n".join(rows)

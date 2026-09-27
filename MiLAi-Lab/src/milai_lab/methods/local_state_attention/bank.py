"""Durable local States and source events in the existing LangGraph BaseStore."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from langgraph.store.base import BaseStore


@dataclass(frozen=True)
class StateScope:
    run_id: str
    arm_id: str
    user_id: str
    workspace_id: str = "default"

    def namespace(self, kind: str) -> tuple[str, ...]:
        if not all((self.run_id, self.arm_id, self.user_id, self.workspace_id)):
            raise ValueError("LSA_SCOPE_EMPTY_PART")
        return ("local_state", self.run_id, self.arm_id, self.user_id,
                self.workspace_id, kind)


class LocalStateBank:
    def __init__(self, store: BaseStore, *, max_states: int = 32,
                 max_events: int = 256) -> None:
        self.store = store
        self.max_states = max_states
        self.max_events = max_events

    def _all(self, scope: StateScope, kind: str, limit: int) -> list[dict[str, Any]]:
        rows = self.store.search(scope.namespace(kind), limit=limit + 1)
        if len(rows) > limit:
            raise ValueError("LSA_STORAGE_LIMIT_EXCEEDED")
        return [dict(row.value) for row in rows]

    def states(self, scope: StateScope) -> list[dict[str, Any]]:
        return sorted(self._all(scope, "states", self.max_states), key=lambda row: row["id"])

    def events(self, scope: StateScope) -> list[dict[str, Any]]:
        return sorted(self._all(scope, "events", self.max_events),
                      key=lambda row: row["arrival_index"])

    def record_event(self, scope: StateScope, event: dict[str, Any]) -> None:
        key = event["id"]
        if not isinstance(key, str) or not key:
            raise ValueError("LSA_EVENT_ID_MISSING")
        if self.is_forgotten(scope, key):
            return
        prior = self.store.get(scope.namespace("events"), key)
        if prior is not None:
            if {k: v for k, v in prior.value.items()
                    if k not in {"pending", "arrival_index"}} != event:
                raise ValueError("LSA_EVENT_ID_CHANGED")
            return
        existing = self.events(scope)
        if len(existing) >= self.max_events:
            raise ValueError("LSA_EVENT_STORAGE_FULL")
        sequence = max((row["arrival_index"] for row in existing), default=-1) + 1
        self.store.put(scope.namespace("events"), key,
                       {**event, "pending": True, "arrival_index": sequence}, index=False)

    def pending(self, scope: StateScope) -> list[dict[str, Any]]:
        return [row for row in self.events(scope) if row["pending"]]

    def focus(self, scope: StateScope, query_id: str) -> list[str] | None:
        row = self.store.get(scope.namespace("meta"), "focus")
        if row is None or row.value.get("query_id") != query_id:
            return None
        return [str(item) for item in row.value["ids"]]

    def set_focus(self, scope: StateScope, query_id: str, ids: list[str]) -> None:
        self.store.put(scope.namespace("meta"), "focus",
                       {"query_id": query_id, "ids": ids}, index=False)

    def apply(self, scope: StateScope, edits: list[dict[str, Any]],
              event_ids: set[str]) -> tuple[list[dict[str, Any]], bool]:
        """Apply independent valid edits; retain pending when any edit is invalid."""
        current = {row["id"]: row for row in self.states(scope)}
        available = {row["id"] for row in self.events(scope)}
        receipts: list[dict[str, Any]] = []
        invalid = False
        for edit in edits:
            if not isinstance(edit, dict):
                invalid = True
                receipts.append({"status": "skipped_invalid_edit"})
                continue
            state_id = edit.get("id")
            refs = edit.get("evidence", [])
            content = edit.get("content")
            if ((state_id is not None and
                 (not isinstance(state_id, str) or state_id not in current))
                    or not isinstance(refs, list)
                    or any(not isinstance(ref, str) or ref not in available for ref in refs)
                    or not isinstance(content, str) or not content.strip()
                    or len(content) > 4000):
                invalid = True
                receipts.append({"id": state_id, "status": "skipped_invalid_edit"})
                continue
            title = edit.get("title")
            needs = edit.get("needs")
            if ((title is not None and (not isinstance(title, str) or len(title) > 200))
                    or (needs is not None and (not isinstance(needs, list)
                    or any(not isinstance(item, str) for item in needs)))):
                invalid = True
                receipts.append({"id": state_id, "status": "skipped_invalid_edit"})
                continue
            old = current.get(state_id) if state_id is not None else None
            if old is None and (not title or len(current) >= self.max_states):
                invalid = True
                receipts.append({"id": state_id, "status": "skipped_invalid_edit"})
                continue
            key = state_id or uuid.uuid4().hex
            value: dict[str, Any] = {
                     "id": key,
                     "title": title if title is not None else (old["title"] if old else ""),
                     "content": content,
                     "needs": needs if needs is not None else (old["needs"] if old else []),
                     "evidence_refs": sorted(set((old["evidence_refs"] if old else []) + refs)),
                     "revision": old["revision"] if old else 0,
                     "archived": old["archived"] if old else False}
            if old is not None and value == old:
                status = "noop"
            else:
                value["revision"] += 1
                self.store.put(scope.namespace("states"), key, value, index=False)
                current[key] = value
                status = "created" if old is None else "updated"
            receipts.append({"id": key, "status": status, "revision": value["revision"]})
        if not invalid:
            for event_id in event_ids:
                item = self.store.get(scope.namespace("events"), event_id)
                if item is not None and item.value["pending"]:
                    self.store.put(scope.namespace("events"), event_id,
                                   {**item.value, "pending": False}, index=False)
        return receipts, invalid

    @staticmethod
    def _tombstone_key(source_id: str) -> str:
        return "forgotten:" + hashlib.sha256(source_id.encode()).hexdigest()

    def is_forgotten(self, scope: StateScope, source_id: str) -> bool:
        return self.store.get(scope.namespace("meta"),
                              self._tombstone_key(source_id)) is not None

    def _forget_identity(self, scope: StateScope, source_id: str) -> None:
        self.store.put(scope.namespace("meta"), self._tombstone_key(source_id),
                       {"forgotten": True}, index=False)

    def forget_source(self, scope: StateScope, source_id: str) -> list[str]:
        """Authorized deletion removes source content and every dependent State body."""
        self._forget_identity(scope, source_id)
        removed = []
        for state in self.states(scope):
            if source_id in state["evidence_refs"]:
                self.store.delete(scope.namespace("states"), state["id"])
                removed.append(state["id"])
        self.store.delete(scope.namespace("events"), source_id)
        focus = self.store.get(scope.namespace("meta"), "focus")
        if focus is not None:
            self.set_focus(scope, focus.value["query_id"],
                           [key for key in focus.value["ids"] if key not in removed])
        return removed

    def delete_scope(self, scope: StateScope) -> None:
        for event in self.events(scope):
            self._forget_identity(scope, event["id"])
        for kind, rows in (("states", self.states(scope)), ("events", self.events(scope))):
            for row in rows:
                self.store.delete(scope.namespace(kind), row["id"])
        self.store.delete(scope.namespace("meta"), "focus")

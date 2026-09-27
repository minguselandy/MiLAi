"""Durable local States and source events in the existing LangGraph BaseStore."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
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


@dataclass(frozen=True)
class EvidenceResolution:
    events: list[dict[str, Any]]
    deleted_source_ids: list[str]
    missing_source_ids: list[str]


class LocalStateBank:
    def __init__(self, store: BaseStore, *, max_states: int = 32,
                 max_events: int = 256, max_state_content_chars: int = 4000,
                 max_total_content_chars: int | None = None) -> None:
        if (type(max_state_content_chars) is not int or max_state_content_chars <= 0
                or (max_total_content_chars is not None
                    and (type(max_total_content_chars) is not int
                         or max_total_content_chars <= 0))):
            raise ValueError("LSA_CONTENT_LIMIT_INVALID")
        self.store = store
        self.max_states = max_states
        self.max_events = max_events
        self.max_state_content_chars = max_state_content_chars
        self.max_total_content_chars = max_total_content_chars
        self._stats: dict[str, dict[str, int]] = {}

    @staticmethod
    def _bytes(value: Any) -> int:
        return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))

    def _access(self, operation: str, call: Callable[[], Any],
                request: Any) -> Any:
        row = self._stats.setdefault(operation, {
            "calls": 0, "failures": 0, "cpu_ns": 0, "wall_ns": 0,
            "request_bytes": 0, "result_bytes": 0})
        request_bytes = self._bytes(request)
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        try:
            try:
                result = call()
            finally:
                row["calls"] += 1
                row["request_bytes"] += request_bytes
                row["cpu_ns"] += time.process_time_ns() - start_cpu
                row["wall_ns"] += time.perf_counter_ns() - start_wall
        except BaseException:
            row["failures"] += 1
            raise
        if operation == "get" and result is not None:
            row["result_bytes"] += self._bytes(result.value)
        elif operation == "search":
            row["result_bytes"] += sum(self._bytes(item.value) for item in result)
        return result

    def store_stats(self) -> dict[str, dict[str, int]]:
        """Return this bank's completed Store calls for one runtime phase."""
        return {operation: row.copy() for operation, row in self._stats.items()}

    def _get(self, scope: StateScope, kind: str, key: str) -> Any:
        return self._access("get", lambda: self.store.get(scope.namespace(kind), key),
                            {"namespace": scope.namespace(kind), "key": key})

    def _search(self, scope: StateScope, kind: str, limit: int) -> Any:
        return self._access("search", lambda: self.store.search(
            scope.namespace(kind), limit=limit),
            {"namespace": scope.namespace(kind), "limit": limit})

    def _put(self, scope: StateScope, kind: str, key: str,
             value: dict[str, Any]) -> None:
        self._access("put", lambda: self.store.put(
            scope.namespace(kind), key, value, index=False),
            {"namespace": scope.namespace(kind), "key": key, "value": value})

    def _delete(self, scope: StateScope, kind: str, key: str) -> None:
        self._access("delete", lambda: self.store.delete(scope.namespace(kind), key),
                     {"namespace": scope.namespace(kind), "key": key})

    def _all(self, scope: StateScope, kind: str, limit: int) -> list[dict[str, Any]]:
        rows = self._search(scope, kind, limit + 1)
        if len(rows) > limit:
            raise ValueError("LSA_STORAGE_LIMIT_EXCEEDED")
        return [dict(row.value) for row in rows]

    def states(self, scope: StateScope) -> list[dict[str, Any]]:
        return sorted(self._all(scope, "states", self.max_states), key=lambda row: row["id"])

    def events(self, scope: StateScope) -> list[dict[str, Any]]:
        return sorted(self._all(scope, "events", self.max_events),
                      key=lambda row: row["arrival_index"])

    def resolve_evidence(self, scope: StateScope,
                         source_ids: list[str]) -> EvidenceResolution:
        """Read only named, live source events in this scope; never search an archive."""
        events: list[dict[str, Any]] = []
        deleted: list[str] = []
        missing: list[str] = []
        for source_id in dict.fromkeys(source_ids):
            if not isinstance(source_id, str) or not source_id:
                raise ValueError("LSA_EVIDENCE_SOURCE_ID_INVALID")
            if self.is_forgotten(scope, source_id):
                deleted.append(source_id)
                continue
            item = self._get(scope, "events", source_id)
            if item is None:
                missing.append(source_id)
            elif item.value.get("id") != source_id:
                raise ValueError("LSA_EVIDENCE_ID_CHANGED")
            else:
                events.append(dict(item.value))
        return EvidenceResolution(events, deleted, missing)

    def record_event(self, scope: StateScope, event: dict[str, Any]) -> None:
        key = event["id"]
        if not isinstance(key, str) or not key:
            raise ValueError("LSA_EVENT_ID_MISSING")
        if self.is_forgotten(scope, key):
            return
        prior = self._get(scope, "events", key)
        if prior is not None:
            if {k: v for k, v in prior.value.items()
                    if k not in {"pending", "arrival_index"}} != event:
                raise ValueError("LSA_EVENT_ID_CHANGED")
            return
        existing = self.events(scope)
        if len(existing) >= self.max_events:
            raise ValueError("LSA_EVENT_STORAGE_FULL")
        sequence = max((row["arrival_index"] for row in existing), default=-1) + 1
        self._put(scope, "events", key,
                  {**event, "pending": True, "arrival_index": sequence})

    def pending(self, scope: StateScope) -> list[dict[str, Any]]:
        return [row for row in self.events(scope) if row["pending"]]

    def focus(self, scope: StateScope, query_id: str) -> list[str] | None:
        row = self._get(scope, "meta", "focus")
        if row is None or row.value.get("query_id") != query_id:
            return None
        return [str(item) for item in row.value["ids"]]

    def set_focus(self, scope: StateScope, query_id: str, ids: list[str]) -> None:
        self._put(scope, "meta", "focus", {"query_id": query_id, "ids": ids})

    def clear_focus(self, scope: StateScope) -> None:
        self._delete(scope, "meta", "focus")

    def apply(self, scope: StateScope, edits: list[dict[str, Any]],
              event_ids: set[str], query_source_id: str | None = None,
              allowed_existing_ids: set[str] | None = None,
              allow_create: bool = True,
              ) -> tuple[list[dict[str, Any]], bool]:
        """Apply independent valid edits; retain pending when any edit is invalid."""
        current = {row["id"]: row for row in self.states(scope)}
        available = {row["id"] for row in self.events(scope)}
        visible_dependencies = set(event_ids)
        if query_source_id is not None:
            visible_dependencies.add(query_source_id)
        legacy_dependency_unknown = False
        for state in current.values():
            if "dependency_source_ids" not in state or state.get("dependency_unknown"):
                legacy_dependency_unknown = True
            else:
                visible_dependencies.update(state["dependency_source_ids"])
        receipts: list[dict[str, Any]] = []
        invalid = False
        for edit in edits:
            if not isinstance(edit, dict):
                invalid = True
                receipts.append({"status": "skipped_invalid_edit"})
                continue
            state_id = edit.get("id")
            if ((state_id is None and not allow_create)
                    or (isinstance(state_id, str)
                        and allowed_existing_ids is not None
                        and state_id not in allowed_existing_ids)):
                invalid = True
                receipts.append({"id": state_id, "status": "skipped_invalid_edit",
                                 "reason": ("creation_not_allowed" if state_id is None
                                            else "outside_update_candidates")})
                continue
            refs = edit.get("evidence", [])
            content = edit.get("content")
            if ((state_id is not None and
                 (not isinstance(state_id, str) or state_id not in current))
                    or not isinstance(refs, list)
                    or any(not isinstance(ref, str) or ref not in available for ref in refs)
                    or not isinstance(content, str) or not content.strip()):
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
            public_old = ({key: old[key] for key in value} if old is not None else None)
            if old is not None and value == public_old:
                status = "noop"
            else:
                if len(content) > self.max_state_content_chars:
                    invalid = True
                    receipts.append({"id": state_id, "status": "skipped_invalid_edit",
                                     "reason": "state_content_limit"})
                    continue
                projected_total = (sum(len(row["content"]) for row in current.values())
                                   - (len(old["content"]) if old else 0) + len(content))
                if (self.max_total_content_chars is not None
                        and projected_total > self.max_total_content_chars):
                    invalid = True
                    receipts.append({"id": state_id, "status": "skipped_invalid_edit",
                                     "reason": "aggregate_content_limit"})
                    continue
                value["revision"] += 1
                value["dependency_source_ids"] = sorted(
                    visible_dependencies | set(refs)
                    | set(old.get("dependency_source_ids", []) if old else []))
                if legacy_dependency_unknown:
                    value["dependency_unknown"] = True
                self._put(scope, "states", key, value)
                current[key] = value
                status = "created" if old is None else "updated"
            receipts.append({"id": key, "status": status, "revision": value["revision"]})
        if not invalid:
            for event_id in event_ids:
                item = self._get(scope, "events", event_id)
                if item is not None and item.value["pending"]:
                    self._put(scope, "events", event_id,
                              {**item.value, "pending": False})
        return receipts, invalid

    @staticmethod
    def _tombstone_key(source_id: str) -> str:
        return "forgotten:" + hashlib.sha256(source_id.encode()).hexdigest()

    def is_forgotten(self, scope: StateScope, source_id: str) -> bool:
        return self._get(scope, "meta", self._tombstone_key(source_id)) is not None

    def has_forgotten_sources(self, scope: StateScope) -> bool:
        """Conservatively gate history when this owner has any source tombstone."""
        offset = 0
        while True:
            def search_page(current_offset: int = offset) -> Any:
                return self.store.search(scope.namespace("meta"), limit=64,
                                         offset=current_offset)

            rows = self._access("search", search_page,
                {"namespace": scope.namespace("meta"), "limit": 64, "offset": offset})
            if any(row.key.startswith("forgotten:") for row in rows):
                return True
            if len(rows) < 64:
                return False
            offset += len(rows)

    def _forget_identity(self, scope: StateScope, source_id: str) -> None:
        self._put(scope, "meta", self._tombstone_key(source_id), {"forgotten": True})

    def forget_source(self, scope: StateScope, source_id: str) -> list[str]:
        """Authorized deletion removes source content and every dependent State body."""
        self._forget_identity(scope, source_id)
        removed = []
        for state in self.states(scope):
            if (source_id in state["evidence_refs"]
                    or source_id in state.get("dependency_source_ids", [])
                    or "dependency_source_ids" not in state
                    or state.get("dependency_unknown")):
                self._delete(scope, "states", state["id"])
                removed.append(state["id"])
        self._delete(scope, "events", source_id)
        focus = self._get(scope, "meta", "focus")
        if focus is not None:
            self.set_focus(scope, focus.value["query_id"],
                           [key for key in focus.value["ids"] if key not in removed])
        return removed

    def delete_scope(self, scope: StateScope) -> None:
        for event in self.events(scope):
            self._forget_identity(scope, event["id"])
        for kind, rows in (("states", self.states(scope)), ("events", self.events(scope))):
            for row in rows:
                self._delete(scope, kind, row["id"])
        self._delete(scope, "meta", "focus")

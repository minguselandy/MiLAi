"""Actual local SQLite task world; no Product imports or semantic answer selection."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path

PUBLIC_RESOURCES = frozenset({"task", "policy", "current", "history", "records", "pending"})
PRIVATE_KEYS = frozenset({"gold", "gold_answer", "checker", "future_events", "expected_answer"})


def wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(wire(value).encode()).hexdigest()


def assert_public(value: object) -> None:
    if isinstance(value, dict):
        if PRIVATE_KEYS.intersection(value):
            raise ValueError("PRIVATE_EVALUATION_FIELD_FORBIDDEN")
        for item in value.values():
            assert_public(item)
    elif isinstance(value, list):
        for item in value:
            assert_public(item)


class WorldError(ValueError):
    pass


class World:
    """One scope per file. Full SQLite transactions, CAS and durable operation receipts."""

    def __init__(self, path: Path, scope: str):
        if not path.is_file():
            raise WorldError("WORLD_NOT_FOUND")
        self.path, self.scope = path, scope

    @classmethod
    def create(cls, path: Path, scope: str, public: dict) -> World:
        if path.exists() or not scope:
            raise WorldError("FRESH_WORLD_AND_SCOPE_REQUIRED")
        assert_public(public)
        if not {"task", "policy", "current", "objects"}.issubset(public):
            raise WorldError("WORLD_CONTRACT_INCOMPLETE")
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            **copy.deepcopy(public),
            "scope": scope,
            "version": 0,
            "records": {},
            "pending": {},
            "history": [],
        }
        with sqlite3.connect(path) as db:
            db.executescript("""
                PRAGMA synchronous=FULL;
                CREATE TABLE state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), body TEXT);
                CREATE TABLE operations (id TEXT PRIMARY KEY, request_hash TEXT, receipt TEXT);
                CREATE TABLE ledger (sequence INTEGER PRIMARY KEY, event TEXT);
            """)
            db.execute("INSERT INTO state VALUES (1, ?)", (wire(state),))
        return cls(path, scope)

    def _state(self, db: sqlite3.Connection) -> dict:
        state = json.loads(db.execute("SELECT body FROM state WHERE singleton=1").fetchone()[0])
        if state["scope"] != self.scope:
            raise WorldError("SCOPE_DENIED")
        return state

    def snapshot(self) -> dict:
        with sqlite3.connect(self.path) as db:
            return self._state(db)

    def read(self, resource: str) -> dict:
        if resource not in PUBLIC_RESOURCES:
            raise WorldError("RESOURCE_NOT_PUBLIC")
        state = self.snapshot()
        return {
            "resource": resource,
            "version": state["version"],
            "content": state[resource],
            "content_sha256": digest(state[resource]),
        }

    def ledger(self) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            self._state(db)
            return [
                json.loads(row[0])
                for row in db.execute("SELECT event FROM ledger ORDER BY sequence")
            ]

    def clone(self, destination: Path, new_scope: str) -> World:
        if destination.exists() or not new_scope:
            raise WorldError("FRESH_CLONE_REQUIRED")
        self.snapshot()  # authorize before copying any bytes
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
            state = self._state(target)
            state["scope"] = new_scope
            target.execute("UPDATE state SET body=? WHERE singleton=1", (wire(state),))
            # A is preserved as ordinary history; B needs independent idempotency identities.
            target.execute("DELETE FROM operations")
        return World(destination, new_scope)

    def act(
        self, *, operation_id: str, expected_version: int, action: str, object_id: str, data: dict
    ) -> dict:
        if not operation_id or type(expected_version) is not int or not isinstance(data, dict):
            raise WorldError("INVALID_ACTION_ENVELOPE")
        if action not in {"put_record", "request_clarification"}:
            raise WorldError("ACTION_NOT_ALLOWED")
        assert_public(data)
        if "object_id" in data or "scope" in data or "version" in data:
            raise WorldError("IMMUTABLE_IDENTITY_FIELD")
        request = {
            "operation_id": operation_id,
            "expected_version": expected_version,
            "action": action,
            "object_id": object_id,
            "data": data,
            "scope": self.scope,
        }
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._state(db)
            prior = db.execute(
                "SELECT request_hash,receipt FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
            if prior:
                if prior[0] != digest(request):
                    raise WorldError("OPERATION_ID_REUSE_CONFLICT")
                return json.loads(prior[1])
            if object_id not in state["objects"]:
                raise WorldError("OBJECT_SCOPE_DENIED")
            if state["version"] != expected_version:
                raise WorldError("VERSION_CONFLICT_RELOAD_CURRENT_STATE")
            before_hash = digest(state)
            if action == "put_record":
                state["records"][object_id] = {"object_id": object_id, **copy.deepcopy(data)}
                state["pending"].pop(object_id, None)
            else:
                if (
                    set(data) != {"question"}
                    or not isinstance(data["question"], str)
                    or not data["question"].strip()
                ):
                    raise WorldError("CLARIFICATION_QUESTION_REQUIRED")
                state["pending"][object_id] = data["question"]
            state["version"] += 1
            receipt = {
                "status": "ACTION_EXECUTED_LOCAL_WORLD",
                "operation_id": operation_id,
                "version": state["version"],
                "object_id": object_id,
                "action": action,
                "before_sha256": before_hash,
            }
            state["history"].append(
                {"kind": "business_action", "action": action, "object_id": object_id, "data": data}
            )
            receipt["after_sha256"] = digest(state)
            db.execute("UPDATE state SET body=? WHERE singleton=1", (wire(state),))
            db.execute(
                "INSERT INTO operations VALUES (?,?,?)",
                (operation_id, digest(request), wire(receipt)),
            )
            db.execute(
                "INSERT INTO ledger(event) VALUES (?)",
                (wire({"request": request, "receipt": receipt, "snapshot": state}),),
            )
            return receipt

    def publish(self, *, event_id: str, current: dict, task: dict | None = None) -> dict:
        """Harness-only predetermined event; never exposed as an Agent tool."""
        assert_public(current)
        if task is not None:
            assert_public(task)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._state(db)
            previous = next(
                (item for item in state["history"] if item.get("event_id") == event_id), None
            )
            request_hash = digest({"current": current, "task": task})
            if previous:
                if previous["request_hash"] != request_hash:
                    raise WorldError("EVENT_ID_REUSE_CONFLICT")
                return {"event_id": event_id, "version": previous["version"], "replayed": True}
            state["history"].append({"kind": "prior_public_record", "content": state["current"]})
            state["current"] = copy.deepcopy(current)
            if task is not None:
                state["task"] = copy.deepcopy(task)
            state["version"] += 1
            state["history"].append(
                {
                    "kind": "publication",
                    "event_id": event_id,
                    "request_hash": request_hash,
                    "version": state["version"],
                }
            )
            db.execute("UPDATE state SET body=? WHERE singleton=1", (wire(state),))
            db.execute(
                "INSERT INTO ledger(event) VALUES (?)",
                (wire({"kind": "external_event", "event_id": event_id, "snapshot": state}),),
            )
            return {"event_id": event_id, "version": state["version"], "replayed": False}

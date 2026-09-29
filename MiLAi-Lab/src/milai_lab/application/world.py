"""Owner-scoped SQLite application world; no model or runner dependencies."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid as uuid
from pathlib import Path
from typing import Any


class ApplicationWorld:
    """Compute receipts from committed, user-scoped SQLite state."""

    def __init__(self, path: Path, initial_label_available: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.tool_lock = threading.RLock()
        self.conn.row_factory = sqlite3.Row
        with self.conn:
            self.conn.execute("CREATE TABLE IF NOT EXISTS settings "
                              "(name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            self.conn.execute("CREATE TABLE IF NOT EXISTS world_events "
                              "(event_id TEXT PRIMARY KEY, available INTEGER NOT NULL)")
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS reservations ("
                "reservation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, item_key TEXT NOT NULL, "
                "quantity INTEGER NOT NULL, destination TEXT NOT NULL, packing TEXT NOT NULL, "
                "label_status TEXT NOT NULL, UNIQUE(user_id,item_key))")
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS attempts ("
                "id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, item_key TEXT NOT NULL, "
                "operation TEXT NOT NULL, outcome TEXT NOT NULL)")
            self.conn.execute(
                "INSERT OR IGNORE INTO settings(name,value) VALUES('label_available',?)",
                (int(initial_label_available),))

    def close(self) -> None:
        self.conn.close()

    def set_label_available(self, event_id: str, available: bool) -> None:
        with self.conn:
            prior = self.conn.execute(
                "SELECT available FROM world_events WHERE event_id=?", (event_id,)).fetchone()
            if prior is not None:
                if prior["available"] != int(available):
                    raise ValueError("APPLICATION_WORLD_EVENT_CHANGED")
                return
            self.conn.execute("UPDATE settings SET value=? WHERE name='label_available'",
                              (int(available),))
            self.conn.execute("INSERT INTO world_events VALUES(?,?)",
                              (event_id, int(available)))

    def _available(self) -> bool:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE name='label_available'").fetchone()
        return bool(row["value"])

    @staticmethod
    def _receipt(**fields: Any) -> str:
        return json.dumps(fields, ensure_ascii=False)

    @staticmethod
    def _state(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in (
            "reservation_id", "item_key", "quantity", "destination", "packing",
            "label_status")}

    def reserve_and_label(self, user_id: str, item_key: str, quantity: int,
                          destination: str, packing: str) -> str:
        if quantity < 1 or not all((item_key, destination, packing)):
            return self._receipt(ok=False, status="invalid_arguments")
        with self.conn:
            prior = self.conn.execute(
                "SELECT * FROM reservations WHERE user_id=? AND item_key=?",
                (user_id, item_key)).fetchone()
            if prior is not None:
                self.conn.execute("INSERT INTO attempts(user_id,item_key,operation,outcome) "
                                  "VALUES(?,?,'reserve_and_label','duplicate')",
                                  (user_id, item_key))
                return self._receipt(ok=False, status="duplicate_reservation_attempt",
                                     **self._state(prior))
            reservation_id = "RSV-" + str(uuid.uuid4())
            self.conn.execute(
                "INSERT INTO reservations VALUES(?,?,?,?,?,?,?)",
                (reservation_id, user_id, item_key, quantity, destination, packing,
                 "not_created"))
            self.conn.execute("INSERT INTO attempts(user_id,item_key,operation,outcome) "
                              "VALUES(?,?,'reserve_and_label','reserved')",
                              (user_id, item_key))
        if not self._available():
            row = self.conn.execute("SELECT * FROM reservations WHERE reservation_id=?",
                                    (reservation_id,)).fetchone()
            return self._receipt(ok=False, status="reserved_label_failed",
                                 reason="label_service_unavailable", **self._state(row))
        with self.conn:
            self.conn.execute("UPDATE reservations SET label_status='created' "
                              "WHERE reservation_id=?", (reservation_id,))
        row = self.conn.execute("SELECT * FROM reservations WHERE reservation_id=?",
                                (reservation_id,)).fetchone()
        return self._receipt(ok=True, status="label_created", **self._state(row))

    def get_reservation(self, user_id: str, item_key: str) -> str:
        row = self.conn.execute(
            "SELECT * FROM reservations WHERE user_id=? AND item_key=?",
            (user_id, item_key)).fetchone()
        return (self._receipt(ok=True, status="found", **self._state(row)) if row
                else self._receipt(ok=False, status="not_found", item_key=item_key))

    def complete_label(self, user_id: str, reservation_id: str) -> str:
        row = self.conn.execute(
            "SELECT * FROM reservations WHERE user_id=? AND reservation_id=?",
            (user_id, reservation_id)).fetchone()
        if row is None:
            return self._receipt(ok=False, status="not_found", reservation_id=reservation_id)
        if row["label_status"] == "created":
            return self._receipt(ok=False, status="already_labeled", **self._state(row))
        if not self._available():
            return self._receipt(ok=False, status="label_service_unavailable",
                                 **self._state(row))
        with self.conn:
            self.conn.execute("UPDATE reservations SET label_status='created' "
                              "WHERE reservation_id=?", (reservation_id,))
            self.conn.execute("INSERT INTO attempts(user_id,item_key,operation,outcome) "
                              "VALUES(?,?,'complete_label','created')",
                              (user_id, row["item_key"]))
        updated = self.conn.execute("SELECT * FROM reservations WHERE reservation_id=?",
                                    (reservation_id,)).fetchone()
        return self._receipt(ok=True, status="label_created", **self._state(updated))

    def snapshot(self) -> dict[str, Any]:
        return {
            "label_available": self._available(),
            "reservations": [dict(row) for row in self.conn.execute(
                "SELECT * FROM reservations ORDER BY user_id,item_key")],
            "attempts": [dict(row) for row in self.conn.execute(
                "SELECT * FROM attempts ORDER BY id")],
        }

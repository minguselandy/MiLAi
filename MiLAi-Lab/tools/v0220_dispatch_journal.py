"""Durable Host-side dispatch fencing for uncertain Lab commits, not business state."""

from __future__ import annotations

import json
import sqlite3

from v0218_world import World, wire
from v0220_action_contract import ContractError


class UnresolvedDispatch(RuntimeError):
    pass


class DispatchJournal:
    def __init__(self, world: World):
        self.world = world
        with sqlite3.connect(world.path) as db:
            db.execute("BEGIN IMMEDIATE")
            world._state(db)
            db.execute(
                "CREATE TABLE IF NOT EXISTS v0220_dispatch "
                "(id TEXT PRIMARY KEY, request TEXT NOT NULL, receipt TEXT)"
            )

    def begin(self, operation_id: str, request: dict) -> dict | None:
        """Persist before dispatch; unresolved different operations are fenced across restarts."""
        body = wire(request)
        with sqlite3.connect(self.world.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self.world._state(db)
            prior = db.execute(
                "SELECT request,receipt FROM v0220_dispatch WHERE id=?", (operation_id,)
            ).fetchone()
            if prior:
                if prior[0] != body:
                    raise ContractError("OPERATION_ID_REUSE_CONFLICT")
                if prior[1] is not None:
                    return json.loads(prior[1])
            unresolved = db.execute(
                "SELECT id FROM v0220_dispatch WHERE receipt IS NULL"
            ).fetchall()
            if any(row[0] != operation_id for row in unresolved):
                raise UnresolvedDispatch("UNRESOLVED_PRIOR_OPERATION")
            if prior is None:
                db.execute("INSERT INTO v0220_dispatch VALUES (?,?,NULL)", (operation_id, body))
        return None

    def settle(self, operation_id: str, receipt: dict) -> None:
        if type(receipt.get("committed")) is not bool:
            raise ContractError("CANNOT_SETTLE_UNKNOWN")
        with sqlite3.connect(self.world.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self.world._state(db)
            row = db.execute(
                "SELECT receipt FROM v0220_dispatch WHERE id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise ContractError("DISPATCH_NOT_FOUND")
            if row[0] is not None and json.loads(row[0]) != receipt:
                raise ContractError("DISPATCH_RECEIPT_CONFLICT")
            db.execute(
                "UPDATE v0220_dispatch SET receipt=? WHERE id=?", (wire(receipt), operation_id)
            )

    def unresolved(self) -> list[str]:
        with sqlite3.connect(self.world.path) as db:
            self.world._state(db)
            return [
                row[0]
                for row in db.execute(
                    "SELECT id FROM v0220_dispatch WHERE receipt IS NULL ORDER BY id"
                )
            ]

    def clear_cloned_operation_ids(self) -> None:
        """Called only after an authorized fresh clone, never as recovery of unknown commits."""
        with sqlite3.connect(self.world.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self.world._state(db)
            db.execute("DELETE FROM v0220_dispatch")

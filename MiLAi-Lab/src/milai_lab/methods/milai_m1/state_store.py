"""Task-local, durable M1 basis and idempotent delta/error receipts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, cast

from milai_lab.baselines.langmem_revision_store import canonical_json

ScopeKey = tuple[str, str, str, str]


class DecisionBasisStore:
    """One active task per run/arm/user; prior task slots remain separate."""

    FORMAT = "MILAI_M1_PROPOSITION_V18"

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        existing = {row["name"] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "bases" in existing and "m1_format" not in existing:
            self.conn.close()
            raise ValueError("M1_STATE_FORMAT_MISMATCH")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS m1_format(version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS write_transactions(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL, recorded_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS active_tasks(
                run_id TEXT, arm_id TEXT, user_id TEXT, task_id TEXT NOT NULL,
                PRIMARY KEY(run_id,arm_id,user_id));
            CREATE TABLE IF NOT EXISTS bases(
                run_id TEXT, arm_id TEXT, user_id TEXT, task_id TEXT,
                revision INTEGER NOT NULL, basis_json TEXT,
                reasons_json TEXT NOT NULL,
                PRIMARY KEY(run_id,arm_id,user_id,task_id));
            CREATE TABLE IF NOT EXISTS delta_receipts(
                request_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL,
                run_id TEXT NOT NULL, arm_id TEXT NOT NULL,
                user_id TEXT NOT NULL, task_id TEXT NOT NULL,
                delta_sha256 TEXT NOT NULL, status TEXT NOT NULL,
                error_code TEXT, before_revision INTEGER,
                after_revision INTEGER, recorded_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL, arm_id TEXT NOT NULL,
                user_id TEXT NOT NULL, task_id TEXT NOT NULL,
                request_id TEXT, event TEXT NOT NULL, detail_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL);
        """)
        marker = self.conn.execute("SELECT version FROM m1_format").fetchone()
        if marker is None:
            if "bases" in existing:
                self.conn.close()
                raise ValueError("M1_STATE_FORMAT_MISMATCH")
            with self.conn:
                self.conn.execute("INSERT INTO m1_format VALUES(?)", (self.FORMAT,))
        elif marker["version"] != self.FORMAT:
            self.conn.close()
            raise ValueError("M1_STATE_FORMAT_MISMATCH")

    def close(self) -> None:
        self.conn.close()

    def _row(self, key: ScopeKey) -> sqlite3.Row | None:
        return cast(sqlite3.Row | None, self.conn.execute(
            "SELECT * FROM bases WHERE run_id=? AND arm_id=? AND user_id=? AND task_id=?",
            key,
        ).fetchone())

    def get(self, key: ScopeKey) -> dict[str, Any] | None:
        with self._lock:
            row = self._row(key)
            if row is None or row["basis_json"] is None:
                return None
            basis: dict[str, Any] = json.loads(row["basis_json"])
            basis["recheck_reasons"] = json.loads(row["reasons_json"])
            basis["needs_recheck"] = bool(basis["recheck_reasons"])
            return basis

    def activate(self, key: ScopeKey) -> None:
        run, arm, user, task = key
        with self._lock, self.conn:
            prior = self.conn.execute(
                "SELECT task_id FROM active_tasks WHERE run_id=? AND arm_id=? AND user_id=?",
                (run, arm, user),
            ).fetchone()
            if prior is not None and prior["task_id"] == task:
                return
            self.conn.execute(
                "INSERT INTO active_tasks VALUES(?,?,?,?) ON CONFLICT(run_id,arm_id,user_id) "
                "DO UPDATE SET task_id=excluded.task_id", key,
            )
            self._write_locked("activate")

    def _write_locked(self, operation: str) -> None:
        self.conn.execute(
            "INSERT INTO write_transactions(operation,recorded_at) "
            "VALUES(?,datetime('now'))", (operation,),
        )

    def _add_reason_locked(self, key: ScopeKey, reason: dict[str, Any]) -> bool:
        row = self._row(key)
        if row is None or row["basis_json"] is None:
            return False
        reasons: list[dict[str, Any]] = json.loads(row["reasons_json"])
        if reason in reasons:
            return False
        reasons.append(reason)
        self.conn.execute(
            "UPDATE bases SET reasons_json=? WHERE run_id=? AND arm_id=? "
            "AND user_id=? AND task_id=?", (canonical_json(reasons), *key),
        )
        self._event_locked(key, None, "RECHECK_TRIGGERED", reason)
        return True

    def add_reason(self, key: ScopeKey, reason: dict[str, Any]) -> bool:
        with self._lock, self.conn:
            if self.reason_was_acknowledged(key, reason):
                return False
            added = self._add_reason_locked(key, reason)
            if added:
                self._write_locked("trigger_recheck")
            return added

    def reason_was_acknowledged(self, key: ScopeKey, reason: dict[str, Any]) -> bool:
        with self._lock:
            return self.conn.execute(
                "SELECT 1 FROM events WHERE run_id=? AND arm_id=? AND user_id=? AND task_id=? "
                "AND event='RECHECK_ACKNOWLEDGED' AND detail_json=? LIMIT 1",
                (*key, canonical_json(reason)),
            ).fetchone() is not None

    def _event_locked(
        self, key: ScopeKey, request_id: str | None, event: str, detail: Any,
    ) -> None:
        self.conn.execute(
            "INSERT INTO events(run_id,arm_id,user_id,task_id,request_id,event,"
            "detail_json,recorded_at) VALUES(?,?,?,?,?,?,?,datetime('now'))",
            (*key, request_id, event, canonical_json(detail)),
        )

    def receipt(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM delta_receipts WHERE request_id=?", (request_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def record_projection(self, key: ScopeKey, request_id: str) -> None:
        """Count a pending notice only after an actual completed request exists."""
        with self._lock, self.conn:
            basis = self.get(key)
            if basis is None or not basis["recheck_reasons"]:
                return
            prior = self.conn.execute(
                "SELECT 1 FROM events WHERE request_id=? AND event='RECHECK_PROJECTED'",
                (request_id,),
            ).fetchone()
            if prior is not None:
                return
            self._event_locked(key, request_id, "RECHECK_PROJECTED", {
                "reasons": basis["recheck_reasons"],
            })
            self._write_locked("project_recheck")

    def record_error(
        self, key: ScopeKey, request_id: str, receipt_id: str,
        raw_delta: Any, error_code: str,
    ) -> None:
        sha = hashlib.sha256(canonical_json(raw_delta).encode()).hexdigest()
        with self._lock, self.conn:
            prior = self.receipt(request_id)
            if prior is not None:
                if prior["delta_sha256"] != sha or prior["receipt_id"] != receipt_id:
                    raise ValueError("M1_REQUEST_RECEIPT_CHANGED")
                return
            row = self._row(key)
            revision = row["revision"] if row is not None else None
            self.conn.execute(
                "INSERT INTO delta_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                (request_id, receipt_id, *key, sha, "ERROR", error_code,
                 revision, revision),
            )
            self._event_locked(key, request_id, "DELTA_REJECTED", {"code": error_code})
            self._write_locked("reject_delta")

    def apply(
        self, key: ScopeKey, request_id: str, receipt_id: str,
        delta: dict[str, Any] | None, adopted: list[dict[str, Any]],
        acknowledged: list[dict[str, Any]], proof_refs: list[str],
    ) -> str:
        sha = hashlib.sha256(canonical_json(delta).encode()).hexdigest()
        with self._lock, self.conn:
            prior = self.receipt(request_id)
            if prior is not None:
                if prior["delta_sha256"] != sha or prior["receipt_id"] != receipt_id:
                    raise ValueError("M1_REQUEST_RECEIPT_CHANGED")
                if prior["status"] == "ERROR":
                    raise ValueError(prior["error_code"])
                return str(prior["status"])
            row = self._row(key)
            before_revision = int(row["revision"]) if row is not None else 0
            before = json.loads(row["basis_json"]) if row and row["basis_json"] else None
            reasons: list[dict[str, Any]] = json.loads(row["reasons_json"]) if row else []
            remaining = [reason for reason in reasons if reason not in acknowledged]
            after = before
            status = "NO_STATE_CHANGE"
            if delta is not None and delta["op"] == "clear":
                if before is not None:
                    after = None
                    remaining = []
                    status = ("CLEARED_TASK_ENDED" if delta.get("clear_reason") == "task_ended"
                              else "CLEARED_RECHECK_COMPLETED" if acknowledged
                              else "CLEARED")
            elif delta is not None:
                semantic = {field: delta[field] for field in
                            ("proposition", "action_scope", "adopted_evidence",
                             "unresolved_gap")}
                semantic["host_status"] = delta["status"]
                previous_semantic = None if before is None else {
                    key: before[key] for key in semantic
                }
                if semantic != previous_semantic:
                    decision_id = (before["decision_id"] if before is not None
                                   else hashlib.sha256(
                                       canonical_json([*key, request_id]).encode()
                                   ).hexdigest())
                    after = {**semantic, "decision_id": decision_id,
                             "revision": before_revision + 1, "task_id": key[3],
                             "adopted_bindings": adopted,
                             "recheck_outcome": delta["recheck_outcome"]}
                    status = "SET"
                elif before is not None and before["recheck_outcome"] != delta["recheck_outcome"]:
                    after = {**before, "recheck_outcome": delta["recheck_outcome"]}
            after_revision = before_revision + (status in {
                "SET", "CLEARED", "CLEARED_TASK_ENDED", "CLEARED_RECHECK_COMPLETED",
            })
            if status != "NO_STATE_CHANGE" or remaining != reasons or after != before:
                self.conn.execute(
                    "INSERT INTO bases VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(run_id,arm_id,user_id,task_id) DO UPDATE SET "
                    "revision=excluded.revision,basis_json=excluded.basis_json,"
                    "reasons_json=excluded.reasons_json",
                    (*key, after_revision,
                     canonical_json(after) if after is not None else None,
                     canonical_json(remaining)),
                )
            self.conn.execute(
                "INSERT INTO delta_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                (request_id, receipt_id, *key, sha, status, None,
                 before_revision, after_revision),
            )
            self._event_locked(key, request_id, status, {
                "delta": delta, "adopted_bindings": adopted,
                "basis_active_after": after is not None,
                "semantic_revision_after": after_revision,
                "adopted_count_after": len(after["adopted_evidence"]) if after else 0,
                "recheck_count_after": len(remaining),
            })
            for reason in acknowledged:
                self._event_locked(key, request_id, "RECHECK_ACKNOWLEDGED", reason)
            if acknowledged:
                self._event_locked(key, request_id, "RECHECK_COMPLETED", {
                    "outcome": delta["recheck_outcome"] if delta else None,
                    "reasons": acknowledged, "new_adopted_refs": proof_refs,
                })
            elif delta is not None and delta.get("recheck_outcome") == "unresolved":
                self._event_locked(key, request_id, "RECHECK_UNRESOLVED", {
                    "reasons": reasons, "new_adopted_refs": [],
                })
            elif status == "CLEARED_TASK_ENDED" and reasons:
                self._event_locked(key, request_id, "RECHECK_ABANDONED_TASK_ENDED", {
                    "reasons": reasons,
                })
            self._write_locked("apply_delta")
            return status

    def rows(self, table: str) -> list[dict[str, Any]]:
        if table not in {"active_tasks", "bases", "delta_receipts", "events",
                         "write_transactions", "m1_format"}:
            raise ValueError("M1_TABLE_UNKNOWN")
        with self._lock:
            return [dict(row) for row in self.conn.execute(f"SELECT * FROM {table}")]  # noqa: S608

"""Durable admission accounting for the explicitly authorized first Utility batch.

Every outbound attempt is reserved before transport. Unknown usage retains the
whole upper bound, including failed calls; opening the same ledger never resets
the budget or clock. This module neither sends requests nor authorizes a study.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Literal

Kind = Literal["text", "embedding"]
LIMITS = {"text": (400, 3_000_000), "embedding": (128, 50_000)}
TOTAL_REQUESTS = 528
WALL_SECONDS = 4 * 60 * 60


class BudgetStop(ValueError):
    """No further outbound attempt may be dispatched."""


class FiniteResearchBudget:
    """SQLite transactions serialize reservations even across worker processes.

    The runner must pin this *one* path and frozen manifest SHA for the entire
    batch. Use a fresh request ID for every retry and maintenance request. A
    reservation is deliberately never deleted or refunded. Tokenizer/model-info
    HTTP calls may conservatively consume text request slots with a proven zero
    generation-token upper bound; they are not reported as text generations.
    """

    def __init__(self, path: Path, *, manifest_sha256: str) -> None:
        if len(manifest_sha256) != 64 or any(c not in "0123456789abcdef" for c in manifest_sha256):
            raise ValueError("INVALID_FROZEN_MANIFEST_SHA256")
        self._wall_origin = time.time()
        self._mono_origin = time.monotonic()
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS batch "
                "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                "manifest TEXT NOT NULL, started REAL, last_clock REAL, stopped TEXT)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
                "purpose TEXT NOT NULL, payload_sha256 TEXT NOT NULL, "
                "upper_tokens INTEGER NOT NULL, "
                "reported_tokens INTEGER, terminal INTEGER NOT NULL DEFAULT 0, failed INTEGER, "
                "reserved_at REAL NOT NULL)"
            )
            self.db.execute(
                "INSERT OR IGNORE INTO batch(singleton,manifest) VALUES(1,?)", (manifest_sha256,)
            )
            if self.db.execute("SELECT manifest FROM batch").fetchone()[0] != manifest_sha256:
                raise BudgetStop("FROZEN_MANIFEST_CHANGED")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            self.db.close()
            raise

    def _now(self) -> float:
        # A wall clock adjustment backwards must not extend this process's lease.
        return max(time.time(), self._wall_origin + time.monotonic() - self._mono_origin)

    def remaining_seconds(self) -> float:
        """Recheck immediately at dispatch; never start the clock just by inspecting it."""
        started, last, stopped = self.db.execute(
            "SELECT started,last_clock,stopped FROM batch"
        ).fetchone()
        if stopped:
            raise BudgetStop(stopped)
        now = self._now()
        if last is not None and now < last:
            raise BudgetStop("CLOCK_ROLLBACK")
        remaining = WALL_SECONDS if started is None else started + WALL_SECONDS - now
        if remaining <= 0:
            raise BudgetStop("BATCH_WALL_TIME_LIMIT")
        return float(remaining)

    def status(self) -> dict[str, Any]:
        started, stopped = self.db.execute("SELECT started,stopped FROM batch").fetchone()
        kinds = {}
        for kind, (request_cap, token_cap) in LIMITS.items():
            count, charged, reported, unknown, pending = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(COALESCE(reported_tokens,upper_tokens)),0), "
                "COALESCE(SUM(reported_tokens),0), "
                "COALESCE(SUM(CASE WHEN reported_tokens IS NULL THEN upper_tokens ELSE 0 END),0), "
                "COALESCE(SUM(CASE WHEN terminal=0 THEN 1 ELSE 0 END),0) "
                "FROM attempts WHERE kind=?",
                (kind,),
            ).fetchone()
            kinds[kind] = {
                "requests": count,
                "charged_tokens": charged,
                "reported_tokens": reported,
                "unknown_token_upper_bound": unknown,
                "pending_requests": pending,
                "request_cap": request_cap,
                "token_cap": token_cap,
            }
        return {
            "started_at_unix": started,
            "deadline_unix": None if started is None else started + WALL_SECONDS,
            "stopped": stopped,
            "kinds": kinds,
            "total_requests": sum(row["requests"] for row in kinds.values()),
            "requests_by_purpose": dict(
                self.db.execute("SELECT purpose,COUNT(*) FROM attempts GROUP BY purpose").fetchall()
            ),
        }

    def reserve(self, kind: Kind, *, upper_tokens: int, purpose: str, payload_sha256: str) -> int:
        if kind not in LIMITS or type(upper_tokens) is not int or upper_tokens < 0:
            raise ValueError("INVALID_REQUEST_RESERVATION")
        if purpose not in {"generation", "embedding", "tokenize", "model_info"}:
            raise ValueError("UNKNOWN_REQUEST_PURPOSE")
        if (kind == "embedding") != (purpose == "embedding"):
            raise ValueError("REQUEST_KIND_MISMATCH")
        if upper_tokens == 0 and purpose not in {"tokenize", "model_info"}:
            raise ValueError("UNKNOWN_USAGE_CANNOT_BE_ZERO")
        if len(payload_sha256) != 64 or any(c not in "0123456789abcdef" for c in payload_sha256):
            raise ValueError("INVALID_PAYLOAD_SHA256")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            now = self._now()
            started, last, stopped = self.db.execute(
                "SELECT started,last_clock,stopped FROM batch"
            ).fetchone()
            reason = stopped
            if last is not None and now < last:
                reason = "CLOCK_ROLLBACK"
            if started is not None and now >= started + WALL_SECONDS:
                reason = "BATCH_WALL_TIME_LIMIT"
            state = self.status()
            used = state["kinds"][kind]
            if used["requests"] >= LIMITS[kind][0] or state["total_requests"] >= TOTAL_REQUESTS:
                reason = reason or "BATCH_REQUEST_LIMIT"
            if used["charged_tokens"] + upper_tokens > LIMITS[kind][1]:
                reason = reason or "BATCH_TOKEN_LIMIT"
            if reason:
                self.db.execute("UPDATE batch SET stopped=?", (reason,))
                self.db.execute("COMMIT")
                raise BudgetStop(reason)
            self.db.execute("UPDATE batch SET started=COALESCE(started,?),last_clock=?", (now, now))
            cursor = self.db.execute(
                "INSERT INTO attempts(kind,purpose,payload_sha256,upper_tokens,reserved_at) "
                "VALUES(?,?,?,?,?)",
                (kind, purpose, payload_sha256, upper_tokens, now),
            )
            request_id = cursor.lastrowid
            assert request_id is not None
            self.db.execute("COMMIT")
            return request_id
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def settle(self, request_id: int, *, reported_tokens: int | None, failed: bool) -> None:
        if reported_tokens is not None and (
            type(reported_tokens) is not int or reported_tokens < 0
        ):
            raise ValueError("INVALID_REPORTED_USAGE")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT upper_tokens,terminal FROM attempts WHERE id=?", (request_id,)
            ).fetchone()
            if row is None or row[1]:
                raise ValueError("MISSING_OR_ALREADY_SETTLED_REQUEST")
            violation = reported_tokens is not None and reported_tokens > row[0]
            self.db.execute(
                "UPDATE attempts SET reported_tokens=?,terminal=1,failed=? WHERE id=?",
                (reported_tokens, int(failed), request_id),
            )
            if violation:
                self.db.execute("UPDATE batch SET stopped='USAGE_BOUND_VIOLATION'")
            self.db.execute("COMMIT")
            if violation:
                raise BudgetStop("USAGE_BOUND_VIOLATION")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self.db.close()

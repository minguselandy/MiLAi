"""One durable Attention expansion per frozen arm/task, including failed attempts.

This is a dispatch/capture seam, not a model client or a second budget ledger.
The caller pins one private path, authenticates admission/state and supplies a
budgeted retriever. A manifest digest alone is not permission to execute.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from milai_lab.methods.state_attention import (
    DEFAULT_LIMITS,
    POLICY,
    AttentionLimits,
    AttentionState,
    CoverageReview,
    decide_attention,
    question_digest,
)
from milai_lab.methods.state_focus import Eligibility, SourceSnapshot, SourceUnit


@dataclass(frozen=True)
class RetrievedSources:
    sources: tuple[SourceUnit, ...]
    receipt_ref: str


class AttentionExpansion:
    """Private SQLite capture. No reset, retry, review fabrication or model call.

    Concurrent/recovered callers share a committed singleton reservation. An
    unsettled reservation means UNKNOWN execution, not proof a process is live.
    Do not switch paths or execution identities to evade it. All external requests
    inside callbacks still require the batch's existing global budget guard.
    """

    def __init__(
        self,
        path: Path,
        *,
        admission_sha256: str,
        execution_id: str,
        task_id: str,
        scope: str,
        question: str,
        limits: AttentionLimits = DEFAULT_LIMITS,
    ) -> None:
        if (
            len(admission_sha256) != 64
            or any(c not in "0123456789abcdef" for c in admission_sha256)
            or not execution_id
            or not task_id
            or not scope
            or not question.strip()
        ):
            raise ValueError("INVALID_ATTENTION_EXECUTION_BINDING")
        self.task_id, self.scope, self.question, self.limits = task_id, scope, question, limits
        identity = json.dumps(
            {
                "schema": "milai-attention-expansion-v1",
                "admission": admission_sha256,
                "execution_id": execution_id,
                "task_id": task_id,
                "scope": scope,
                "input_sha256": question_digest(question),
                "policy": POLICY,
                "limits": asdict(limits),
            },
            sort_keys=True,
        )
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            tables = {
                r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if tables - {"attention_binding", "attention_expansion"}:
                raise ValueError("ATTENTION_DATABASE_NOT_OWNED")
            path.chmod(0o600)
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS attention_binding "
                "(id INTEGER PRIMARY KEY CHECK(id=1), identity TEXT NOT NULL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS attention_expansion "
                "(id INTEGER PRIMARY KEY CHECK(id=1), record TEXT NOT NULL)"
            )
            self.db.execute("INSERT OR IGNORE INTO attention_binding VALUES(1,?)", (identity,))
            if self.db.execute("SELECT identity FROM attention_binding").fetchone()[0] != identity:
                raise ValueError("ATTENTION_EXECUTION_BINDING_CHANGED")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    def receipt(self) -> dict[str, Any] | None:
        row = self.db.execute("SELECT record FROM attention_expansion").fetchone()
        return json.loads(row[0]) if row else None

    def restored_snapshot(self) -> SourceSnapshot | None:
        """Return captured bytes, not permission or fresh semantic review."""
        row = self.receipt()
        if row is None or row["status"] != "COMPLETED":
            return None
        snapshot = SourceSnapshot(self.scope, tuple(SourceUnit(**s) for s in row["sources"]))
        if snapshot.sha256 != row["snapshot_sha256"]:
            raise ValueError("ATTENTION_CAPTURED_SNAPSHOT_CHANGED")
        return snapshot

    def _save(self, record: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE attention_expansion SET record=? WHERE id=1",
            (json.dumps(record, ensure_ascii=False, allow_nan=False),),
        )

    def step(
        self,
        *,
        sequence: int,
        snapshot: SourceSnapshot,
        baseline_ids: tuple[str, ...],
        state: AttentionState | None,
        coverage: CoverageReview | None,
        check_source: Callable[[SourceUnit], Eligibility],
        before_dispatch: Callable[[], None],
        retrieve: Callable[[dict[str, Any]], RetrievedSources],
    ) -> tuple[dict[str, Any], SourceSnapshot]:
        """Persist before dispatch; return a new pool requiring fresh state/review.

        before_dispatch must check actual admission/deadline without external calls.
        The retriever must guard each model/embedding request and export complete costs at
        receipt_ref; this capture never replaces or resets global budget accounting.
        A returned pool/CONTEXT decision is not Actor exposure. Revalidate again
        immediately before any later Actor dispatch.
        """
        if snapshot.scope != self.scope:
            raise ValueError("ATTENTION_EXECUTION_SCOPE_CHANGED")

        def decide(attempts: int) -> dict[str, Any]:
            return decide_attention(
                task_id=self.task_id,
                question=self.question,
                sequence=sequence,
                snapshot=snapshot,
                baseline_ids=baseline_ids,
                state=state,
                coverage=coverage,
                expansion_attempts=attempts,
                check_source=check_source,
                limits=self.limits,
            )

        decision = decide(int(self.receipt() is not None))
        if decision["action"] != "RETRIEVE_ONCE":
            return decision, snapshot
        record = {
            "status": "RESERVED",
            "decision": decision,
            "dispatch_started": False,
            "elapsed_seconds": None,
            "receipt_ref": None,
            "error_type": None,
            "external_usage": "UNKNOWN_UNTIL_JOINED_TO_GLOBAL_LEDGER",
        }
        inserted = self.db.execute(
            "INSERT OR IGNORE INTO attention_expansion VALUES(1,?)",
            (json.dumps(record, ensure_ascii=False),),
        ).rowcount
        if not inserted:
            return decide(1), snapshot
        started = time.monotonic()
        try:
            before_dispatch()
            # Reservation/queueing may outlive an eligibility observation.
            fresh = decide(0)
            if fresh != decision:
                record.update(
                    status="CANCELLED_PRE_DISPATCH", elapsed_seconds=time.monotonic() - started
                )
                self._save(record)
                return decide(1), snapshot
            record.update(status="DISPATCHING", dispatch_started=True)
            self._save(record)
            intent = decision["retrieval"]
            result = retrieve(copy.deepcopy(intent))
            if not isinstance(result.receipt_ref, str) or not result.receipt_ref:
                raise ValueError("ATTENTION_RETRIEVAL_RECEIPT_MISSING")
            # Keep the cost join even when returned sources fail admission below.
            record["receipt_ref"] = result.receipt_ref
            if (
                len(result.sources) > intent["limit"]
                or sum(len(s.content.encode()) for s in result.sources) > intent["max_bytes"]
                or any(s.source_id in intent["exclude_source_ids"] for s in result.sources)
            ):
                raise ValueError("ATTENTION_RETRIEVAL_CONTRACT_VIOLATION")
            merged = SourceSnapshot(self.scope, (*snapshot.units, *result.sources))
            if any(check_source(s) != "ELIGIBLE" for s in merged.units):
                raise ValueError("ATTENTION_SOURCE_NOT_ELIGIBLE_AFTER_RETRIEVAL")
            record.update(
                status="COMPLETED",
                elapsed_seconds=time.monotonic() - started,
                receipt_ref=result.receipt_ref,
                snapshot_sha256=merged.sha256,
                sources=[asdict(s) for s in merged.units],
            )
            self._save(record)
            return decision, merged
        except BaseException as error:
            record.update(
                status="FAILED",
                elapsed_seconds=time.monotonic() - started,
                error_type=type(error).__name__,
            )
            # Do not retain a not-yet-committed successful body after a write failure.
            record.pop("sources", None)
            record.pop("snapshot_sha256", None)
            self._save(record)
            raise

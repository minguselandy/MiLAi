"""Model-hidden, synchronous Store effect ledger for the LangMem B1 arm."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypeVar

from langgraph.store.base import BaseStore, Item, Op, PutOp, Result, SearchOp

T = TypeVar("T")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_identity(value: Any) -> tuple[str, str, str]:
    """Hash raw UTF-8 strings and typed canonical JSON for other values."""
    if isinstance(value, str):
        kind, encoded = "string", value.encode("utf-8")
    else:
        kind = type(value).__name__
        encoded = canonical_json({"type": kind, "value": value}).encode("utf-8")
    sha = hashlib.sha256(encoded).hexdigest()
    return kind, sha, f"body:{kind}:{sha}"


def _item(item: Item | None) -> dict[str, Any] | None:
    return item.dict() if item is not None else None


class RevisionSidecar:
    """One SQLite writer; source Store and this ledger are intentionally separate."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS bodies(
                body_ref TEXT PRIMARY KEY, kind TEXT NOT NULL,
                content_sha256 TEXT NOT NULL, body_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations(
                observation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                arm_id TEXT NOT NULL, thread_id TEXT NOT NULL,
                session_id TEXT NOT NULL, public_message_index INTEGER NOT NULL,
                role TEXT NOT NULL, actor_ref TEXT NOT NULL, artifact TEXT NOT NULL,
                content_sha256 TEXT NOT NULL, body_ref TEXT NOT NULL,
                observed_at TEXT NOT NULL, delivery_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS tool_calls(
                call_key TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
                generation_id TEXT NOT NULL, call_id TEXT NOT NULL,
                tool_name TEXT NOT NULL, arguments_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                deliveries INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'started',
                journal_status TEXT, result_body_ref TEXT,
                tool_message_status TEXT, last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS operations(
                operation_id TEXT PRIMARY KEY, call_key TEXT NOT NULL,
                attempt_no INTEGER NOT NULL, ordinal INTEGER NOT NULL,
                namespace_json TEXT NOT NULL, memory_id TEXT NOT NULL,
                requested_action TEXT NOT NULL, status TEXT NOT NULL,
                actual_effect TEXT, pre_item_json TEXT, post_item_json TEXT,
                started_at TEXT NOT NULL, completed_at TEXT,
                error_type TEXT, extra_reads INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS revisions(
                namespace_json TEXT NOT NULL, memory_id TEXT NOT NULL,
                revision INTEGER NOT NULL, operation_id TEXT NOT NULL UNIQUE,
                requested_action TEXT NOT NULL, actual_effect TEXT NOT NULL,
                content_json TEXT, content_kind TEXT, content_sha256 TEXT,
                body_ref TEXT, source_refs_json TEXT, source_status TEXT NOT NULL,
                recorded_at TEXT NOT NULL, supersedes_revision INTEGER,
                created_at TEXT, updated_at TEXT, tombstone INTEGER NOT NULL,
                content_unchanged INTEGER NOT NULL, history_status TEXT NOT NULL,
                post_item_json TEXT,
                PRIMARY KEY(namespace_json, memory_id, revision)
            );
            CREATE TABLE IF NOT EXISTS searches(
                search_id TEXT PRIMARY KEY, call_key TEXT NOT NULL,
                attempt_no INTEGER NOT NULL, ordinal INTEGER NOT NULL,
                thread_id TEXT NOT NULL, generation_id TEXT NOT NULL,
                call_id TEXT NOT NULL, arguments_json TEXT NOT NULL,
                namespace_json TEXT NOT NULL, query_text TEXT,
                filter_json TEXT, result_limit INTEGER NOT NULL,
                result_offset INTEGER NOT NULL, returned_at TEXT,
                status TEXT NOT NULL, returned_json TEXT,
                tool_message_body_ref TEXT, tool_message_status TEXT,
                error_type TEXT
            );
            CREATE TABLE IF NOT EXISTS requests(
                request_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
                public_message_index INTEGER NOT NULL, request_index INTEGER NOT NULL,
                status TEXT NOT NULL, planned_at TEXT NOT NULL,
                finished_at TEXT, provider_receipt_id TEXT,
                request_object_sha256 TEXT, request_json TEXT,
                trace_path TEXT, trace_byte_offset INTEGER, trace_record_sha256 TEXT,
                http_status INTEGER, error_type TEXT
            );
            CREATE TABLE IF NOT EXISTS request_material(
                request_id TEXT NOT NULL, tool_call_id TEXT NOT NULL,
                source_kind TEXT NOT NULL, source_id TEXT,
                content_sha256 TEXT, body_ref TEXT,
                coverage TEXT NOT NULL, range_start INTEGER,
                range_end INTEGER,
                PRIMARY KEY(request_id, tool_call_id)
            );
            CREATE TABLE IF NOT EXISTS assistant_lineage(
                thread_id TEXT NOT NULL, response_id TEXT NOT NULL,
                generating_request_id TEXT NOT NULL,
                original_body_ref TEXT NOT NULL,
                exact_snapshot_json TEXT NOT NULL,
                unknown_items INTEGER NOT NULL,
                PRIMARY KEY(thread_id, response_id)
            );
            CREATE TABLE IF NOT EXISTS stats(
                id INTEGER PRIMARY KEY CHECK(id=1), transactions INTEGER NOT NULL,
                observer_cpu_ns INTEGER NOT NULL, observer_wall_ns INTEGER NOT NULL,
                extra_store_reads INTEGER NOT NULL,
                extra_read_cpu_ns INTEGER NOT NULL, extra_read_wall_ns INTEGER NOT NULL,
                initial_db_bytes INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS health(
                id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL,
                reason TEXT NOT NULL, recorded_at TEXT NOT NULL
            );
        """)
        if self.conn.execute("SELECT 1 FROM stats WHERE id=1").fetchone() is None:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO stats VALUES(1,0,0,0,0,0,0,?)",
                    (path.stat().st_size,),
                )

    def close(self) -> None:
        self.conn.close()

    def mark_incomplete(self, reason: str) -> None:
        marker = self.path.with_suffix(self.path.suffix + ".incomplete")
        try:
            with self._lock, self.conn:
                self.conn.execute(
                    "INSERT OR REPLACE INTO health VALUES(1,'INSTRUMENTATION_INCOMPLETE',"
                    "?,datetime('now'))", (reason,),
                )
        except Exception:
            try:
                marker.write_text("INSTRUMENTATION_INCOMPLETE\n", encoding="utf-8")
            except OSError:
                pass

    def unresolved(self) -> list[str]:
        reasons = []
        marker = self.path.with_suffix(self.path.suffix + ".incomplete")
        if marker.exists():
            reasons.append("DURABLE_INCOMPLETE_MARKER")
        with self._lock:
            row = self.conn.execute("SELECT reason FROM health WHERE id=1").fetchone()
            if row is not None:
                reasons.append("DURABLE_HEALTH:" + row["reason"])
            for table, status in (("operations", "started"),
                                  ("operations", "unknown"),
                                  ("operations", "binding_unknown"),
                                  ("searches", "started"),
                                  ("tool_calls", "started"),
                                  ("requests", "planned_unknown")):
                count = self.conn.execute(
                    f"SELECT count(*) FROM {table} WHERE status=?", (status,),  # noqa: S608
                ).fetchone()[0]
                if count:
                    reasons.append(f"UNRESOLVED_{table.upper()}_{status.upper()}:{count}")
        return reasons

    def _write(self, action: Callable[[sqlite3.Connection], T]) -> T:
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        with self._lock:
            with self.conn:
                result = action(self.conn)
            elapsed_cpu = time.process_time_ns() - cpu
            elapsed_wall = time.perf_counter_ns() - wall
            with self.conn:
                self.conn.execute(
                    "UPDATE stats SET transactions=transactions+2, "
                    "observer_cpu_ns=observer_cpu_ns+?, observer_wall_ns=observer_wall_ns+? "
                    "WHERE id=1", (elapsed_cpu, elapsed_wall),
                )
            return result

    def _body(self, conn: sqlite3.Connection, content: Any) -> tuple[str, str]:
        kind, sha, ref = content_identity(content)
        conn.execute(
            "INSERT OR IGNORE INTO bodies VALUES(?,?,?,?)",
            (ref, kind, sha, canonical_json(content)),
        )
        return sha, ref

    def observe(
        self, observation_id: str, run_id: str, arm_id: str,
        thread_id: str, session_id: str, public_index: int,
        role: str, actor_ref: str, artifact: str, content: Any,
        *, count_redelivery: bool = False,
    ) -> str:
        def save(conn: sqlite3.Connection) -> str:
            sha, ref = self._body(conn, content)
            prior = conn.execute(
                "SELECT content_sha256,body_ref FROM observations WHERE observation_id=?",
                (observation_id,),
            ).fetchone()
            if prior is not None:
                if prior["content_sha256"] != sha or prior["body_ref"] != ref:
                    raise ValueError("OBSERVATION_ID_CONTENT_CHANGED")
                if count_redelivery:
                    conn.execute(
                        "UPDATE observations SET delivery_count=delivery_count+1 "
                        "WHERE observation_id=?", (observation_id,),
                    )
                return ref
            conn.execute(
                "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now'),1)",
                (observation_id, run_id, arm_id, thread_id, session_id, public_index,
                 role, actor_ref, artifact, sha, ref),
            )
            return ref
        return self._write(save)

    def begin_call(
        self, call_key: str, thread_id: str, generation_id: str,
        call_id: str, tool_name: str, arguments: dict[str, Any],
        *, replayed: bool = False,
    ) -> int:
        def save(conn: sqlite3.Connection) -> int:
            row = conn.execute(
                "SELECT attempts,arguments_json FROM tool_calls WHERE call_key=?",
                (call_key,),
            ).fetchone()
            args_json = canonical_json(arguments)
            if row is not None and row["arguments_json"] != args_json:
                raise ValueError("TOOL_CALL_ID_ARGUMENTS_CHANGED")
            if row is None:
                conn.execute(
                    "INSERT INTO tool_calls(call_key,thread_id,generation_id,call_id,"
                    "tool_name,arguments_json,attempts) VALUES(?,?,?,?,?,?,?)",
                    (call_key, thread_id, generation_id, call_id, tool_name,
                     args_json, 0 if replayed else 1),
                )
                return 0 if replayed else 1
            if replayed:
                return int(row["attempts"])
            attempt = int(row["attempts"]) + 1
            conn.execute(
                "UPDATE tool_calls SET attempts=?,status='started' WHERE call_key=?",
                (attempt, call_key),
            )
            return attempt
        return self._write(save)

    def finish_call(
        self, call_key: str, content: Any | None, status: str,
        journal_status: str | None, *, error: str | None = None,
    ) -> str | None:
        def save(conn: sqlite3.Connection) -> str | None:
            ref = self._body(conn, content)[1] if content is not None else None
            conn.execute(
                "UPDATE tool_calls SET deliveries=deliveries+?,status=?,"
                "journal_status=?,result_body_ref=?,tool_message_status=?,last_error=? "
                "WHERE call_key=?",
                (1 if content is not None else 0, status, journal_status,
                 ref, status if content is not None else None, error, call_key),
            )
            return ref
        return self._write(save)

    def begin_operation(
        self, operation_id: str, call_key: str, attempt_no: int, ordinal: int,
        namespace: tuple[str, ...], memory_id: str, requested_action: str,
        before: Item | None,
    ) -> None:
        self._write(lambda conn: conn.execute(
            "INSERT OR IGNORE INTO operations(operation_id,call_key,attempt_no,ordinal,"
            "namespace_json,memory_id,requested_action,status,pre_item_json,started_at) "
            "VALUES(?,?,?,?,?,?,?,'started',?,datetime('now'))",
            (operation_id, call_key, attempt_no, ordinal, canonical_json(namespace),
             memory_id, requested_action,
             canonical_json(_item(before)) if before is not None else None),
        ))

    def finish_operation(
        self, operation_id: str, before: Item | None, after: Item | None,
        *, deleted: bool, extra_reads: int, before_known: bool,
    ) -> dict[str, Any] | None:
        def save(conn: sqlite3.Connection) -> tuple[str, dict[str, Any] | None]:
            operation = conn.execute(
                "SELECT * FROM operations WHERE operation_id=?", (operation_id,),
            ).fetchone()
            if operation is None:
                raise ValueError("STORE_OPERATION_BEGIN_MISSING")
            if operation["status"] == "complete":
                row = conn.execute(
                    "SELECT * FROM revisions WHERE operation_id=?", (operation_id,),
                ).fetchone()
                return "complete", dict(row) if row is not None else None
            namespace_json, memory_id = operation["namespace_json"], operation["memory_id"]
            prior = conn.execute(
                "SELECT * FROM revisions WHERE namespace_json=? AND memory_id=? "
                "ORDER BY revision DESC LIMIT 1", (namespace_json, memory_id),
            ).fetchone()
            history = "COMPLETE" if prior is not None or before is None else "IMPORTED_UNKNOWN"
            if (not before_known or
                    (prior is not None and before is None and not prior["tombstone"])):
                history = "BINDING_UNKNOWN"
            if prior is not None and before is not None:
                if (prior["tombstone"] or prior["post_item_json"]
                        != canonical_json(_item(before))):
                    history = "BINDING_UNKNOWN"
            if deleted:
                effect = "delete" if before is not None and after is None else "none"
                if after is not None:
                    history = "BINDING_UNKNOWN"
            else:
                effect = ("recreate" if prior is not None and prior["tombstone"] else "insert")
                if before is not None:
                    effect = "update"
                if after is None:
                    history = "BINDING_UNKNOWN"
            revision: dict[str, Any] | None = None
            if history != "BINDING_UNKNOWN" and effect != "none":
                number = int(prior["revision"]) + 1 if prior is not None else 1
                if deleted:
                    content = None
                elif after is not None:
                    content = after.value.get("content")
                else:
                    raise ValueError("STORE_POST_ITEM_MISSING")
                sha, ref = (None, None) if deleted else self._body(conn, content)
                unchanged = (before is not None and after is not None and not deleted
                             and before.value == after.value)
                post = _item(after)
                conn.execute(
                    "INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (namespace_json, memory_id, number, operation_id,
                     operation["requested_action"], effect,
                     None if deleted else canonical_json(content),
                     None if deleted else content_identity(content)[0], sha, ref,
                     None, "UNKNOWN_NOT_DECLARED",
                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     int(prior["revision"]) if prior is not None else None,
                     post["created_at"] if post else None,
                     post["updated_at"] if post else None,
                     int(deleted), int(unchanged), history,
                     canonical_json(post) if post is not None else None),
                )
                revision = {"namespace": json.loads(namespace_json), "memory_id": memory_id,
                            "revision": number, "actual_effect": effect, "tombstone": deleted}
            conn.execute(
                "UPDATE operations SET status=?,actual_effect=?,post_item_json=?,"
                "completed_at=datetime('now'),extra_reads=? WHERE operation_id=?",
                ("complete" if history != "BINDING_UNKNOWN" else "binding_unknown",
                 effect, canonical_json(_item(after)) if after is not None else None,
                 extra_reads, operation_id),
            )
            return ("complete" if history != "BINDING_UNKNOWN" else "binding_unknown",
                    revision)
        status, revision = self._write(save)
        if status == "binding_unknown":
            raise ValueError("REVISION_BINDING_UNKNOWN")
        return revision

    def fail_operation(self, operation_id: str, status: str, error_type: str) -> None:
        self._write(lambda conn: conn.execute(
            "UPDATE operations SET status=?,error_type=?,completed_at=datetime('now') "
            "WHERE operation_id=?", (status, error_type, operation_id),
        ))

    def begin_search(
        self, search_id: str, call_key: str, attempt_no: int, ordinal: int,
        thread_id: str, generation_id: str, call_id: str,
        arguments: dict[str, Any], op: SearchOp,
    ) -> None:
        self._write(lambda conn: conn.execute(
            "INSERT OR IGNORE INTO searches(search_id,call_key,attempt_no,ordinal,"
            "thread_id,generation_id,call_id,arguments_json,namespace_json,query_text,"
            "filter_json,result_limit,result_offset,status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'started')",
            (search_id, call_key, attempt_no, ordinal, thread_id, generation_id,
             call_id, canonical_json(arguments), canonical_json(op.namespace_prefix),
             op.query, canonical_json(op.filter), op.limit, op.offset),
        ))

    def finish_search(self, search_id: str, results: list[Any]) -> list[dict[str, Any]]:
        def save(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            returned = []
            for item in results:
                raw = item.dict()
                namespace_json = canonical_json(item.namespace)
                prior = conn.execute(
                    "SELECT * FROM revisions WHERE namespace_json=? AND memory_id=? "
                    "ORDER BY revision DESC LIMIT 1",
                    (namespace_json, item.key),
                ).fetchone()
                if prior is None:
                    version, binding = None, "IMPORTED_UNKNOWN"
                elif prior["tombstone"] or prior["post_item_json"] != canonical_json({
                    key: value for key, value in raw.items() if key != "score"
                }):
                    version, binding = None, "BINDING_UNKNOWN"
                else:
                    version, binding = int(prior["revision"]), "EXACT"
                content = item.value.get("content")
                kind, sha, ref = content_identity(content)
                self._body(conn, content)
                returned.append({
                    "namespace": list(item.namespace), "memory_id": item.key,
                    "revision": version, "revision_status": binding,
                    "score": item.score, "content_sha256": sha,
                    "content_kind": kind, "body_ref": ref,
                    "store_item": raw,
                })
            conn.execute(
                "UPDATE searches SET status='returned',returned_at=datetime('now'),"
                "returned_json=? WHERE search_id=?",
                (canonical_json(returned), search_id),
            )
            return returned
        return self._write(save)

    def finish_search_message(self, search_id: str, content: Any, status: str) -> None:
        def save(conn: sqlite3.Connection) -> None:
            _, ref = self._body(conn, content)
            conn.execute(
                "UPDATE searches SET tool_message_body_ref=?,tool_message_status=? "
                "WHERE search_id=?", (ref, status, search_id),
            )
        self._write(save)

    def fail_search(self, search_id: str, status: str, error_type: str) -> None:
        self._write(lambda conn: conn.execute(
            "UPDATE searches SET status=?,error_type=?,returned_at=datetime('now') "
            "WHERE search_id=?", (status, error_type, search_id),
        ))

    def add_extra_read(self, cpu_ns: int, wall_ns: int) -> None:
        self._write(lambda conn: conn.execute(
            "UPDATE stats SET extra_store_reads=extra_store_reads+1,"
            "extra_read_cpu_ns=extra_read_cpu_ns+?,"
            "extra_read_wall_ns=extra_read_wall_ns+? WHERE id=1",
            (cpu_ns, wall_ns),
        ))

    def plan_request(self, request_id: str, thread_id: str, public_index: int,
                     request_index: int) -> None:
        self._write(lambda conn: conn.execute(
            "INSERT OR IGNORE INTO requests(request_id,thread_id,public_message_index,"
            "request_index,status,planned_at) VALUES(?,?,?,?, 'planned_unknown',datetime('now'))",
            (request_id, thread_id, public_index, request_index),
        ))

    def finish_request(
        self, request_id: str, status: str, event: dict[str, Any],
        trace_ref: dict[str, Any] | None = None,
        projected_material: dict[str, dict[str, str]] | None = None,
    ) -> None:
        request = event.get("request")
        request_json = canonical_json(request) if request is not None else None
        request_sha = (hashlib.sha256(request_json.encode("utf-8")).hexdigest()
                       if request_json else None)
        receipt = event.get("receipt")
        receipt_id = receipt.get("id") if isinstance(receipt, dict) else None
        exception = event.get("exception")
        error_type = exception.get("type") if isinstance(exception, dict) else None
        def save(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE requests SET status=?,finished_at=datetime('now'),"
                "provider_receipt_id=?,request_object_sha256=?,request_json=?,"
                "trace_path=?,trace_byte_offset=?,trace_record_sha256=?,"
                "http_status=?,error_type=? WHERE request_id=?",
                (status, receipt_id, request_sha,
                 request_json if trace_ref is None else None,
                 trace_ref.get("path") if trace_ref else None,
                 trace_ref.get("byte_offset") if trace_ref else None,
                 trace_ref.get("record_sha256") if trace_ref else None,
                 event.get("http_status"), error_type, request_id),
            )
            if not isinstance(request, dict):
                return
            for message in request.get("messages", []):
                if message.get("role") != "tool":
                    continue
                call_id = message.get("tool_call_id")
                content = message.get("content")
                if not isinstance(call_id, str):
                    continue
                _, content_sha, body_ref = content_identity(content)
                source = conn.execute(
                    "SELECT search_id AS source_id,tool_message_body_ref AS ref "
                    "FROM searches WHERE call_id=? AND thread_id=(SELECT thread_id FROM requests "
                    "WHERE request_id=?) AND tool_message_body_ref IS NOT NULL "
                    "ORDER BY rowid DESC LIMIT 1", (call_id, request_id),
                ).fetchone()
                kind = "search"
                if source is None:
                    source = conn.execute(
                        "SELECT call_key AS source_id,result_body_ref AS ref "
                        "FROM tool_calls WHERE call_id=? AND thread_id=(SELECT thread_id FROM "
                        "requests WHERE request_id=?) AND result_body_ref IS NOT NULL "
                        "ORDER BY rowid DESC LIMIT 1", (call_id, request_id),
                    ).fetchone()
                    kind = "tool_call"
                coverage = "FULL" if source is not None and source["ref"] == body_ref else "UNBOUND"
                projection = (projected_material or {}).get(call_id)
                if (coverage == "UNBOUND" and kind == "search" and source is not None
                        and projection is not None
                        and source["source_id"] == projection["source_search_id"]
                        and source["ref"] == projection["original_body_ref"]
                        and body_ref == projection["projected_body_ref"]):
                    coverage = projection.get("coverage", "PROJECTED_WITHHELD")
                conn.execute(
                    "INSERT OR REPLACE INTO request_material VALUES(?,?,?,?,?,?,?,?,?)",
                    (request_id, call_id, kind if source else "unknown",
                     source["source_id"] if source else None, content_sha, body_ref,
                     coverage, 0,
                     len(content.encode("utf-8")) if isinstance(content, str) else None),
                )
        self._write(save)

    def latest_revision(self, namespace: tuple[str, ...], memory_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM revisions WHERE namespace_json=? AND memory_id=? "
                "ORDER BY revision DESC LIMIT 1",
                (canonical_json(namespace), memory_id),
            ).fetchone()
            return dict(row) if row is not None else None

    def record_assistant_lineage(
        self, thread_id: str, response_id: str, request_id: str,
        content: str, exact_snapshot: list[dict[str, Any]], unknown_items: int,
    ) -> bool:
        """Bind an ordinary checkpoint message to its completed Provider request."""
        body_ref = content_identity(content)[2]
        snapshot_json = canonical_json(exact_snapshot)

        def save(conn: sqlite3.Connection) -> bool:
            request = conn.execute(
                "SELECT thread_id,status,provider_receipt_id FROM requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if (request is None or request["thread_id"] != thread_id
                    or request["status"] != "completed"
                    or request["provider_receipt_id"] != response_id):
                return False
            prior = conn.execute(
                "SELECT * FROM assistant_lineage WHERE thread_id=? AND response_id=?",
                (thread_id, response_id),
            ).fetchone()
            row = (request_id, body_ref, snapshot_json, unknown_items)
            if prior is not None:
                if tuple(prior[key] for key in (
                    "generating_request_id", "original_body_ref",
                    "exact_snapshot_json", "unknown_items",
                )) != row:
                    raise ValueError("ASSISTANT_LINEAGE_RESPONSE_ID_COLLISION")
                return True
            conn.execute(
                "INSERT INTO assistant_lineage VALUES(?,?,?,?,?,?)",
                (thread_id, response_id, *row),
            )
            return True

        return self._write(save)

    def get_assistant_lineage(self, thread_id: str,
                              response_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM assistant_lineage WHERE thread_id=? AND response_id=?",
                (thread_id, response_id),
            ).fetchone()
            return dict(row) if row is not None else None

    def rows(self, table: str) -> list[dict[str, Any]]:
        if table not in {"bodies", "observations", "tool_calls", "operations", "revisions",
                         "searches", "requests", "request_material", "assistant_lineage"}:
            raise ValueError("UNKNOWN_SIDECAR_TABLE")
        with self._lock:
            return [dict(row) for row in self.conn.execute(f"SELECT * FROM {table}")]  # noqa: S608

    def costs(self) -> dict[str, Any]:
        with self._lock:
            row = dict(self.conn.execute("SELECT * FROM stats WHERE id=1").fetchone())
        row["sqlite_db_bytes"] = self.path.stat().st_size
        row["net_sqlite_db_bytes"] = row["sqlite_db_bytes"] - row["initial_db_bytes"]
        row["byte_scope"] = (
            "SQLite main DB including retained revision bodies and indexes; DELETE journal mode"
        )
        return row


class ObservedStore(BaseStore):
    """Delegate the current synchronous LangMem Store calls without changing results."""

    def __init__(self, inner: BaseStore, observer: Any) -> None:
        self.inner = inner
        self.observer = observer
        self.supports_ttl = inner.supports_ttl
        self.ttl_config = inner.ttl_config

    def _read(self, namespace: tuple[str, ...], key: str) -> Item | None:
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        try:
            return self.inner.get(namespace, key, refresh_ttl=False)
        finally:
            self.observer.safe(
                self.observer.sidecar.add_extra_read,
                time.process_time_ns() - cpu, time.perf_counter_ns() - wall,
            )

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        operations = list(ops)
        context = self.observer.current_call()
        if context is None:
            return self.inner.batch(operations)
        pending: list[tuple[int, PutOp | SearchOp, str, Item | None, bool]] = []
        for index, op in enumerate(operations):
            if isinstance(op, PutOp):
                before = None
                before_known = True
                try:
                    before = self._read(op.namespace, op.key)
                except Exception:
                    before_known = False
                    self.observer.incomplete("EXTRA_STORE_READ_FAILED")
                ordinal = context.next_ordinal()
                operation_id = f"{context.call_key}:{context.attempt_no}:store:{ordinal}"
                self.observer.safe(
                    self.observer.sidecar.begin_operation,
                    operation_id, context.call_key, context.attempt_no, ordinal,
                    op.namespace, op.key, context.arguments.get("action", "create"), before,
                )
                pending.append((index, op, operation_id, before, before_known))
            elif isinstance(op, SearchOp) and context.tool_name == "search_memory":
                ordinal = context.next_ordinal()
                search_id = f"{context.call_key}:{context.attempt_no}:search:{ordinal}"
                self.observer.safe(
                    self.observer.sidecar.begin_search,
                    search_id, context.call_key, context.attempt_no, ordinal,
                    context.thread_id, context.generation_id, context.call_id,
                    context.arguments, op,
                )
                context.search_ids.append(search_id)
                pending.append((index, op, search_id, None, True))
        try:
            results = self.inner.batch(operations)
        except Exception as error:
            status = "unknown"
            for _, op, identifier, _, _ in pending:
                self.observer.safe(
                    self.observer.sidecar.fail_search if isinstance(op, SearchOp)
                    else self.observer.sidecar.fail_operation,
                    identifier, status, type(error).__name__,
                )
            raise
        for index, op, identifier, before, before_known in pending:
            if isinstance(op, PutOp):
                try:
                    after = self._read(op.namespace, op.key)
                except Exception:
                    self.observer.incomplete("EXTRA_STORE_READ_FAILED")
                    continue
                self.observer.safe(
                    self.observer.sidecar.finish_operation,
                    identifier, before, after,
                    deleted=op.value is None, extra_reads=1 + int(before_known),
                    before_known=before_known,
                )
            else:
                self.observer.safe(
                    self.observer.sidecar.finish_search, identifier, results[index],
                )
        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        raise NotImplementedError("B1 observes only the current synchronous LangMem path")

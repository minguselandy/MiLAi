"""Persistent, reference-based tables shared by the builder and M0/M1 loader."""

from __future__ import annotations

import json
import sqlite3
import zlib
from pathlib import Path
from typing import Any

DB_NAME = "memory_control.sqlite3"

SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE roots (
    id INTEGER PRIMARY KEY, dataset TEXT NOT NULL, native_group TEXT NOT NULL,
    raw_path TEXT NOT NULL, location TEXT NOT NULL, details BLOB,
    views_built INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY, root_id INTEGER NOT NULL REFERENCES roots(id),
    split TEXT NOT NULL, source_row INTEGER NOT NULL, native_id TEXT NOT NULL,
    query TEXT NOT NULL, setting TEXT NOT NULL,
    clean_role TEXT NOT NULL DEFAULT 'excluded', states_built INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX tasks_root ON tasks(root_id, id);
CREATE INDEX tasks_clean ON tasks(clean_role, root_id, id);
CREATE TABLE annotations (task_id INTEGER PRIMARY KEY REFERENCES tasks(id), data BLOB NOT NULL);
CREATE TABLE exclusions (
    task_id INTEGER NOT NULL REFERENCES tasks(id), reason TEXT NOT NULL,
    PRIMARY KEY (task_id, reason)
);
CREATE TABLE objects (
    id INTEGER PRIMARY KEY, root_id INTEGER NOT NULL REFERENCES roots(id),
    position INTEGER NOT NULL, kind TEXT NOT NULL, role TEXT NOT NULL,
    location TEXT NOT NULL, preview TEXT NOT NULL, body BLOB, characters INTEGER NOT NULL,
    block INTEGER, UNIQUE (root_id, position)
);
CREATE TABLE views (
    id INTEGER PRIMARY KEY, object_id INTEGER NOT NULL REFERENCES objects(id),
    tier TEXT NOT NULL, page INTEGER NOT NULL, method TEXT NOT NULL,
    ranges BLOB NOT NULL, reader_tokens INTEGER NOT NULL, encoder_tokens INTEGER NOT NULL,
    UNIQUE (object_id, tier, page)
);
CREATE TABLE candidates (
    focus_id INTEGER PRIMARY KEY REFERENCES views(id),
    context_id INTEGER REFERENCES views(id), equivalence TEXT
);
CREATE TABLE states (
    id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
    recipe TEXT NOT NULL, sampling TEXT NOT NULL, control_steps INTEGER NOT NULL,
    prefix BLOB NOT NULL, candidates BLOB NOT NULL, actions BLOB NOT NULL,
    delivered BLOB NOT NULL, material_tokens INTEGER NOT NULL,
    object_count INTEGER NOT NULL, encoder_length_bucket INTEGER NOT NULL
);
CREATE INDEX states_task ON states(task_id, id);
CREATE TABLE weak_labels (
    state_id INTEGER PRIMARY KEY REFERENCES states(id), evidence BLOB NOT NULL,
    corpus_coverage TEXT NOT NULL
);
CREATE TABLE rollout_jobs (
    state_id INTEGER PRIMARY KEY REFERENCES states(id), protocol TEXT NOT NULL,
    continuation TEXT NOT NULL
);
CREATE TABLE action_outcomes (
    state_id INTEGER NOT NULL REFERENCES states(id), action_id TEXT NOT NULL,
    run_id TEXT NOT NULL, reader_protocol TEXT NOT NULL, execution_status TEXT NOT NULL,
    next_state BLOB, delivered_material BLOB, task_result BLOB, costs BLOB,
    PRIMARY KEY (state_id, action_id, run_id)
);
CREATE TABLE anomalies (
    id INTEGER PRIMARY KEY, dataset TEXT NOT NULL, split TEXT,
    task_id INTEGER REFERENCES tasks(id), reason TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE VIEW task_index AS
    SELECT t.*, r.dataset, r.native_group, r.raw_path, r.location
    FROM tasks t JOIN roots r ON r.id=t.root_id;
CREATE VIEW observation_settings AS
    SELECT t.id AS task_id, t.setting, 'processed_source_only' AS protocol FROM tasks t
    UNION ALL
    SELECT t.id, 'official_persona_primed_reference_only', 'original_history_then_query'
    FROM task_index t WHERE t.dataset='personamem_v2';
"""


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def packed(value: Any) -> bytes:
    return zlib.compress(dumps(value).encode(), 1)


def unpack(value: bytes) -> Any:
    return json.loads(zlib.decompress(value))


def body_text(body: bytes | None) -> str:
    return zlib.decompress(body).decode() if body is not None else ""


def connect(path: Path, *, writable: bool = False) -> sqlite3.Connection:
    db = (
        sqlite3.connect(path)
        if writable
        else sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    if not writable:
        db.execute("PRAGMA query_only=ON")
    return db


def set_meta(db: sqlite3.Connection, key: str, value: Any) -> None:
    db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (key, dumps(value)))


def get_meta(db: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def anomaly(
    db: sqlite3.Connection,
    source: str,
    split: str | None,
    task: int | None,
    reason: str,
    detail: Any,
) -> None:
    db.execute(
        "INSERT INTO anomalies(dataset,split,task_id,reason,detail) VALUES (?,?,?,?,?)",
        (source, split, task, reason, dumps(detail)),
    )

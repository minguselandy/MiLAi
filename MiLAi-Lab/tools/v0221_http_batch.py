"""Durable single-batch coordinator for explicit historical carry, HTTP-only revision.

This is an experiment accounting/launch journal, not Product or Memory State.
All mutations are confined to the new batch's SQLite journal and own evidence.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from v02_local_provider import read_events
from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import read, save, sha, validate
from v0220_provider_hardened import ProviderStop, historical_usage, usage_state

REVISION = "V0221_HTTP_ONLY_EXACT_CARRY_V1"


class Batch:
    def __init__(self, root: Path, binding_sha: str):
        self.root = root.resolve()
        if sha(self.root / "execution-binding.json") != binding_sha:
            raise ProviderStop("EXECUTION_BINDING_DRIFT")
        self.binding_sha = binding_sha
        self.binding = read(self.root / "execution-binding.json")
        self.auth = self.authorize("W1")
        self.plan = read(self.root / "manifest.json")["contract"]
        self.path = self.root / "batch.sqlite"

    def authorize(self, stage: str) -> dict:
        if sha(self.root / "execution-binding.json") != self.binding_sha:
            raise ProviderStop("EXECUTION_BINDING_DRIFT")
        for name in ("authorization.json", "authorization-source.json", "manifest.json"):
            if sha(self.root / name) != self.binding[name]:
                raise ProviderStop("AUTHORIZATION_OR_MANIFEST_DRIFT")
        auth = read(self.root / "authorization.json")
        grant = read(self.root / "authorization-source.json")
        if (
            auth["revision"] != REVISION
            or auth["path"] != "B"
            or auth["historical_usage_settled"] is not False
            or auth.get("reconciliation") is not None
            or grant["origin"] != "USER_CONVERSATION"
            or grant["explicit_historical_carry"] is not True
            or grant["http_only"] is not True
        ):
            raise ProviderStop("EXPLICIT_HTTP_ONLY_PATH_B_GRANT_REQUIRED")
        if auth["root"] != str(self.root) or auth["batch_id"] != self.root.name:
            raise ProviderStop("AUTHORIZATION_OTHER_BATCH")
        if stage not in auth["stages"] or set(auth["stages"]) - set(grant["stages"]):
            raise ProviderStop("STAGE_NOT_AUTHORIZED")
        if not auth["issued_unix"] <= time.time() < auth["expires_unix"]:
            raise ProviderStop("AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")
        if (
            auth["endpoint"] != ENDPOINT
            or auth["model"] != MODEL
            or auth["caps"] != {"W2": 16, "W3": 96}
            or auth["concurrency"] != 1
            or auth["raw_cap"] is not None
            or auth["automatic_retry"] is not False
            or auth["new_unknown_stops_all"] is not True
        ):
            raise ProviderStop("AUTHORIZATION_SCOPE_MISMATCH")
        try:
            history = historical_usage(
                tuple(Path(s["path"]) for s in auth["historical"]["sources"])
            )
        except (ValueError, KeyError, TypeError, OSError):
            raise ProviderStop("HISTORICAL_LEDGER_CORRUPT") from None
        if (
            history != auth["historical"]
            or history["violations"]
            or auth["accepted_unknown"] != history["unresolved_reservations"]
        ):
            raise ProviderStop("HISTORICAL_HASH_OR_EXCEPTION_DRIFT")
        manifest = validate(self.root, manifest_sha256=self.binding["manifest.json"])
        if [s["path"] for s in history["sources"]] != manifest["contract"]["historical_paths"]:
            raise ProviderStop("COMPLETE_FROZEN_HISTORY_REQUIRED")
        return auth

    def initialize(self) -> None:
        self.authorize("W1")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE episodes (id TEXT PRIMARY KEY,stage TEXT,ordinal INTEGER,
                    cap INTEGER,status TEXT,pid INTEGER,deadline REAL);
                CREATE TABLE events (seq INTEGER PRIMARY KEY,event TEXT NOT NULL);
            """)
            db.execute("INSERT INTO meta VALUES ('binding',?)", (self.binding_sha,))
            for stage in ("W2", "W3"):
                for i, spec in enumerate(self.plan[stage]):
                    db.execute(
                        "INSERT INTO episodes VALUES (?,?,?,?, 'PENDING',NULL,NULL)",
                        (spec["id"], stage, i, 1 if stage == "W2" else 4),
                    )

    @contextmanager
    def transaction(self):
        # mode=rw must not silently create a fresh journal after deletion/restart.
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0]
                != self.binding_sha
            ):
                raise ProviderStop("COORDINATOR_BINDING_DRIFT")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def events(self, db) -> list[dict]:
        return [json.loads(r[0]) for r in db.execute("SELECT event FROM events ORDER BY seq")]

    def check_journal(self, db) -> dict:
        if db.execute("SELECT value FROM meta WHERE key='stop'").fetchone():
            raise ProviderStop("BATCH_STOPPED_NO_RETRY")
        events = self.events(db)
        state = usage_state(events)
        if not state["new_generation_allowed"]:
            raise ProviderStop("NEW_BATCH_UNKNOWN_OR_VIOLATION")
        mirrored = []
        for spec in [*self.plan["W2"], *self.plan["W3"]]:
            path = self.root / "episodes" / spec["id"] / "provider/provider-ledger-v2.jsonl"
            mirrored.extend(read_events(path))

        # Compare event sets in canonical order; request IDs are unique across all episodes.
        def normalize(rows):
            return sorted(json.dumps(v, sort_keys=True) for v in rows)

        if normalize(events) != normalize(mirrored):
            raise ProviderStop("CENTRAL_AND_EPISODE_LEDGER_DIVERGED")
        return state

    def allow_preflight(self, result_path: Path) -> None:
        self.authorize("W1")
        if read(result_path)["status"] != "G_PREFLIGHT_PASS":
            raise ProviderStop("FULL_PREFLIGHT_REQUIRED")
        with self.transaction() as db:
            self.check_journal(db)
            db.execute("INSERT INTO meta VALUES ('preflight',?)", (sha(result_path),))

    def references(self) -> list[dict]:
        with self.transaction() as db:
            row = db.execute("SELECT value FROM meta WHERE key='reference_index'").fetchone()
        if row is None or sha(self.root / "reference-requests.json") != row[0]:
            raise ProviderStop("REFERENCE_REQUEST_INDEX_DRIFT")
        return read(self.root / "reference-requests.json")

    def launch_once(self) -> None:
        self.authorize("W2")
        save(
            self.root / "live-launch.json",
            {"pid": os.getpid(), "unix": time.time(), "binding_sha256": self.binding_sha},
        )

    def claim(self, episode: str) -> None:
        spec = next((s for s in [*self.plan["W2"], *self.plan["W3"]] if s["id"] == episode), None)
        if spec is None:
            raise ProviderStop("EPISODE_OUTSIDE_FROZEN_PLAN")
        stage = spec["stage"]
        self.authorize(stage)
        with self.transaction() as db:
            self.check_journal(db)
            gate = db.execute("SELECT value FROM meta WHERE key='preflight'").fetchone()
            if gate is None or sha(self.root / "preflight/result.json") != gate[0]:
                raise ProviderStop("PREFLIGHT_NOT_ADMITTED_OR_DRIFTED")
            if db.execute("SELECT id FROM episodes WHERE status='RUNNING'").fetchone():
                raise ProviderStop("SINGLE_ACTIVE_EPISODE_ONLY")
            if stage == "W3" and db.execute(
                "SELECT COUNT(*) FROM episodes WHERE stage='W2' AND status='PASS'"
            ).fetchone()[0] != len(self.plan["W2"]):
                raise ProviderStop("W3_REQUIRES_COMPLETE_W2_PASS")
            row = db.execute(
                "SELECT * FROM episodes WHERE stage=? AND status!='PASS' ORDER BY ordinal", (stage,)
            ).fetchone()
            if row is None or row["id"] != episode or row["status"] != "PENDING":
                raise ProviderStop("NO_RESTART_OR_OUT_OF_ORDER_EPISODE")
            phase_key = stage + "_deadline"
            deadline = db.execute("SELECT value FROM meta WHERE key=?", (phase_key,)).fetchone()
            if deadline is None:
                limit = time.time() + (1800 if stage == "W2" else 7200)
                db.execute("INSERT INTO meta VALUES (?,?)", (phase_key, str(limit)))
            else:
                limit = float(deadline[0])
            if time.time() >= min(limit, self.auth["expires_unix"]):
                raise ProviderStop("BATCH_PHASE_DEADLINE")
            db.execute(
                "UPDATE episodes SET status='RUNNING',pid=?,deadline=? WHERE id=?",
                (os.getpid(), min(limit, time.time() + 300, self.auth["expires_unix"]), episode),
            )

    def admit(self, episode: str) -> dict:
        with self.transaction() as db:
            self.check_journal(db)
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
            if row is None or row["status"] != "RUNNING" or row["pid"] != os.getpid():
                raise ProviderStop("EPISODE_NOT_OWNED_BY_THIS_PROCESS")
            self.authorize(row["stage"])
            if time.time() >= row["deadline"]:
                raise ProviderStop("EPISODE_DEADLINE")
            return dict(row)

    def record(self, episode: str, event: dict) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
            if row is None or row["status"] != "RUNNING" or row["pid"] != os.getpid():
                raise ProviderStop("EVENT_FROM_UNOWNED_EPISODE")
            events = self.events(db)
            if event["event"] == "RESERVED":
                self.authorize(row["stage"])
                self.check_journal(db)
                stage_ids = {
                    r[0]
                    for r in db.execute("SELECT id FROM episodes WHERE stage=?", (row["stage"],))
                }
                reservations = [e for e in events if e["event"] == "RESERVED"]
                if (
                    sum(e["session"] == episode for e in reservations) >= row["cap"]
                    or sum(e["session"] in stage_ids for e in reservations)
                    >= self.auth["caps"][row["stage"]]
                    or time.time() >= row["deadline"]
                    or event["session"] != episode
                ):
                    raise ProviderStop("BATCH_COUNT_OR_TIME_BOUND")
            else:
                reservation = next(
                    (
                        e
                        for e in events
                        if e["event"] == "RESERVED" and e["request_id"] == event["request_id"]
                    ),
                    None,
                )
                if reservation is None or reservation["session"] != episode:
                    raise ProviderStop("EVENT_REQUEST_NOT_OWNED")
            usage_state([*events, event])  # Strict event transitions before durable append.
            db.execute("INSERT INTO events(event) VALUES (?)", (json.dumps(event),))
            if event["event"] in {"USAGE_UNKNOWN", "BOUND_VIOLATION"}:
                db.execute("INSERT OR IGNORE INTO meta VALUES ('stop',?)", (event["event"],))

    def finish(self, episode: str) -> None:
        with self.transaction() as db:
            self.check_journal(db)
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
            if row is None or row["status"] != "RUNNING":
                raise ProviderStop("NO_RUNNING_EPISODE_TO_FINISH")
            count = sum(
                e["event"] == "RESERVED" and e["session"] == episode for e in self.events(db)
            )
            if not (count == 1 if row["stage"] == "W2" else 3 <= count <= 4):
                raise ProviderStop("EMPTY_OR_INCOMPLETE_EPISODE_CANNOT_PASS")
            db.execute("UPDATE episodes SET status='PASS' WHERE id=?", (episode,))

    def stop(self, reason: str) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO meta VALUES ('stop',?)", (reason,))
            db.execute("UPDATE episodes SET status='FAIL' WHERE status='RUNNING'")

    def snapshot(self) -> dict:
        with self.transaction() as db:
            stop = db.execute("SELECT value FROM meta WHERE key='stop'").fetchone()
            return {
                "stop": stop[0] if stop else None,
                "episodes": [
                    dict(r) for r in db.execute("SELECT * FROM episodes ORDER BY stage,ordinal")
                ],
                "cost": usage_state(self.events(db)),
            }

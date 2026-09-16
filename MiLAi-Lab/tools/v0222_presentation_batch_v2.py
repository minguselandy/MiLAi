"""Prospective scoped presentation coordinator; no instance is created on import.

Only transaction/events/stop primitives are reused from the old coordinator.
No old admission method is inherited. Every operation explicitly owns a fresh
read scope; no success is retained across HTTP boundaries. This module does not
send HTTP. Artifact preparation and independent finish/gate wiring remain
separate integration work, not implied by admission or accounting success.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from v02_local_provider import append_event, read_events
from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import save
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import fingerprint
from v0221_http_batch import Batch as JournalPrimitives
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_batch import (
    BOUNDARY_BINDING,
    BOUNDARY_REVIEW_SHA,
    BOUNDARY_ROOT,
    CAPS,
    IDENTITY,
    PARENT_BINDING,
    PARENT_ROOT,
    PHASE_SECONDS,
    REVISION,
)
from v0222_presentation_batch import ROOT as PRESENTATION_ROOT
from v0222_presentation_batch import authorization_source as previous_authorization_source
from v0222_scoped_evidence import _guard, _strict_json, read_artifact, verify_manifest
from v0222_scoped_history import INVENTORY_PATH, INVENTORY_SHA256

ROOT = Path("/cra/memory/mx_memory/evidence/v0222-presentation-scoped/20260912-http-r1")
COORDINATOR_REVISION = "SCOPED_ADMISSION_V2"
PRESENTATION_BINDING = "bcc255fcbf4ab390f295b601cc353f98c23fb6800d8bfe54349bdb2325b197e1"


def authorization_source() -> dict:
    return {
        **previous_authorization_source(),
        "coordinator_revision": COORDINATOR_REVISION,
        "stopped_presentation_batch_not_resumed": True,
        "prior_passes_do_not_offset_new_matrix": True,
    }


def make_authorization(root: Path, *, issued: float, expires: float, history: dict) -> dict:
    """Pure intended contract builder, not a grant or a history verifier."""
    if root != ROOT:
        raise ProviderStop("ONE_FIXED_NEW_SCOPED_PRESENTATION_ROOT_REQUIRED")
    if (
        type(issued) not in (int, float)
        or type(expires) not in (int, float)
        or not math.isfinite(issued)
        or not math.isfinite(expires)
        or not 0 < expires - issued <= 36 * 3600
    ):
        raise ProviderStop("FINITE_36_HOUR_AUTHORIZATION_REQUIRED")
    return {
        "revision": REVISION,
        "coordinator_revision": COORDINATOR_REVISION,
        "root": str(ROOT),
        "batch_id": ROOT.name,
        "issued_unix": issued,
        "expires_unix": expires,
        "stages": ["PREP", "P3", "P4"],
        "path": "B",
        "historical_usage_settled": False,
        "reconciliation": None,
        "endpoint": ENDPOINT,
        "model": MODEL,
        "caps": dict(CAPS),
        "concurrency": 1,
        "raw_cap": None,
        "phase_wall_seconds": dict(PHASE_SECONDS),
        "episode_wall_seconds": 300,
        "http_wall_seconds": 60,
        "automatic_retry": False,
        "new_unknown_stops_all": True,
        "diagnostic_content_failures_continue": False,
        "first_acceptance_failure_stops_all": True,
        "historical": copy.deepcopy(history),
        "accepted_unknown": copy.deepcopy(history["unresolved_reservations"]),
        "parent_root": str(PARENT_ROOT),
        "parent_binding": PARENT_BINDING,
        "boundary_root": str(BOUNDARY_ROOT),
        "boundary_binding": BOUNDARY_BINDING,
        "boundary_result_review_sha256": BOUNDARY_REVIEW_SHA,
        "presentation_root": str(PRESENTATION_ROOT),
        "presentation_binding": PRESENTATION_BINDING,
        "history_inventory_sha256": INVENTORY_SHA256,
    }


class Batch:
    transaction = JournalPrimitives.transaction
    events = JournalPrimitives.events
    stop = JournalPrimitives.stop
    snapshot = JournalPrimitives.snapshot

    def __init__(self, root: Path, binding_sha: str):
        if root != ROOT or root.resolve() != root:
            raise ProviderStop("ONE_FIXED_CANONICAL_NEW_SCOPED_ROOT_REQUIRED")
        self.root, self.binding_sha = root, binding_sha
        self.path = root / "batch.sqlite"
        # Constructor validation is not a live admission or a claim.
        with AdmissionReadScope() as scope:
            self.binding = scope.read_json(root / "execution-binding.json", binding_sha)
            self.auth, self.plan = self._authorize("PREP", scope)
        self._time_check(self.auth)

    @staticmethod
    def _time_check(auth):
        if not auth["issued_unix"] <= time.time() < auth["expires_unix"]:
            raise ProviderStop("AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")

    def _authorize(self, stage: str, scope: AdmissionReadScope) -> tuple[dict, dict]:
        # Explicit import avoids any circular dependency on Batch in lineage.
        from v0222_presentation_lineage_v2 import verify_lineage

        with _guard(scope):
            binding = scope.read_json(self.root / "execution-binding.json", self.binding_sha)
            if set(binding) != {"authorization.json", "authorization-source.json", "manifest.json"}:
                raise ProviderStop("EXACT_EXECUTION_BINDING_REQUIRED")
            if fingerprint(binding) != fingerprint(self.binding):
                raise ProviderStop("IN_MEMORY_BINDING_DRIFT")
            auth = scope.read_json(self.root / "authorization.json", binding["authorization.json"])
            grant = scope.read_json(
                self.root / "authorization-source.json", binding["authorization-source.json"]
            )
            history = verify_lineage(scope)
            expected = make_authorization(
                self.root, issued=auth["issued_unix"], expires=auth["expires_unix"], history=history
            )
            if fingerprint(auth) != fingerprint(expected):
                raise ProviderStop("EXACT_SCOPED_AUTHORIZATION_AND_HISTORY_REQUIRED")
            if fingerprint(grant) != fingerprint(authorization_source()):
                raise ProviderStop("EXPLICIT_USER_SCOPE_SOURCE_REQUIRED")
            if stage not in auth["stages"]:
                raise ProviderStop("STAGE_NOT_AUTHORIZED")
            self._time_check(auth)
            manifest = verify_manifest(scope, self.root, binding["manifest.json"])
            plan = manifest["contract"]
            required = {
                "revision": REVISION,
                "coordinator_revision": COORDINATOR_REVISION,
                "selected_decoder": "D11",
                "selected_presentation": "B1",
                "parent_root": str(PARENT_ROOT),
                "parent_binding": PARENT_BINDING,
                "boundary_root": str(BOUNDARY_ROOT),
                "boundary_binding": BOUNDARY_BINDING,
                "presentation_root": str(PRESENTATION_ROOT),
                "presentation_binding": PRESENTATION_BINDING,
                "historical_paths": [row["path"] for row in history["sources"]],
                "http_identity": IDENTITY,
            }
            if any(fingerprint(plan.get(k)) != fingerprint(v) for k, v in required.items()):
                raise ProviderStop("FROZEN_SCOPED_PRESENTATION_CONTRACT_REQUIRED")
            if (hasattr(self, "plan") and fingerprint(plan) != fingerprint(self.plan)) or (
                hasattr(self, "auth") and fingerprint(auth) != fingerprint(self.auth)
            ):
                raise ProviderStop("IN_MEMORY_AUTHORIZATION_OR_PLAN_DRIFT")
            self._validate_plan(scope, plan)
            return auth, plan

    def _validate_plan(self, scope, plan):
        inventory = scope.read_json(INVENTORY_PATH, INVENTORY_SHA256)
        previous = []
        for root in (PARENT_ROOT, PRESENTATION_ROOT):
            path = root / "execution-binding.json"
            binding = scope.read_json(path, inventory["files"][str(path)])
            previous.append(
                scope.read_json(root / "manifest.json", binding["manifest.json"])["contract"]
            )
        old_scopes = {s["scope"] for old in previous for stage in CAPS for s in old[stage]}
        ids, scopes = [], []
        for stage, count in (("P3", 16), ("P4", 24)):
            if len(plan[stage]) != count or len(previous[-1][stage]) != count:
                raise ProviderStop("COMPLETE_ORIGINAL_16_PLUS_24_MATRIX_REQUIRED")
            for spec, old in zip(plan[stage], previous[-1][stage], strict=True):
                allowed = (
                    {"id", "scope", "initial_state_sha256"} if stage == "P4" else {"id", "scope"}
                )
                if (
                    not isinstance(spec.get("id"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", spec["id"])
                    or not isinstance(spec.get("scope"), str)
                    or not spec["scope"]
                    or spec["scope"] in old_scopes
                    or fingerprint({k: v for k, v in spec.items() if k not in allowed})
                    != fingerprint({k: v for k, v in old.items() if k not in allowed})
                ):
                    raise ProviderStop("ORIGINAL_MATRIX_AND_FRESH_SCOPES_REQUIRED")
                if stage == "P4" and (
                    type(spec.get("initial_state_sha256")) is not str
                    or not re.fullmatch(r"[a-f0-9]{64}", spec["initial_state_sha256"])
                    or any(
                        spec["initial_state_sha256"] == p[stage][old_index]["initial_state_sha256"]
                        for p in previous
                        for old_index in range(len(p[stage]))
                    )
                ):
                    raise ProviderStop("NEW_SCOPE_DERIVED_INITIAL_HASH_REQUIRED")
                ids.append(spec["id"])
                scopes.append(spec["scope"])
        if len(set(ids)) != 40 or len(set(scopes)) != 40:
            raise ProviderStop("GLOBALLY_UNIQUE_EPISODES_AND_SCOPES_REQUIRED")

    def spec(self, episode):
        for stage in CAPS:
            for spec in self.plan[stage]:
                if spec["id"] == episode:
                    return copy.deepcopy(spec)
        raise ProviderStop("EPISODE_OUTSIDE_FROZEN_PLAN")

    def authorize(self, stage="PREP"):
        with AdmissionReadScope() as scope:
            auth, _ = self._authorize(stage, scope)
        self._time_check(auth)
        return auth

    def initialize(self):
        self.authorize("PREP")
        save(self.root / "coordinator-created.json", {"binding_sha256": self.binding_sha})
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE episodes(id TEXT PRIMARY KEY,stage TEXT,ordinal INTEGER,
                    cap INTEGER,status TEXT,pid INTEGER,deadline REAL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY,event TEXT NOT NULL);
                CREATE TABLE artifacts(name TEXT PRIMARY KEY,path TEXT,sha256 TEXT,
                    dependencies TEXT NOT NULL);
                CREATE TABLE launches(stage TEXT PRIMARY KEY,pid INTEGER,started REAL);
                CREATE TABLE claims(episode TEXT PRIMARY KEY,pid INTEGER,
                    started REAL,deadline REAL);
            """)
            db.execute("INSERT INTO meta VALUES ('binding',?)", (self.binding_sha,))
            for stage in CAPS:
                for index, spec in enumerate(self.plan[stage]):
                    db.execute(
                        "INSERT INTO episodes VALUES (?,?,?,?, 'PENDING',NULL,NULL)",
                        (spec["id"], stage, index, 1 if stage == "P3" else 4),
                    )

    def launch_once(self, stage):
        if stage not in CAPS:
            raise ProviderStop("NON_GENERATION_STAGE")
        with self._operation(stage) as (db, scope, _state):
            self._ready(db, stage, scope)
            if db.execute("SELECT 1 FROM launches WHERE stage=?", (stage,)).fetchone():
                raise ProviderStop("STAGE_ALREADY_LAUNCHED_NO_RESTART")
            if db.execute("SELECT 1 FROM episodes WHERE status='RUNNING'").fetchone():
                raise ProviderStop("SINGLE_ACTIVE_EPISODE_ONLY")
            now = time.time()
            save(
                self.root / ("live-launch-" + stage + ".json"),
                {
                    "stage": stage,
                    "pid": os.getpid(),
                    "unix": now,
                    "binding_sha256": self.binding_sha,
                },
            )
            db.execute("INSERT INTO launches VALUES (?,?,?)", (stage, os.getpid(), now))
            db.execute(
                "INSERT INTO meta VALUES (?,?)",
                (
                    stage + "_deadline",
                    str(min(now + PHASE_SECONDS[stage], self.auth["expires_unix"])),
                ),
            )

    def claim(self, episode):
        stage = self.spec(episode)["stage"]
        with self._operation(stage) as (db, scope, _state):
            self._ready(db, stage, scope)
            launcher = db.execute("SELECT pid FROM launches WHERE stage=?", (stage,)).fetchone()
            if launcher is None:
                raise ProviderStop("STAGE_NOT_LAUNCHED")
            if (
                launcher[0] == os.getpid()
                or db.execute("SELECT 1 FROM launches WHERE pid=?", (os.getpid(),)).fetchone()
            ):
                raise ProviderStop("SEPARATE_COLD_WORKER_PROCESS_REQUIRED")
            if db.execute("SELECT 1 FROM episodes WHERE status='RUNNING'").fetchone():
                raise ProviderStop("SINGLE_ACTIVE_EPISODE_ONLY")
            if db.execute("SELECT 1 FROM episodes WHERE pid=?", (os.getpid(),)).fetchone():
                raise ProviderStop("FRESH_CLIENT_PROCESS_REQUIRED")
            row = db.execute(
                "SELECT * FROM episodes WHERE stage=? AND status!='PASS' ORDER BY ordinal", (stage,)
            ).fetchone()
            if row is None or row["id"] != episode or row["status"] != "PENDING":
                raise ProviderStop("NO_RESTART_OR_OUT_OF_ORDER_EPISODE")
            deadline = float(
                db.execute("SELECT value FROM meta WHERE key=?", (stage + "_deadline",)).fetchone()[
                    0
                ]
            )
            now = time.time()
            claimed_deadline = min(deadline, now + 300, self.auth["expires_unix"])
            save(
                self.claim_marker_path(episode),
                {
                    "episode": episode,
                    "pid": os.getpid(),
                    "started": now,
                    "deadline": claimed_deadline,
                    "binding_sha256": self.binding_sha,
                },
            )
            db.execute(
                "INSERT INTO claims VALUES (?,?,?,?)", (episode, os.getpid(), now, claimed_deadline)
            )
            db.execute(
                "UPDATE episodes SET status='RUNNING',pid=?,deadline=? WHERE id=?",
                (os.getpid(), claimed_deadline, episode),
            )

    def _artifact(self, db, name, scope):
        row = db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone()
        return self._artifact_row(db, row, scope)

    def _artifact_row(self, db, row, scope):
        with _guard(scope):
            return self._read_artifact_row(db, row, scope)

    def _read_artifact_row(self, db, row, scope):
        if row is None:
            raise ProviderStop("FROZEN_ARTIFACT_REQUIRED")
        dynamic = {self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")}
        dynamic.update(
            self._ledger(r[0]) for r in db.execute("SELECT id FROM episodes WHERE status!='PASS'")
        )

        def reject_dynamic(paths):
            if any(Path(path) in dynamic for path in paths):
                raise ProviderStop("DYNAMIC_JOURNAL_CANNOT_BE_PINNED_AS_ARTIFACT")

        reject_dynamic([row["path"]])
        dependencies = _strict_json(row["dependencies"])
        if not isinstance(dependencies, dict):
            raise ProviderStop("ARTIFACT_DEPENDENCIES_MAPPING_REQUIRED")
        reject_dynamic(dependencies)
        value = scope.read_json(Path(row["path"]), row["sha256"])
        if isinstance(value, dict) and isinstance(value.get("files"), dict):
            reject_dynamic(value["files"])
        return read_artifact(scope, row)

    def _ready(self, db, stage, scope):
        for name, status in (
            ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
            ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
            (stage + "_preflight", "G_PREFLIGHT_PASS"),
        ):
            if self._artifact(db, name, scope).get("status") != status:
                raise ProviderStop("STAGE_GATE_STATUS_NOT_MET")
        self._artifact(db, stage + "_references", scope)
        if stage == "P4":
            self._artifact(db, "P4_resolved_specs", scope)
            gate = self._artifact(db, "P3_gate", scope)
            passed = db.execute(
                "SELECT COUNT(*) FROM episodes WHERE stage='P3' AND status='PASS'"
            ).fetchone()[0]
            if gate.get("status") != "G_P3_PASS" or passed != 16:
                raise ProviderStop("P4_REQUIRES_NEW_COMPLETE_P3_16_PASS")

    def _check_journal(self, db, scope, *, inflight=None):
        if db.execute("SELECT 1 FROM meta WHERE key='stop'").fetchone():
            raise ProviderStop("BATCH_STOPPED_NO_RETRY")
        marker = json.loads((self.root / "coordinator-created.json").read_bytes())
        if marker != {"binding_sha256": self.binding_sha}:
            raise ProviderStop("COORDINATOR_INITIALIZATION_MARKER_DRIFT")
        rows = [dict(r) for r in db.execute("SELECT * FROM episodes ORDER BY stage,ordinal")]
        if [(r["id"], r["stage"], r["ordinal"], r["cap"]) for r in rows] != [
            (s["id"], stage, i, 1 if stage == "P3" else 4)
            for stage in CAPS
            for i, s in enumerate(self.plan[stage])
        ]:
            raise ProviderStop("COORDINATOR_PLAN_OR_CAP_DRIFT")
        self._check_claims(db, rows)
        events = self.events(db)
        state = usage_state(events)
        reservations = [e for e in events if e["event"] == "RESERVED"]
        for row in rows:
            if sum(e.get("session") == row["id"] for e in reservations) > row["cap"]:
                raise ProviderStop("COORDINATOR_EPISODE_REQUEST_CAP_EXCEEDED")
        for stage in CAPS:
            stage_ids = {r["id"] for r in rows if r["stage"] == stage}
            if sum(e.get("session") in stage_ids for e in reservations) > CAPS[stage]:
                raise ProviderStop("COORDINATOR_STAGE_REQUEST_CAP_EXCEEDED")
        if any(
            type(e.get("output_cap")) is not int
            or e["output_cap"] != 4096
            or e.get("cumulative_raw_cap") is not None
            or e["raw_upper_bound"] > 65536
            for e in reservations
        ):
            raise ProviderStop("COORDINATOR_FROZEN_REQUEST_CAP_DRIFT")
        pending = state["unresolved_reservations"]
        own = (
            inflight is not None
            and len(pending) == 1
            and not state["violations"]
            and pending[0]["state"] in {"RESERVED", "DISPATCH_STARTED"}
            and pending[0]["reservation"].get("session") == inflight
        )
        if (not state["new_generation_allowed"] and not own) or (inflight is not None and not own):
            raise ProviderStop("NEW_BATCH_UNKNOWN_OR_INVALID_OWN_RESERVATION")
        self._mirrors(db)
        for row in db.execute("SELECT * FROM artifacts"):
            self._artifact_row(db, row, scope)
        for launch in db.execute("SELECT * FROM launches ORDER BY stage"):
            stage = launch["stage"]
            if stage not in CAPS:
                raise ProviderStop("UNKNOWN_STAGE_LAUNCH")
            self._ready(db, stage, scope)
            actual = json.loads((self.root / ("live-launch-" + stage + ".json")).read_bytes())
            expected = {
                "stage": stage,
                "pid": launch["pid"],
                "unix": launch["started"],
                "binding_sha256": self.binding_sha,
            }
            deadline = db.execute(
                "SELECT value FROM meta WHERE key=?", (stage + "_deadline",)
            ).fetchone()
            if fingerprint(actual) != fingerprint(expected):
                raise ProviderStop("LAUNCH_MARKER_DRIFT")
            if deadline is None or float(deadline[0]) != min(
                launch["started"] + PHASE_SECONDS[stage], self.auth["expires_unix"]
            ):
                raise ProviderStop("PHASE_DEADLINE_DRIFT")
        return state

    def _check_claims(self, db, rows):
        claims = {r["episode"]: dict(r) for r in db.execute("SELECT * FROM claims")}
        claimed = {r["id"] for r in rows if r["pid"] is not None}
        if set(claims) != claimed:
            raise ProviderStop("EXACT_EPISODE_CLAIM_JOURNAL_REQUIRED")
        for row in rows:
            if row["status"] == "PENDING":
                if row["pid"] is not None or row["deadline"] is not None:
                    raise ProviderStop("PENDING_EPISODE_CANNOT_HAVE_OWNER_OR_DEADLINE")
                continue
            if row["status"] not in {"RUNNING", "PASS", "FAIL"} or row["id"] not in claims:
                raise ProviderStop("INVALID_EPISODE_STATUS_OR_CLAIM")
            claim = claims[row["id"]]
            launch = db.execute("SELECT * FROM launches WHERE stage=?", (row["stage"],)).fetchone()
            if launch is None or any(
                type(claim[k]) not in (int, float) or not math.isfinite(claim[k])
                for k in ("started", "deadline")
            ):
                raise ProviderStop("FINITE_CLAIM_AND_STAGE_LAUNCH_REQUIRED")
            expected_deadline = min(
                launch["started"] + PHASE_SECONDS[row["stage"]],
                claim["started"] + 300,
                self.auth["expires_unix"],
            )
            if (
                claim["pid"] != row["pid"]
                or claim["pid"] == launch["pid"]
                or claim["started"] < launch["started"]
                or row["deadline"] != expected_deadline
                or claim["deadline"] != expected_deadline
            ):
                raise ProviderStop("CLAIM_OWNER_OR_EPISODE_DEADLINE_DRIFT")
            marker = json.loads(self.claim_marker_path(row["id"]).read_bytes())
            if fingerprint(marker) != fingerprint({**claim, "binding_sha256": self.binding_sha}):
                raise ProviderStop("CLAIM_MARKER_DRIFT")

    def claim_marker_path(self, episode):
        # Reuse the pure canonical-ID/plan check, without creating any path.
        # Session owns creation of episodes/<id>; claim evidence must not make
        # that directory exist before the unchanged fresh-session guard runs.
        self._ledger(episode)
        return self.root / "claims" / (episode + ".json")

    def _ledger(self, episode):
        if type(episode) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", episode):
            raise ProviderStop("CANONICAL_EPISODE_ID_REQUIRED")
        self.spec(episode)
        return self.root / "episodes" / episode / "provider/provider-ledger-v2.jsonl"

    def _mirrors(self, db):
        # Mutable journals are read anew, never pinned with a locally minted hash.
        mirrored = []
        for stage in CAPS:
            for spec in self.plan[stage]:
                events = read_events(self._ledger(spec["id"]))
                usage_state(events)
                if any(e.get("session") != spec["id"] for e in events if e["event"] == "RESERVED"):
                    raise ProviderStop("EPISODE_LEDGER_REQUEST_OWNERSHIP_DRIFT")
                mirrored.extend(events)
        if sorted(map(fingerprint, self.events(db))) != sorted(map(fingerprint, mirrored)):
            raise ProviderStop("CENTRAL_AND_EPISODE_LEDGER_DIVERGED")

    def _owned(self, db, episode, *, settlement=False):
        row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
        statuses = {"RUNNING", "FAIL"} if settlement else {"RUNNING"}
        if row is None or row["status"] not in statuses or row["pid"] != os.getpid():
            raise ProviderStop("EPISODE_NOT_OWNED_BY_THIS_PROCESS")
        return row

    @contextmanager
    def _operation(self, stage, *, episode=None, inflight=False):
        try:
            with self.transaction() as db:
                with AdmissionReadScope() as scope:
                    auth, _ = self._authorize(stage, scope)
                    state = self._check_journal(db, scope, inflight=episode if inflight else None)
                    if episode is not None:
                        self._owned(db, episode)
                    yield db, scope, state
                # Close may consume the last available seconds; check after it.
                self._time_check(auth)
                if db.execute("SELECT 1 FROM meta WHERE key='stop'").fetchone():
                    raise ProviderStop("BATCH_STOPPED_NO_RETRY")
                if episode is not None and time.time() >= self._owned(db, episode)["deadline"]:
                    raise ProviderStop("EPISODE_DEADLINE")
                # claim starts as PENDING, so there was no owned episode before
                # yield. Its newly created deadline must also survive close.
                for running in db.execute("SELECT deadline FROM episodes WHERE status='RUNNING'"):
                    if (
                        type(running[0]) not in (int, float)
                        or not math.isfinite(running[0])
                        or time.time() >= running[0]
                    ):
                        raise ProviderStop("EPISODE_DEADLINE")
                deadline = db.execute(
                    "SELECT value FROM meta WHERE key=?", (stage + "_deadline",)
                ).fetchone()
                if deadline is not None and time.time() >= float(deadline[0]):
                    raise ProviderStop("BATCH_PHASE_DEADLINE")
        except BaseException as exc:
            # Both the scope and original SQL transaction have exited first.
            try:
                self.stop(str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__)
            except BaseException as stop_error:
                exc.add_note("SECONDARY_STOP_FAILURE: " + type(stop_error).__name__)
            raise

    def admit(self, episode):
        with self._operation(self.spec(episode)["stage"], episode=episode) as (db, _, _state):
            row = dict(self._owned(db, episode))
        return row

    def http_admit(self, episode, *, inflight=False):
        with self._operation(self.spec(episode)["stage"], episode=episode, inflight=inflight) as (
            db,
            _,
            _state,
        ):
            row = dict(self._owned(db, episode))
        return row

    def reserve_request(self, episode, event):
        stage = self.spec(episode)["stage"]
        with self._operation(stage, episode=episode) as (db, _, _state):
            if (
                event.get("event") != "RESERVED"
                or event.get("session") != episode
                or type(event.get("output_cap")) is not int
                or event["output_cap"] != 4096
                or event.get("cumulative_raw_cap") is not None
                or type(event.get("raw_upper_bound")) is not int
                or event["raw_upper_bound"] > 65536
            ):
                raise ProviderStop("FROZEN_REQUEST_RESERVATION_REQUIRED")
            row, events = self._owned(db, episode), self.events(db)
            reservations = [e for e in events if e["event"] == "RESERVED"]
            stage_ids = {s["id"] for s in self.plan[stage]}
            if (
                sum(e["session"] == episode for e in reservations) >= row["cap"]
                or sum(e["session"] in stage_ids for e in reservations) >= CAPS[stage]
            ):
                raise ProviderStop("BATCH_REQUEST_COUNT_LIMIT")
            usage_state([*events, event])
            self._append_mirrored(db, episode, event)

    def _append_mirrored(self, db, episode, event):
        # Filesystem and SQL cannot be one atomic transaction. Any failure stops;
        # retained divergence is evidence and never repaired by blind replay.
        db.execute("INSERT INTO events(event) VALUES (?)", (json.dumps(event),))
        append_event(self._ledger(episode), event)

    def dispatch_started(self, episode, request_id):
        """Durable FSM marker; a separate fresh http_admit is still required."""
        with self._operation(self.spec(episode)["stage"], episode=episode, inflight=True) as (
            db,
            _,
            _state,
        ):
            events = self.events(db)
            event = {"event": "DISPATCH_STARTED", "request_id": request_id}
            reservation = next(
                (e for e in events if e["event"] == "RESERVED" and e["request_id"] == request_id),
                None,
            )
            if reservation is None or reservation.get("session") != episode:
                raise ProviderStop("EVENT_REQUEST_NOT_OWNED")
            usage_state([*events, event])
            self._append_mirrored(db, episode, event)

    def settle_event(self, episode, event):
        """Record only an owned request's response/usage, even after stop/expiry.

        DISPATCH_STARTED is deliberately excluded: stopping can never create a
        new dispatch. UNKNOWN->KNOWN is not a valid old FSM transition and is
        not silently reconciled here. No new HTTP/admission/output is returned.
        """
        try:
            if event.get("event") not in {
                "RESPONSE_RECEIVED",
                "USAGE_KNOWN",
                "USAGE_UNKNOWN",
                "BOUND_VIOLATION",
            }:
                raise ProviderStop("SETTLEMENT_EVENT_ONLY")
            with self.transaction() as db:
                self._owned(db, episode, settlement=True)
                self._mirrors(db)
                events = self.events(db)
                reservation = next(
                    (
                        e
                        for e in events
                        if e["event"] == "RESERVED" and e["request_id"] == event.get("request_id")
                    ),
                    None,
                )
                if reservation is None or reservation.get("session") != episode:
                    raise ProviderStop("EVENT_REQUEST_NOT_OWNED")
                state = usage_state([*events, event])
                self._append_mirrored(db, episode, event)
                if event["event"] == "USAGE_KNOWN":
                    usage = event["usage"]
                    if (
                        usage["prompt_tokens"] != reservation["prompt_tokens"]
                        or usage["completion_tokens"] > reservation["output_cap"]
                        or usage["total_tokens"] > reservation["raw_upper_bound"]
                    ):
                        violation = {
                            "event": "BOUND_VIOLATION",
                            "request_id": event["request_id"],
                            "usage": usage,
                        }
                        state = usage_state([*events, event, violation])
                        self._append_mirrored(db, episode, violation)
                if state["violations"] or event["event"] == "USAGE_UNKNOWN":
                    reason = "BOUND_VIOLATION" if state["violations"] else "USAGE_UNKNOWN"
                    db.execute("INSERT OR IGNORE INTO meta VALUES ('stop',?)", (reason,))
                    db.execute("UPDATE episodes SET status='FAIL' WHERE status='RUNNING'")
        except BaseException as exc:
            try:
                self.stop(str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__)
            except BaseException as stop_error:
                exc.add_note("SECONDARY_STOP_FAILURE: " + type(stop_error).__name__)
            raise

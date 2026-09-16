"""Bounded D1/D2 accounting; execution completion is never a task/gold verdict.

The original live Transport uses this small coordinator directly. R04 static
scope, fresh history/current inputs and R02 primary-preserving transactions are
retained. No model, instance, Product or World is created on import.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path

from v02_local_provider import read_events
from v0218_world import World
from v0220_evidence import save
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import fingerprint
from v0221_http_batch import Batch as JournalPrimitives
from v0222_presentation_batch_v2 import IDENTITY
from v0222_presentation_batch_v2 import Batch as OriginalCore
from v0222_scoped_evidence import _guard, verify_manifest
from v0223_transaction_primary_fix import corrected_transaction
from v0224_verified_digest_batch import StaticAuthority
from v0224_verified_digest_lineage import verify_lineage_r03
from v0224_verified_digest_scope import BundleReadScope

ROOTS = {
    stage: Path("/cra/memory/mx_memory/evidence/v0224/20260913-task-completion-v1")
    / ("taskv1-" + stage.lower())
    for stage in ("D1", "D2")
}
REVISION = "V0224_D1_D2_TASK_ACCOUNTING_01"
BC_STATUS = "G_BC_COMPLETE_LIVE_PASS"


def require(value, reason):
    if not value:
        raise ProviderStop(reason)


def validate_plan(plan, stage):
    require(stage in ROOTS, "EXACT_D1_D2_STAGE_REQUIRED")
    require(
        type(plan) is dict and set(plan) == {"revision", "http_identity", stage},
        "EXACT_TASK_STAGE_PLAN_REQUIRED",
    )
    require(
        plan["revision"] == REVISION and plan["http_identity"] == IDENTITY,
        "EXACT_TASK_HTTP_IDENTITY_REQUIRED",
    )
    specs = plan[stage]
    require(
        type(specs) is list and 0 < len(specs) <= (16 if stage == "D1" else 32),
        "BOUNDED_COMPLETE_TASK_MATRIX_REQUIRED",
    )
    common = {
        "id",
        "stage",
        "scope",
        "profile",
        "arm",
        "max_generations",
        "public_source",
        "initial_state_sha256",
        "root",
        "variant",
    }
    for spec in specs:
        required = common | ({"intent", "event"} if stage == "D1" else set())
        require(
            type(spec) is dict and set(spec) == required,
            "ACTOR_PLAN_FIELDS_ONLY_NO_PRIVATE_CHECKER",
        )
        require(
            spec["stage"] == stage
            and type(spec["id"]) is str
            and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", spec["id"])
            and type(spec["scope"]) is str
            and bool(spec["scope"]),
            "EXACT_TASK_ID_SCOPE_REQUIRED",
        )
        require(
            type(spec["max_generations"]) is int
            and spec["max_generations"] == (5 if stage == "D1" else 16),
            "FIXED_TASK_GENERATION_CAP_REQUIRED",
        )
        require(
            (spec["profile"] == "RECOVERY_ORACLE" and spec["arm"] == "ORACLE")
            if stage == "D1"
            else (spec["profile"] == "NATURAL_NO_CARRY" and spec["arm"] in {"N0-exec", "R0-exec"}),
            "TASK_PROFILE_ORACLE_ISOLATION",
        )
        source = spec["public_source"]
        require(
            type(source) is dict and set(source) == {"path", "sha256"},
            "EXACT_PUBLIC_SOURCE_PIN_REQUIRED",
        )
        require(
            type(spec["initial_state_sha256"]) is str
            and re.fullmatch("[a-f0-9]{64}", spec["initial_state_sha256"]),
            "EXACT_INITIAL_WORLD_HASH_REQUIRED",
        )
    require(
        len({s["id"] for s in specs}) == len(specs) == len({s["scope"] for s in specs}),
        "UNIQUE_COLD_EPISODE_SCOPE_REQUIRED",
    )


class Batch(JournalPrimitives):
    transaction = corrected_transaction
    _owned = OriginalCore._owned
    _append_mirrored = OriginalCore._append_mirrored
    dispatch_started = OriginalCore.dispatch_started
    settle_event = OriginalCore.settle_event

    def __init__(self, root, contract_sha256, *, static_authority):
        require(type(static_authority) is StaticAuthority, "EXACT_R04_STATIC_AUTHORITY_REQUIRED")
        require(root in ROOTS.values() and root.resolve() == root, "FIXED_FRESH_TASK_ROOT_REQUIRED")
        self.root, self.path, self.binding_sha = root, root / "batch.sqlite", contract_sha256
        self.stage = next(s for s, p in ROOTS.items() if p == root)
        self._static_authority = static_authority
        self._owner = (os.getpid(), threading.get_ident())
        self._contract = None
        with self._new_scope() as scope:
            self.auth, self.plan = self._authorize("PREP", scope)

    def _new_scope(self):
        return BundleReadScope(**self._static_authority.scope_arguments())

    def _authorize(self, stage, scope):
        require(self._owner == (os.getpid(), threading.get_ident()), "TASK_BATCH_OWNER_DRIFT")
        with _guard(scope):
            contract = scope.read_json(self.root / "contract.json", self.binding_sha)
            require(
                type(contract) is dict
                and set(contract)
                == {
                    "status",
                    "root",
                    "stage",
                    "plan",
                    "authorization",
                    "manifest_sha256",
                    "bc_certificate",
                    "static_authority",
                    "control_files",
                },
                "EXACT_EXTERNAL_TASK_CONTRACT_REQUIRED",
            )
            require(
                contract["status"] == "D_TASK_ACTOR_CONTRACT_FROZEN"
                and contract["root"] == str(self.root)
                and contract["stage"] == self.stage,
                "FIXED_TASK_CONTRACT_REQUIRED",
            )
            require(
                contract["static_authority"] == self._static_authority.contract_value(),
                "TASK_AUTHORITY_DRIFT",
            )
            if self._contract is not None:
                require(contract == self._contract, "IN_MEMORY_TASK_CONTRACT_DRIFT")
            plan = contract["plan"]
            validate_plan(plan, self.stage)
            require(stage in ("PREP", self.stage), "TASK_STAGE_NOT_AUTHORIZED")
            certificate = contract["bc_certificate"]
            require(
                type(certificate) is dict and set(certificate) == {"path", "sha256"},
                "EXTERNAL_BC_CERTIFICATE_REQUIRED",
            )
            with scope.physical_reads():
                cert = scope.read_json(Path(certificate["path"]), certificate["sha256"])
                require(
                    cert.get("status") == BC_STATUS
                    and cert.get("blocking_findings") == []
                    and bool(cert.get("files")),
                    "COMPLETE_ACTUAL_BC_CERTIFICATE_REQUIRED",
                )
                for path, digest in cert["files"].items():
                    scope.read_bytes(Path(path), digest)
                require(
                    type(contract["control_files"]) is dict and bool(contract["control_files"]),
                    "PUBLIC_EXECUTION_CONTROL_PINS_REQUIRED",
                )
                for path, digest in contract["control_files"].items():
                    scope.read_bytes(Path(path), digest)
                for spec in plan[self.stage]:
                    source = spec["public_source"]
                    scope.read_json(Path(source["path"]), source["sha256"])
            history = verify_lineage_r03(scope)
            auth = contract["authorization"]
            issued, expires = auth.get("issued_unix"), auth.get("expires_unix")
            require(
                all(type(t) in (int, float) and math.isfinite(t) for t in (issued, expires))
                and 0 < expires - issued <= 36 * 3600
                and issued <= time.time() < expires,
                "FINITE_CURRENT_TASK_AUTHORIZATION_REQUIRED",
            )
            expected = {
                "revision": REVISION,
                "root": str(self.root),
                "stages": ["PREP", self.stage],
                "issued_unix": issued,
                "expires_unix": expires,
                "cap": sum(s["max_generations"] for s in plan[self.stage]),
                "concurrency": 1,
                "episode_wall_seconds": 900 if self.stage == "D1" else 3600,
                "http_wall_seconds": 60,
                "auxiliary_http_seconds": 5,
                "output_cap": 4096,
                "raw_upper_bound": 65536,
                "automatic_retry": False,
                "new_unknown_stops_all": True,
                "device_calls_allowed": False,
                "historical": history,
                "accepted_unknown": history["unresolved_reservations"],
            }
            require(auth == expected, "EXACT_CURRENT_TASK_AUTHORIZATION_AND_HISTORY_REQUIRED")
            manifest = verify_manifest(scope, self.root, contract["manifest_sha256"])
            require(manifest["contract"] == plan, "MANIFEST_TASK_PLAN_DRIFT")
            if self._contract is None:
                self._contract = copy.deepcopy(contract)
            return copy.deepcopy(auth), copy.deepcopy(plan)

    def authorize(self, stage="PREP"):
        with self._new_scope() as scope:
            auth, _ = self._authorize(stage, scope)
        return auth

    def spec(self, episode):
        for spec in self.plan[self.stage]:
            if spec["id"] == episode:
                return copy.deepcopy(spec)
        raise ProviderStop("EPISODE_OUTSIDE_FROZEN_TASK_PLAN")

    def _ledger(self, episode):
        self.spec(episode)
        return self.root / "episodes" / episode / "provider/provider-ledger-v2.jsonl"

    def _mirrors(self, db):
        mirrored = []
        for spec in self.plan[self.stage]:
            local = read_events(self._ledger(spec["id"]))
            usage_state(local)
            require(
                all(e.get("session") == spec["id"] for e in local if e["event"] == "RESERVED"),
                "LOCAL_EVENT_OWNER_DRIFT",
            )
            mirrored.extend(local)
        require(
            sorted(map(fingerprint, mirrored)) == sorted(map(fingerprint, self.events(db))),
            "CENTRAL_AND_EPISODE_LEDGER_DIVERGED",
        )

    def _check_journal(self, db, *, inflight=None):
        require(
            not db.execute("SELECT 1 FROM meta WHERE key='stop'").fetchone(),
            "BATCH_STOPPED_NO_RETRY",
        )
        rows = [dict(r) for r in db.execute("SELECT * FROM episodes ORDER BY ordinal")]
        require(
            [(r["id"], r["stage"], r["ordinal"], r["cap"]) for r in rows]
            == [
                (s["id"], self.stage, i, s["max_generations"])
                for i, s in enumerate(self.plan[self.stage])
            ],
            "TASK_PLAN_OR_CAP_DRIFT",
        )
        require(sum(r["status"] == "RUNNING" for r in rows) <= 1, "SINGLE_ACTIVE_TASK_REQUIRED")
        claims = {r["episode"]: dict(r) for r in db.execute("SELECT * FROM claims")}
        launch = db.execute("SELECT * FROM launches").fetchall()
        require(
            len(launch) <= 1 and (not launch or launch[0]["stage"] == self.stage),
            "EXACT_SINGLE_TASK_LAUNCH_REQUIRED",
        )
        require(
            set(claims) == {r["id"] for r in rows if r["pid"] is not None},
            "EXACT_TASK_CLAIMS_REQUIRED",
        )
        require(
            len({r["pid"] for r in claims.values()}) == len(claims),
            "DISTINCT_COLD_TASK_PIDS_REQUIRED",
        )
        for row in rows:
            if row["status"] == "PENDING":
                require(
                    row["pid"] is None and row["deadline"] is None, "PENDING_TASK_CANNOT_HAVE_OWNER"
                )
                continue
            require(
                row["status"] in {"RUNNING", "EXECUTION_COMPLETE", "FAIL"}
                and row["id"] in claims
                and launch,
                "TASK_STATUS_OR_CLAIM_DRIFT",
            )
            claim = claims[row["id"]]
            parent = launch[0]
            require(
                type(claim["pid"]) is int
                and claim["pid"] > 0
                and row["pid"] == claim["pid"] != parent["pid"]
                and parent["started"] <= claim["started"]
                and claim["deadline"]
                == row["deadline"]
                == min(
                    claim["started"] + self.auth["episode_wall_seconds"], self.auth["expires_unix"]
                ),
                "TASK_OWNER_OR_DEADLINE_DRIFT",
            )
            require(
                json.loads((self.root / "claims" / (row["id"] + ".json")).read_bytes())
                == {**claim, "binding_sha256": self.binding_sha},
                "TASK_CLAIM_MARKER_DRIFT",
            )
        if launch:
            require(
                json.loads((self.root / "launch.json").read_bytes())
                == {**dict(launch[0]), "binding_sha256": self.binding_sha},
                "TASK_LAUNCH_MARKER_DRIFT",
            )
        self._mirrors(db)
        events = self.events(db)
        state = usage_state(events)
        reservations = [e for e in events if e["event"] == "RESERVED"]
        require(
            len(reservations) <= self.auth["cap"]
            and all(
                sum(e.get("session") == r["id"] for e in reservations) <= r["cap"] for r in rows
            ),
            "TASK_REQUEST_CAP_EXCEEDED",
        )
        require(
            all(
                e.get("session") in {s["id"] for s in self.plan[self.stage]}
                and type(e.get("output_cap")) is int
                and e["output_cap"] == 4096
                and e.get("cumulative_raw_cap") is None
                and type(e.get("raw_upper_bound")) is int
                and e["raw_upper_bound"] <= 65536
                for e in reservations
            ),
            "FROZEN_TASK_RESERVATION_DRIFT",
        )
        pending = state["unresolved_reservations"]
        own = (
            inflight is not None
            and len(pending) == 1
            and not state["violations"]
            and pending[0]["state"] in {"RESERVED", "DISPATCH_STARTED"}
            and pending[0]["reservation"].get("session") == inflight
        )
        require(
            (state["new_generation_allowed"] or own) and (inflight is None or own),
            "NEW_UNKNOWN_OR_UNOWNED_INFLIGHT_REQUEST",
        )
        return state

    @contextmanager
    def _operation(self, stage, *, episode=None, inflight=False):
        try:
            with self.transaction() as db:
                with self._new_scope() as scope:
                    auth, _ = self._authorize(stage, scope)
                    state = self._check_journal(db, inflight=episode if inflight else None)
                    if episode is not None:
                        require(
                            time.time() < self._owned(db, episode)["deadline"],
                            "TASK_EPISODE_DEADLINE",
                        )
                    closing_deadlines = [
                        r[0]
                        for r in db.execute("SELECT deadline FROM episodes WHERE status='RUNNING'")
                    ]
                    yield db, scope, state
                require(
                    time.time() < auth["expires_unix"], "TASK_AUTHORIZATION_EXPIRED_DURING_SCOPE"
                )
                for deadline in closing_deadlines:
                    require(time.time() < deadline, "TASK_EPISODE_DEADLINE_DURING_SCOPE")
                for row in db.execute("SELECT deadline FROM episodes WHERE status='RUNNING'"):
                    require(time.time() < row["deadline"], "TASK_EPISODE_DEADLINE_DURING_SCOPE")
        except BaseException as primary:
            try:
                self.stop(
                    str(primary) if isinstance(primary, ProviderStop) else type(primary).__name__
                )
            except BaseException as secondary:
                primary.add_note("SECONDARY_STOP_FAILURE: " + repr(secondary))
            raise

    def initialize(self):
        self.authorize("PREP")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with sqlite3.connect(self.path) as db:
            db.executescript("""PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
                CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE episodes(id TEXT PRIMARY KEY,stage TEXT,ordinal INTEGER,
                    cap INTEGER,status TEXT,pid INTEGER,deadline REAL);
                CREATE TABLE claims(episode TEXT PRIMARY KEY,pid INTEGER,
                    started REAL,deadline REAL);
                CREATE TABLE launches(stage TEXT PRIMARY KEY,pid INTEGER,started REAL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY,event TEXT NOT NULL);""")
            db.execute("INSERT INTO meta VALUES ('binding',?)", (self.binding_sha,))
            db.executemany(
                "INSERT INTO episodes VALUES(?,?,?,?,'PENDING',NULL,NULL)",
                [
                    (s["id"], self.stage, i, s["max_generations"])
                    for i, s in enumerate(self.plan[self.stage])
                ],
            )

    def launch_once(self, stage):
        require(stage == self.stage, "TASK_STAGE_REQUIRED")
        with self._operation(stage) as (db, _, _state):
            require(not db.execute("SELECT 1 FROM launches").fetchone(), "NO_TASK_STAGE_RELAUNCH")
            row = {"stage": stage, "pid": os.getpid(), "started": time.time()}
            save(self.root / "launch.json", {**row, "binding_sha256": self.binding_sha})
            db.execute("INSERT INTO launches VALUES(:stage,:pid,:started)", row)

    def claim(self, episode):
        with self._operation(self.stage) as (db, _, _state):
            require(
                not db.execute("SELECT 1 FROM episodes WHERE status='RUNNING'").fetchone(),
                "SINGLE_ACTIVE_TASK_REQUIRED",
            )
            parent = db.execute("SELECT * FROM launches").fetchone()
            row = db.execute(
                "SELECT * FROM episodes WHERE status!='EXECUTION_COMPLETE' ORDER BY ordinal"
            ).fetchone()
            require(
                parent is not None
                and parent["pid"] != os.getpid()
                and row is not None
                and row["id"] == episode
                and row["status"] == "PENDING",
                "COLD_ORDERED_TASK_CLAIM_REQUIRED",
            )
            started = time.time()
            claim = {
                "episode": episode,
                "pid": os.getpid(),
                "started": started,
                "deadline": min(
                    started + self.auth["episode_wall_seconds"], self.auth["expires_unix"]
                ),
            }
            save(
                self.root / "claims" / (episode + ".json"),
                {**claim, "binding_sha256": self.binding_sha},
            )
            db.execute("INSERT INTO claims VALUES(:episode,:pid,:started,:deadline)", claim)
            db.execute(
                "UPDATE episodes SET status='RUNNING',pid=:pid,deadline=:deadline "
                "WHERE id=:episode",
                claim,
            )

    admit = OriginalCore.admit
    http_admit = OriginalCore.http_admit

    def reserve_request(self, episode, event):
        with self._operation(self.stage, episode=episode) as (db, _, _state):
            require(
                event.get("event") == "RESERVED"
                and event.get("session") == episode
                and type(event.get("output_cap")) is int
                and event["output_cap"] == 4096
                and event.get("cumulative_raw_cap") is None
                and type(event.get("raw_upper_bound")) is int
                and event["raw_upper_bound"] <= 65536,
                "FROZEN_REQUEST_RESERVATION_REQUIRED",
            )
            events = self.events(db)
            reserved = [e for e in events if e["event"] == "RESERVED"]
            require(
                len(reserved) < self.auth["cap"]
                and sum(e["session"] == episode for e in reserved)
                < self._owned(db, episode)["cap"],
                "TASK_REQUEST_CAP_EXCEEDED",
            )
            usage_state([*events, event])
            self._append_mirrored(db, episode, event)

    def finish(self, episode, exit_record_path, exit_record_sha256):
        with self._operation(self.stage) as (db, scope, _state):
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
            parent = db.execute("SELECT * FROM launches").fetchone()
            require(
                row is not None
                and row["status"] == "RUNNING"
                and parent["pid"] == os.getpid()
                and row["pid"] != os.getpid(),
                "PARENT_OWNED_TASK_FINISH_REQUIRED",
            )
            require(
                Path(exit_record_path) == self.root / "exits" / (episode + ".json"),
                "EXACT_COLD_EXIT_PATH_REQUIRED",
            )
            with scope.physical_reads():
                exit_record = scope.read_json(Path(exit_record_path), exit_record_sha256)
            require(
                exit_record.get("pid") == row["pid"]
                and exit_record.get("parent_pid") == os.getpid()
                and type(exit_record.get("returncode")) is int
                and exit_record["returncode"] == 0
                and exit_record.get("timed_out") is False,
                "ACTUAL_COLD_TASK_EXIT_REQUIRED",
            )
            try:
                os.kill(row["pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise ProviderStop("TASK_CHILD_MUST_EXIT_BEFORE_PARENT_FINISH")
            events = self.events(db)
            ids = {
                e["request_id"]
                for e in events
                if e["event"] == "RESERVED" and e.get("session") == episode
            }
            cost = usage_state([e for e in events if e["request_id"] in ids])
            require(
                cost["new_generation_allowed"] and 0 < cost["requests"] <= row["cap"],
                "COMPLETE_KNOWN_TASK_USAGE_REQUIRED",
            )
            # Host's result is execution evidence, never an oracle/scorer PASS.
            result_path = self.root / "episodes" / episode / "worker-result.json"
            raw = result_path.read_bytes()
            result = scope.read_json(result_path, hashlib.sha256(raw).hexdigest())
            require(
                result.get("pid") == row["pid"]
                and result.get("unresolved_operations") == []
                and not result.get("close_exception_type")
                and result.get("execution_status") == "EXECUTION_COMPLETE",
                "CLEAN_TASK_HOST_COMPLETION_REQUIRED",
            )
            require(time.time() < row["deadline"], "TASK_EPISODE_DEADLINE")
            require(
                type(result.get("files")) is dict and bool(result["files"]),
                "HOST_EXECUTION_EVIDENCE_FILES_REQUIRED",
            )
            for name, expected in result["files"].items():
                path = Path(name)
                require(
                    path.is_relative_to(self.root / "episodes" / episode)
                    or path == self.root / "worlds" / (episode + ".sqlite"),
                    "OWN_TASK_EVIDENCE_ONLY",
                )
                with scope.physical_reads():
                    scope.read_bytes(path, expected)
            world_path = self.root / "worlds" / (episode + ".sqlite")
            require(
                world_path.is_file() and world_path.resolve() == world_path,
                "EXACT_EXISTING_TASK_WORLD_REQUIRED",
            )
            world = World(world_path, self.spec(episode)["scope"])
            with closing(sqlite3.connect(world_path.as_uri() + "?mode=ro", uri=True)) as world_db:
                world_db.execute("BEGIN")
                world._state(world_db)
                require(
                    not world_db.execute(
                        "SELECT id FROM v0220_dispatch WHERE receipt IS NULL"
                    ).fetchall(),
                    "NO_UNRESOLVED_WORLD_DISPATCH_REQUIRED",
                )
            for name, actual in (
                ("final-world.json", world.snapshot()),
                ("final-ledger.json", world.ledger()),
            ):
                path = self.root / "episodes" / episode / name
                require(str(path) in result["files"], "COMPLETE_WORLD_AND_LEDGER_READBACK_REQUIRED")
                with scope.physical_reads():
                    require(
                        scope.read_json(path, result["files"][str(path)]) == actual,
                        "WORLD_OR_LEDGER_READBACK_DRIFT",
                    )
            db.execute("UPDATE episodes SET status='EXECUTION_COMPLETE' WHERE id=?", (episode,))
            return {
                "id": episode,
                "status": "EXECUTION_COMPLETE",
                "pid": row["pid"],
                "usage": cost,
                "task_correctness": "NOT_EVALUATED",
            }

    def snapshot(self):
        with self._operation("PREP") as (db, _, state):
            return {
                "episodes": [
                    dict(r) for r in db.execute("SELECT * FROM episodes ORDER BY ordinal")
                ],
                "cost": state,
                "task_correctness": "NOT_EVALUATED",
            }

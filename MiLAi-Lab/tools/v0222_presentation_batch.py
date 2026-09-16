"""Finite full/finish and conditional execution gates for the single B1 candidate.

This module constructs no authorization instance on import. Only a separately
sealed, reviewed root can advance. Historical diagnostics never become PASS here.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path

from v02_local_provider import read_events
from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import read, save, sha, validate
from v0220_provider_hardened import ProviderStop, historical_usage, usage_state
from v0220_wire_contract import fingerprint
from v0221_http_batch import Batch as PriorJournal
from v0222_boundary_batch import (
    HISTORICAL_SOURCES as PREVIOUS_SOURCES,
)
from v0222_boundary_batch import (
    IDENTITY,
    PARENT_BINDING,
    PARENT_P3_REVIEW_SHA,
    PARENT_ROOT,
    PARENT_STOP,
    _verify_files,
    _verify_tree,
)
from v0222_boundary_batch import (
    Batch as BoundaryArtifacts,
)
from v0222_boundary_batch import (
    authorization_source as previous_authorization_source,
)

REVISION = "INTENT_BOUNDARY_RUNTIME_V1"
ROOT = Path("/cra/memory/mx_memory/evidence/v0222-presentation/20260912-http-r1")
BOUNDARY_ROOT = Path("/cra/memory/mx_memory/evidence/v0222-boundary/20260911-http-r1")
BOUNDARY_BINDING = "7b7d4659f7250af493470882e8c6c2f0009e1762ddd751c3a79c431e0a0b928a"
BOUNDARY_REVIEW_SHA = "99a9c0caf97743ad0aaf6769f46e62b6f6b0ed12d13132ec6f9e3d69b39d40e3"
BOUNDARY_RESULT_SHA = "7524f244daeca98378a428566b90d72025306d33bfadebc83be336312bd520c6"
BOUNDARY_DECISION_SHA = "24e1906666f9499aa52d53c898601d08beb19461f7e1b3ae7058d48d6914b9b8"
BOUNDARY_LEDGER_HASHES = (
    "6e582ddb58c778bdfe20c9e7fd72994093223afc81389d0bf843dbc1ea5836b0",
    "a2a8f99b7ae5011781a847258471cce22304a3d7f482d0b26194ce113265385c",
    "7ad23bf15093ea0e72d41dde9aa6546fe0016d9ee598846ec67cf577e78aaffa",
    "7b3ab9045a13346641e8e20acc908bba4b0b3709b6edb36ea49a9a31f4720bf4",
    "c4679747bcfb42978d0abda759267791308f1741fbfecdd8656af9a5a4781629",
    "bdd0ad7070f7874adfccd43eb5fab2e8730c1a7f43431a2b54f4496827c4af34",
    "75b8015fbfae5b4685240a68c51ae18e6a257d747f639bf9df2883b59dbf1032",
    "761208d803fd033d720e171c99f607a2cf48b8e6bd13de264ac88e0edb7f0258",
    "a0704ba18566a2e67abb7c9e69f6015bf84f71dba602ec821b48cb429ddced82",
    "ea78163e57c2a543cf624f986d97fdfc74e4f6c655b025f46dce19fc7784c107",
    "93ded4cea097ee6f66fd31e379b9e951886ceaa2980dbfed5d1ed0e994d48178",
    "49e1fa2dc6a0567dd2f7bc940fe35d0ab5454bfc9d2d86d9a1508112c89f586c",
    "67040a82f4ecfbcc5c916e8ce3558e9040d4c15d2416a5524ebc2044f657a3d0",
    "e7379fbc27d569805dbdc39e3f710ce8950eb119a6af4cc5826b4bc3767caa89",
    "63a94cf19c66e9925f5c2a75851e2ffba9bdfe57168f7c982242f791fd718377",
    "2613b59b81a650214c4b6978830f0b6c9506a1bd4b844242404b573389c4bfa6",
)
HISTORICAL_SOURCES = (
    *PREVIOUS_SOURCES,
    *(
        (str(BOUNDARY_ROOT / "episodes" / f"r1-{i:02}" / "provider/provider-ledger-v2.jsonl"), h)
        for i, h in enumerate(BOUNDARY_LEDGER_HASHES, 1)
    ),
)
HISTORY_TOTALS = (45, 631670, 28284)
CAPS = {"P3": 16, "P4": 96}
PHASE_SECONDS = {"P3": 1800, "P4": 7200}
REFERENCE_KINDS = ("canonical", "presented", "wire", "output", "presentation_diff")


def historical_usage_presentation(paths: tuple[Path, ...]) -> dict:
    """Exact 44 independent ledgers; only the pinned original unknown is carried."""
    expected = [{"path": p, "sha256": h} for p, h in HISTORICAL_SOURCES]
    if (
        len(paths) != 44
        or len({p.resolve() for p in paths}) != 44
        or [str(p.resolve()) for p in paths] != [p for p, _ in HISTORICAL_SOURCES]
    ):
        raise ProviderStop("EXACT_44_ORDERED_DISTINCT_HISTORICAL_LEDGERS_REQUIRED")
    if [{"path": str(p.resolve()), "sha256": sha(p)} for p in paths] != expected:
        raise ProviderStop("HISTORICAL_LEDGER_HASH_DRIFT")
    old = historical_usage(paths[:2])
    newer = [usage_state(read_events(p)) for p in paths[2:]]
    if any(s["unresolved_reservations"] or s["violations"] for s in newer):
        raise ProviderStop("NO_NEW_HISTORICAL_UNKNOWN_WHITELIST")
    result = {
        **old,
        "sources": expected,
        "requests": old["requests"] + sum(s["requests"] for s in newer),
        "known_raw_tokens": old["known_raw_tokens"] + sum(s["known_raw_tokens"] for s in newer),
    }
    if (
        (result["requests"], result["known_raw_tokens"], result["reserved_raw_upper_bound"])
        != HISTORY_TOTALS
        or len(result["unresolved_reservations"]) != 1
        or result["violations"]
    ):
        raise ProviderStop("EXACT_ORIGINAL_UNKNOWN_AND_HISTORY_TOTALS_REQUIRED")
    return result


def authorization_source() -> dict:
    previous = previous_authorization_source()
    return {
        **{
            k: previous[k]
            for k in (
                "origin",
                "user_instruction",
                "explicit_historical_carry",
                "http_only",
                "execute_goal_and_followup",
                "subagent_review_delegated",
                "review_is_not_user_consent",
            )
        },
        "stages": ["PREP", "P3", "P4"],
        "old_batch_remains_stopped": True,
        "selected_presentation_only": "B1",
        "selected_decoder_only": "D11",
        "first_acceptance_failure_stops_all": True,
        "diagnostic_content_failures_continue": False,
        "business_dispatches_only_in_gated_P4": True,
        "recovery_natural_task_memory_generations": False,
    }


def make_authorization(root: Path, *, issued: float, expires: float) -> dict:
    if root.resolve() != ROOT:
        raise ProviderStop("ONE_FIXED_NEW_PRESENTATION_ROOT_REQUIRED")
    if (
        type(issued) not in (int, float)
        or type(expires) not in (int, float)
        or not math.isfinite(issued)
        or not math.isfinite(expires)
        or not 0 < expires - issued <= 36 * 3600
    ):
        raise ProviderStop("FINITE_36_HOUR_AUTHORIZATION_REQUIRED")
    history = historical_usage_presentation(tuple(Path(p) for p, _ in HISTORICAL_SOURCES))
    return {
        "revision": REVISION,
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
        "historical": history,
        "accepted_unknown": history["unresolved_reservations"],
        "parent_root": str(PARENT_ROOT),
        "parent_binding": PARENT_BINDING,
        "boundary_root": str(BOUNDARY_ROOT),
        "boundary_binding": BOUNDARY_BINDING,
        "boundary_result_review_sha256": BOUNDARY_REVIEW_SHA,
    }


def verify_lineage() -> None:
    """Recheck the complete immutable closure and both terminal coordinator states."""
    seen = set()
    for path, digest in (
        (BOUNDARY_ROOT / "independent-result-review.json", BOUNDARY_REVIEW_SHA),
        (BOUNDARY_ROOT / "execution-binding.json", BOUNDARY_BINDING),
        (BOUNDARY_ROOT / "result.json", BOUNDARY_RESULT_SHA),
        (BOUNDARY_ROOT / "final-decision.json", BOUNDARY_DECISION_SHA),
        (PARENT_ROOT / "execution-binding.json", PARENT_BINDING),
        (PARENT_ROOT / "P3-independent-review.json", PARENT_P3_REVIEW_SHA),
    ):
        _verify_tree(path, digest, seen)
    review = read(BOUNDARY_ROOT / "independent-result-review.json")
    if (
        review.get("status") != "BOUNDARY_RESULT_REVIEW_PASS"
        or review.get("selected_condition") != "B1"
        or review.get("experimental_verdict") != "INTENT_BOUNDARY_SIGNAL"
        or read(BOUNDARY_ROOT / "final-decision.json")
        != {
            "status": "INTENT_BOUNDARY_SIGNAL",
            "selected_condition": "B1",
        }
    ):
        raise ProviderStop("FROZEN_FINAL_BOUNDARY_SIGNAL_AND_REVIEW_REQUIRED")
    for root, binding, expected_stop, rows, history_slice in (
        (
            PARENT_ROOT,
            PARENT_BINDING,
            PARENT_STOP,
            read(PARENT_ROOT / "P3-independent-review.json")["terminal"]["episodes_snapshot"],
            slice(3, 28),
        ),
        (BOUNDARY_ROOT, BOUNDARY_BINDING, None, review["execution"]["episodes"], slice(28, 44)),
    ):
        with sqlite3.connect((root / "batch.sqlite").as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            meta = dict(db.execute("SELECT key,value FROM meta"))
            if meta.get("binding") != binding or meta.get("stop") != expected_stop:
                raise ProviderStop("HISTORICAL_TERMINAL_STOP_OR_BINDING_CHANGED")
            actual = [dict(r) for r in db.execute("SELECT * FROM episodes ORDER BY stage,ordinal")]
            if fingerprint(actual) != fingerprint(rows):
                raise ProviderStop("HISTORICAL_TERMINAL_EPISODES_CHANGED")
            central = [
                json.loads(r[0]) for r in db.execute("SELECT event FROM events ORDER BY seq")
            ]
            local = [e for p, _ in HISTORICAL_SOURCES[history_slice] for e in read_events(Path(p))]
            if sorted(map(fingerprint, central)) != sorted(map(fingerprint, local)):
                raise ProviderStop("HISTORICAL_CENTRAL_AND_EPISODE_LEDGERS_DIVERGED")
            launches = [dict(r) for r in db.execute("SELECT * FROM launches ORDER BY stage")]
            if root == BOUNDARY_ROOT and fingerprint(launches) != fingerprint(
                [review["execution"]["launch"]]
            ):
                raise ProviderStop("HISTORICAL_BOUNDARY_LAUNCH_CHANGED")
            if root == PARENT_ROOT and any(r["stage"] == "P4" for r in launches):
                raise ProviderStop("STOPPED_PARENT_P4_CANNOT_BE_LAUNCHED")


class Batch(PriorJournal):
    # These generic readers have no stage/cap/authorization policy.
    _artifact = BoundaryArtifacts._artifact
    artifact = BoundaryArtifacts.artifact

    def __init__(self, root: Path, binding_sha: str):
        self.root = root.resolve()
        if self.root != ROOT:
            raise ProviderStop("ONE_FIXED_NEW_PRESENTATION_ROOT_REQUIRED")
        self.binding_sha = binding_sha
        self.binding = read(self.root / "execution-binding.json")
        self.path = self.root / "batch.sqlite"
        self.auth = self.authorize("PREP")
        self.plan = read(self.root / "manifest.json")["contract"]
        self._validate_plan()

    def authorize(self, stage: str = "PREP") -> dict:
        if sha(self.root / "execution-binding.json") != self.binding_sha:
            raise ProviderStop("EXECUTION_BINDING_DRIFT")
        if set(self.binding) != {
            "authorization.json",
            "authorization-source.json",
            "manifest.json",
        }:
            raise ProviderStop("EXACT_EXECUTION_BINDING_REQUIRED")
        for name, digest in self.binding.items():
            if sha(self.root / name) != digest:
                raise ProviderStop("AUTHORIZATION_OR_MANIFEST_DRIFT")
        auth = read(self.root / "authorization.json")
        wanted = make_authorization(
            self.root, issued=auth["issued_unix"], expires=auth["expires_unix"]
        )
        if fingerprint(auth) != fingerprint(wanted):
            raise ProviderStop("AUTHORIZATION_SCOPE_OR_EXACT_HISTORY_MISMATCH")
        if fingerprint(read(self.root / "authorization-source.json")) != fingerprint(
            authorization_source()
        ):
            raise ProviderStop("EXPLICIT_USER_SCOPE_SOURCE_REQUIRED")
        if stage not in auth["stages"]:
            raise ProviderStop("STAGE_NOT_AUTHORIZED")
        if not auth["issued_unix"] <= time.time() < auth["expires_unix"]:
            raise ProviderStop("AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")
        manifest = validate(self.root, manifest_sha256=self.binding["manifest.json"])
        plan = manifest["contract"]
        if (hasattr(self, "plan") and fingerprint(self.plan) != fingerprint(plan)) or (
            hasattr(self, "auth") and fingerprint(self.auth) != fingerprint(auth)
        ):
            raise ProviderStop("IN_MEMORY_AUTHORIZATION_OR_PLAN_DRIFT")
        required = {
            "revision": REVISION,
            "selected_decoder": "D11",
            "selected_presentation": "B1",
            "parent_root": str(PARENT_ROOT),
            "parent_binding": PARENT_BINDING,
            "boundary_root": str(BOUNDARY_ROOT),
            "boundary_binding": BOUNDARY_BINDING,
            "historical_paths": [p for p, _ in HISTORICAL_SOURCES],
            "http_identity": IDENTITY,
        }
        if any(fingerprint(plan.get(k)) != fingerprint(v) for k, v in required.items()):
            raise ProviderStop("FROZEN_PRESENTATION_CONTRACT_REQUIRED")
        verify_lineage()
        return auth

    def _validate_plan(self):
        original = read(PARENT_ROOT / "manifest.json")["contract"]
        ids, scopes = [], []
        old_scopes = {s["scope"] for stage in CAPS for s in original[stage]}
        for stage, count in (("P3", 16), ("P4", 24)):
            specs = self.plan[stage]
            if len(specs) != count or len(original[stage]) != count:
                raise ProviderStop("COMPLETE_ORIGINAL_16_PLUS_24_MATRIX_REQUIRED")
            for spec, old in zip(specs, original[stage], strict=True):
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
                    raise ProviderStop("ORIGINAL_SOURCE_ORDER_ACTION_INTENT_OR_NEW_SCOPE_REQUIRED")
                if stage == "P4" and (
                    not isinstance(spec.get("initial_state_sha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", spec["initial_state_sha256"])
                    or spec["initial_state_sha256"] == old["initial_state_sha256"]
                ):
                    raise ProviderStop("NEW_SCOPE_DERIVED_INITIAL_HASH_REQUIRED")
                ids.append(spec["id"])
                scopes.append(spec["scope"])
        if len(set(ids)) != 40 or len(set(scopes)) != 40:
            raise ProviderStop("GLOBALLY_UNIQUE_EPISODES_AND_ISOLATED_SCOPES_REQUIRED")

    def spec(self, episode: str) -> dict:
        for stage in CAPS:
            for spec in self.plan[stage]:
                if spec["id"] == episode:
                    return spec
        raise ProviderStop("EPISODE_OUTSIDE_FROZEN_PLAN")

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
            """)
            db.execute("INSERT INTO meta VALUES ('binding',?)", (self.binding_sha,))
            for stage in CAPS:
                for i, spec in enumerate(self.plan[stage]):
                    db.execute(
                        "INSERT INTO episodes VALUES (?,?,?,?, 'PENDING',NULL,NULL)",
                        (spec["id"], stage, i, 1 if stage == "P3" else 4),
                    )

    def references(self, stage: str) -> list:
        if stage not in CAPS:
            raise ProviderStop("NON_GENERATION_STAGE")
        return self.artifact(stage + "_references")["references"]

    def freeze_artifact(self, name: str, path: Path, status: str | None = None):
        self.authorize("PREP")
        path = path.resolve()
        if not path.is_relative_to(self.root):
            raise ProviderStop("STAGE_ARTIFACT_OUTSIDE_BATCH")
        value = read(path)
        if status is not None and value.get("status") != status:
            raise ProviderStop("STAGE_GATE_STATUS_NOT_MET")
        if name.endswith(("_audit", "_observation")):
            raise ProviderStop("ONLY_INDEPENDENT_FINISH_CAN_FREEZE_EPISODE_AUDITS")
        dependencies = value.get("files", {})
        if name != "P3_gate":
            _verify_files(dependencies)
        if name in {stage + "_preflight" for stage in CAPS}:
            from v0222_presentation_audit import validate_preflight

            validate_preflight(self, value, name[:2])
        if name in {stage + "_references" for stage in CAPS}:
            from v0222_presentation_audit import validate_reference

            stage = name[:2]
            refs = value["references"]
            expected = [
                (s["id"], turn)
                for s in self.plan[stage]
                for turn in range(1, (1 if stage == "P3" else len(s["actions"]) + 2) + 1)
            ]
            if [(r.get("episode"), r.get("turn")) for r in refs] != expected:
                raise ProviderStop("COMPLETE_ORDERED_STAGE_REFERENCES_REQUIRED")
            for reference in refs:
                spec = self.spec(reference["episode"])
                if (
                    reference.get("stage") != stage
                    or type(reference.get("turn")) is not int
                    or reference.get("selected_condition") != "B1"
                    or reference.get("selected_decoder") != "D11"
                ):
                    raise ProviderStop("FIXED_PRESENTATION_AND_DECODER_REFERENCE_REQUIRED")
                validate_reference(self, reference, spec)
                for kind in REFERENCE_KINDS:
                    if dependencies.get(reference[kind]) != reference["hashes"][kind]:
                        raise ProviderStop("ALL_REFERENCE_FILES_MUST_BE_BOUND")
        if name == "P4_resolved_specs":
            if fingerprint(value.get("specs")) != fingerprint(self.plan["P4"]):
                raise ProviderStop("EXACT_RESOLVED_24_SCOPE_INITIAL_HASH_SPECS_REQUIRED")
        if name == "P3_gate" and fingerprint(value) != fingerprint(self.p3_gate()):
            raise ProviderStop("P3_GATE_NOT_DERIVED_FROM_16_ACTUAL_PASS_AUDITS")
        with self.transaction() as db:
            self.check_journal(db)
            if db.execute("SELECT 1 FROM artifacts WHERE name=?", (name,)).fetchone():
                raise ProviderStop("STAGE_ARTIFACT_ALREADY_FROZEN")
            db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?)",
                (name, str(path), sha(path), json.dumps(dependencies)),
            )

    def check_journal(self, db, *, inflight: str | None = None) -> dict:
        if read(self.root / "coordinator-created.json") != {"binding_sha256": self.binding_sha}:
            raise ProviderStop("COORDINATOR_INITIALIZATION_MARKER_DRIFT")
        if db.execute("SELECT 1 FROM meta WHERE key='stop'").fetchone():
            raise ProviderStop("BATCH_STOPPED_NO_RETRY")
        rows = [dict(r) for r in db.execute("SELECT * FROM episodes ORDER BY stage,ordinal")]
        if [(r["id"], r["stage"], r["ordinal"], r["cap"]) for r in rows] != [
            (s["id"], stage, i, 1 if stage == "P3" else 4)
            for stage in CAPS
            for i, s in enumerate(self.plan[stage])
        ]:
            raise ProviderStop("COORDINATOR_PLAN_OR_CAP_DRIFT")
        events = self.events(db)
        state = usage_state(events)
        pending = state["unresolved_reservations"]
        own_inflight = (
            inflight is not None
            and len(pending) == 1
            and not state["violations"]
            and pending[0]["state"] in {"RESERVED", "DISPATCH_STARTED"}
            and pending[0]["reservation"].get("session") == inflight
        )
        if not state["new_generation_allowed"] and not own_inflight:
            raise ProviderStop("NEW_BATCH_UNKNOWN_OR_VIOLATION")
        if inflight is not None and not own_inflight:
            raise ProviderStop("EXACT_OWN_UNSENT_RESERVATION_REQUIRED")
        mirrored = [
            e
            for stage in CAPS
            for s in self.plan[stage]
            for e in read_events(
                self.root / "episodes" / s["id"] / "provider/provider-ledger-v2.jsonl"
            )
        ]
        if sorted(map(fingerprint, events)) != sorted(map(fingerprint, mirrored)):
            raise ProviderStop("CENTRAL_AND_EPISODE_LEDGER_DIVERGED")
        for row in db.execute("SELECT * FROM artifacts"):
            self._artifact(row)
        for launch in db.execute("SELECT * FROM launches ORDER BY stage"):
            stage = launch["stage"]
            if stage not in CAPS:
                raise ProviderStop("UNKNOWN_STAGE_LAUNCH")
            self._ready(db, stage)
            if fingerprint(read(self.root / ("live-launch-" + stage + ".json"))) != fingerprint(
                {
                    "stage": stage,
                    "pid": launch["pid"],
                    "unix": launch["started"],
                    "binding_sha256": self.binding_sha,
                }
            ):
                raise ProviderStop("LAUNCH_MARKER_DRIFT")
            deadline = db.execute(
                "SELECT value FROM meta WHERE key=?", (stage + "_deadline",)
            ).fetchone()
            if deadline is None or float(deadline[0]) != min(
                launch["started"] + PHASE_SECONDS[stage], self.auth["expires_unix"]
            ):
                raise ProviderStop("PHASE_DEADLINE_DRIFT")
        return state

    def _ready(self, db, stage):
        for name, status in (
            ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
            ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
            (stage + "_preflight", "G_PREFLIGHT_PASS"),
        ):
            if (
                self._artifact(
                    db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone()
                ).get("status")
                != status
            ):
                raise ProviderStop("STAGE_GATE_STATUS_NOT_MET")
        self._artifact(
            db.execute("SELECT * FROM artifacts WHERE name=?", (stage + "_references",)).fetchone()
        )
        if stage == "P4":
            self._artifact(
                db.execute("SELECT * FROM artifacts WHERE name='P4_resolved_specs'").fetchone()
            )
            gate = self._artifact(
                db.execute("SELECT * FROM artifacts WHERE name='P3_gate'").fetchone()
            )
            if (
                gate.get("status") != "G_P3_PASS"
                or db.execute(
                    "SELECT COUNT(*) FROM episodes WHERE stage='P3' AND status='PASS'"
                ).fetchone()[0]
                != 16
            ):
                raise ProviderStop("P4_REQUIRES_NEW_COMPLETE_P3_16_PASS")

    def launch_once(self, stage: str):
        self.authorize(stage)
        if stage not in CAPS:
            raise ProviderStop("NON_GENERATION_STAGE")
        with self.transaction() as db:
            self.check_journal(db)
            self._ready(db, stage)
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

    def claim(self, episode: str):
        spec = self.spec(episode)
        stage = spec["stage"]
        self.authorize(stage)
        with self.transaction() as db:
            self.check_journal(db)
            self._ready(db, stage)
            launcher = db.execute("SELECT pid FROM launches WHERE stage=?", (stage,)).fetchone()
            if not launcher:
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
            if time.time() >= deadline:
                raise ProviderStop("BATCH_PHASE_DEADLINE")
            db.execute(
                "UPDATE episodes SET status='RUNNING',pid=?,deadline=? WHERE id=?",
                (os.getpid(), min(deadline, time.time() + 300), episode),
            )

    def http_admit(self, episode: str, *, inflight: bool = False) -> dict:
        if not inflight:
            return self.admit(episode)
        with self.transaction() as db:
            self.check_journal(db, inflight=episode)
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
            if row is None or row["status"] != "RUNNING" or row["pid"] != os.getpid():
                raise ProviderStop("EPISODE_NOT_OWNED_BY_THIS_PROCESS")
            self.authorize(row["stage"])
            if time.time() >= row["deadline"]:
                raise ProviderStop("EPISODE_DEADLINE")
            return dict(row)

    def record(self, episode: str, event: dict):
        if event.get("event") == "RESERVED" and (
            type(event.get("output_cap")) is not int
            or event["output_cap"] != 4096
            or event.get("cumulative_raw_cap") is not None
            or type(event.get("raw_upper_bound")) is not int
            or event["raw_upper_bound"] > 65536
        ):
            raise ProviderStop("FROZEN_REQUEST_CAP_MISMATCH")
        super().record(episode, event)

    def _finish_owner(self, db, episode):
        row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
        launcher = (
            None
            if row is None
            else db.execute("SELECT pid FROM launches WHERE stage=?", (row["stage"],)).fetchone()
        )
        if (
            row is None
            or row["status"] != "RUNNING"
            or launcher is None
            or os.getpid() != launcher[0]
            or row["pid"] == launcher[0]
            or time.time() >= row["deadline"]
        ):
            raise ProviderStop("NO_OWNED_LIVE_EPISODE_TO_FINISH")
        return row

    def finish(self, episode: str) -> dict:
        try:
            return self._finish(episode)
        except BaseException as exc:
            self.stop(str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__)
            raise

    def _finish(self, episode: str) -> dict:
        from v0222_presentation_audit import audit_episode

        spec = self.spec(episode)
        self.authorize(spec["stage"])
        with self.transaction() as db:
            self.check_journal(db)
            self._finish_owner(db, episode)
        audit = audit_episode(self, episode)  # The independent auditor can open its own DB readers.
        if (
            audit.get("status") != "PASS"
            or audit.get("id") != episode
            or audit.get("stage") != spec["stage"]
            or type(audit.get("pid")) is not int
        ):
            raise ProviderStop("FULL_ACCEPTANCE_AUDIT_NOT_PASS")
        dependencies = audit["files"]
        _verify_files(dependencies)
        directory = self.root / "episodes" / episode
        required = {
            str(p)
            for p in directory.rglob("*")
            if p.is_file()
            and p.suffix in {".json", ".jsonl"}
            and p.name != "independent-audit.json"
        }
        if not required or not required <= dependencies.keys():
            raise ProviderStop("ALL_RAW_EPISODE_FILES_MUST_BE_BOUND")
        with self.transaction() as db:
            self.check_journal(db)
            row = self._finish_owner(db, episode)
            if audit["pid"] != row["pid"]:
                raise ProviderStop("AUDIT_WORKER_PID_MISMATCH")
            events = self.events(db)
            keys = {
                e["request_id"]
                for e in events
                if e["event"] == "RESERVED" and e.get("session") == episode
            }
            if not (len(keys) == 1 if spec["stage"] == "P3" else 3 <= len(keys) <= 4):
                raise ProviderStop("INCOMPLETE_OR_EXCESSIVE_ACTUAL_REQUESTS")
            if fingerprint(audit.get("cost")) != fingerprint(
                usage_state([e for e in events if e["request_id"] in keys])
            ):
                raise ProviderStop("AUDIT_COST_NOT_ACTUAL_EPISODE_LEDGER")
            _verify_files(dependencies)
            path = directory / "independent-audit.json"
            save(path, audit)
            db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?)",
                (episode + "_audit", str(path), sha(path), json.dumps(dependencies)),
            )
            db.execute("UPDATE episodes SET status='PASS' WHERE id=?", (episode,))
        return audit

    def p3_gate(self) -> dict:
        from v0222_presentation_audit import audit_episode

        self.authorize("PREP")
        with self.transaction() as db:
            self.check_journal(db)
            audits = []
            files = {}
            for spec in self.plan["P3"]:
                row = db.execute("SELECT status FROM episodes WHERE id=?", (spec["id"],)).fetchone()
                if row[0] != "PASS":
                    raise ProviderStop("P3_GATE_REQUIRES_16_ACTUAL_PASS")
                artifact = db.execute(
                    "SELECT * FROM artifacts WHERE name=?", (spec["id"] + "_audit",)
                ).fetchone()
                audits.append(self._artifact(artifact))
                files[artifact["path"]] = artifact["sha256"]
                files.update(json.loads(artifact["dependencies"]))
        for spec, audit in zip(self.plan["P3"], audits, strict=True):
            if fingerprint(audit_episode(self, spec["id"])) != fingerprint(audit):
                raise ProviderStop("P3_AUDIT_NOT_REPRODUCIBLE_FROM_RAW")
        return {
            "status": "G_P3_PASS",
            "binding_sha256": self.binding_sha,
            "episodes": [s["id"] for s in self.plan["P3"]],
            "full_passed": 8,
            "finish_passed": 8,
            "files": files,
        }

    def freeze_p3_gate(self, path: Path):
        self.freeze_artifact("P3_gate", path, "G_P3_PASS")

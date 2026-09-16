"""Single, separately sealed residual-boundary diagnostic; no World or retries.

The immutable prior journal owns event accounting and transactions. This module
only narrows authorization, history, stage ordering and independent observations.
"""

from __future__ import annotations

# ruff: noqa: RUF001 -- preserve the actual user's Chinese authorization verbatim.
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
from v0222_batch import HISTORICAL_SOURCES as OLD_SOURCES

REVISION = "RESIDUAL_INTENT_BOUNDARY_V1"
ROOT = Path("/cra/memory/mx_memory/evidence/v0222-boundary/20260911-http-r1")
PARENT_ROOT = Path("/cra/memory/mx_memory/evidence/v0222/20260911-http-r1")
PARENT_BINDING = "f6abde2c7258eba7288aa0cb7c74e03aafb97a486127f9b7a5827525c30c70d9"
PARENT_P3_REVIEW_SHA = "2b45d98bb287ae04a05e851f3eb59f57635112c0913fd7ee6e78babfd36bdd2e"
PARENT_STOP = "FULL_INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH"
ROOT_ORDER = (
    "A-1db36ca3de1602c36e98",
    "A-1816ef11f35c3921798c",
    "A-e5324eaf97ba5a9b16dd",
    "A-4d36e6825968f3ce3862",
)
SOURCE_EPISODES = ("p3-01", "p3-03", "p3-05", "p3-07")
PARENT_LEDGER_HASHES = (
    "c1d38268bc1d7225e5b39ba7e30d3ea11dcf505645ea5fd5510b31c4aaf74c3f",
    "682f35a22fc64416d2898d19695f53c9d2d671188424432e4cbe7d70eeda4b07",
    "bb46b3d7e91dc1804772dd0e75ce295ea7c99b5e7e9f6d1a8ee87a4288336f0d",
    "a801384685f9539af7ed1f2dbeccbf6a4937dfca4db15d88f98c8cb45cf42501",
    "c7280ef07ea7f7394d8e61e058260d0fac484cfbd26365b9d73246be5ee7eabd",
    "860f36c6190fcc77a5a13f4a2204a749d4874045eeb7f596b4016ddf5578255d",
    "771bd8f3c68a0aa74302ae338820465b9e0f7592eedc8597ee5b88faffc0a377",
    "caa3fd0f20cdfc5fb110344ba1217f13b848d94cf5ad8179ddd2a18b7bbcaf67",
    "da7d5578dfcc9af18def5de37a248de7c65b73046a9a712faed975d160325633",
    "aba3d349c492909609b29497f744c880b1b70d5d2260c6a807ab1016e908452d",
    "25351cc598dfb7e6d725fc7732315caf1c8f756892d2572cfe512807bf74eab8",
    "4cecf150781562f529652732dcefca48b09dfb0dfbeac4a0bc077053f35a1fbe",
    "84c6899cd45cdfc72e52795706e76abac40cbd10d3af6aba1f81f221de159fb8",
    "fd7031bf8a7776c34bb93301d578d2d66b0fcfc43a333bb439186855875a88bb",
    "b3a8911280c08e738dfae29cf0af4fce0c875db5ad7aebaa565be80a9d866614",
    "d2cce76abdcc92b0dac0f65b58d657d2cd4e595fe4bc69160c65c56b1b75195e",
    "736dcabd5dcac94b78f2c8c65699a7b355b7fed25fd43fbbb3c80ca38972ca69",
    "6b33433e21823da5b230011ca03bc74a7a55d7b928f89ee6aeb8cd4dc77dcdb4",
    "b1755e9679db81ca634d0aad43019790c1424340cc0191e3e85599d1f6f53445",
    "76debaffbd19ac027efdbe61f791cd6e5a292c3f4b07fbcca0c4c0add117769c",
    "b4d2cf757db16ce74281e72443c2261e1fcf81b3a0770d3ebb3861b7af4dd970",
    "06559bfe35edf58e405d2301ac74cda55263a96291282f9f114a2f0bad287988",
    "56bbfe082de37f6f4d5ee7e8f6c40f81f8fee8e4ea1e57d44ef684be5b138e50",
    "d7697081f822260a1323d6c67c29c9b71b75b8250471a89150ab6ffa455f1280",
    "5b28c8550f3ddc7385f6343b2df5052c4ef7360c8991cdfd574d380d600cc51e",
)
HISTORICAL_SOURCES = (
    *OLD_SOURCES,
    *(
        (str(PARENT_ROOT / "episodes" / ep / "provider/provider-ledger-v2.jsonl"), digest)
        for ep, digest in zip(
            [f"p1-{i:02d}" for i in range(1, 25)] + ["p3-01"],
            PARENT_LEDGER_HASHES,
            strict=True,
        )
    ),
)
HISTORY_TOTALS = (29, 62874, 28284)
IDENTITY = {"endpoint": ENDPOINT, "model": MODEL, "context": 65536, "version": "0.27.1"}


def historical_usage_boundary(paths: tuple[Path, ...]) -> dict:
    """Exactly 28 original episode ledgers; never count the central mirror twice."""
    expected = [{"path": p, "sha256": h} for p, h in HISTORICAL_SOURCES]
    if len(paths) != 28 or [str(p.resolve()) for p in paths] != [p for p, _ in HISTORICAL_SOURCES]:
        raise ProviderStop("EXACT_28_ORDERED_HISTORICAL_LEDGERS_REQUIRED")
    if len({p.resolve() for p in paths}) != 28:
        raise ProviderStop("DISTINCT_HISTORICAL_LEDGERS_REQUIRED")
    if [{"path": str(p.resolve()), "sha256": sha(p)} for p in paths] != expected:
        raise ProviderStop("HISTORICAL_LEDGER_HASH_DRIFT")
    old = historical_usage(paths[:2])
    current = [usage_state(read_events(p)) for p in paths[2:]]
    if any(s["unresolved_reservations"] or s["violations"] for s in current):
        raise ProviderStop("NO_NEW_HISTORICAL_UNKNOWN_WHITELIST")
    result = {
        **old,
        "sources": expected,
        "requests": old["requests"] + sum(s["requests"] for s in current),
        "known_raw_tokens": old["known_raw_tokens"] + sum(s["known_raw_tokens"] for s in current),
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
    return {
        "origin": "USER_CONVERSATION",
        "user_instruction": (
            "详细阅读并执行/cra/memory/mx_memory/MiLAi-Lab/studies/active/"
            "MILA_V0222_解码语义与意图保真改进_GOAL_20260911.md，执行完任务后进入执行"
            "/cra/memory/mx_memory/MiLAi-Lab/docs/V0222_后续执行与Memory再准入规划.md，"
            "遇到问题反思改进，避免刻板编程，保持探索性和创新性，人工授权，标注，审查使用subagent代替"
        ),
        "explicit_historical_carry": True,
        "http_only": True,
        "execute_goal_and_followup": True,
        "subagent_review_delegated": True,
        "review_is_not_user_consent": True,
        "diagnostic_content_failures_continue": True,
        "single_residual_boundary_candidate_only": True,
        "old_batch_remains_stopped": True,
        "business_dispatches": False,
        "future_full_or_memory_generations": False,
        "stages": ["PREP", "R1"],
    }


def make_authorization(root: Path, *, issued: float, expires: float) -> dict:
    if root.resolve() != ROOT:
        raise ProviderStop("ONE_FIXED_NEW_BOUNDARY_ROOT_REQUIRED")
    if (
        type(issued) not in (int, float)
        or type(expires) not in (int, float)
        or not math.isfinite(issued)
        or not math.isfinite(expires)
        or not 0 < expires - issued <= 36 * 3600
    ):
        raise ProviderStop("FINITE_36_HOUR_AUTHORIZATION_REQUIRED")
    history = historical_usage_boundary(tuple(Path(p) for p, _ in HISTORICAL_SOURCES))
    return {
        "revision": REVISION,
        "root": str(ROOT),
        "batch_id": ROOT.name,
        "issued_unix": issued,
        "expires_unix": expires,
        "stages": ["PREP", "R1"],
        "path": "B",
        "historical_usage_settled": False,
        "reconciliation": None,
        "endpoint": ENDPOINT,
        "model": MODEL,
        "caps": {"R1": 16},
        "concurrency": 1,
        "raw_cap": None,
        "phase_wall_seconds": 1800,
        "episode_wall_seconds": 300,
        "http_wall_seconds": 60,
        "automatic_retry": False,
        "new_unknown_stops_all": True,
        "diagnostic_content_failures_continue": True,
        "historical": history,
        "accepted_unknown": history["unresolved_reservations"],
        "parent_binding": PARENT_BINDING,
        "parent_root": str(PARENT_ROOT),
        "parent_p3_review_sha256": PARENT_P3_REVIEW_SHA,
    }


def _verify_files(files: dict) -> None:
    if not isinstance(files, dict) or not files:
        raise ProviderStop("EXPLICIT_ARTIFACT_FILES_REQUIRED")
    for name, digest in files.items():
        if not Path(name).is_absolute() or sha(Path(name)) != digest:
            raise ProviderStop("FROZEN_DEPENDENCY_DRIFT")


def _verify_tree(path: Path, digest: str, seen: set | None = None) -> None:
    """Follow explicit hash maps, not arbitrary model strings or embedded actions."""
    seen = set() if seen is None else seen
    if (str(path), digest) in seen:
        return
    if sha(path) != digest:
        raise ProviderStop("PARENT_EVIDENCE_DEPENDENCY_DRIFT")
    seen.add((str(path), digest))
    if path.suffix != ".json":
        return

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key in ("files", "dependencies", "inputs"):
                for name, expected in value.get(key, {}).items():
                    _verify_tree(Path(name), expected, seen)
            for key, expected in value.get("hashes", {}).items():
                if isinstance(value.get(key), str) and Path(value[key]).is_absolute():
                    _verify_tree(Path(value[key]), expected, seen)
            # Reference indexes can themselves be nested in result wrappers.
            for key in ("references", "entries"):
                if key in value:
                    visit(value[key])

    value = read(path)
    if path.name == "manifest.json" and isinstance(value, dict) and all(
        key in value for key in ("dependencies", "inputs", "python", "packages")
    ):
        # Recheck the executed-source copies and environment seal, not just live files.
        validate(path.parent, manifest_sha256=digest)
    visit(value)


def verify_parent() -> None:
    seen = set()  # Only deduplicate within this check; never cache across admissions.
    binding_path = PARENT_ROOT / "execution-binding.json"
    if sha(binding_path) != PARENT_BINDING:
        raise ProviderStop("PARENT_BINDING_DRIFT")
    binding = read(binding_path)
    for name, digest in binding.items():
        _verify_tree(PARENT_ROOT / name, digest, seen)
    review_path = PARENT_ROOT / "P3-independent-review.json"
    _verify_tree(review_path, PARENT_P3_REVIEW_SHA, seen)
    review = read(review_path)
    if (
        review.get("status") != "P3_FAILURE_EVIDENCE_AND_STOP_REVIEW_PASS"
        or review.get("binding_sha256") != PARENT_BINDING
        or review.get("terminal", {}).get("permanent_batch_stop") != PARENT_STOP
    ):
        raise ProviderStop("PARENT_STOP_REVIEW_REQUIRED")
    with sqlite3.connect((PARENT_ROOT / "batch.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        meta = dict(db.execute("SELECT key,value FROM meta"))
        if meta.get("binding") != PARENT_BINDING or meta.get("stop") != PARENT_STOP:
            raise ProviderStop("PARENT_MUST_REMAIN_PERMANENTLY_STOPPED")
        if db.execute(
            "SELECT COUNT(*) FROM episodes WHERE stage='P4' AND status!='PENDING'"
        ).fetchone()[0]:
            raise ProviderStop("PARENT_FUTURE_STAGE_CHANGED")
        rows = [dict(row) for row in db.execute("SELECT * FROM episodes ORDER BY stage,ordinal")]
        if fingerprint(rows) != fingerprint(review["terminal"].get("episodes_snapshot")):
            raise ProviderStop("PARENT_TERMINAL_EPISODES_CHANGED")
        central = [
            json.loads(row[0]) for row in db.execute("SELECT event FROM events ORDER BY seq")
        ]
        local = [event for path, _ in HISTORICAL_SOURCES[3:] for event in read_events(Path(path))]
        if sorted(map(fingerprint, central)) != sorted(map(fingerprint, local)):
            raise ProviderStop("PARENT_CENTRAL_AND_EXACT_25_EPISODE_LEDGERS_DIVERGED")
        for path, digest, dependencies in db.execute(
            "SELECT path,sha256,dependencies FROM artifacts"
        ):
            _verify_tree(Path(path), digest, seen)
            if json.loads(dependencies):
                _verify_files(json.loads(dependencies))


class Batch(PriorJournal):
    def __init__(self, root: Path, binding_sha: str):
        self.root = root.resolve()
        if self.root != ROOT:
            raise ProviderStop("ONE_FIXED_NEW_BOUNDARY_ROOT_REQUIRED")
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
        expected = make_authorization(
            self.root, issued=auth["issued_unix"], expires=auth["expires_unix"]
        )
        if fingerprint(auth) != fingerprint(expected):
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
        if (
            plan.get("revision") != REVISION
            or plan.get("selected_decoder") != "D11"
            or plan.get("parent_root") != str(PARENT_ROOT)
            or plan.get("parent_binding") != PARENT_BINDING
            or plan.get("historical_paths") != [p for p, _ in HISTORICAL_SOURCES]
            or fingerprint(plan.get("http_identity")) != fingerprint(IDENTITY)
        ):
            raise ProviderStop("FROZEN_BOUNDARY_CONTRACT_REQUIRED")
        verify_parent()
        return auth

    def _validate_plan(self):
        specs = self.plan["episodes"]
        expected = [
            (root, cold, condition, source)
            for cold in (1, 2)
            for root, source in zip(ROOT_ORDER, SOURCE_EPISODES, strict=True)
            for condition in (("B0", "B1") if cold == 1 else ("B1", "B0"))
        ]
        parent = {s["id"]: s for s in read(PARENT_ROOT / "manifest.json")["contract"]["P3"]}
        if len(specs) != 16 or len({s["id"] for s in specs}) != 16:
            raise ProviderStop("COMPLETE_16_POSITION_MATRIX_REQUIRED")
        for spec, position in zip(specs, expected, strict=True):
            if (
                spec.get("stage") != "R1"
                or not isinstance(spec.get("id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", spec["id"])
                or type(spec.get("cold")) is not int
                or tuple(spec.get(k) for k in ("root", "cold", "condition", "source_episode"))
                != position
                or fingerprint(spec.get("expected")) != fingerprint(parent[position[3]]["expected"])
                or parent[position[3]]["root"] != spec["root"]
            ):
                raise ProviderStop("FROZEN_ROOT_ORDER_SOURCE_OR_EXPECTED_DRIFT")

    def spec(self, episode: str) -> dict:
        for spec in self.plan["episodes"]:
            if spec["id"] == episode:
                return spec
        raise ProviderStop("EPISODE_OUTSIDE_FROZEN_PLAN")

    def initialize(self) -> None:
        self.authorize("PREP")
        # Survives deletion of the SQLite journal: initialization is not a reset API.
        save(self.root / "coordinator-created.json", {"binding_sha256": self.binding_sha})
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
                CREATE TABLE artifacts (name TEXT PRIMARY KEY,path TEXT,sha256 TEXT,
                    dependencies TEXT NOT NULL);
                CREATE TABLE launches (stage TEXT PRIMARY KEY,pid INTEGER,started REAL);
            """)
            db.execute("INSERT INTO meta VALUES ('binding',?)", (self.binding_sha,))
            for i, spec in enumerate(self.plan["episodes"]):
                db.execute(
                    "INSERT INTO episodes VALUES (?, 'R1', ?, 1, 'PENDING', NULL, NULL)",
                    (spec["id"], i),
                )

    def _artifact(self, row):
        if row is None or sha(Path(row["path"])) != row["sha256"]:
            raise ProviderStop("FROZEN_STAGE_ARTIFACT_MISSING_OR_DRIFTED")
        dependencies = json.loads(row["dependencies"])
        if dependencies:
            _verify_files(dependencies)
        value = read(Path(row["path"]))
        if "files" in value:
            _verify_files(value["files"])
        return value

    def artifact(self, name: str):
        with self.transaction() as db:
            return self._artifact(
                db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone()
            )

    def freeze_artifact(self, name: str, path: Path, status: str | None = None):
        self.authorize("PREP")
        path = path.resolve()
        if not path.is_relative_to(self.root):
            raise ProviderStop("STAGE_ARTIFACT_OUTSIDE_BATCH")
        value = read(path)
        if status is not None and value.get("status") != status:
            raise ProviderStop("STAGE_GATE_STATUS_NOT_MET")
        if name.endswith("_observation"):
            raise ProviderStop("ONLY_INDEPENDENT_FINISH_CAN_FREEZE_OBSERVATIONS")
        dependencies = value.get("files", {})
        if name in {"references", "scope_review", "engineering_checks", "preflight"}:
            _verify_files(dependencies)
        if name == "preflight":
            from v0222_boundary_audit import validate_preflight

            validate_preflight(self, value)
        if name in {"firstpass_decision", "final_decision"}:
            if fingerprint(value) != fingerprint(self.decision(final=name == "final_decision")):
                raise ProviderStop("DECISION_NOT_DERIVED_FROM_COMPLETE_RAW_OBSERVATIONS")
        if name == "references":
            from v0222_boundary_audit import validate_reference

            refs = value["references"]
            if [r["episode"] for r in refs] != [s["id"] for s in self.plan["episodes"]]:
                raise ProviderStop("COMPLETE_ORDERED_REFERENCES_REQUIRED")
            for reference, spec in zip(refs, self.plan["episodes"], strict=True):
                validate_reference(self, reference, spec)
                for key in ("canonical", "wire", "output", "diff"):
                    if dependencies.get(reference[key]) != reference["hashes"][key]:
                        raise ProviderStop("ALL_REFERENCE_FILES_MUST_BE_BOUND")
                if (
                    dependencies.get(reference["source_canonical"])
                    != reference["source_canonical_sha256"]
                ):
                    raise ProviderStop("ORIGINAL_SOURCE_MUST_BE_BOUND")
        with self.transaction() as db:
            self.check_journal(db)
            if db.execute("SELECT 1 FROM artifacts WHERE name=?", (name,)).fetchone():
                raise ProviderStop("STAGE_ARTIFACT_ALREADY_FROZEN")
            db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?)",
                (name, str(path), sha(path), json.dumps(dependencies)),
            )

    def references(self) -> list:
        return self.artifact("references")["references"]

    def check_journal(self, db, *, inflight: str | None = None) -> dict:
        if read(self.root / "coordinator-created.json") != {"binding_sha256": self.binding_sha}:
            raise ProviderStop("COORDINATOR_INITIALIZATION_MARKER_DRIFT")
        if db.execute("SELECT 1 FROM meta WHERE key='stop'").fetchone():
            raise ProviderStop("BATCH_STOPPED_NO_RETRY")
        rows = [dict(r) for r in db.execute("SELECT * FROM episodes ORDER BY ordinal")]
        if [(r["id"], r["stage"], r["ordinal"], r["cap"]) for r in rows] != [
            (s["id"], "R1", i, 1) for i, s in enumerate(self.plan["episodes"])
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
            for spec in self.plan["episodes"]
            for e in read_events(
                self.root / "episodes" / spec["id"] / "provider/provider-ledger-v2.jsonl"
            )
        ]
        if sorted(map(fingerprint, events)) != sorted(map(fingerprint, mirrored)):
            raise ProviderStop("CENTRAL_AND_EPISODE_LEDGER_DIVERGED")
        for row in db.execute("SELECT * FROM artifacts"):
            self._artifact(row)
        launch = db.execute("SELECT * FROM launches WHERE stage='R1'").fetchone()
        if launch:
            self._ready(db)
            marker = read(self.root / "live-launch.json")
            if fingerprint(marker) != fingerprint(
                {
                    "pid": launch["pid"],
                    "unix": launch["started"],
                    "binding_sha256": self.binding_sha,
                }
            ):
                raise ProviderStop("LAUNCH_MARKER_DRIFT")
            deadline = db.execute("SELECT value FROM meta WHERE key='R1_deadline'").fetchone()
            expected_deadline = min(launch["started"] + 1800, self.auth["expires_unix"])
            if deadline is None or float(deadline[0]) != expected_deadline:
                raise ProviderStop("PHASE_DEADLINE_DRIFT")
        return state

    def http_admit(self, episode: str, *, inflight: bool = False) -> dict:
        if not inflight:
            return self.admit(episode)
        with self.transaction() as db:
            self.check_journal(db, inflight=episode)
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
            if row is None or row["status"] != "RUNNING" or row["pid"] != os.getpid():
                raise ProviderStop("EPISODE_NOT_OWNED_BY_THIS_PROCESS")
            self.authorize("R1")
            if time.time() >= row["deadline"]:
                raise ProviderStop("EPISODE_DEADLINE")
            return dict(row)

    def _ready(self, db):
        for name, status in (
            ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
            ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
            ("preflight", "G_PREFLIGHT_PASS"),
        ):
            if (
                self._artifact(
                    db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone()
                ).get("status")
                != status
            ):
                raise ProviderStop("STAGE_GATE_STATUS_NOT_MET")
        self._artifact(db.execute("SELECT * FROM artifacts WHERE name='references'").fetchone())

    def launch_once(self):
        self.authorize("R1")
        with self.transaction() as db:
            self.check_journal(db)
            self._ready(db)
            if db.execute("SELECT 1 FROM launches").fetchone():
                raise ProviderStop("STAGE_ALREADY_LAUNCHED_NO_RESTART")
            now = time.time()
            save(
                self.root / "live-launch.json",
                {"pid": os.getpid(), "unix": now, "binding_sha256": self.binding_sha},
            )
            db.execute("INSERT INTO launches VALUES ('R1',?,?)", (os.getpid(), now))
            db.execute(
                "INSERT INTO meta VALUES ('R1_deadline',?)",
                (str(min(now + 1800, self.auth["expires_unix"])),),
            )

    def claim(self, episode: str):
        self.spec(episode)
        self.authorize("R1")
        with self.transaction() as db:
            self.check_journal(db)
            self._ready(db)
            launcher = db.execute("SELECT pid FROM launches WHERE stage='R1'").fetchone()
            if not launcher:
                raise ProviderStop("STAGE_NOT_LAUNCHED")
            if launcher[0] == os.getpid():
                raise ProviderStop("SEPARATE_COLD_WORKER_PROCESS_REQUIRED")
            if db.execute("SELECT 1 FROM episodes WHERE status='RUNNING'").fetchone():
                raise ProviderStop("SINGLE_ACTIVE_EPISODE_ONLY")
            if db.execute("SELECT 1 FROM episodes WHERE pid=?", (os.getpid(),)).fetchone():
                raise ProviderStop("FRESH_CLIENT_PROCESS_REQUIRED")
            row = db.execute(
                "SELECT * FROM episodes WHERE status!='OBSERVED' ORDER BY ordinal"
            ).fetchone()
            if row is None or row["id"] != episode or row["status"] != "PENDING":
                raise ProviderStop("NO_RESTART_OR_OUT_OF_ORDER_EPISODE")
            if row["ordinal"] >= 8:
                decision = self._artifact(
                    db.execute("SELECT * FROM artifacts WHERE name='firstpass_decision'").fetchone()
                )
                if decision.get("repeat_required") is not True:
                    raise ProviderStop("SECOND_PASS_NOT_TRIGGERED")
            deadline = float(
                db.execute("SELECT value FROM meta WHERE key='R1_deadline'").fetchone()[0]
            )
            if time.time() >= deadline:
                raise ProviderStop("BATCH_PHASE_DEADLINE")
            db.execute(
                "UPDATE episodes SET status='RUNNING',pid=?,deadline=? WHERE id=?",
                (os.getpid(), min(deadline, time.time() + 300), episode),
            )

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

    def finish(self, episode: str) -> dict:
        from v0222_boundary_audit import audit_episode

        self.authorize("R1")
        with self.transaction() as db:
            self.check_journal(db)
            self._finish_owner(db, episode)
        observation = audit_episode(self, episode)  # No nested SQLite write transaction.
        spec = self.spec(episode)
        if (
            type(observation.get("exact_fidelity")) is not bool
            or observation.get("status") != "OBSERVED"
            or any(
                fingerprint(observation.get(k)) != fingerprint(spec[k])
                for k in ("id", "root", "cold", "condition")
            )
        ):
            raise ProviderStop("INDEPENDENT_OBSERVATION_SPEC_MISMATCH")
        dependencies = observation["files"]
        _verify_files(dependencies)
        directory = self.root / "episodes" / episode
        required = {
            str(p)
            for p in directory.rglob("*")
            if p.is_file()
            and p.suffix in {".json", ".jsonl"}
            and p.name != "independent-observation.json"
        }
        if not required or not required <= dependencies.keys():
            raise ProviderStop("ALL_RAW_OBSERVATION_FILES_MUST_BE_BOUND")
        with self.transaction() as db:
            self.check_journal(db)
            row = self._finish_owner(db, episode)
            if type(observation.get("pid")) is not int or observation["pid"] != row["pid"]:
                raise ProviderStop("OBSERVATION_WORKER_PID_MISMATCH")
            if (
                sum(
                    e["event"] == "RESERVED" and e.get("session") == episode
                    for e in self.events(db)
                )
                != 1
            ):
                raise ProviderStop("ONE_ACTUAL_REQUEST_REQUIRED")
            _verify_files(dependencies)
            path = directory / "independent-observation.json"
            save(path, observation)
            db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?)",
                (episode + "_observation", str(path), sha(path), json.dumps(dependencies)),
            )
            db.execute("UPDATE episodes SET status='OBSERVED' WHERE id=?", (episode,))
        return observation

    def _finish_owner(self, db, episode: str):
        row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
        launcher = db.execute("SELECT pid FROM launches WHERE stage='R1'").fetchone()
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

    def decision(self, final: bool = False) -> dict:
        from v0222_boundary_audit import audit_episode
        from v0222_boundary_contract import decision

        self.authorize("PREP")
        specs = self.plan["episodes"][: 16 if final else 8]
        with self.transaction() as db:
            self.check_journal(db)
            observations = []
            for spec in specs:
                row = db.execute("SELECT status FROM episodes WHERE id=?", (spec["id"],)).fetchone()
                if row[0] != "OBSERVED":
                    raise ProviderStop("COMPLETE_OBSERVED_PASS_REQUIRED")
                observations.append(
                    self._artifact(
                        db.execute(
                            "SELECT * FROM artifacts WHERE name=?", (spec["id"] + "_observation",)
                        ).fetchone()
                    )
                )
        for spec, observation in zip(specs, observations, strict=True):
            if fingerprint(audit_episode(self, spec["id"])) != fingerprint(observation):
                raise ProviderStop("DECISION_OBSERVATION_NOT_REPRODUCIBLE_FROM_RAW")
        return decision(observations, final=final)

    def set_decision(self, path: Path, final: bool = False):
        self.freeze_artifact("final_decision" if final else "firstpass_decision", path)

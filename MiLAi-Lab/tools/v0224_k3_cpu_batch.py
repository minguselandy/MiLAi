"""K3 functional CPU binding under the user completion-priority instruction.

Fresh scope entry methods are source copies with only the scope factory changed.
R02 transaction correction remains a separate, explicitly installed context.
No real fixture or execution authorization is granted by importing this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path

from v0220_evidence import save
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import fingerprint
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_batch_v2 import (
    BOUNDARY_BINDING,
    BOUNDARY_ROOT,
    CAPS,
    IDENTITY,
    PARENT_BINDING,
    PARENT_ROOT,
    PRESENTATION_BINDING,
    PRESENTATION_ROOT,
    REVISION,
    ROOT,
    make_authorization,
)
from v0222_presentation_finish_v2 import Batch as LiveBatch
from v0222_presentation_gates_v2 import FREEZABLE, SCOPE_PREREQUISITES, AuditView
from v0222_scoped_cpu_guard import CPU_MODE, require_cpu_network_guard
from v0222_scoped_evidence import _guard, verify_manifest
from v0224_verified_digest_batch import StaticAuthority
from v0224_verified_digest_lineage import verify_lineage_r03
from v0224_verified_digest_scope import BundleReadScope

# Fixed prospective instances, never selected by model input.
CPU_BASE = Path("/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-completion-v1")
K3_INSTANCE = "completev1-k3"
CPU_ROOT = CPU_BASE / K3_INSTANCE
INSTANCE_ORDER = (K3_INSTANCE,)
INSTANCE_NAMES = frozenset(INSTANCE_ORDER)
CPU_REVISION = "V0224_R04_K3_FUNCTIONAL_PRIORITY_V1"
CPU_PHASE_SECONDS = {"P3": 36 * 3600, "P4": 36 * 3600}


def selected_root() -> Path:
    name = os.environ.get("MILA_V0224_INSTANCE", K3_INSTANCE)
    if name not in INSTANCE_NAMES:
        raise ProviderStop("EXPLICIT_FROZEN_V0224_INSTANCE_REQUIRED")
    return CPU_BASE / name


def workpoint_purpose(root: Path | None = None) -> str:
    current = selected_root() if root is None else root
    if current.parent != CPU_BASE or current.name not in INSTANCE_NAMES:
        raise ProviderStop("EXACT_WORKFLOW_ROOT_PURPOSE_REQUIRED")
    return "K3_FULL_CPU_WORKFLOW" if current.name == K3_INSTANCE else "A1_REFERENCE_CALIBRATION"


def authorized_stages(root: Path | None = None) -> list[str]:
    return ["PREP", "P3", "P4"] if workpoint_purpose(root) == "K3_FULL_CPU_WORKFLOW" else ["PREP"]


def cpu_authorization_source() -> dict:
    return {
        "origin": "USER_DIRECTED_V0224_EXECUTION_SUBAGENT_REVIEWED",
        "execution_mode": CPU_MODE,
        "coordinator_revision": CPU_REVISION,
        "cpu_efficiency_gate_enforced": False,
        "purpose": workpoint_purpose(),
        "stages": authorized_stages(),
        "real_http_allowed": False,
        "device_calls_allowed": False,
        "mock_cost_is_not_real_cost": True,
        "model_capability_or_live_admission": False,
    }


def make_cpu_authorization(root: Path, *, issued: float, expires: float, history: dict) -> dict:
    """Pure contract data, not a directory creation or a grant of HTTP authority."""
    if root != selected_root() or root.resolve() != root:
        raise ProviderStop("ONE_FIXED_CANONICAL_CPU_REPLAY_ROOT_REQUIRED")
    return {
        **make_authorization(ROOT, issued=issued, expires=expires, history=history),
        "root": str(root),
        "batch_id": root.name,
        "phase_wall_seconds": dict(CPU_PHASE_SECONDS),
        "purpose": workpoint_purpose(root),
        "stages": authorized_stages(root),
        "coordinator_revision": CPU_REVISION,
        "cpu_efficiency_gate_enforced": False,
        "execution_mode": CPU_MODE,
        "real_http_allowed": False,
        "device_calls_allowed": False,
        "mock_cost_is_not_real_cost": True,
    }


class OfflineBatch(LiveBatch):
    def __init__(self, root: Path, binding_sha: str, *, static_authority: StaticAuthority):
        require_cpu_network_guard()
        if root != selected_root() or root.resolve() != root:
            raise ProviderStop("ONE_FIXED_CANONICAL_CPU_REPLAY_ROOT_REQUIRED")
        if type(static_authority) is not StaticAuthority:
            raise ProviderStop("EXPLICIT_IMMUTABLE_STATIC_AUTHORITY_REQUIRED")
        self._static_authority = static_authority
        self.root, self.binding_sha = root, binding_sha
        self.path = root / "batch.sqlite"
        with self._new_scope() as scope:
            self.binding = scope.read_json(root / "execution-binding.json", binding_sha)
            self.auth, self.plan = self._authorize("PREP", scope)
        self._time_check(self.auth)

    def _authorize(self, stage: str, scope: AdmissionReadScope) -> tuple[dict, dict]:
        require_cpu_network_guard()
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
            history = verify_lineage_r03(scope)
            expected = make_cpu_authorization(
                self.root, issued=auth["issued_unix"], expires=auth["expires_unix"], history=history
            )
            if fingerprint(auth) != fingerprint(expected):
                raise ProviderStop("EXACT_SCOPED_CPU_CONTRACT_AND_HISTORY_REQUIRED")
            if fingerprint(grant) != fingerprint(cpu_authorization_source()):
                raise ProviderStop("EXPLICIT_CPU_ONLY_SOURCE_REQUIRED")
            if stage not in auth["stages"]:
                raise ProviderStop("STAGE_NOT_AUTHORIZED")
            self._time_check(auth)
            manifest = verify_manifest(scope, self.root, binding["manifest.json"])
            plan = manifest["contract"]
            required = {
                "static_authority": self._static_authority.contract_value(),
                "purpose": workpoint_purpose(self.root),
                "revision": REVISION,
                "coordinator_revision": CPU_REVISION,
                "cpu_efficiency_gate_enforced": False,
                "execution_mode": CPU_MODE,
                "real_http_allowed": False,
                "device_calls_allowed": False,
                "mock_cost_is_not_real_cost": True,
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
                raise ProviderStop("FROZEN_SCOPED_CPU_CONTRACT_REQUIRED")
            if (hasattr(self, "plan") and fingerprint(plan) != fingerprint(self.plan)) or (
                hasattr(self, "auth") and fingerprint(auth) != fingerprint(self.auth)
            ):
                raise ProviderStop("IN_MEMORY_AUTHORIZATION_OR_PLAN_DRIFT")
            self._validate_plan(scope, plan)
            return auth, plan

    def _new_scope(self):
        return BundleReadScope(**self._static_authority.scope_arguments())

    def _read_artifact_row(self, db, row, scope):
        with scope.physical_reads():
            return super()._read_artifact_row(db, row, scope)

    def authorize(self, stage="PREP"):
        with self._new_scope() as scope:
            auth, _ = self._authorize(stage, scope)
        self._time_check(auth)
        return auth

    @contextmanager
    def _operation(self, stage, *, episode=None, inflight=False):
        try:
            with self.transaction() as db:
                with self._new_scope() as scope:
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

    def artifact(self, name):
        with self._gate_failure():
            with self._new_scope() as scope:
                auth, plan = self._authorize("PREP", scope)
                with self._gate_baseline(scope) as (db, snapshot):
                    value = self._artifact(db, name, scope)
            with self.transaction() as db:
                self._gate_final(db, snapshot, auth, self._artifact_stage(name), plan)
            return value

    def freeze_artifact(self, name, path: Path, status: str | None = None):
        with self._gate_failure():
            if name not in FREEZABLE:
                raise ProviderStop("ONLY_PUBLIC_PREPARATION_ARTIFACTS_MAY_BE_FROZEN")
            path = Path(path)
            if (
                not path.is_absolute()
                or ".." in path.parts
                or path.resolve() != path
                or not path.is_relative_to(self.root)
            ):
                raise ProviderStop("STAGE_ARTIFACT_OUTSIDE_CANONICAL_BATCH_PATH")
            with self._new_scope() as scope:
                auth, plan = self._authorize("PREP", scope)
                with self._gate_baseline(scope) as (db, snapshot):
                    if db.execute("SELECT 1 FROM artifacts WHERE name=?", (name,)).fetchone():
                        raise ProviderStop("STAGE_ARTIFACT_ALREADY_FROZEN")
                    row, value = self._candidate(db, name, path, scope)
                    references = {}
                    artifacts = {}
                    control_pins = {}
                    if name in {"P3_preflight", "P4_preflight"}:
                        stage = name[:2]
                        references[stage] = self._artifact(db, stage + "_references", scope)[
                            "references"
                        ]
                    elif name in {"P3_references", "P4_references"}:
                        references[name[:2]] = value["references"]
                    elif name == "P_full_preparation":
                        for artifact_name in (
                            "P3_references",
                            "P4_references",
                            "P4_resolved_specs",
                        ):
                            artifact_value = self._artifact(db, artifact_name, scope)
                            artifact_row = dict(
                                db.execute(
                                    "SELECT * FROM artifacts WHERE name=?", (artifact_name,)
                                ).fetchone()
                            )
                            artifacts[artifact_name] = {
                                "row": artifact_row,
                                "value": artifact_value,
                            }
                    elif name == "scope_review":
                        artifacts = self._capture_artifacts(db, scope, SCOPE_PREREQUISITES)
                        control_pins = self._scope_control_pins(scope)
                # Independent auditing may call references; it never gets a live DB callback.
                if status is not None and value.get("status") != status:
                    raise ProviderStop("STAGE_GATE_STATUS_NOT_MET")
                self._validate_candidate(
                    name,
                    value,
                    AuditView(
                        self.root,
                        plan,
                        references,
                        binding_sha=self.binding_sha,
                        artifacts=artifacts,
                        control_pins=control_pins,
                    ),
                )
            with self.transaction() as db:
                self._gate_final(db, snapshot, auth, self._artifact_stage(name), plan)
                db.execute(
                    "INSERT INTO artifacts VALUES (?,?,?,?)",
                    (row["name"], row["path"], row["sha256"], row["dependencies"]),
                )

    def finish(self, episode):
        with self._gate_failure():
            stage = self.spec(episode)["stage"]
            with self._new_scope() as scope:
                auth, plan = self._authorize(stage, scope)
                with self._gate_baseline(scope) as (db, snapshot):
                    self._finish_owner(db, episode)
                    rows = self._audit_rows(db, episode)
                    events = self.events(db)
                audit = self._audit(episode, rows, events)
                if (
                    audit.get("status") != "PASS"
                    or audit.get("id") != episode
                    or audit.get("stage") != stage
                    or audit.get("pid") != rows["episode_row"]["pid"]
                ):
                    raise ProviderStop("FULL_ACCEPTANCE_AUDIT_NOT_PASS")
                self._verify_episode_files(episode, audit)
                path = self.root / "episodes" / episode / "independent-audit.json"
                save(path, audit)
                audit_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                # Only the new audit document itself enters scope; its dynamic
                # raw ledger dependencies are deliberately not traversed here.
                if fingerprint(scope.read_json(path, audit_sha)) != fingerprint(audit):
                    raise ProviderStop("SAVED_AUDIT_DRIFT")
            with self.transaction() as db:
                self._gate_final(db, snapshot, auth, stage, plan)
                self._verify_episode_files(episode, audit)
                self._last_deadline(db, auth, stage, episode)
                db.execute(
                    "INSERT INTO artifacts VALUES (?,?,?,?)",
                    (episode + "_audit", str(path), audit_sha, json.dumps(audit["files"])),
                )
                db.execute("UPDATE episodes SET status='PASS' WHERE id=?", (episode,))
            return audit

    def _p3_gate(self, path=None):
        with self._gate_failure():
            if path is not None:
                path = Path(path)
                if (
                    not path.is_absolute()
                    or ".." in path.parts
                    or path.resolve() != path
                    or not path.is_relative_to(self.root)
                ):
                    raise ProviderStop("STAGE_ARTIFACT_OUTSIDE_CANONICAL_BATCH_PATH")
            with self._new_scope() as scope:
                auth, plan = self._authorize("P3", scope)
                specs = plan["P3"]
                if (
                    len(specs) != 16
                    or sum(s["variant"] == "full" for s in specs) != 8
                    or sum(s["variant"] == "finish" for s in specs) != 8
                ):
                    raise ProviderStop("COMPLETE_8_FULL_8_FINISH_MATRIX_REQUIRED")
                audits, rows, files = [], [], {}
                with self._gate_baseline(scope) as (db, snapshot):
                    launch = db.execute("SELECT * FROM launches WHERE stage='P3'").fetchone()
                    if launch is None or launch["pid"] != os.getpid():
                        raise ProviderStop("ONLY_STAGE_PARENT_CAN_DERIVE_P3_GATE")
                    if (
                        path is not None
                        and db.execute("SELECT 1 FROM artifacts WHERE name='P3_gate'").fetchone()
                    ):
                        raise ProviderStop("STAGE_ARTIFACT_ALREADY_FROZEN")
                    events = self.events(db)
                    for spec in specs:
                        episode = spec["id"]
                        row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
                        if row is None or row["status"] != "PASS":
                            raise ProviderStop("P3_GATE_REQUIRES_16_ACTUAL_PASS")
                        artifact = db.execute(
                            "SELECT * FROM artifacts WHERE name=?", (episode + "_audit",)
                        ).fetchone()
                        audits.append(self._artifact_row(db, artifact, scope))
                        rows.append(self._audit_rows(db, episode))
                        self._merge_files(files, {artifact["path"]: artifact["sha256"]})
                        self._merge_files(files, json.loads(artifact["dependencies"]))
                        self._merge_files(files, audits[-1]["files"])
                for spec, audit, audit_rows in zip(specs, audits, rows, strict=True):
                    current = self._audit(spec["id"], audit_rows, events)
                    if fingerprint(current) != fingerprint(audit):
                        raise ProviderStop("P3_AUDIT_NOT_REPRODUCIBLE_FROM_RAW")
                    self._verify_episode_files(spec["id"], current)
                gate = {
                    "status": "G_P3_PASS",
                    "binding_sha256": self.binding_sha,
                    "episodes": [s["id"] for s in specs],
                    "full_passed": 8,
                    "finish_passed": 8,
                    "files": files,
                }
                if path is not None:
                    if not path.exists():
                        save(path, gate)
                    gate_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                    if fingerprint(scope.read_json(path, gate_sha)) != fingerprint(gate):
                        raise ProviderStop("P3_GATE_NOT_DERIVED_FROM_16_ACTUAL_PASS_AUDITS")
            with self.transaction() as db:
                self._gate_final(db, snapshot, auth, "P3", plan)
                self._verify_dependencies(files)
                for spec, audit in zip(specs, audits, strict=True):
                    self._verify_episode_files(spec["id"], audit)
                self._last_deadline(db, auth, "P3")
                if path is not None:
                    db.execute(
                        "INSERT INTO artifacts VALUES (?,?,?,?)",
                        ("P3_gate", str(path), gate_sha, json.dumps(files)),
                    )
            return gate

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
                    str(min(now + CPU_PHASE_SECONDS[stage], self.auth["expires_unix"])),
                ),
            )

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
                launch["started"] + CPU_PHASE_SECONDS[stage], self.auth["expires_unix"]
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
                launch["started"] + CPU_PHASE_SECONDS[row["stage"]],
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

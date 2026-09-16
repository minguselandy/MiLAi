"""Explicit CPU completion segment: sixteen missing P4 attempts, no imported PASS.

The original R04 physical admissions and journal FSM remain inherited. Only the
cold-attempt/terminal containment changes to 3600 seconds. Logical spec identity
is retained across separately bound batch attempts to reuse original references.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from v0220_evidence import dependencies, save
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import fingerprint
from v0222_admission_read_scope import AdmissionReadScope
from v0222_http import strict_http_json
from v0222_presentation_audit import audit_episode
from v0222_presentation_gates_v2 import TABLE_QUERIES
from v0222_presentation_terminal_v2 import (
    _bytes,
    _episode_files,
    _finite,
    _require,
    _sha,
    _world_bytes,
)
from v0222_scoped_cpu_guard import CPU_MODE, require_cpu_network_guard
from v0222_scoped_evidence import _guard, verify_manifest
from v0224_k3_cpu_batch import (
    BOUNDARY_BINDING,
    BOUNDARY_ROOT,
    IDENTITY,
    PARENT_BINDING,
    PARENT_ROOT,
    PRESENTATION_BINDING,
    PRESENTATION_ROOT,
    REVISION,
    ROOT,
    make_authorization,
)
from v0224_k3_cpu_batch import (
    OfflineBatch as OriginalBatch,
)
from v0224_static_bundle import BundleLimits
from v0224_verified_digest_batch import StaticAuthority
from v0224_verified_digest_lineage import verify_lineage_r03

CPU_BASE = Path("/cra/memory/mx_memory/evidence/v0224/20260913-cpu-completion-segment-v1")
INSTANCE = "segmentv1-p4"
CPU_ROOT = CPU_BASE / INSTANCE
CPU_REVISION = "V0224_CPU_COMPLETION_SEGMENT_V1"
CPU_PHASE_SECONDS = {"P3": 129600, "P4": 129600}
PHASE_SECONDS = CPU_PHASE_SECONDS
CLAIM_SECONDS = 3600
PREDECESSOR_ROOT = Path(
    "/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-completion-v1/completev1-k3"
)
FAILURE_PATH = Path(
    "/cra/memory/mx_memory/evidence/v0224/20260913-a-completion-priority-v1/P4-failure-external-terminal.json"
)
FAILURE_SHA256 = "10838aed8f4c21a73d10e35ece7ca75f8da5ea48e901d0b238f6ae7d359363a0"


def selected_root():
    if os.environ.get("MILA_V0224_INSTANCE", INSTANCE) != INSTANCE:
        raise ProviderStop("EXACT_COMPLETION_SEGMENT_SELECTOR_REQUIRED")
    return CPU_ROOT


def workpoint_purpose(root=None):
    if (selected_root() if root is None else root) != CPU_ROOT:
        raise ProviderStop("EXACT_COMPLETION_SEGMENT_ROOT_REQUIRED")
    return "K3_MISSING_P4_COMPLETION_SEGMENT"


def authorized_stages(root=None):
    workpoint_purpose(root)
    return ["PREP", "P4"]


def cpu_authorization_source():
    return dict(
        origin="USER_DIRECTED_COMPLETION_SEGMENT",
        execution_mode=CPU_MODE,
        coordinator_revision=CPU_REVISION,
        purpose=workpoint_purpose(),
        stages=authorized_stages(),
        real_http_allowed=False,
        device_calls_allowed=False,
        mock_cost_is_not_real_cost=True,
        cpu_efficiency_gate_enforced=False,
        claim_seconds=CLAIM_SECONDS,
        phase_wall_seconds=dict(CPU_PHASE_SECONDS),
        model_capability_or_live_admission=False,
    )


def make_cpu_authorization(root, *, issued, expires, history):
    if root != selected_root() or root.resolve() != root:
        raise ProviderStop("ONE_FIXED_CANONICAL_CPU_REPLAY_ROOT_REQUIRED")
    return {
        **make_authorization(ROOT, issued=issued, expires=expires, history=history),
        **cpu_authorization_source(),
        "root": str(root),
        "batch_id": root.name,
        "episode_wall_seconds": CLAIM_SECONDS,
    }


class OfflineBatch(OriginalBatch):
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
                "claim_seconds": CLAIM_SECONDS,
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
            claimed_deadline = min(deadline, now + CLAIM_SECONDS, self.auth["expires_unix"])
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
                claim["started"] + CLAIM_SECONDS,
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

    def _audit(self, episode, rows, events):
        return audit_claimed_episode(self, episode, **rows, events=events)

    def references(self, stage):
        if stage != "P4":
            raise ProviderStop("ONLY_MISSING_P4_REFERENCES_ALLOWED")
        ids = {spec["id"] for spec in self.plan["P4"]}
        rows = super().references(stage)
        selected = [row for row in rows if row["episode"] in ids]
        expected = [
            (s["id"], turn) for s in self.plan["P4"] for turn in range(1, len(s["actions"]) + 3)
        ]
        if [(r["episode"], r["turn"]) for r in selected] != expected:
            raise ProviderStop("COMPLETE_UNCHANGED_SEGMENT_REFERENCES_REQUIRED")
        return selected

    def _validate_plan(self, scope, plan):
        validate_predecessor(scope, plan)

    def _ready(self, db, stage, scope):
        if stage != "P4":
            raise ProviderStop("ONLY_MISSING_P4_STAGE_ALLOWED")
        lineage = validate_predecessor(scope, self.plan)
        with scope.physical_reads():
            prior = _pinned_json(scope, lineage["predecessor_snapshot"])
        inherited = {r["name"]: r for r in prior["artifacts"]}
        for name in (
            "scope_review",
            "engineering_checks",
            "P4_preflight",
            "P3_gate",
            "P4_references",
            "P4_resolved_specs",
        ):
            row = db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone()
            if row is None or fingerprint(dict(row)) != fingerprint(inherited[name]):
                raise ProviderStop("EXACT_INHERITED_ARTIFACT_ROW_REQUIRED")
        for name, status in (
            ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
            ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
            ("P4_preflight", "G_PREFLIGHT_PASS"),
            ("P3_gate", "G_P3_PASS"),
        ):
            value = self._artifact(db, name, scope)
            if value.get("status") != status:
                raise ProviderStop("SEGMENT_INHERITED_GATE_STATUS_NOT_MET")
        self._artifact(db, "P4_references", scope)
        self._artifact(db, "P4_resolved_specs", scope)
        if db.execute("SELECT COUNT(*) FROM episodes WHERE stage != 'P4'").fetchone()[0]:
            raise ProviderStop("NO_IMPORTED_PREDECESSOR_PASS_ROWS")


Batch = OfflineBatch


def audit_claimed_episode(
    batch,
    episode: str,
    *,
    episode_row: dict,
    claim_row: dict,
    launch_row: dict,
    events: list,
) -> dict:
    """Check an owned completed output, returning the old audit plus three pins.

    RUNNING is for parent finish; PASS supports later P3-gate re-audits. FAIL and
    PENDING never qualify. Historical episode deadlines are derived, not compared
    to the current clock: later gate re-audit must not retroactively expire PASS.
    ``events`` is the complete fresh current-batch central event list. This method
    reads files only and never stops, freezes, authorizes or mutates a Batch.
    """
    _require(
        type(episode) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", episode) is not None,
        "CANONICAL_EPISODE_ID_REQUIRED",
    )
    root = Path(batch.root)
    _require(root.is_absolute() and root.resolve() == root, "CANONICAL_BATCH_ROOT_REQUIRED")
    binding = batch.binding_sha
    _require(
        type(binding) is str and re.fullmatch(r"[0-9a-f]{64}", binding) is not None,
        "EXACT_TERMINAL_BINDING_REQUIRED",
    )
    _require(
        all(type(row) is dict for row in (episode_row, claim_row, launch_row))
        and type(events) is list,
        "EXPLICIT_TERMINAL_ROWS_AND_EVENTS_REQUIRED",
    )
    episode_row, claim_row, launch_row, events = copy.deepcopy(
        (episode_row, claim_row, launch_row, events)
    )
    spec, plan, auth = copy.deepcopy((batch.spec(episode), batch.plan, batch.auth))
    stage = spec["stage"]
    _require(stage in PHASE_SECONDS and spec["id"] == episode, "EXACT_TERMINAL_SPEC_REQUIRED")
    cap = 1 if stage == "P3" else 4
    _require(
        episode_row.get("id") == episode
        and episode_row.get("stage") == stage
        and episode_row.get("status") in {"RUNNING", "PASS"}
        and type(episode_row.get("cap")) is int
        and episode_row["cap"] == cap
        and type(episode_row.get("ordinal")) is int
        and episode_row["ordinal"] >= 0,
        "RUNNING_OR_PASSED_EXACT_EPISODE_ROW_REQUIRED",
    )
    _require(
        set(claim_row) == {"episode", "pid", "started", "deadline"}
        and set(launch_row) == {"stage", "pid", "started"}
        and claim_row["episode"] == episode
        and launch_row["stage"] == stage
        and all(
            type(row.get("pid")) is int and row["pid"] > 0
            for row in (episode_row, claim_row, launch_row)
        )
        and episode_row["pid"] == claim_row["pid"] != launch_row["pid"]
        and all(
            _finite(value)
            for value in (
                claim_row["started"],
                claim_row["deadline"],
                launch_row["started"],
                episode_row.get("deadline"),
                auth.get("expires_unix"),
            )
        ),
        "EXACT_COLD_CLAIM_AND_LAUNCH_REQUIRED",
    )
    deadline = min(
        launch_row["started"] + PHASE_SECONDS[stage],
        claim_row["started"] + CLAIM_SECONDS,
        auth["expires_unix"],
    )
    _require(
        launch_row["started"] <= claim_row["started"] < deadline
        and fingerprint(episode_row["deadline"]) == fingerprint(claim_row["deadline"])
        and claim_row["deadline"] == deadline,
        "CLAIM_DERIVED_DEADLINE_DRIFT",
    )
    claim_path = Path(batch.claim_marker_path(episode))
    _require(claim_path == root / "claims" / (episode + ".json"), "EXTERNAL_CLAIM_PATH_REQUIRED")
    launch_path = root / ("live-launch-" + stage + ".json")
    exit_path = root / "exits" / (episode + ".json")
    external = {p: _bytes(p) for p in (claim_path, launch_path, exit_path)}
    claim, launch, exit_record = (
        strict_http_json(external[p].decode("utf-8")) for p in (claim_path, launch_path, exit_path)
    )
    _require(
        fingerprint(claim) == fingerprint({**claim_row, "binding_sha256": binding})
        and fingerprint(launch)
        == fingerprint(
            {
                "stage": stage,
                "pid": launch_row["pid"],
                "unix": launch_row["started"],
                "binding_sha256": binding,
            }
        ),
        "EXACT_CLAIM_AND_LAUNCH_MARKERS_REQUIRED",
    )
    _require(
        type(exit_record) is dict
        and type(exit_record.get("pid")) is int
        and type(exit_record.get("parent_pid")) is int
        and exit_record["pid"] == claim_row["pid"]
        and exit_record["parent_pid"] == launch_row["pid"]
        and type(exit_record.get("returncode")) is int
        and exit_record["returncode"] == 0
        and exit_record.get("timed_out") is False
        and _finite(exit_record.get("seconds"))
        and exit_record["seconds"] <= CLAIM_SECONDS,
        "CLEAN_BOUNDED_COLD_WORKER_EXIT_REQUIRED",
    )
    directory = root / "episodes" / episode
    before = _episode_files(directory)
    ledger_path = directory / "provider" / "provider-ledger-v2.jsonl"
    local = [strict_http_json(line) for line in before[ledger_path].decode("utf-8").splitlines()]
    _require(all(type(e) is dict for e in [*events, *local]), "EVENT_OBJECTS_REQUIRED")
    usage_state(events)  # Validate the complete supplied central FSM before selecting IDs.
    ids = {
        e["request_id"] for e in events if e["event"] == "RESERVED" and e.get("session") == episode
    }
    central = [e for e in events if e["request_id"] in ids]
    _require(
        fingerprint(central) == fingerprint(local), "EXACT_ORDERED_CENTRAL_LOCAL_EVENTS_REQUIRED"
    )
    cost = usage_state(central)
    _require(
        cost["new_generation_allowed"] and cost["requests"] in ({1} if stage == "P3" else {3, 4}),
        "COMPLETE_BOUNDED_TERMINAL_COST_REQUIRED",
    )
    world = root / "worlds" / (episode + ".sqlite")
    if stage == "P4":
        before[world] = _world_bytes(world)
    frozen_view = SimpleNamespace(
        root=root,
        spec=lambda _: copy.deepcopy(spec),
        plan=plan,
        auth=auth,
    )
    result = audit_episode(frozen_view, episode)
    _require(
        result["id"] == episode
        and result["stage"] == stage
        and result["status"] == "PASS"
        and type(result["pid"]) is int
        and result["pid"] == claim_row["pid"]
        and fingerprint(result["cost"]) == fingerprint(cost),
        "ORIGINAL_INDEPENDENT_AUDIT_MUST_MATCH_CLAIM_AND_CENTRAL_COST",
    )
    expected_files = {str(p): _sha(raw) for p, raw in before.items()}
    _require(
        fingerprint(result["files"]) == fingerprint(expected_files),
        "COMPLETE_ORIGINAL_EPISODE_EVIDENCE_SET_REQUIRED",
    )
    after = _episode_files(directory)
    if stage == "P4":
        after[world] = _world_bytes(world)
    _require(before == after, "TERMINAL_EPISODE_EVIDENCE_CHANGED_DURING_AUDIT")
    for path, raw in external.items():
        _require(_bytes(path) == raw, "TERMINAL_EXTERNAL_EVIDENCE_CHANGED_DURING_AUDIT")
    _require(
        fingerprint((batch.spec(episode), batch.plan, batch.auth, batch.binding_sha))
        == fingerprint((spec, plan, auth, binding)),
        "TERMINAL_BATCH_CONTROL_CHANGED_DURING_AUDIT",
    )
    result = copy.deepcopy(result)
    result["files"].update({str(p): _sha(raw) for p, raw in external.items()})
    return result


SEGMENT_LINEAGE_PATH = CPU_BASE / "completion-segment-lineage.json"
SEGMENT_LINEAGE_SHA256 = "99247ca5971eba845dc01cf5a6cb104556a1bdffc04fb1ebbfd70ee8ccb2afac"
PREDECESSOR_CONTRACT_SHA256 = "e9741312450a9634624a787a67a037c4235d20ca6042d7131478013d6fbae33d"


def _pinned_json(scope, descriptor):
    if type(descriptor) is not dict or set(descriptor) != {"path", "sha256"}:
        raise ProviderStop("EXACT_EXTERNAL_PIN_DESCRIPTOR_REQUIRED")
    return scope.read_json(Path(descriptor["path"]), descriptor["sha256"])


def _old_snapshot():
    path = PREDECESSOR_ROOT / "batch.sqlite"
    if path.resolve() != path or not path.is_file():
        raise ProviderStop("CANONICAL_EXISTING_PREDECESSOR_SQL_REQUIRED")
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        return {
            table: [dict(row) for row in db.execute(query)]
            for table, query in TABLE_QUERIES.items()
        }
    finally:
        db.close()


def validate_predecessor(scope, plan):
    """Frozen prior acceptance, not re-admission of the stopped old batch.

    All prior current evidence is physical, including paths also present in the
    immutable bundle. SQLite is compared semantically, never hash-pinned as an
    artifact or edited. The old FAIL and STOP must remain visible.
    """
    expected_pin = {"path": str(SEGMENT_LINEAGE_PATH), "sha256": SEGMENT_LINEAGE_SHA256}
    if plan.get("completion_segment") != expected_pin:
        raise ProviderStop("EXACT_SEGMENT_LINEAGE_PIN_REQUIRED")
    with scope.physical_reads():
        lineage = _pinned_json(scope, expected_pin)
        if (
            lineage["predecessor_root"] != str(PREDECESSOR_ROOT)
            or lineage["failure_terminal"] != {"path": str(FAILURE_PATH), "sha256": FAILURE_SHA256}
            or lineage["predecessor_contract"]["sha256"] != PREDECESSOR_CONTRACT_SHA256
        ):
            raise ProviderStop("EXACT_FAILED_PREDECESSOR_REQUIRED")
        files = lineage["files"]
        if type(files) is not dict or not files:
            raise ProviderStop("COMPLETE_PREDECESSOR_FILES_REQUIRED")
        dynamic = {
            str(PREDECESSOR_ROOT / ("batch.sqlite" + suffix)) for suffix in ("", "-wal", "-shm")
        }
        if dynamic.intersection(files):
            raise ProviderStop("PREDECESSOR_SQL_REQUIRES_SEMANTIC_SNAPSHOT")
        for path, digest in files.items():
            scope.read_bytes(Path(path), digest)
        contract = _pinned_json(scope, lineage["predecessor_contract"])
        if (
            contract["root"] != str(PREDECESSOR_ROOT)
            or contract["binding_sha256"] != lineage["predecessor_binding_sha256"]
        ):
            raise ProviderStop("PREDECESSOR_BINDING_DRIFT")
        binding = scope.read_json(
            PREDECESSOR_ROOT / "execution-binding.json", lineage["predecessor_binding_sha256"]
        )
        manifest = scope.read_json(PREDECESSOR_ROOT / "manifest.json", binding["manifest.json"])
        original = manifest["contract"]
        snapshot = _pinned_json(scope, lineage["predecessor_snapshot"])
        if set(snapshot) != set(TABLE_QUERIES):
            raise ProviderStop("COMPLETE_PREDECESSOR_SIX_TABLES_REQUIRED")
        if fingerprint(snapshot) != fingerprint(_old_snapshot()):
            raise ProviderStop("PREDECESSOR_SQL_SEMANTIC_DRIFT")
        if len(original["P3"]) != 16 or len(original["P4"]) != 24:
            raise ProviderStop("ORIGINAL_COMPLETE_40_MATRIX_REQUIRED")
        p3 = [s["id"] for s in original["P3"]]
        p4 = [s["id"] for s in original["P4"]]
        if (
            lineage["accepted_prefix"] != {"P3_ids": p3, "P4_ids": p4[:8]}
            or lineage["positions"] != p4[8:]
            or plan["P3"] != []
            or fingerprint(plan["P4"]) != fingerprint(original["P4"][8:])
        ):
            raise ProviderStop("EXACT_UNCHANGED_MISSING_SIXTEEN_SPECS_REQUIRED")
        rows = snapshot["episodes"]
        if [(r["id"], r["stage"], r["ordinal"], r["status"]) for r in rows] != [
            *((episode, "P3", i, "PASS") for i, episode in enumerate(p3)),
            *(
                (episode, "P4", i, "PASS" if i < 8 else "FAIL" if i == 8 else "PENDING")
                for i, episode in enumerate(p4)
            ),
        ]:
            raise ProviderStop("EXACT_ACCEPTED_PREFIX_AND_FAILED_ATTEMPT_REQUIRED")
        if not any(row["key"] == "stop" for row in snapshot["meta"]):
            raise ProviderStop("OLD_FAILURE_MUST_REMAIN_STOPPED")
        artifacts = {row["name"]: row for row in snapshot["artifacts"]}
        for name, status in [
            ("P3_gate", "G_P3_PASS"),
            ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
            ("P4_preflight", "G_PREFLIGHT_PASS"),
        ]:
            row = artifacts[name]
            value = scope.read_json(Path(row["path"]), row["sha256"])
            if value.get("status") != status:
                raise ProviderStop("INHERITED_ACCEPTANCE_ARTIFACT_REQUIRED")
        for stage, count in [("P3", 16), ("P4", 80)]:
            row = artifacts[stage + "_references"]
            value = scope.read_json(Path(row["path"]), row["sha256"])
            if len(value["references"]) != count:
                raise ProviderStop("ALL_ORIGINAL_REFERENCE_ROWS_REQUIRED")
        if fingerprint(snapshot) != fingerprint(_old_snapshot()):
            raise ProviderStop("PREDECESSOR_SQL_CHANGED_DURING_REVIEW")
        return lineage


def load_batch(contract_path, contract_sha256):
    require_cpu_network_guard()
    path = Path(contract_path)
    if not path.is_absolute() or path.resolve() != path or ".." in path.parts:
        raise ProviderStop("CANONICAL_EXTERNAL_CONTRACT_REQUIRED")
    with AdmissionReadScope() as scope:
        contract = scope.read_json(path, contract_sha256)
        if (
            contract.get("status") != "CPU_COMPLETION_SEGMENT_FROZEN"
            or contract.get("root") != str(CPU_ROOT)
            or contract.get("execution_revision") != CPU_REVISION
        ):
            raise ProviderStop("EXACT_COMPLETION_SEGMENT_CONTRACT_REQUIRED")
        pins = contract["files"]
        if not set(map(str, dependencies([Path(__file__).resolve()]))).issubset(pins):
            raise ProviderStop("COMPLETE_EXECUTING_SOURCE_PINS_REQUIRED")
        for source, digest in pins.items():
            scope.read_bytes(Path(source), digest)
    spec = contract["static_authority"]
    authority = StaticAuthority(
        bundle_path=Path(spec["bundle_path"]),
        bundle_sha256=spec["bundle_sha256"],
        receipt_path=Path(spec["receipt_path"]),
        receipt_sha256=spec["receipt_sha256"],
        limits=BundleLimits(**spec["limits"]),
    )
    batch = Batch(CPU_ROOT, contract["binding_sha256"], static_authority=authority)
    return contract, batch
